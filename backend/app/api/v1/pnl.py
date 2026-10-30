import os
import re
import json
import calendar
import hashlib
import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.facebook import _resolve_scoped_default_account
from app.core.deps import require_permission
from app.database import SessionLocal, get_db
from app.models import FacebookAd, FacebookAdSet, FacebookCampaign, PnlCostEntry, PnlMonthSnapshot, User, normalize_account_id
from app.services.bhm_everflow_service import BhmEverflowService
from app.services.everflow_service import EVERFLOW_TZ_BY_ID, META_ID_RE, EverflowService
from app.services.facebook_service import FacebookService
from app.services.redtrack_service import RedTrackService, today_in_rt_tz

router = APIRouter()
logger = logging.getLogger(__name__)


CATEGORIES = {"labor", "tooling", "creative", "data", "other"}
COST_TYPES = {
    "one_off",
    "recurring_monthly",
    "pct_of_spend",
    "pct_of_revenue",
    "pct_of_gross_profit",
    "pct_of_profit",
}
ALLOCATIONS = {"full", "by_spend", "even"}
CENT = Decimal("0.01")
EVERFLOW_ACCOUNT_IDS_ENV = "SWITCHBOARD_EVERFLOW_AD_ACCOUNT_IDS"
EVERFLOW_ACCOUNT_OFFERS_ENV = "SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS"
PNL_ALL_ACCOUNTS_SCOPE_ENV = "PNL_ALL_ACCOUNTS_SCOPE_IDS"
# Offers whose traffic is entirely ours (Steve, 2026-10-26: "if the revenue is tied to FBQ or GBC those are all our
# internal traffic so all revenue should be kept"): Get Business Coverage and Fast Business Quote. Every conversion on
# them counts, even with no usable sub3. Any other offer (Fast Auto Quote.org carries outside traffic) keeps the stricter
# rule: only revenue that ties to a Meta ad set / campaign counts. Override with PNL_ALL_INTERNAL_OFFERS (comma list).
PNL_INTERNAL_OFFERS_ENV = "PNL_ALL_INTERNAL_OFFERS"
DEFAULT_INTERNAL_OFFERS = ("get business coverage", "fast business quote")
# A Meta URL-parameter macro that reached Everflow unexpanded, e.g. {{adset.id}}.
UNEXPANDED_META_MACRO_RE = re.compile(r"\{\{\s*adset\.id\s*\}\}", re.IGNORECASE)
AUDIT_SUB_FIELDS = tuple(f"sub{number}" for number in range(1, 9))
AUDIT_CACHE_TTL_SECONDS = 300
AUDIT_CACHE_MAX_ENTRIES = 24
_attribution_audit_cache: dict[tuple[str, str, str], tuple[float, dict]] = {}


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _float(value) -> float:
    return float(_money(value))


def _month_bounds(month: str | None = None) -> tuple[date, date]:
    today = today_in_rt_tz()
    if month:
        try:
            start = datetime.strptime(month, "%Y-%m").date().replace(day=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    else:
        start = today.replace(day=1)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, next_month - timedelta(days=1)


def _resolve_period(
    period: str = "mtd",
    month: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[date, date, str]:
    today = today_in_rt_tz()
    if period != "custom" and (date_from or date_to):
        raise HTTPException(
            status_code=400,
            detail="date_from/date_to require period=custom. Pass period=custom to use date_from/date_to.",
        )
    if period == "custom":
        if not date_from or not date_to:
            raise HTTPException(status_code=400, detail="date_from and date_to are required for custom period")
        try:
            start = datetime.strptime(date_from, "%Y-%m-%d").date()
            end = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from/date_to must be YYYY-MM-DD")
        if end < start:
            raise HTTPException(status_code=400, detail="date_to must be after date_from")
        return start, end, f"{start.isoformat()} - {end.isoformat()}"

    start, month_end = _month_bounds(month)
    if period == "month":
        return start, month_end, start.strftime("%B %Y")
    if period == "mtd":
        end = min(month_end, today) if start <= today else month_end
        return start, end, f"MTD {start.strftime('%b %Y')}"
    raise HTTPException(status_code=400, detail="period must be month, mtd, or custom")


def _active_account_ids(db: Session) -> list[str]:
    rows = (
        db.query(FacebookAdSet.fb_account_id)
        .filter(FacebookAdSet.fb_account_id.isnot(None))
        .distinct()
        .all()
    )
    return sorted({normalize_account_id(row[0]) for row in rows if row[0]})


def _require_account(current_user: User, ad_account_id: str | None) -> str:
    if ad_account_id == "all":
        return "all"
    resolved = _resolve_scoped_default_account(current_user, ad_account_id)
    if not resolved:
        raise HTTPException(status_code=400, detail="ad_account_id is required for P&L.")
    return normalize_account_id(resolved)


def _all_accounts_scope_ids() -> set[str] | None:
    """Which accounts count as "All Accounts" for the aggregate P&L view.

    Steve, 2026-09-09: "All Accounts" (the Dashboard's blended P&L widget, and
    the profit base for Abel's %-of-net-profit cost entry) should only ever
    include RHO / RHO 4 / RHO 3 - Auto Insurance / Trusted Home Service / DIN
    Auto Insurance — not every active Meta account. Without this, a media
    buyer's spend on some unrelated test/legacy account silently drags down
    the aggregate net profit Abel's commission is computed against.
    Unset (empty env var) falls back to every active account, so this stays
    backward-compatible if the scope is ever intentionally cleared.
    """
    raw = os.getenv(PNL_ALL_ACCOUNTS_SCOPE_ENV, "")
    ids = {normalize_account_id(account.strip()) for account in raw.split(",") if account.strip()}
    return ids or None


def _permitted_active_account_ids(db: Session, current_user: User) -> list[str]:
    active = set(_active_account_ids(db))
    scope = _all_accounts_scope_ids()
    if scope is not None:
        active &= scope
    allowed = current_user.allowed_account_ids()
    if allowed is not None:
        active &= {normalize_account_id(account_id) for account_id in allowed}
    return sorted(active)


def _everflow_account_ids() -> set[str]:
    raw = os.getenv(EVERFLOW_ACCOUNT_IDS_ENV, "")
    return {normalize_account_id(account.strip()) for account in raw.split(",") if account.strip()}


def _revenue_provider_for_account(account_id: str) -> str:
    """Which source (if any) provides this account's billable revenue.

    Everflow-only, per Steve 2026-09-09: Everflow is the point of truth for
    billable revenue network-wide; RedTrack is click/conversion tracking, not
    a revenue source of truth, and previously being used as a silent fallback
    here is exactly what made the P&L "All Accounts" total ($21,340) disagree
    with Joel's Everflow portal figure ($18,782.85) — RedTrack revenue from a
    second account (RHO 4) was getting blended in as if it were billable.
    An account with no Everflow offer mapping now has no billable-revenue
    source at all, rather than falling back to a lower-trust number.
    """
    account_id = normalize_account_id(account_id)
    if account_id in _everflow_account_ids():
        return "everflow"
    if account_id in _bhm_everflow_offer_map():
        return "bhm_everflow"
    return "none"


# BHM's own Everflow (network realm): which offers belong to which Meta account, and which affiliates are our internal
# Meta traffic. Steve, 2026-10-29: LoanDepot 4566, Splitero 4626, internal affiliates 232 and 125. Env overrides:
# BHM_EVERFLOW_ACCOUNT_OFFERS ({"act_...": ["4626"]}) and BHM_EVERFLOW_INTERNAL_AFFILIATE_IDS ("232,125").
BHM_EVERFLOW_ACCOUNT_OFFERS_ENV = "BHM_EVERFLOW_ACCOUNT_OFFERS"
BHM_EVERFLOW_AFFILIATES_ENV = "BHM_EVERFLOW_INTERNAL_AFFILIATE_IDS"
DEFAULT_BHM_EVERFLOW_ACCOUNT_OFFERS = {
    "act_994325837966073": ["4626"],   # Splitero - HEI
    "act_375215180951288": ["4566"],   # Loan Depot - HELOC
}
DEFAULT_BHM_EVERFLOW_AFFILIATES = "232,125"


def _bhm_everflow_offer_map() -> dict[str, set[str]]:
    raw = os.getenv(BHM_EVERFLOW_ACCOUNT_OFFERS_ENV)
    try:
        mapping = json.loads(raw) if raw else DEFAULT_BHM_EVERFLOW_ACCOUNT_OFFERS
        return {
            normalize_account_id(account): {str(o).strip() for o in offers if str(o).strip()}
            for account, offers in mapping.items()
            if isinstance(offers, list) and offers
        }
    except Exception:  # noqa: BLE001 — a bad env value must never 500 every P&L request
        logger.error("%s is not a JSON object of account -> [offer ids]; BHM Everflow revenue is disabled", BHM_EVERFLOW_ACCOUNT_OFFERS_ENV)
        return {}


def _bhm_everflow_affiliates() -> set[str]:
    raw = os.getenv(BHM_EVERFLOW_AFFILIATES_ENV) or DEFAULT_BHM_EVERFLOW_AFFILIATES
    return {a.strip() for a in raw.split(",") if a.strip()}


def _bhm_everflow_rows(db: Session, offer_ids: set[str], start: date, end: date) -> list[dict]:
    """Internal-affiliate conversions on these offers, with unexpanded {{adset.id}} recovered where possible."""
    rows = BhmEverflowService().get_internal_conversions(start, end, offer_ids, _bhm_everflow_affiliates())
    return _recover_macro_adsets(db, rows)


def _with_source(result: tuple, source: str) -> tuple:
    revenue, events, unmapped, _, incomplete, unattributed, breakdown = result
    return revenue, events, unmapped, source, incomplete, unattributed, breakdown


def _everflow_offer_names_for_account(account_id: str) -> set[str]:
    """Return the Switchboard offer names allowed for this Meta account.

    Format:
      SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS='{"act_123":["Get Business Coverage"]}'

    Everflow keys are not account-scoped. If an Everflow-enabled account has no
    offer mapping, fail closed so auto/commercial/home-services revenue cannot
    be blended into the wrong P&L.
    """
    raw = os.getenv(EVERFLOW_ACCOUNT_OFFERS_ENV, "")
    if not raw.strip():
        return set()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    values = parsed.get(normalize_account_id(account_id)) if isinstance(parsed, dict) else None
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def _audit_revenue_attribution(
    rows: list[dict],
    offer_names: set[str],
    scoped_adsets: set[str],
    scoped_ads: dict[str, str],
    scoped_campaigns: set[str],
    foreign_meta_ids: set[str],
) -> dict:
    """Audit current P&L coverage separately from candidate future mappings.

    Production P&L currently only assigns an Everflow ``sub3`` that matches a
    Meta ad-set ID.  A match in another field is useful evidence about the
    live tracking contract, but it must never be presented as P&L-ready or
    timing-ready until the consuming resolver has been deliberately changed.
    """
    allowed_offers = {name.casefold() for name in offer_names if name}
    buckets = {
        "current_pnl_exact_sub3_adset": {"events": 0, "revenue": Decimal("0"), "reasons": {}, "event_types": {}},
        "current_pnl_campaign_only_sub3": {"events": 0, "revenue": Decimal("0"), "reasons": {}, "event_types": {}},
        "candidate_adset_other_field": {"events": 0, "revenue": Decimal("0"), "reasons": {}, "event_types": {}},
        "candidate_ad_other_field": {"events": 0, "revenue": Decimal("0"), "reasons": {}, "event_types": {}},
        "foreign_meta_id": {"events": 0, "revenue": Decimal("0"), "reasons": {}, "event_types": {}},
        "missing_or_unknown": {"events": 0, "revenue": Decimal("0"), "reasons": {}, "event_types": {}},
    }
    field_presence = {field: {"events": 0, "revenue": Decimal("0")} for field in AUDIT_SUB_FIELDS}
    total_events = 0
    total_revenue = Decimal("0")

    def record(bucket_name: str, revenue: Decimal, reason: str, event_name: str) -> None:
        bucket = buckets[bucket_name]
        bucket["events"] += 1
        bucket["revenue"] += revenue
        bucket["reasons"][reason] = bucket["reasons"].get(reason, 0) + 1
        event = bucket["event_types"].setdefault(event_name, {"events": 0, "revenue": Decimal("0")})
        event["events"] += 1
        event["revenue"] += revenue

    for row in rows:
        if allowed_offers and EverflowService._offer_name(row).casefold() not in allowed_offers:
            continue
        raw_revenue = row.get("revenue")
        try:
            if raw_revenue in (None, ""):
                raise InvalidOperation
            revenue = Decimal(str(raw_revenue))
            if not revenue.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Switchboard returned a conversion with missing or invalid revenue")
        event_name = str(row.get("event") or "unknown").strip() or "unknown"
        total_events += 1
        total_revenue += revenue
        values = []
        for field in AUDIT_SUB_FIELDS:
            value = str(row.get(field) or "").strip()
            if not value:
                continue
            field_presence[field]["events"] += 1
            field_presence[field]["revenue"] += revenue
            values.append((field, value))

        sub3 = str(row.get("sub3") or "").strip()
        if sub3 in scoped_adsets:
            record("current_pnl_exact_sub3_adset", revenue, "sub3 matched Meta ad set (current P&L path)", event_name)
            continue
        if sub3 in scoped_campaigns:
            record("current_pnl_campaign_only_sub3", revenue, "sub3 matched Meta campaign (not ad-set attributable)", event_name)
            continue
        other_values = [(field, value) for field, value in values if field != "sub3"]
        candidate_adset = next(((field, value) for field, value in other_values if value in scoped_adsets), None)
        if candidate_adset:
            record("candidate_adset_other_field", revenue, f"{candidate_adset[0]} matched Meta ad set (not current P&L path)", event_name)
            continue
        candidate_ad = next(((field, value) for field, value in values if value in scoped_ads), None)
        if candidate_ad:
            record("candidate_ad_other_field", revenue, f"{candidate_ad[0]} matched Meta ad (not timing-validated)", event_name)
            continue
        foreign = next(((field, value) for field, value in values if value in foreign_meta_ids), None)
        if foreign:
            record("foreign_meta_id", revenue, f"{foreign[0]} matched a different Meta account", event_name)
            continue
        numeric = next(((field, value) for field, value in values if META_ID_RE.fullmatch(value)), None)
        record(
            "missing_or_unknown",
            revenue,
            f"{numeric[0]} is not in the synced Meta identity map" if numeric else "no usable Meta ID in sub1–sub8",
            event_name,
        )

    classified_revenue = sum((bucket["revenue"] for bucket in buckets.values()), Decimal("0"))
    current_pnl_revenue = buckets["current_pnl_exact_sub3_adset"]["revenue"]
    return {
        "total_events": total_events,
        "total_revenue": _float(total_revenue),
        "classification_total": _float(classified_revenue),
        "classification_difference": _float(total_revenue - classified_revenue),
        "current_pnl_adset_revenue": _float(current_pnl_revenue),
        "current_pnl_adset_coverage": float(current_pnl_revenue / total_revenue) if total_revenue > 0 else None,
        "buckets": {
            name: {
                "events": data["events"],
                "revenue": _float(data["revenue"]),
                "reasons": data["reasons"],
                "event_types": {
                    event_name: {"events": event["events"], "revenue": _float(event["revenue"])}
                    for event_name, event in data["event_types"].items()
                },
            }
            for name, data in buckets.items()
        },
        "field_presence": {
            field: {"events": data["events"], "revenue": _float(data["revenue"])}
            for field, data in field_presence.items()
        },
    }


def _source_offer_breakdown(rows: list[dict], configured_offers: set[str]) -> dict:
    """Aggregate every source row so an offer-map error cannot look clean."""
    offers: dict[str, dict] = {}
    total_revenue = Decimal("0")
    for row in rows:
        raw_revenue = row.get("revenue")
        try:
            if raw_revenue in (None, ""):
                raise InvalidOperation
            revenue = Decimal(str(raw_revenue))
            if not revenue.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Switchboard returned a conversion with missing or invalid revenue")
        offer = EverflowService._offer_name(row) or "(missing offer name)"
        slot = offers.setdefault(offer, {"events": 0, "revenue": Decimal("0")})
        slot["events"] += 1
        slot["revenue"] += revenue
        total_revenue += revenue
    allowed = {name.casefold() for name in configured_offers if name}
    source_offer_keys = {name.casefold() for name in offers}
    configured_offers_without_source = sorted(
        name for name in configured_offers if name.casefold() not in source_offer_keys
    )
    admitted_events = 0
    admitted_revenue = Decimal("0")
    excluded_events = 0
    excluded_revenue = Decimal("0")
    excluded_offers = {}
    for name, slot in offers.items():
        if name.casefold() in allowed:
            admitted_events += slot["events"]
            admitted_revenue += slot["revenue"]
        else:
            excluded_events += slot["events"]
            excluded_revenue += slot["revenue"]
            excluded_offers[name] = {"events": slot["events"], "revenue": _float(slot["revenue"])}

    return {
        "events": sum(slot["events"] for slot in offers.values()),
        "revenue": _float(total_revenue),
        "offers": {
            name: {"events": slot["events"], "revenue": _float(slot["revenue"])}
            for name, slot in sorted(offers.items(), key=lambda item: -item[1]["revenue"])
        },
        "configured_offer_scope": {
            "admitted_events": admitted_events,
            "admitted_revenue": _float(admitted_revenue),
            "excluded_events": excluded_events,
            "excluded_revenue": _float(excluded_revenue),
            "excluded_offers": excluded_offers,
            "configured_offers_without_source": configured_offers_without_source,
            "status": (
                "no_matching_source_offers" if not admitted_events
                else "configured_offer_without_source" if configured_offers_without_source
                else "mixed_offers" if excluded_events
                else "matched_only"
            ),
        },
    }


def _meta_identity_map_for_audit(db: Session, account_id: str) -> tuple[set[str], dict[str, str], set[str], set[str]]:
    """Return scoped IDs plus known IDs owned by other accounts for audit only."""
    account_id = normalize_account_id(account_id)
    adsets = {
        str(row[0]) for row in db.query(FacebookAdSet.fb_adset_id)
        .filter(FacebookAdSet.fb_account_id == account_id, FacebookAdSet.fb_adset_id.isnot(None)).all()
    }
    campaigns = {
        str(row[0]) for row in db.query(FacebookCampaign.fb_campaign_id)
        .filter(FacebookCampaign.fb_account_id == account_id, FacebookCampaign.fb_campaign_id.isnot(None)).all()
    }
    ads = {
        str(ad_id): str(adset_id)
        for ad_id, adset_id in db.query(FacebookAd.fb_ad_id, FacebookAdSet.fb_adset_id)
        .join(FacebookAdSet, FacebookAd.adset_id == FacebookAdSet.id)
        .filter(FacebookAdSet.fb_account_id == account_id, FacebookAd.fb_ad_id.isnot(None), FacebookAdSet.fb_adset_id.isnot(None)).all()
    }
    all_ids = set()
    for model, field in (
        (FacebookAdSet, FacebookAdSet.fb_adset_id),
        (FacebookCampaign, FacebookCampaign.fb_campaign_id),
        (FacebookAd, FacebookAd.fb_ad_id),
    ):
        all_ids |= {str(row[0]) for row in db.query(field).filter(field.isnot(None)).all()}
    return adsets, ads, campaigns, all_ids - adsets - set(ads) - campaigns


# ---- Recovering ad sets for clicks whose {{adset.id}} macro arrived unexpanded ---------------------------------
# Meta expands {{ad.id}}/{{ad.name}}/{{placement}} but, on a small slice of Facebook mobile-feed clicks (~1% of
# conversions), leaves {{adset.id}}/{{campaign.id}} literal. RedTrack's copy of the same click (Everflow sub5 is the
# RedTrack click id) still holds the real ad id in its sub1, which maps to an ad set through our own ads table.
_RT_AD_ID_CACHE: dict[tuple[str, str], tuple[float, dict[str, str]]] = {}
RT_AD_ID_CACHE_TTL_SECONDS = 600
RT_FAILURE_BACKOFF_SECONDS = 60
_rt_last_failure = 0.0


def _internal_offer_names() -> set[str]:
    raw = os.getenv(PNL_INTERNAL_OFFERS_ENV)
    names = [n.strip().casefold() for n in raw.split(",")] if raw is not None else list(DEFAULT_INTERNAL_OFFERS)
    return {n for n in names if n}


_AD_ADSET_CACHE: dict[str, str] = {}   # ad id -> ad set id; an ad never moves between ad sets, so successes are kept for good
META_AD_LOOKUPS_PER_CALL = 30


_AD_LOOKUP_FAILED_AT: dict[str, float] = {}   # ad id -> when a lookup last failed (deleted/inaccessible ad); retried after 10 min
AD_LOOKUP_RETRY_SECONDS = 600
META_RATE_LIMIT_BACKOFF_SECONDS = 300
_meta_lookup_blocked_until = 0.0


def _meta_adsets_for_ads(ad_ids: set[str]) -> dict[str, str]:
    """Ask Meta which ad set owns each ad (for ads we never synced locally). Best effort, never raises.

    A failing ad (deleted / no access) is skipped and not retried for 10 minutes so it can't block the others; a Meta
    rate-limit response stops all lookups for 5 minutes. At most META_AD_LOOKUPS_PER_CALL Meta calls per invocation."""
    global _meta_lookup_blocked_until
    out = {a: _AD_ADSET_CACHE[a] for a in ad_ids if a in _AD_ADSET_CACHE}
    now = time.time()
    todo = [
        a for a in sorted(ad_ids)
        if a not in _AD_ADSET_CACHE and now - _AD_LOOKUP_FAILED_AT.get(a, 0.0) > AD_LOOKUP_RETRY_SECONDS
    ][:META_AD_LOOKUPS_PER_CALL]
    if not todo or now < _meta_lookup_blocked_until:
        return out
    try:
        svc = FacebookService()
        svc.initialize()
    except Exception as exc:  # noqa: BLE001
        logger.warning("P&L: Meta client unavailable for ad->ad set lookup: %s", exc)
        _meta_lookup_blocked_until = now + META_RATE_LIMIT_BACKOFF_SECONDS
        return out
    for ad_id in todo:
        try:
            adset_id = str(svc.api.call("GET", (ad_id,), params={"fields": "adset_id"}).json().get("adset_id") or "")
        except Exception as exc:  # noqa: BLE001
            message = str(exc).lower()
            if "request limit" in message or "rate limit" in message or "too many calls" in message or "code\": 17" in message or "code\": 4" in message:
                _meta_lookup_blocked_until = time.time() + META_RATE_LIMIT_BACKOFF_SECONDS
                logger.warning("P&L: Meta rate-limited the ad->ad set lookup; pausing it for %ds", META_RATE_LIMIT_BACKOFF_SECONDS)
                break
            _AD_LOOKUP_FAILED_AT[ad_id] = time.time()
            continue
        if META_ID_RE.fullmatch(adset_id):
            _AD_ADSET_CACHE[ad_id] = out[ad_id] = adset_id
        else:
            _AD_LOOKUP_FAILED_AT[ad_id] = time.time()
    return out


def _redtrack_ad_ids_by_click(start: date, end: date) -> dict[str, str]:
    """RedTrack click id -> Meta ad id for conversions in [start, end] (cached 10 min). Raises on failure."""
    key = (start.isoformat(), end.isoformat())
    now = time.time()
    hit = _RT_AD_ID_CACHE.get(key)
    if hit and now - hit[0] < RT_AD_ID_CACHE_TTL_SECONDS:
        return hit[1]
    global _rt_last_failure
    if now - _rt_last_failure < RT_FAILURE_BACKOFF_SECONDS:
        raise RuntimeError("RedTrack failed moments ago; not retrying yet")   # a down RedTrack must not add 30s to every page load
    svc = RedTrackService()
    if not svc.is_configured():
        raise RuntimeError("RedTrack is not configured")
    out: dict[str, str] = {}
    try:
        conversions = svc.get_raw_conversions(key[0], key[1])
    except Exception:
        _rt_last_failure = now
        raise
    for row in conversions:
        click_id = str(row.get("clickid") or "").strip()
        ad_id = str(row.get("sub1") or "").strip()
        if click_id and META_ID_RE.fullmatch(ad_id):
            out[click_id] = ad_id
    if len(_RT_AD_ID_CACHE) >= 8:
        _RT_AD_ID_CACHE.pop(min(_RT_AD_ID_CACHE, key=lambda k: _RT_AD_ID_CACHE[k][0]), None)
    _RT_AD_ID_CACHE[key] = (now, out)
    return out


def _recover_macro_adsets(db: Session, rows: list[dict]) -> list[dict]:
    """Return rows with sub3 replaced by the real ad set id wherever it can be recovered, else unchanged.

    Never raises: if RedTrack is down or the ad is unknown locally the row keeps its literal macro and is counted
    in the all-accounts bucket exactly as before.
    """
    pending = [r for r in rows if UNEXPANDED_META_MACRO_RE.fullmatch(str(r.get("sub3") or "").strip()) and str(r.get("sub5") or "").strip()]
    if not pending:
        return rows
    try:
        days = [EverflowService._conversion_date(r) for r in pending]
        ad_by_click = _redtrack_ad_ids_by_click(min(days) - timedelta(days=1), max(days) + timedelta(days=1))
        wanted = {ad_by_click[c] for c in (str(r.get("sub5")).strip() for r in pending) if c in ad_by_click}
        if not wanted:
            return rows
        adset_by_ad = {
            str(ad_id): str(adset_id)
            for ad_id, adset_id in db.query(FacebookAd.fb_ad_id, FacebookAdSet.fb_adset_id)
            .join(FacebookAdSet, FacebookAd.adset_id == FacebookAdSet.id)
            .filter(FacebookAd.fb_ad_id.in_(wanted), FacebookAdSet.fb_adset_id.isnot(None))
            .all()
        }
        missing = wanted - set(adset_by_ad)
        if missing:
            try:
                from_meta = _meta_adsets_for_ads(missing)
                # Only trust an ad set we also have locally, otherwise it could not be matched to an account anyway.
                known = {
                    str(r[0]) for r in db.query(FacebookAdSet.fb_adset_id).filter(FacebookAdSet.fb_adset_id.in_(set(from_meta.values()))).all()
                } if from_meta else set()
                adset_by_ad.update({a: ad_set for a, ad_set in from_meta.items() if ad_set in known})
            except Exception as exc:  # noqa: BLE001 — keep the locally recovered rows
                logger.warning("P&L: Meta fallback for missing ads failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 — recovery is best-effort, never fail the P&L over it
        logger.warning("P&L: could not recover ad sets for unexpanded-macro conversions: %s", exc)
        return rows
    pending_ids = {id(r) for r in pending}
    recovered = 0
    out = []
    for r in rows:
        if id(r) in pending_ids:
            adset = adset_by_ad.get(ad_by_click.get(str(r.get("sub5")).strip(), ""))
            if adset and META_ID_RE.fullmatch(adset):
                r = {**r, "sub3": adset}
                recovered += 1
        out.append(r)
    if recovered:
        logger.info("P&L: recovered the ad set for %d of %d unexpanded-macro conversions via RedTrack ad id", recovered, len(pending))
    return out


def _spend_for_account(account_id: str, start: date, end: date) -> Decimal:
    """Total Meta spend for the account over [start, end], in the account's own timezone.

    One ACCOUNT-level Insights row instead of every ad set's: RHO has ~570 ad sets, so the ad-set-level pull paged
    ~23 times and took ~14s per load (measured 2026-10-30). The account-level total matched the ad-set sum to the
    cent on 2026-10-26 (both $1,364.31 for the day). Raises on failure, so the P&L marks spend unavailable."""
    from concurrent.futures import ThreadPoolExecutor

    def pull():
        account = FacebookService()._get_account(account_id)
        rows = account.get_insights(
            fields=["spend"],
            params={"time_range": {"since": start.isoformat(), "until": end.isoformat()}, "level": "account"},
        )
        return [dict(row) for row in rows]

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        rows = pool.submit(pull).result(timeout=20)
    finally:
        pool.shutdown(wait=False)   # a timed-out pull is abandoned (read-only), never waited on
    return sum((_money(row.get("spend")) for row in rows), Decimal("0"))


def _spend_map(db: Session, start: date, end: date, known: dict[str, Decimal] | None = None) -> tuple[dict[str, Decimal], bool]:
    results = dict(known or {})
    incomplete = False
    for account_id in _active_account_ids(db):
        if account_id in results:
            continue
        try:
            results[account_id] = _spend_for_account(account_id, start, end)
        except Exception:
            incomplete = True
    return results, incomplete


# RedTrack is deliberately NOT a billable-revenue source (see
# _revenue_provider_for_account). It's still used elsewhere in the app
# (Campaign Performance ROAS, CAPI Match Quality performance-by-pixel) — this
# file just no longer pulls it in for the P&L's "Billable Revenue" number.


def _everflow_revenue_from_report(
    db: Session,
    account_id: str,
    report: dict,
) -> tuple[Decimal, int, int, str, bool, Decimal, dict]:
    adset_ids = {
        row[0]
        for row in db.query(FacebookAdSet.fb_adset_id)
        .filter(
            FacebookAdSet.fb_account_id == account_id,
            FacebookAdSet.fb_adset_id.isnot(None),
        )
        .all()
        if row[0]
    }

    by_adset = report.get("adsets") or {}

    # Ad-set-attributable ONLY, per account — NOT the offer-wide total any more.
    # Steve, 2026-09-09: RHO and RHO 4 both run the "Get Business Coverage" offer,
    # so the old "whole offer belongs to whichever account has it mapped" design
    # (see git history) would make both accounts claim the full portal total —
    # exactly the double-count risk that approach's own comment warned about.
    # Confirmed live same day: of ~$18.8k "Get Business Coverage" revenue this
    # MTD period, only $6,538.16 traces to RHO's own ad sets and $3,144.06 to
    # RHO 4's — the remaining ~$9.1k belongs to ad sets on OTHER Meta accounts
    # (RHO 5 - America First, ResourceHelpOnline) that aren't tracked in this
    # tool, so it's correctly excluded here rather than credited to either.
    # Trade-off accepted: this account's number no longer auto-reconciles to
    # the whole-offer Switchboard portal figure when the offer spans accounts
    # outside this tool — it reconciles to what's actually this account's own.
    matched = {aid: m for aid, m in by_adset.items() if aid in adset_ids}
    revenue = sum((_money(m.get("revenue")) for m in matched.values()), Decimal("0"))
    events = sum((int(m.get("events") or 0) for m in matched.values()), 0)
    event_breakdown: dict[str, dict] = {}
    for m in matched.values():
        for name, bucket in (m.get("event_breakdown") or {}).items():
            slot = event_breakdown.setdefault(name, {"events": 0, "revenue": Decimal("0")})
            slot["events"] += int(bucket.get("events") or 0)
            slot["revenue"] += _money(bucket.get("revenue"))

    return (revenue, events, len(adset_ids - set(matched)), "everflow_live", False,
            Decimal("0"), event_breakdown)


def _everflow_revenue(db: Session, account_id: str, start: date, end: date) -> tuple[Decimal, int, int, str, bool, Decimal, dict]:
    offer_names = _everflow_offer_names_for_account(account_id)
    if not offer_names:
        raise RuntimeError(f"{EVERFLOW_ACCOUNT_OFFERS_ENV} missing offer mapping for {account_id}")
    report = EverflowService().get_revenue_by_adset(start, end, offer_names=offer_names, row_transform=lambda rows: _recover_macro_adsets(db, rows))
    return _everflow_revenue_from_report(db, account_id, report)


def _revenue_for_account(
    db: Session,
    account_id: str,
    start: date,
    end: date,
) -> tuple[Decimal, int, int, str, bool, Decimal, dict]:
    provider = _revenue_provider_for_account(account_id)
    if provider == "everflow":
        try:
            return _everflow_revenue(db, account_id, start, end)
        except Exception:
            return Decimal("0"), 0, 0, "everflow_unavailable", True, Decimal("0"), {}
    if provider == "bhm_everflow":
        try:
            rows = _bhm_everflow_rows(db, _bhm_everflow_offer_map()[normalize_account_id(account_id)], start, end)
            report = EverflowService()._aggregate_rows(rows)
            return _with_source(_everflow_revenue_from_report(db, account_id, report), "bhm_everflow_live")
        except Exception as exc:  # noqa: BLE001
            logger.warning("BHM Everflow revenue failed for %s: %s", account_id, exc)
            return Decimal("0"), 0, 0, "bhm_everflow_unavailable", True, Decimal("0"), {}

    # No Everflow offer mapping for this account — billable revenue is
    # Everflow-only, so there's nothing to report, not a lower-trust estimate.
    return Decimal("0"), 0, 0, "not_tracked", False, Decimal("0"), {}


def _bhm_everflow_monthly_revenue_cache(
    db: Session,
    account_id: str,
    start: date,
    end: date,
) -> dict[str, tuple[Decimal, int, int, str, bool, Decimal, dict]]:
    rows = _bhm_everflow_rows(db, _bhm_everflow_offer_map()[normalize_account_id(account_id)], start, end)
    by_month: dict[str, list[dict]] = {}
    for row in rows:
        by_month.setdefault(EverflowService._conversion_month(row), []).append(row)
    out = {}
    for month_start, month_rows in by_month.items():
        report = EverflowService()._aggregate_rows(month_rows)
        out[month_start] = _with_source(_everflow_revenue_from_report(db, account_id, report), "bhm_everflow_live")
    return out


def _everflow_monthly_revenue_cache(
    db: Session,
    account_id: str,
    start: date,
    end: date,
) -> dict[str, tuple[Decimal, int, int, str, bool, Decimal, dict]]:
    offer_names = _everflow_offer_names_for_account(account_id)
    if not offer_names:
        raise RuntimeError(f"{EVERFLOW_ACCOUNT_OFFERS_ENV} missing offer mapping for {account_id}")
    reports = EverflowService().get_revenue_by_adset_by_month(start, end, offer_names=offer_names, row_transform=lambda rows: _recover_macro_adsets(db, rows))
    return {
        month_start: _everflow_revenue_from_report(db, account_id, report)
        for month_start, report in reports.items()
    }


def _cost_query(db: Session, account_id: str, start: date, end: date):
    return (
        db.query(PnlCostEntry)
        .filter(or_(PnlCostEntry.ad_account_id == account_id, PnlCostEntry.ad_account_id.is_(None)))
        .filter(PnlCostEntry.effective_from <= end)
        .filter(or_(PnlCostEntry.effective_to.is_(None), PnlCostEntry.effective_to >= start))
        .order_by(PnlCostEntry.created_at.desc())
    )


def _aggregate_cost_query(db: Session, account_ids: list[str], start: date, end: date):
    return (
        db.query(PnlCostEntry)
        .filter(or_(PnlCostEntry.ad_account_id.in_(account_ids), PnlCostEntry.ad_account_id.is_(None)))
        .filter(PnlCostEntry.effective_from <= end)
        .filter(or_(PnlCostEntry.effective_to.is_(None), PnlCostEntry.effective_to >= start))
        .order_by(PnlCostEntry.created_at.desc())
    )


def _allocation_share(
    entry: PnlCostEntry,
    account_id: str,
    spend: Decimal,
    all_spend: dict[str, Decimal],
) -> tuple[Decimal, str]:
    if entry.ad_account_id:
        return Decimal("1"), "account"

    # "full" charges the whole amount to the month rather than dividing it across
    # accounts. Steve's call 2026-07-29: seeing a third of a $350 bill reads as
    # wrong even when the arithmetic is right, and he works from one account. The
    # trade-off is that summing several accounts would count a full cost more than
    # once — fine while the P&L is read one account at a time.
    if entry.allocation_method == "full":
        return Decimal("1"), "full"

    active_spenders = {acct: amt for acct, amt in all_spend.items() if amt > 0}
    if entry.allocation_method == "even":
        accounts = list(active_spenders) or list(all_spend) or [account_id]
        return Decimal("1") / Decimal(len(accounts)), "even"

    total_spend = sum(active_spenders.values(), Decimal("0"))
    if total_spend > 0:
        return (spend / total_spend), "by_spend"

    accounts = list(all_spend) or [account_id]
    return Decimal("1") / Decimal(len(accounts)), "even_no_spend"


def _overlap_months(entry: PnlCostEntry, start: date, end: date) -> int:
    overlap_start = max(entry.effective_from, start)
    overlap_end = min(entry.effective_to or end, end)
    if overlap_end < overlap_start:
        return 0
    return (overlap_end.year - overlap_start.year) * 12 + overlap_end.month - overlap_start.month + 1


def _profit_share(entry: PnlCostEntry, profit_base: Decimal, percent: Decimal) -> Decimal:
    # The percent applies only to profit ABOVE the threshold (Abel, 2026-09-29:
    # $15k net on a $10k threshold pays 5% of $5k = $250). Base is net of every
    # non-commission cost, retainer included. No threshold = whole base.
    threshold = _money(entry.profit_threshold) if entry.profit_threshold is not None else Decimal("0")
    excess = max(profit_base - threshold, Decimal("0"))
    return (excess * percent / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)


def _resolve_costs(
    db: Session,
    account_id: str,
    start: date,
    end: date,
    spend: Decimal,
    revenue: Decimal,
    all_spend: dict[str, Decimal] | None = None,
) -> tuple[list[dict], Decimal]:
    entries = _cost_query(db, account_id, start, end).all()
    needs_allocation = any(entry.ad_account_id is None for entry in entries)
    if needs_allocation and all_spend is None:
        all_spend, _ = _spend_map(db, start, end, {account_id: spend})
    elif all_spend is None:
        all_spend = {account_id: spend}

    gross_profit = revenue - spend
    resolved = []
    non_profit_costs = Decimal("0")
    profit_entries = []

    for entry in entries:
        share, allocation_basis = _allocation_share(entry, account_id, spend, all_spend)
        amount = _money(entry.amount)
        if entry.cost_type == "pct_of_profit":
            profit_entries.append((entry, share, allocation_basis))
            continue
        if entry.cost_type == "pct_of_spend":
            resolved_amount = spend * amount / Decimal("100")
        elif entry.cost_type == "pct_of_revenue":
            resolved_amount = revenue * amount / Decimal("100")
        elif entry.cost_type == "pct_of_gross_profit":
            resolved_amount = max(gross_profit, Decimal("0")) * amount / Decimal("100")
        elif entry.cost_type == "recurring_monthly":
            resolved_amount = amount * share * Decimal(_overlap_months(entry, start, end))
        else:
            resolved_amount = amount * share
        resolved_amount = resolved_amount.quantize(CENT, rounding=ROUND_HALF_UP)
        non_profit_costs += resolved_amount
        resolved.append(_serialize_cost(entry, resolved_amount, share, allocation_basis))

    profit_base = revenue - spend - non_profit_costs
    for entry, share, allocation_basis in profit_entries:
        amount = _money(entry.amount)
        resolved_amount = _profit_share(entry, profit_base, amount)
        resolved.append(_serialize_cost(entry, resolved_amount, share, allocation_basis, profit_base=profit_base))

    total = sum((_money(item["resolved_amount"]) for item in resolved), Decimal("0"))
    return resolved, total


def _resolve_aggregate_costs(
    db: Session,
    account_ids: list[str],
    start: date,
    end: date,
    spend: Decimal,
    revenue: Decimal,
) -> tuple[list[dict], Decimal]:
    entries = _aggregate_cost_query(db, account_ids, start, end).all()

    gross_profit = revenue - spend
    resolved = []
    non_profit_costs = Decimal("0")
    profit_entries = []

    for entry in entries:
        amount = _money(entry.amount)
        share = Decimal("1")
        allocation_basis = "account" if entry.ad_account_id else "all_accounts_full"
        if entry.cost_type == "pct_of_profit":
            profit_entries.append((entry, allocation_basis))
            continue
        if entry.cost_type == "pct_of_spend":
            resolved_amount = spend * amount / Decimal("100")
        elif entry.cost_type == "pct_of_revenue":
            resolved_amount = revenue * amount / Decimal("100")
        elif entry.cost_type == "pct_of_gross_profit":
            resolved_amount = max(gross_profit, Decimal("0")) * amount / Decimal("100")
        elif entry.cost_type == "recurring_monthly":
            resolved_amount = amount * Decimal(_overlap_months(entry, start, end))
        else:
            resolved_amount = amount
        resolved_amount = resolved_amount.quantize(CENT, rounding=ROUND_HALF_UP)
        non_profit_costs += resolved_amount
        resolved.append(_serialize_cost(entry, resolved_amount, share, allocation_basis))

    profit_base = revenue - spend - non_profit_costs
    for entry, allocation_basis in profit_entries:
        amount = _money(entry.amount)
        resolved_amount = _profit_share(entry, profit_base, amount)
        resolved.append(_serialize_cost(entry, resolved_amount, Decimal("1"), allocation_basis, profit_base=profit_base))

    total = sum((_money(item["resolved_amount"]) for item in resolved), Decimal("0"))
    return resolved, total


def _serialize_cost(entry: PnlCostEntry, resolved_amount: Decimal, share: Decimal, allocation_basis: str, profit_base: Decimal | None = None) -> dict:
    return {
        "id": entry.id,
        "ad_account_id": normalize_account_id(entry.ad_account_id) if entry.ad_account_id else None,
        "label": entry.label,
        "category": entry.category,
        "cost_type": entry.cost_type,
        "amount": _float(entry.amount),
        "allocation_method": entry.allocation_method,
        "allocation_basis": allocation_basis,
        "allocation_share": float(share),
        "resolved_amount": _float(resolved_amount),
        "effective_from": entry.effective_from.isoformat(),
        "effective_to": entry.effective_to.isoformat() if entry.effective_to else None,
        "notes": entry.notes,
        "profit_threshold": _float(entry.profit_threshold) if entry.profit_threshold is not None else None,
        "vendor": entry.vendor,
        "source": entry.source,
        "profit_base": _float(profit_base) if profit_base is not None else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


def _summary(
    db: Session,
    account_id: str,
    start: date,
    end: date,
    label: str,
    spend_cache: dict[str, Decimal] | None = None,
    spend_cache_incomplete: bool = False,
    revenue_cache: dict[str, tuple[Decimal, int, int, str, bool, Decimal, dict]] | None = None,
    timings: dict[str, float] | None = None,
    snapshot: PnlMonthSnapshot | None = None,
    include_costs: bool = False,
) -> dict:
    data_incomplete = False
    errors = []
    spend_start = time.perf_counter()
    if snapshot is not None:
        # Closed month, already fetched once. Costs are still computed below from
        # the live ledger — only the external figures are frozen.
        spend = _money(snapshot.spend) if snapshot.spend is not None else None
    else:
        try:
            spend = spend_cache[account_id] if spend_cache and account_id in spend_cache else _spend_for_account(account_id, start, end)
        except Exception:
            spend = None
            data_incomplete = True
            errors.append("meta_spend_unavailable")
    if timings is not None:
        timings["meta_spend_ms"] = (time.perf_counter() - spend_start) * 1000

    revenue_start = time.perf_counter()
    if snapshot is not None:
        revenue = _money(snapshot.revenue) if snapshot.revenue is not None else None
        conversions = int(snapshot.conversions or 0)
        unmapped = int(snapshot.unmapped_adsets or 0)
        revenue_source = snapshot.revenue_source or "none"
        revenue_incomplete = False
        unattributed_revenue = _money(snapshot.unattributed_revenue)
        event_breakdown = snapshot.event_breakdown or []
    elif revenue_cache is not None:
        no_rows_source = "bhm_everflow_live" if _revenue_provider_for_account(account_id) == "bhm_everflow" else "everflow_live"
        revenue, conversions, unmapped, revenue_source, revenue_incomplete, unattributed_revenue, event_breakdown = revenue_cache.get(
            start.isoformat(),
            (Decimal("0"), 0, 0, no_rows_source, False, Decimal("0"), {}),
        )
    else:
        revenue, conversions, unmapped, revenue_source, revenue_incomplete, unattributed_revenue, event_breakdown = _revenue_for_account(
            db, account_id, start, end
        )
    if timings is not None:
        timings["revenue_ms"] = (time.perf_counter() - revenue_start) * 1000
    if revenue_incomplete:
        data_incomplete = True
        errors.append("bhm_everflow_unavailable" if revenue_source == "bhm_everflow_unavailable" else "everflow_live_unavailable")

    cost_start = time.perf_counter()
    costs = []
    total_costs = None
    net_profit = None
    margin = None
    roas = None
    gross_profit = revenue - spend if spend is not None and revenue is not None else None

    if spend is not None and revenue is not None:
        if include_costs:
            costs, total_costs = _resolve_costs(db, account_id, start, end, spend, revenue, spend_cache)
            net_profit = revenue - spend - total_costs
            margin = net_profit / revenue if revenue > 0 else None
        else:
            margin = gross_profit / revenue if revenue > 0 else None
        roas = revenue / spend if spend > 0 and revenue > 0 else None
    if timings is not None:
        timings["cost_resolution_ms"] = (time.perf_counter() - cost_start) * 1000

    return {
        "ad_account_id": account_id,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "period_label": label,
        "spend": _float(spend) if spend is not None else None,
        "revenue": _float(revenue) if revenue is not None else None,
        "gross_profit": _float(gross_profit) if gross_profit is not None else None,
        "conversions": conversions,
        "other_costs": _float(total_costs) if total_costs is not None else None,
        "net_profit": _float(net_profit) if net_profit is not None else None,
        "margin": float(margin) if margin is not None else None,
        "margin_type": "net" if include_costs else "gross",
        "scope": "account",
        "roas": float(roas) if roas is not None else None,
        "revenue_source": revenue_source,
        "unattributed_revenue": _float(unattributed_revenue),
        "from_snapshot": snapshot is not None,
        "synced_at": snapshot.synced_at.isoformat() if snapshot is not None and snapshot.synced_at else None,
        # A snapshot stores this already-serialised as a list; a live pull gives a
        # dict keyed by event name. Normalise both to the list shape.
        "event_breakdown": event_breakdown if isinstance(event_breakdown, list) else [
            {"event": name, "events": int(v.get("events") or 0), "revenue": _float(v.get("revenue"))}
            for name, v in (event_breakdown or {}).items()
        ],
        "unmapped_adsets": unmapped,
        "data_incomplete": data_incomplete,
        "errors": errors,
        "has_costs": len(costs) > 0,
        "costs": costs,
    }


def _combine_event_breakdowns(rows: list[dict]) -> list[dict]:
    combined: dict[str, dict] = {}
    for row in rows:
        for event in row.get("event_breakdown") or []:
            name = str(event.get("event") or "unknown").strip() or "unknown"
            slot = combined.setdefault(name, {"event": name, "events": 0, "revenue": Decimal("0")})
            slot["events"] += int(event.get("events") or 0)
            slot["revenue"] += _money(event.get("revenue"))
    return [
        {"event": name, "events": slot["events"], "revenue": _float(slot["revenue"])}
        for name, slot in sorted(combined.items(), key=lambda item: item[1]["revenue"], reverse=True)
    ]


def _aggregate_revenue_source(rows: list[dict]) -> str:
    sources = {row.get("revenue_source") or "none" for row in rows}
    if len(sources) == 1:
        return next(iter(sources))
    providers = {_snapshot_provider(source) or source for source in sources}
    if len(providers) == 1:
        return f"{next(iter(providers))}_mixed"
    return "mixed"


def _all_summary_from_account_rows(
    db: Session,
    account_ids: list[str],
    start: date,
    end: date,
    label: str,
    account_rows: list[dict],
    unknown_revenue: Decimal | None = None,
    unknown_ok: bool = True,
    foreign_revenue: Decimal | None = None,
    network_revenue: Decimal | None = None,
) -> dict:
    spend = sum((_money(row.get("spend")) for row in account_rows if row.get("spend") is not None), Decimal("0"))
    attributed_revenue = sum((_money(row.get("revenue")) for row in account_rows if row.get("revenue") is not None), Decimal("0"))
    # Revenue billed on a Meta CAMPAIGN id of a scoped account but not on any known ad set (broken tracking
    # macro, stale ad-set sync) — it ties to our Meta campaigns, so it is included in the total and reported
    # separately. Revenue with NO Meta id in sub3 is third-party network traffic and is deliberately left out
    # (Steve, 2026-10-24); see network_revenue below. Aug 2026 was short by $3,253.99 before the campaign-id
    # part was added.
    unknown_revenue = _money(unknown_revenue or 0)
    revenue = attributed_revenue + unknown_revenue
    gross_profit = revenue - spend
    costs, total_costs = _resolve_aggregate_costs(db, account_ids, start, end, spend, revenue)
    net_profit = gross_profit - total_costs
    data_incomplete = any(row.get("data_incomplete") or row.get("spend") is None or row.get("revenue") is None for row in account_rows)
    if not unknown_ok:
        # Couldn't reach Everflow for the unknown segment. Say so — reporting the
        # attributed-only total as if it were complete is how this understated
        # August in the first place.
        data_incomplete = True
    errors = []
    if not unknown_ok:
        errors.append("all:everflow_unknown_revenue_unavailable")
    for row in account_rows:
        account = row.get("ad_account_id")
        if row.get("spend") is None:
            errors.append(f"{account}:meta_spend_unavailable")
        if row.get("revenue") is None:
            errors.append(f"{account}:revenue_unavailable")
        for err in row.get("errors") or []:
            errors.append(f"{account}:{err}")

    return {
        "ad_account_id": "all",
        "account_ids": account_ids,
        "scope": "all",
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "period_label": label,
        "spend": _float(spend),
        "revenue": _float(revenue),
        "gross_profit": _float(gross_profit),
        "conversions": sum((int(row.get("conversions") or 0) for row in account_rows), 0),
        "other_costs": _float(total_costs),
        "net_profit": _float(net_profit),
        "margin": float(net_profit / revenue) if revenue > 0 else None,
        "margin_type": "net",
        "roas": float(revenue / spend) if spend > 0 and revenue > 0 else None,
        "revenue_source": _aggregate_revenue_source(account_rows),
        "attributed_revenue": _float(attributed_revenue),
        "unknown_revenue": _float(unknown_revenue),
        # Billed by Switchboard on these offers but traceable to ad sets outside
        # this aggregate's scope. Reported so the difference from the portal
        # total is explainable, deliberately NOT added to revenue.
        "foreign_revenue": _float(_money(foreign_revenue or 0)),
        # sub3 with no Meta id — third-party traffic through BHM's network. Reported so the gap to the
        # Switchboard portal total is explainable; deliberately NOT part of revenue, profit or commissions.
        "network_revenue": _float(_money(network_revenue or 0)),
        "unattributed_revenue": _float(sum((_money(row.get("unattributed_revenue")) for row in account_rows), Decimal("0"))),
        "from_snapshot": bool(account_rows) and all(row.get("from_snapshot") for row in account_rows),
        "synced_at": None,
        "event_breakdown": _combine_event_breakdowns(account_rows),
        "unmapped_adsets": sum((int(row.get("unmapped_adsets") or 0) for row in account_rows), 0),
        "data_incomplete": data_incomplete,
        "errors": errors,
        "has_costs": len(costs) > 0,
        "costs": costs,
    }


def _everflow_unknown_revenue(
    db: Session,
    account_ids: list[str],
    start: date,
    end: date,
) -> tuple[Decimal, bool, Decimal, Decimal]:
    """Billable Everflow revenue for the period that no scoped ad set can claim.

    Returns (unknown_revenue, ok, foreign_revenue, network_revenue).

    Counted as UNKNOWN — real money billed to us that ties to a scoped Meta campaign:
      * `sub3` holding a Meta CAMPAIGN id belonging to a scoped account. This is
        the broken-tracking-macro case — Aug 2026 had $1,306.67 of it across
        five RHO campaigns, unambiguously that account's revenue.

    Reported as NETWORK revenue and NOT added to the total (Steve, 2026-10-24: ignore
    anything that does not tie to the Meta campaigns — some of it is third-party
    traffic sent through BHM's network, separate from the internal media buying):
      * `sub3` missing, blank, or otherwise not a Meta id (e.g. `ThankYouPage`, `Email`) — BUT ONLY on an
        offer that carries outside traffic (Fast Auto Quote.org). On Get Business Coverage and Fast Business
        Quote (see PNL_INTERNAL_OFFERS_ENV) every conversion is ours and is counted as UNKNOWN. Previously this was counted as "unknown" and
        added to revenue, which inflated profit (and Abel's % of net profit base)
        with money the internal campaigns did not generate.

    Counted as UNKNOWN too (Steve, 2026-10-26): `sub3` still holding the literal Meta macro
    `{{adset.id}}`. Checked against RedTrack 2026-10-26: all 147 such October conversions carried a
    RedTrack click id belonging to our own "Commercial Insurance - RHO v1 / RHO 4 | ABO ..." campaigns
    (133 also had a Meta fbclid, referrers facebook.com / instagram.com) — our Meta traffic whose macro did
    not expand, not third-party traffic. It cannot be placed on an ad set, so it is all-accounts only.

    Deliberately EXCLUDED, because crediting it would overstate:
      * revenue already attributable to a known ad set — the per-account rows
        have it, and adding it here would double-count
      * a campaign id belonging to an account outside this aggregate's scope
      * a Meta id we recognise as neither ad set nor campaign. Most likely
        another account's ad set (the 2026-09-09 note records ~$9.1k/month of
        "Get Business Coverage" sitting on accounts this tool doesn't track).
        Returned as `foreign_revenue` so it is visible rather than silently
        dropped — never added to the total.

    Computed ONCE per period from raw conversions, never per account, so the
    2026-09-09 rule that per-account revenue stays ad-set-attributable only is
    untouched and no account can claim a shared offer twice. Because it reads
    raw rows rather than subtracting an attributed figure, it is also safe to
    combine with FROZEN per-account snapshots — it does not drift when ad sets
    sync after a month was snapshotted.
    """
    scope = {normalize_account_id(a) for a in account_ids}
    offer_names: set[str] = set()
    for account_id in _everflow_account_ids():
        if normalize_account_id(account_id) in scope:
            offer_names |= _everflow_offer_names_for_account(account_id)
    if not offer_names:
        return Decimal("0"), True, Decimal("0"), Decimal("0")

    try:
        svc = EverflowService()
        if not svc.is_configured():
            return Decimal("0"), False, Decimal("0"), Decimal("0")
        rows = _recover_macro_adsets(db, svc.get_raw_conversions(start, end))
    except Exception as exc:  # noqa: BLE001 — never fail the P&L over telemetry
        logger.warning("Everflow unknown-revenue lookup failed for %s..%s: %s", start, end, exc)
        return Decimal("0"), False, Decimal("0"), Decimal("0")

    allowed_offers = {name.casefold() for name in offer_names if name}
    known_adsets = {
        row[0] for row in db.query(FacebookAdSet.fb_adset_id)
        .filter(FacebookAdSet.fb_adset_id.isnot(None)).all() if row[0]
    }
    campaign_owner = {
        str(row[0]): normalize_account_id(row[1]) if row[1] else None
        for row in db.query(FacebookCampaign.fb_campaign_id, FacebookCampaign.fb_account_id)
        .filter(FacebookCampaign.fb_campaign_id.isnot(None)).all()
    }

    unknown = Decimal("0")
    foreign = Decimal("0")
    network = Decimal("0")
    macro_rows = 0
    internal_offers = _internal_offer_names()
    for row in rows:
        if allowed_offers and EverflowService._offer_name(row).casefold() not in allowed_offers:
            continue
        # Full precision, NOT _money() — rounding each row before summing drifts
        # from Switchboard's own total (3c over Aug 2026). Quantized once at the
        # end, matching how everflow_service aggregates.
        revenue = Decimal(str(row.get("revenue") or 0))
        sub3 = str(row.get("sub3") or "").strip()

        if UNEXPANDED_META_MACRO_RE.fullmatch(sub3):
            unknown += revenue          # our own Meta click whose {{adset.id}} macro never expanded (see below)
            macro_rows += 1
            continue
        if not META_ID_RE.fullmatch(sub3):
            if EverflowService._offer_name(row).casefold() in internal_offers:
                unknown += revenue      # an all-internal offer: every conversion is ours, tag or no tag
            else:
                network += revenue      # no Meta id on an offer that carries outside traffic — reported, never added
            continue
        if sub3 in known_adsets:
            continue                    # already in a per-account row
        owner = campaign_owner.get(sub3)
        if owner and owner in scope:
            unknown += revenue          # campaign id of a scoped account
        else:
            foreign += revenue          # someone else's, or unrecognised

    if macro_rows:
        logger.info("P&L %s..%s: %d conversions with an unexpanded {{adset.id}} macro counted in the all-accounts total", start, end, macro_rows)
    return (
        unknown.quantize(CENT, rounding=ROUND_HALF_UP),
        True,
        foreign.quantize(CENT, rounding=ROUND_HALF_UP),
        network.quantize(CENT, rounding=ROUND_HALF_UP),
    )


def _bhm_everflow_unplaced_revenue(db: Session, account_ids: list[str], start: date, end: date) -> tuple[Decimal, bool]:
    """BHM Everflow revenue from our internal affiliates that no ad set can claim (blank sub3, unrecovered macro, a
    scoped campaign id). The affiliate filter already makes it ours, so it counts in the all-accounts total, the same
    way every conversion on Get Business Coverage / Fast Business Quote does. A Meta id we cannot place in scope is
    left out, since the internal affiliates may also carry other internal buyers' accounts. Returns (revenue, ok)."""
    scope = {normalize_account_id(a) for a in account_ids}
    offers: set[str] = set()
    for account, account_offers in _bhm_everflow_offer_map().items():
        if account in scope:
            offers |= account_offers
    if not offers:
        return Decimal("0"), True
    try:
        rows = _bhm_everflow_rows(db, offers, start, end)
        known_adsets = {r[0] for r in db.query(FacebookAdSet.fb_adset_id).filter(FacebookAdSet.fb_adset_id.isnot(None)).all() if r[0]}
        scoped_campaigns = {
            str(r[0]) for r in db.query(FacebookCampaign.fb_campaign_id, FacebookCampaign.fb_account_id)
            .filter(FacebookCampaign.fb_campaign_id.isnot(None)).all()
            if r[1] and normalize_account_id(r[1]) in scope
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("BHM Everflow unplaced-revenue lookup failed for %s..%s: %s", start, end, exc)
        return Decimal("0"), False
    total = Decimal("0")
    for r in rows:
        sub3 = str(r.get("sub3") or "").strip()
        if sub3 in known_adsets:
            continue                 # already in that account's own row (or an out-of-scope account's)
        if META_ID_RE.fullmatch(sub3) and sub3 not in scoped_campaigns:
            continue                 # a Meta id we can't place in scope (e.g. another team's account) — never added
        total += Decimal(str(r.get("revenue") or 0))
    return total.quantize(CENT, rounding=ROUND_HALF_UP), True


# ---- Frozen all-accounts extras for closed months ------------------------------------------------------------
# The per-account figures of a closed month are already frozen in pnl_month_snapshots. The all-accounts segment
# (revenue tied to a scoped Meta campaign id, plus the reported-but-excluded network / foreign buckets) used to be
# re-pulled from Everflow on every load, so a paid month could keep moving. Steve, 2026-10-25: paid months are frozen.
# Stored as one more row in the same table under a reserved pseudo-account id — no schema change.
ALL_EXTRAS_SNAPSHOT_PREFIX = "__all_scope_extras__"
ALL_EXTRAS_RULE = "network-excluded-2026-10-24"
# Late conversions / clawbacks keep arriving for a few days after a month ends; the per-account figures freeze
# immediately, so the extras segment waits this long before freezing.
ALL_EXTRAS_FREEZE_GRACE_DAYS = 3


def _all_extras_snapshot_id(scope: list[str]) -> str:
    """One pseudo-account row per account SCOPE, so an admin's frozen month and a restricted user's never overwrite each other."""
    return f"{ALL_EXTRAS_SNAPSHOT_PREFIX}:{hashlib.sha1(','.join(scope).encode()).hexdigest()[:10]}"


def warm_current_month_cache() -> None:
    """Re-pull the current month's revenue rows in the background so a person opening the P&L reads them from the
    5-minute cache instead of waiting ~10s for Everflow (Steve, 2026-10-30: "90 seconds is way too long"). Runs every
    4 minutes from the scheduler. Only the current month: closed months are frozen and never re-pulled."""
    start, end, _ = _resolve_period("mtd")
    switchboard = EverflowService()
    if switchboard.is_configured():
        try:
            rows = switchboard._fetch_conversion_rows(start.isoformat(), end.isoformat(), 80, refresh=True)
            db = SessionLocal()
            try:
                _recover_macro_adsets(db, rows)   # warms the RedTrack click -> ad id map for these rows
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 — the BHM refresh below must still run
            logger.warning("P&L cache warm (Switchboard) failed: %s", exc)
    service = BhmEverflowService()
    if service.is_configured():
        for offers in _bhm_everflow_offer_map().values():
            for offer_id in offers:
                service._offer_rows(start, end, offer_id, 80, refresh=True)


def _closed_full_month(start: date, end: date, grace_days: int = 0) -> bool:
    """True for exactly one whole calendar month that ended at least `grace_days` ago (reporting timezone)."""
    last_day = calendar.monthrange(start.year, start.month)[1]
    return (
        start.day == 1
        and end == date(start.year, start.month, last_day)
        and end < today_in_rt_tz().replace(day=1)
        and today_in_rt_tz() >= end + timedelta(days=grace_days)
    )


def _account_snapshots_complete(db: Session, scope: list[str], start: date) -> bool:
    """True when every account in scope already has its own frozen snapshot for the month.

    The extras segment is classified against the local ad-set / campaign tables, so freezing it while an
    account's own figures are still live (e.g. an unsynced ad-set table) could lock in a misclassification.
    """
    have = {
        row[0] for row in db.query(PnlMonthSnapshot.ad_account_id)
        .filter(PnlMonthSnapshot.month == start, PnlMonthSnapshot.ad_account_id.in_(scope)).all()
    }
    return bool(scope) and set(scope) <= have


def _write_all_extras_snapshot(
    db: Session, scope: list[str], start: date, end: date,
    unknown: Decimal, foreign: Decimal, network: Decimal, current_user: User | None,
) -> None:
    snapshot_id = _all_extras_snapshot_id(scope)
    existing = (
        db.query(PnlMonthSnapshot)
        .filter(PnlMonthSnapshot.ad_account_id == snapshot_id, PnlMonthSnapshot.month == start)
        .first()
    )
    target = existing or PnlMonthSnapshot(ad_account_id=snapshot_id, month=start)
    target.date_from = start
    target.date_to = end
    target.spend = None
    target.revenue = unknown                  # campaign-id-tied revenue that still counts
    target.unattributed_revenue = network     # excluded network / third-party revenue (reported only)
    target.conversions = None
    target.revenue_source = "all_extras"
    target.unmapped_adsets = None
    target.event_breakdown = {"scope": scope, "rule": ALL_EXTRAS_RULE, "foreign_revenue": float(foreign)}
    target.synced_by = current_user.id if current_user is not None else None
    target.synced_at = datetime.now(timezone.utc)
    if existing is None:
        db.add(target)
    try:
        db.commit()
    except Exception:
        db.rollback()  # a snapshot is an optimisation, never a reason to fail the request
        logger.exception("pnl all-extras snapshot write failed month=%s", start.isoformat())


def _all_extras_for_period(
    db: Session, account_ids: list[str], start: date, end: date,
    current_user: User | None = None, *, refresh: bool = False,
) -> tuple[Decimal, bool, Decimal, Decimal]:
    """(unknown, ok, foreign, network) for the all-accounts view; frozen for closed full months.

    A closed month is read from its snapshot when one exists for the SAME account scope and revenue rule, and is
    never re-pulled from Everflow. It is WRITTEN only when the pull succeeded, the month ended 3+ days ago, and every
    account's own figures for that month are already frozen. `refresh=True` (the Re-fetch button) pulls again and
    overwrites. The current month is always live.
    """
    scope = sorted(normalize_account_id(a) for a in account_ids)
    closed = _closed_full_month(start, end)
    if closed and not refresh:
        snap = (
            db.query(PnlMonthSnapshot)
            .filter(PnlMonthSnapshot.ad_account_id == _all_extras_snapshot_id(scope), PnlMonthSnapshot.month == start)
            .first()
        )
        meta = snap.event_breakdown if snap is not None and isinstance(snap.event_breakdown, dict) else None
        if meta and meta.get("scope") == scope and meta.get("rule") == ALL_EXTRAS_RULE:
            return _money(snap.revenue), True, _money(meta.get("foreign_revenue")), _money(snap.unattributed_revenue)
    unknown, ok, foreign, network = _everflow_unknown_revenue(db, account_ids, start, end)
    bhm_unplaced, bhm_ok = _bhm_everflow_unplaced_revenue(db, account_ids, start, end)
    unknown += bhm_unplaced
    ok = ok and bhm_ok
    if (
        ok
        and _closed_full_month(start, end, ALL_EXTRAS_FREEZE_GRACE_DAYS)
        and _account_snapshots_complete(db, scope, start)
    ):
        _write_all_extras_snapshot(db, scope, start, end, unknown, foreign, network, current_user)
    return unknown, ok, foreign, network


def _summary_all(
    db: Session,
    current_user: User,
    start: date,
    end: date,
    label: str,
) -> dict:
    account_ids = _permitted_active_account_ids(db, current_user)
    if not account_ids:
        raise HTTPException(status_code=400, detail="No active ad accounts are available for P&L.")

    # Billable revenue is Everflow-only (see _revenue_provider_for_account) —
    # an account with no Everflow offer mapping resolves to $0/"not_tracked"
    # with no external call at all, so there's no shared batch pull to make
    # here any more.
    account_rows = [
        _account_summary_frozen_if_closed(db, account_id, start, end, label, current_user)
        for account_id in account_ids
    ]
    unknown_revenue, unknown_ok, foreign_revenue, network_revenue = _all_extras_for_period(db, account_ids, start, end, current_user)
    return _all_summary_from_account_rows(
        db, account_ids, start, end, label, account_rows,
        unknown_revenue=unknown_revenue, unknown_ok=unknown_ok,
        foreign_revenue=foreign_revenue,
        network_revenue=network_revenue,
    )


class CostEntryBody(BaseModel):
    ad_account_id: Optional[str] = None
    label: str = Field(..., min_length=1)
    category: str = "other"
    cost_type: str = "one_off"
    amount: Decimal = Field(..., ge=0)
    allocation_method: str = "by_spend"
    effective_from: date
    effective_to: Optional[date] = None
    notes: Optional[str] = None
    profit_threshold: Optional[Decimal] = Field(None, ge=0)
    vendor: Optional[str] = None
    source: str = "manual"


class CostEntryPatch(BaseModel):
    ad_account_id: Optional[str] = None
    label: Optional[str] = None
    category: Optional[str] = None
    cost_type: Optional[str] = None
    amount: Optional[Decimal] = Field(None, ge=0)
    allocation_method: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    notes: Optional[str] = None
    profit_threshold: Optional[Decimal] = Field(None, ge=0)
    vendor: Optional[str] = None
    source: Optional[str] = None


def _validate_cost_fields(data):
    if data.category and data.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {sorted(CATEGORIES)}")
    if data.cost_type and data.cost_type not in COST_TYPES:
        raise HTTPException(status_code=400, detail=f"cost_type must be one of {sorted(COST_TYPES)}")
    if data.allocation_method and data.allocation_method not in ALLOCATIONS:
        raise HTTPException(status_code=400, detail=f"allocation_method must be one of {sorted(ALLOCATIONS)}")
    if data.effective_to and data.effective_from and data.effective_to < data.effective_from:
        raise HTTPException(status_code=400, detail="effective_to must be after effective_from")
    if data.cost_type and data.cost_type.startswith("pct_of_") and data.amount is not None and data.amount > 100:
        raise HTTPException(status_code=400, detail="percent costs cannot exceed 100")


def _normalize_optional_account(current_user: User, ad_account_id: str | None) -> str | None:
    if not ad_account_id:
        if current_user.allowed_account_ids() is not None:
            raise HTTPException(status_code=403, detail="Only unrestricted users can create all-account cost entries.")
        return None
    return normalize_account_id(_resolve_scoped_default_account(current_user, ad_account_id))


def _assert_cost_entry_mutable(current_user: User, entry: PnlCostEntry):
    if entry.ad_account_id:
        _resolve_scoped_default_account(current_user, entry.ad_account_id)
    elif current_user.allowed_account_ids() is not None:
        raise HTTPException(status_code=403, detail="Only unrestricted users can modify all-account cost entries.")


@router.get("/summary")
def get_summary(
    ad_account_id: Optional[str] = Query(None),
    period: str = Query("mtd"),
    month: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:read")),
):
    account_id = _require_account(current_user, ad_account_id)
    start, end, label = _resolve_period(period, month, date_from, date_to)
    if account_id == "all":
        return _summary_all(db, current_user, start, end, label)
    return _account_summary_frozen_if_closed(db, account_id, start, end, label, current_user)


def _account_summary_frozen_if_closed(db: Session, account_id: str, start: date, end: date, label: str, current_user: User) -> dict:
    """Steve, 2026-10-30: a closed month's numbers are fixed unless he asks for a re-fetch. The months table already
    read frozen snapshots, but picking a single closed month (period=month) re-pulled Meta and Everflow every time
    (~15s). Same rule here: a whole closed month is served from its snapshot; if none exists yet, it is pulled once and
    frozen (when solid enough and 3+ days after month end). Re-fetch (POST /months/{month}/resync) is the only way to
    change a frozen month."""
    if not _closed_full_month(start, end):
        return _summary(db, account_id, start, end, label)
    snapshot = _snapshot_for_account_month(db, account_id, start)
    row = _summary(db, account_id, start, end, label, snapshot=snapshot)
    # Late conversions / clawbacks keep landing for a few days after month end, so a month is only frozen from here
    # once it ended ALL_EXTRAS_FREEZE_GRACE_DAYS ago (same grace as the all-accounts extras).
    if snapshot is None and _snapshot_eligible(row) and _closed_full_month(start, end, ALL_EXTRAS_FREEZE_GRACE_DAYS):
        _write_month_snapshot(db, account_id, start, end, row, current_user)
    return row


@router.get("/attribution-audit")
def get_attribution_audit(
    ad_account_id: str = Query(...),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:read")),
):
    """Read-only coverage audit for Switchboard billable-revenue attribution.

    This endpoint returns aggregates only. It intentionally does not expose
    conversion identifiers, click parameters, or any other raw-event data.
    """
    account_id = _require_account(current_user, ad_account_id)
    if account_id == "all":
        raise HTTPException(status_code=400, detail="Choose one ad account for an attribution audit.")
    if _revenue_provider_for_account(account_id) != "everflow":
        raise HTTPException(status_code=400, detail="This account has no configured Switchboard revenue source.")
    offers = _everflow_offer_names_for_account(account_id)
    if not offers:
        raise HTTPException(status_code=400, detail=f"{EVERFLOW_ACCOUNT_OFFERS_ENV} has no offer mapping for this account.")

    if bool(date_from) != bool(date_to):
        raise HTTPException(status_code=400, detail="date_from and date_to must be supplied together.")
    if date_from and date_to:
        try:
            start = datetime.strptime(date_from, "%Y-%m-%d").date()
            end = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from and date_to must be YYYY-MM-DD.")
    else:
        end = datetime.now(EVERFLOW_TZ_BY_ID[80]).date()
        start = end - timedelta(days=29)
    if end < start:
        raise HTTPException(status_code=400, detail="date_to must be on or after date_from.")
    if (end - start).days > 30:
        raise HTTPException(status_code=400, detail="Attribution audits are limited to 31 days per request.")

    now = time.time()
    expired_keys = [key for key, (created_at, _) in _attribution_audit_cache.items() if now - created_at >= AUDIT_CACHE_TTL_SECONDS]
    for key in expired_keys:
        _attribution_audit_cache.pop(key, None)
    cache_key = (account_id, start.isoformat(), end.isoformat())
    cached = _attribution_audit_cache.get(cache_key)
    if cached:
        return {**cached[1], "cached": True}

    service = EverflowService()
    if not service.is_configured():
        raise HTTPException(status_code=503, detail="Switchboard Everflow is not configured on this server.")
    try:
        rows = service.get_raw_conversions(start, end)
        source = _source_offer_breakdown(rows, offers)
        scoped_adsets, scoped_ads, scoped_campaigns, foreign_ids = _meta_identity_map_for_audit(db, account_id)
        audit = _audit_revenue_attribution(rows, offers, scoped_adsets, scoped_ads, scoped_campaigns, foreign_ids)
    except Exception as exc:  # noqa: BLE001 - source data must never be rendered as a clean $0 audit
        logger.warning("pnl.attribution_audit failed account=%s: %s", account_id, exc)
        raise HTTPException(status_code=502, detail="Switchboard attribution audit could not produce a complete source report.")

    payload = {
        "ad_account_id": account_id,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "timezone": "America/New_York",
        "offer_names": sorted(offers),
        "source_report": source,
        "meta_identity_counts": {
            "adsets": len(scoped_adsets),
            "ads": len(scoped_ads),
            "campaigns": len(scoped_campaigns),
        },
        "best_times_eligibility": {
            "status": "not_ready",
            "current_direct_everflow_field": "sub3",
            "reason": "This audit does not validate RedTrack timing coverage or upgrade Best Times confidence.",
        },
        "portal_reconciliation": {
            "status": "not_run",
            "reason": "Raw conversion coverage is not an independent comparison with the Switchboard portal total.",
        },
        "read_only": True,
        "cached": False,
        **audit,
    }
    if len(_attribution_audit_cache) >= AUDIT_CACHE_MAX_ENTRIES:
        oldest_key = min(_attribution_audit_cache, key=lambda key: _attribution_audit_cache[key][0])
        _attribution_audit_cache.pop(oldest_key, None)
    _attribution_audit_cache[cache_key] = (now, payload)
    return payload


def _snapshot_provider(revenue_source: str | None) -> str | None:
    """Which provider produced a stored month's revenue."""
    if not revenue_source:
        return None
    if revenue_source.startswith("everflow"):
        return "everflow"
    if revenue_source.startswith("bhm_everflow"):
        return "bhm_everflow"
    if revenue_source == "not_tracked":
        return "none"
    if revenue_source.startswith("redtrack"):
        # No longer a valid billable-revenue provider (see
        # _revenue_provider_for_account) — returned as its own tag, distinct
        # from "everflow"/"none", so an old RedTrack-sourced snapshot never
        # matches an account's current provider and always gets re-fetched.
        return "redtrack"
    return None


def _snapshot_eligible(row: dict) -> bool:
    """Whether a closed month's figures are solid enough to freeze.

    A frozen wrong number is worse than re-fetching a right one, so:

    - `revenue_source == "none"` is never frozen. It means no revenue rows were
      found at all, which is indistinguishable from the local ad-set table not
      having synced yet — freezing it would lock the month at $0 revenue.
    - a `cache_exact` hit IS frozen even though it carries data_incomplete. It is
      an exact-period match, i.e. real data. Excluding it meant any month whose
      live pull ever failed could never be frozen and got re-fetched on every
      load forever, which defeats the point for RedTrack accounts.
    - anything else incomplete (live source down, cache_fallback, missing spend)
      is left to re-fetch.
    """
    source = row.get("revenue_source") or "none"
    if source == "none" or row.get("spend") is None or row.get("revenue") is None:
        return False
    if source.endswith("cache_exact"):
        return True
    return not row.get("data_incomplete")


def _write_month_snapshot(db: Session, account_id: str, start: date, end: date, row: dict, current_user: User) -> None:
    """Freeze a closed month's external figures. Upserts on (account, month)."""
    existing = (
        db.query(PnlMonthSnapshot)
        .filter(PnlMonthSnapshot.ad_account_id == account_id, PnlMonthSnapshot.month == start)
        .first()
    )
    target = existing or PnlMonthSnapshot(ad_account_id=account_id, month=start)
    target.date_from = start
    target.date_to = end
    target.spend = row.get("spend")
    target.revenue = row.get("revenue")
    target.unattributed_revenue = row.get("unattributed_revenue")
    target.conversions = row.get("conversions")
    target.revenue_source = row.get("revenue_source")
    target.unmapped_adsets = row.get("unmapped_adsets")
    # Stored as the list shape the API already returns, so reads need no translation.
    target.event_breakdown = row.get("event_breakdown")
    target.synced_by = current_user.id
    target.synced_at = datetime.now(timezone.utc)
    if existing is None:
        db.add(target)
    try:
        db.commit()
    except Exception:
        # A snapshot is an optimisation, never a reason to fail the request — a
        # concurrent writer winning the unique constraint is fine.
        db.rollback()
        logger.exception("pnl.months snapshot write failed account=%s month=%s", account_id, start.isoformat())


def _snapshot_for_account_month(db: Session, account_id: str, start: date) -> PnlMonthSnapshot | None:
    stored = (
        db.query(PnlMonthSnapshot)
        .filter(PnlMonthSnapshot.ad_account_id == account_id, PnlMonthSnapshot.month == start)
        .first()
    )
    if stored and _snapshot_provider(stored.revenue_source) == _revenue_provider_for_account(account_id):
        return stored
    return None


def _get_months_all(
    db: Session,
    current_user: User,
    periods: list[tuple[date, date, str]],
) -> list[dict]:
    account_ids = _permitted_active_account_ids(db, current_user)
    if not account_ids:
        raise HTTPException(status_code=400, detail="No active ad accounts are available for P&L.")
    current_month = periods[0][0] if periods else today_in_rt_tz().replace(day=1)
    rows = []
    for start, end, label in periods:
        snapshots = {
            account_id: _snapshot_for_account_month(db, account_id, start)
            for account_id in account_ids
        } if start != current_month else {}
        use_snapshots = bool(snapshots) and all(snapshot is not None for snapshot in snapshots.values())
        account_rows = []
        for account_id in account_ids:
            snapshot = snapshots.get(account_id) if use_snapshots else None
            row = _summary(db, account_id, start, end, label, snapshot=snapshot, include_costs=False)
            if snapshot is None and start != current_month and _snapshot_eligible(row):
                _write_month_snapshot(db, account_id, start, end, row, current_user)
            account_rows.append(row)
        # Same unknown segment as /summary. Without this the trailing-window
        # table keeps understating closed months — which is exactly where the
        # Aug 2026 $42,191.52-vs-$45,445.51 gap was spotted. One Everflow read
        # per month shown; the per-account figures may be frozen snapshots, and
        # that is safe here because the unknown segment is derived from raw
        # conversions rather than by subtracting the attributed total.
        unknown_revenue, unknown_ok, foreign_revenue, network_revenue = _all_extras_for_period(db, account_ids, start, end, current_user)
        rows.append(_all_summary_from_account_rows(
            db, account_ids, start, end, label, account_rows,
            unknown_revenue=unknown_revenue, unknown_ok=unknown_ok,
            foreign_revenue=foreign_revenue,
            network_revenue=network_revenue,
        ))
    return rows


@router.get("/months")
def get_months(
    ad_account_id: Optional[str] = Query(None),
    limit: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:read")),
):
    request_start = time.perf_counter()
    account_id = _require_account(current_user, ad_account_id)
    today = today_in_rt_tz()
    start = today.replace(day=1)
    periods = []
    rows = []
    for i in range(limit):
        month_start = (start.replace(day=1) - timedelta(days=1)).replace(day=1) if i else start
        for _ in range(max(i - 1, 0)):
            month_start = (month_start - timedelta(days=1)).replace(day=1)
        period = "mtd" if i == 0 else "month"
        s, e, label = _resolve_period(period, month_start.strftime("%Y-%m"))
        periods.append((s, e, label))

    if account_id == "all":
        rows = _get_months_all(db, current_user, periods)
        logger.info(
            "pnl.months total account=all months=%d duration_ms=%.1f rows=%d",
            len(periods),
            (time.perf_counter() - request_start) * 1000,
            len(rows),
        )
        return rows

    # Closed months never change, so they are fetched once and frozen in
    # pnl_month_snapshots. Only the current month (periods[0], the MTD row) is
    # fetched live on every load. Costs are always recomputed from the ledger, so
    # adding a retainer still moves historic net profit.
    current_month = periods[0][0] if periods else None
    stored_rows = db.query(PnlMonthSnapshot).filter(
        PnlMonthSnapshot.ad_account_id == account_id,
        PnlMonthSnapshot.month.in_([s for s, _, _ in periods]),
    ).all() if periods else []
    # Drop any snapshot written by a different revenue provider than this account
    # now uses. Switching an account from RedTrack to Switchboard would otherwise
    # leave every closed month serving the old source's figures while the current
    # month showed the new one — the same page disagreeing with itself.
    active_provider = _revenue_provider_for_account(account_id)
    snapshots = {}
    stale_provider_months = []
    for row in stored_rows:
        if _snapshot_provider(row.revenue_source) == active_provider:
            snapshots[row.month] = row
        else:
            stale_provider_months.append(row.month)
    if stale_provider_months:
        logger.info(
            "pnl.months discarding %d snapshot(s) from a previous provider account=%s now=%s months=%s",
            len(stale_provider_months), account_id, active_provider,
            ",".join(m.isoformat() for m in stale_provider_months),
        )
    # Only months we still have to fetch need the external calls below.
    periods_to_fetch = [
        (s, e, label) for s, e, label in periods
        if s == current_month or s not in snapshots
    ]

    revenue_cache = None
    revenue_provider = active_provider
    if revenue_provider == "bhm_everflow" and periods_to_fetch:
        try:
            revenue_cache = _bhm_everflow_monthly_revenue_cache(
                db, account_id, min(s for s, _, _ in periods_to_fetch), max(e for _, e, _ in periods_to_fetch)
            )
        except Exception:
            logger.exception("pnl.months bhm_everflow_cache account=%s status=error", account_id)
            revenue_cache = {
                s.isoformat(): (Decimal("0"), 0, 0, "bhm_everflow_unavailable", True, Decimal("0"), {})
                for s, _, _ in periods_to_fetch
            }
    if revenue_provider == "everflow" and periods_to_fetch:
        cache_start = time.perf_counter()
        try:
            earliest = min(s for s, _, _ in periods_to_fetch)
            latest = max(e for _, e, _ in periods_to_fetch)
            revenue_cache = _everflow_monthly_revenue_cache(db, account_id, earliest, latest)
            logger.info(
                "pnl.months everflow_cache account=%s months=%d range=%s..%s duration_ms=%.1f status=ok",
                account_id,
                len(periods),
                earliest.isoformat(),
                latest.isoformat(),
                (time.perf_counter() - cache_start) * 1000,
            )
        except Exception:
            revenue_cache = {
                s.isoformat(): (Decimal("0"), 0, 0, "everflow_unavailable", True, Decimal("0"), {})
                for s, _, _ in periods_to_fetch
            }
            logger.exception(
                "pnl.months everflow_cache account=%s months=%d duration_ms=%.1f status=error",
                account_id,
                len(periods),
                (time.perf_counter() - cache_start) * 1000,
            )
    # revenue_provider == "none": no Everflow mapping, nothing to fetch —
    # revenue_cache stays None and _summary() resolves each period to
    # $0/"not_tracked" via _revenue_for_account with no external call.

    for s, e, label in periods:
        # Don't pre-build a cross-account spend map here. _summary only needs one
        # when the period actually has an all-account cost to allocate; building it
        # unconditionally costs one Meta call per account per month (24+ calls for
        # a 6-month history on 4 accounts) even when nothing needs allocating.
        month_start = time.perf_counter()
        timings: dict[str, float] = {}
        snapshot = snapshots.get(s) if s != current_month else None
        row = _summary(
            db, account_id, s, e, label,
            revenue_cache=revenue_cache, timings=timings, snapshot=snapshot,
        )
        # Freeze a closed month the first time it is fetched cleanly. Never the
        # current month, and never an incomplete result — a frozen bad number is
        # worse than re-fetching a good one.
        if snapshot is None and s != current_month and _snapshot_eligible(row):
            _write_month_snapshot(db, account_id, s, e, row, current_user)
        rows.append(row)
        logger.info(
            "pnl.months month account=%s label=%s range=%s..%s total_ms=%.1f meta_ms=%.1f revenue_ms=%.1f cost_ms=%.1f revenue_source=%s incomplete=%s errors=%s",
            account_id,
            label,
            s.isoformat(),
            e.isoformat(),
            (time.perf_counter() - month_start) * 1000,
            timings.get("meta_spend_ms", 0),
            timings.get("revenue_ms", 0),
            timings.get("cost_resolution_ms", 0),
            row.get("revenue_source"),
            row.get("data_incomplete"),
            ",".join(row.get("errors") or []) or "none",
        )
    logger.info(
        "pnl.months total account=%s months=%d duration_ms=%.1f provider=%s rows=%d",
        account_id,
        len(periods),
        (time.perf_counter() - request_start) * 1000,
        revenue_provider,
        len(rows),
    )
    return rows


@router.post("/months/{month}/resync")
def resync_month(
    month: str,
    ad_account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:write")),
):
    """Re-fetch one closed month and overwrite its frozen figures.

    Closed months are cached because they don't change. When they do — a
    correction upstream, a clawback, an account that wasn't tracked properly at
    the time — this is the escape hatch.
    """
    account_id = _require_account(current_user, ad_account_id)
    start, end = _month_bounds(month)
    current_month = today_in_rt_tz().replace(day=1)
    if start >= current_month:
        # `>=`, not `==`. A future month would sail past an equality check, return
        # empty from every source without erroring, and get frozen at $0 — then
        # served as fact once it rolled into the trailing window months later.
        raise HTTPException(
            status_code=400,
            detail="Only closed months can be resynced. The current month is always live.",
        )

    label = start.strftime("%B %Y")
    if account_id == "all":
        account_ids = _permitted_active_account_ids(db, current_user)
        if not account_ids:
            raise HTTPException(status_code=400, detail="No active ad accounts are available for P&L.")
        account_rows = []
        for scoped_account_id in account_ids:
            row = _summary(db, scoped_account_id, start, end, label, include_costs=False)
            if row.get("data_incomplete"):
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"{scoped_account_id} re-fetch came back incomplete ("
                        + (", ".join(row.get("errors") or []) or "unknown")
                        + "), so the stored figures were left alone. Try again shortly."
                    ),
                )
            _write_month_snapshot(db, scoped_account_id, start, end, row, current_user)
            row["from_snapshot"] = True
            account_rows.append(row)
        # Resync returns the same shape as /summary, so it needs the unknown
        # segment too — otherwise a resync would "correct" a month back down to
        # the attributed-only figure it was just fixed from.
        unknown_revenue, unknown_ok, foreign_revenue, network_revenue = _all_extras_for_period(db, account_ids, start, end, current_user, refresh=True)
        if not unknown_ok:
            raise HTTPException(
                status_code=502,
                detail="The per-account figures were re-fetched, but the all-accounts extras (Everflow) came back incomplete, "
                       "so those were left as they were. Try the re-fetch again shortly.",
            )
        return _all_summary_from_account_rows(
            db, account_ids, start, end, label, account_rows,
            unknown_revenue=unknown_revenue, unknown_ok=unknown_ok,
            foreign_revenue=foreign_revenue,
            network_revenue=network_revenue,
        )

    row = _summary(db, account_id, start, end, label)
    if row.get("data_incomplete"):
        raise HTTPException(
            status_code=502,
            detail=(
                "Re-fetch came back incomplete ("
                + (", ".join(row.get("errors") or []) or "unknown")
                + "), so the stored figures were left alone. Try again shortly."
            ),
        )
    _write_month_snapshot(db, account_id, start, end, row, current_user)
    return row


@router.get("/costs")
def list_costs(
    ad_account_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:read")),
):
    account_id = _require_account(current_user, ad_account_id)
    start, end = _month_bounds(month)
    if account_id == "all":
        summary = _summary_all(db, current_user, start, end, start.strftime("%B %Y"))
        return summary.get("costs") or []
    # _spend_for_account raises on Meta failure by design (so /summary can report
    # data_incomplete instead of a fake $0). The ledger is still worth rendering
    # without it — only the pct_of_spend rows degrade.
    try:
        spend = _spend_for_account(account_id, start, end)
    except Exception:
        spend = Decimal("0")
    revenue, _, _, _, _, _, _ = _revenue_for_account(db, account_id, start, end)
    costs, _ = _resolve_costs(db, account_id, start, end, spend, revenue)
    return costs


@router.post("/costs", status_code=status.HTTP_201_CREATED)
def create_cost(
    body: CostEntryBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:write")),
):
    _validate_cost_fields(body)
    entry = PnlCostEntry(
        ad_account_id=_normalize_optional_account(current_user, body.ad_account_id),
        label=body.label.strip(),
        category=body.category,
        cost_type=body.cost_type,
        amount=body.amount,
        allocation_method=body.allocation_method,
        effective_from=body.effective_from,
        # A one-off lands on a single date; pin the window so it can't repeat monthly.
        effective_to=body.effective_from if body.cost_type == "one_off" else body.effective_to,
        notes=body.notes,
        profit_threshold=body.profit_threshold if body.cost_type == "pct_of_profit" else None,
        vendor=body.vendor,
        source=body.source,
        created_by=current_user.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _serialize_cost(entry, _money(0), Decimal("1"), "created")


@router.patch("/costs/{entry_id}")
def update_cost(
    entry_id: str,
    body: CostEntryPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:write")),
):
    entry = db.query(PnlCostEntry).filter(PnlCostEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Cost entry not found")
    _assert_cost_entry_mutable(current_user, entry)
    _validate_cost_fields(body)
    data = body.dict(exclude_unset=True)
    if "ad_account_id" in data:
        entry.ad_account_id = _normalize_optional_account(current_user, data.pop("ad_account_id"))
    for key, value in data.items():
        if key == "label" and value is not None:
            value = value.strip()
        setattr(entry, key, value)
    if entry.cost_type != "pct_of_profit":
        entry.profit_threshold = None
    if entry.cost_type == "one_off":
        entry.effective_to = entry.effective_from
    if entry.effective_to and entry.effective_from and entry.effective_to < entry.effective_from:
        raise HTTPException(status_code=400, detail="effective_to must be after effective_from")
    if entry.cost_type.startswith("pct_of_") and entry.amount > 100:
        raise HTTPException(status_code=400, detail="percent costs cannot exceed 100")
    db.commit()
    db.refresh(entry)
    return _serialize_cost(entry, _money(0), Decimal("1"), "updated")


@router.delete("/costs/{entry_id}")
def delete_cost(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:write")),
):
    entry = db.query(PnlCostEntry).filter(PnlCostEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Cost entry not found")
    _assert_cost_entry_mutable(current_user, entry)
    db.delete(entry)
    db.commit()
    return {"deleted": True}
