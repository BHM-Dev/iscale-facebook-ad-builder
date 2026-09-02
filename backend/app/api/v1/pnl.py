import os
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.facebook import _resolve_scoped_default_account
from app.core.deps import require_permission
from app.database import get_db
from app.models import FacebookAdSet, PnlCostEntry, PnlMonthSnapshot, RedTrackCache, User, normalize_account_id
from app.services.everflow_service import EverflowService
from app.services.facebook_service import FacebookService
from app.services.redtrack_service import BASE_URL as REDTRACK_BASE_URL, RedTrackService, today_in_rt_tz

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


def _permitted_active_account_ids(db: Session, current_user: User) -> list[str]:
    active = set(_active_account_ids(db))
    allowed = current_user.allowed_account_ids()
    if allowed is not None:
        active &= {normalize_account_id(account_id) for account_id in allowed}
    return sorted(active)


def _everflow_account_ids() -> set[str]:
    raw = os.getenv(EVERFLOW_ACCOUNT_IDS_ENV, "")
    return {normalize_account_id(account.strip()) for account in raw.split(",") if account.strip()}


def _revenue_provider_for_account(account_id: str) -> str:
    return "everflow" if normalize_account_id(account_id) in _everflow_account_ids() else "redtrack"


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


def _spend_for_account(account_id: str, start: date, end: date) -> Decimal:
    insights = FacebookService().get_account_insights_bulk(
        ad_account_id=account_id,
        date_from=start.isoformat(),
        date_to=end.isoformat(),
    )
    return sum((_money(row.get("spend")) for row in insights.values()), Decimal("0"))


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


def _live_redtrack_report(start: date, end: date) -> dict:
    """Live RedTrack pull for an exact period.

    Deliberately not RedTrackService.get_report_by_adset(): that method returns {}
    on failure, which is indistinguishable from "no conversions" and would make us
    silently report $0 revenue instead of falling back to cache. We need the
    exception. Keep the request shape in sync with that method.
    """
    svc = RedTrackService()
    if not svc.is_configured():
        raise RuntimeError("REDTRACK_API_KEY not configured")
    resp = httpx.get(
        f"{REDTRACK_BASE_URL}/report",
        headers=svc._headers(),
        params={
            **svc._auth_params(),
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "group": "sub2",
        },
        timeout=15,
    )
    resp.raise_for_status()
    rows = resp.json()
    result = {}
    for row in (rows if isinstance(rows, list) else rows.get("data", [])):
        adset_id = str(row.get("sub2") or "").strip()
        if not adset_id or adset_id == "0":
            continue
        result[adset_id] = {
            "conversions": int(row.get("total_conversions") or 0),
            "revenue": round(float(row.get("total_revenue") or 0), 2),
        }
    return result


def _redtrack_adset_ids(db: Session, account_id: str) -> set[str]:
    return {
        row[0]
        for row in db.query(FacebookAdSet.fb_adset_id)
        .filter(
            FacebookAdSet.fb_account_id == account_id,
            FacebookAdSet.fb_adset_id.isnot(None),
        )
        .all()
        if row[0]
    }


def _redtrack_revenue_from_report(report: dict, adset_ids: set[str]) -> tuple[Decimal, int, int, str, bool]:
    filtered = {
        fb_adset_id: metrics
        for fb_adset_id, metrics in (report or {}).items()
        if fb_adset_id in adset_ids
    }
    revenue = sum((_money(metrics.get("revenue")) for metrics in filtered.values()), Decimal("0"))
    conversions = sum((int(metrics.get("conversions") or 0) for metrics in filtered.values()), 0)
    return revenue, conversions, len(adset_ids - set(filtered)), "live", False


def _redtrack_revenue_from_cache(
    db: Session,
    adset_ids: set[str],
    start: date,
    end: date,
) -> tuple[Decimal, int, int, str, bool]:
    exact_rows = (
        db.query(RedTrackCache)
        .filter(
            RedTrackCache.fb_adset_id.in_(list(adset_ids)),
            RedTrackCache.date_from == start,
            RedTrackCache.date_to == end,
        )
        .all()
    )
    rows = exact_rows
    # Only widen to a broader cached window (e.g. the 7-day preset) when the
    # REQUESTED range itself spans multiple days — there a wider cached window is
    # a defensible best-effort proxy. For a single-day request (start == end,
    # e.g. "today" or an early-month MTD view), the scheduler's only other
    # cached windows are for OTHER specific single days ("yesterday") or a
    # 7-day span — neither is a substitute for the exact day asked for, and
    # silently reporting the 7-day total AS that one day's revenue overstates it
    # by up to 7x while looking like real, current data. Confirmed live
    # 2026-09-02: this was the concrete mechanism behind Joel flagging Dashboard
    # numbers as "showing incorrect values" during a RedTrack rate-limit window.
    # Better to report unavailable than fabricate a plausible-looking number.
    if not rows and start != end:
        fallback_rows = (
            db.query(RedTrackCache)
            .filter(
                RedTrackCache.fb_adset_id.in_(list(adset_ids)),
                RedTrackCache.date_from <= end,
                RedTrackCache.date_to >= start,
            )
            .all()
        )
        by_adset = {}
        for row in fallback_rows:
            current = by_adset.get(row.fb_adset_id)
            current_span = (current.date_to - current.date_from).days if current else -1
            row_span = (row.date_to - row.date_from).days
            # Prefer the SMALLEST overlapping window, not the largest — a
            # tighter window is a closer approximation of the requested range.
            # (Previously preferred the largest span, which is how a single
            # cached last_7d row could dominate over a closer-fitting one.)
            if current is None or row_span < current_span or (row_span == current_span and row.synced_at > current.synced_at):
                by_adset[row.fb_adset_id] = row
        rows = list(by_adset.values())
    mapped = {row.fb_adset_id for row in rows}
    revenue = sum((_money(row.revenue) for row in rows), Decimal("0"))
    conversions = sum((row.conversions or 0) for row in rows)
    source = "cache_exact" if exact_rows else ("cache_fallback" if rows else "none")
    return revenue, conversions, len(adset_ids - mapped), source, True


def _redtrack_revenue(db: Session, account_id: str, start: date, end: date) -> tuple[Decimal, int, int, str, bool]:
    adset_ids = _redtrack_adset_ids(db, account_id)
    if not adset_ids:
        return Decimal("0"), 0, 0, "none", False

    try:
        return _redtrack_revenue_from_report(_live_redtrack_report(start, end), adset_ids)
    except Exception:
        pass

    return _redtrack_revenue_from_cache(db, adset_ids, start, end)


def _redtrack_monthly_revenue_cache(
    db: Session,
    account_id: str,
    periods: list[tuple[date, date, str]],
) -> dict[str, tuple[Decimal, int, int, str, bool, Decimal, dict]]:
    adset_ids = {
        adset_id
        for adset_id in _redtrack_adset_ids(db, account_id)
    }
    empty = (Decimal("0"), 0, 0, "none", False, Decimal("0"), {})
    if not periods:
        # ThreadPoolExecutor(max_workers=0) raises. get_months always passes at
        # least one period (limit has ge=1), but this is a general helper.
        return {}
    if not adset_ids:
        return {s.isoformat(): empty for s, _, _ in periods}

    results: dict[str, tuple[Decimal, int, int, str, bool, Decimal, dict]] = {}
    live_reports: dict[str, dict] = {}
    failed_periods: set[str] = set()

    # Measured 2026-07-29: six concurrent pulls made ~20% difference to wall time
    # (23.3s -> ~19s; Meta's six sequential calls dominate) but pushed months onto
    # cache_fallback and none that had previously come back live — RedTrack does not
    # like a six-way burst. Dropped to 3 that day; that still wasn't enough — real
    # production logs (2026-09-01) show recurring HTTP 429 "Too many requests" from
    # RedTrack roughly hourly, independent of and on top of the 30-min scheduled
    # cache-refresh job's own calls. Serialized fully (max_workers=1): this endpoint
    # is Month-Over-Month history, not a page a media buyer stares at waiting on —
    # a few extra seconds of load time is a much smaller cost than tripping the
    # account-wide rate limit that then also degrades the scheduler's own pulls and
    # every other page reading live RedTrack data.
    max_workers = 1

    def _pull(start: date, end: date) -> dict:
        try:
            return _live_redtrack_report(start, end)
        except Exception:
            # A 429 retried with zero delay lands in the same rate-limit window and
            # just gets 429'd again — this was making the burst worse, not better.
            time.sleep(2)
            return _live_redtrack_report(start, end)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_pull, s, e): (s, e, label)
            for s, e, label in periods
        }
        for future in as_completed(futures):
            s, e, label = futures[future]
            key = s.isoformat()
            try:
                live_reports[key] = future.result()
            except Exception:
                failed_periods.add(key)
                logger.exception(
                    "pnl.months redtrack_live period failed account=%s label=%s range=%s..%s",
                    account_id,
                    label,
                    s.isoformat(),
                    e.isoformat(),
                )

    for s, e, _ in periods:
        key = s.isoformat()
        if key in live_reports:
            revenue, conversions, unmapped, source, incomplete = _redtrack_revenue_from_report(live_reports[key], adset_ids)
        else:
            revenue, conversions, unmapped, source, incomplete = _redtrack_revenue_from_cache(db, adset_ids, s, e)
        redtrack_source = f"redtrack_{source}" if source != "none" else "none"
        results[key] = (revenue, conversions, unmapped, redtrack_source, incomplete, Decimal("0"), {})

    logger.info(
        "pnl.months redtrack_cache account=%s months=%d live_ok=%d live_failed=%d",
        account_id,
        len(periods),
        len(live_reports),
        len(failed_periods),
    )
    return results


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

    # Revenue is EVERYTHING the offer filter admits, per Steve 2026-07-29: the P&L
    # has to reconcile with the Switchboard portal he checks. Verified against
    # June 2026 (Pacific): ad-set-attributable $53,981.76 + $1,939.89 with no
    # usable sub3 = $55,921.65, which is the portal's Get Business Coverage total.
    # Reporting only the attributable part read ~3.5% light every month.
    #
    # SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS is what scopes revenue to an account
    # now, not the ad-set list. That holds only while each Everflow account maps
    # to its own offers — if two accounts ever share an offer, both would claim
    # the whole thing and this has to go back to ad-set scoping with the
    # remainder on its own line.
    # total_revenue is rounded once from full precision by the service. Re-summing
    # the per-ad-set values here would reintroduce the drift it exists to avoid.
    unattributed = _money(report.get("unattributed_revenue"))
    revenue = _money(report.get("total_revenue"))
    events = sum((int(m.get("events") or 0) for m in by_adset.values()), 0)
    events += int(report.get("unattributed_events") or 0)

    # Still reported so the split stays visible: how much of the above could not
    # be tied to an ad set, and how many of this account's ad sets saw nothing.
    return (revenue, events, len(adset_ids - set(by_adset)), "everflow_live", False,
            unattributed, report.get("event_breakdown") or {})


def _everflow_revenue(db: Session, account_id: str, start: date, end: date) -> tuple[Decimal, int, int, str, bool, Decimal, dict]:
    offer_names = _everflow_offer_names_for_account(account_id)
    if not offer_names:
        raise RuntimeError(f"{EVERFLOW_ACCOUNT_OFFERS_ENV} missing offer mapping for {account_id}")
    report = EverflowService().get_revenue_by_adset(start, end, offer_names=offer_names)
    return _everflow_revenue_from_report(db, account_id, report)


def _revenue_for_account(db: Session, account_id: str, start: date, end: date) -> tuple[Decimal, int, int, str, bool, Decimal, dict]:
    if _revenue_provider_for_account(account_id) == "everflow":
        try:
            return _everflow_revenue(db, account_id, start, end)
        except Exception:
            return Decimal("0"), 0, 0, "everflow_unavailable", True, Decimal("0"), {}

    revenue, conversions, unmapped, source, incomplete = _redtrack_revenue(db, account_id, start, end)
    redtrack_source = f"redtrack_{source}" if source != "none" else "none"
    # RedTrack has no payable-event split — it reports conversions, not event types.
    return revenue, conversions, unmapped, redtrack_source, incomplete, Decimal("0"), {}


def _everflow_monthly_revenue_cache(
    db: Session,
    account_id: str,
    start: date,
    end: date,
) -> dict[str, tuple[Decimal, int, int, str, bool, Decimal, dict]]:
    offer_names = _everflow_offer_names_for_account(account_id)
    if not offer_names:
        raise RuntimeError(f"{EVERFLOW_ACCOUNT_OFFERS_ENV} missing offer mapping for {account_id}")
    reports = EverflowService().get_revenue_by_adset_by_month(start, end, offer_names=offer_names)
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
        resolved_amount = (max(profit_base, Decimal("0")) * amount / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
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
        resolved_amount = (max(profit_base, Decimal("0")) * amount / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
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
        revenue, conversions, unmapped, revenue_source, revenue_incomplete, unattributed_revenue, event_breakdown = revenue_cache.get(
            start.isoformat(),
            (Decimal("0"), 0, 0, "everflow_live", False, Decimal("0"), {}),
        )
    else:
        revenue, conversions, unmapped, revenue_source, revenue_incomplete, unattributed_revenue, event_breakdown = _revenue_for_account(db, account_id, start, end)
    if timings is not None:
        timings["revenue_ms"] = (time.perf_counter() - revenue_start) * 1000
    if revenue_incomplete:
        data_incomplete = True
        errors.append("everflow_live_unavailable" if revenue_source == "everflow_unavailable" else "redtrack_live_unavailable")

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
) -> dict:
    spend = sum((_money(row.get("spend")) for row in account_rows if row.get("spend") is not None), Decimal("0"))
    revenue = sum((_money(row.get("revenue")) for row in account_rows if row.get("revenue") is not None), Decimal("0"))
    gross_profit = revenue - spend
    costs, total_costs = _resolve_aggregate_costs(db, account_ids, start, end, spend, revenue)
    net_profit = gross_profit - total_costs
    data_incomplete = any(row.get("data_incomplete") or row.get("spend") is None or row.get("revenue") is None for row in account_rows)
    errors = []
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
    account_rows = [_summary(db, account_id, start, end, label, include_costs=False) for account_id in account_ids]
    return _all_summary_from_account_rows(db, account_ids, start, end, label, account_rows)


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
    return _summary(db, account_id, start, end, label)


def _snapshot_provider(revenue_source: str | None) -> str | None:
    """Which provider produced a stored month's revenue."""
    if not revenue_source:
        return None
    if revenue_source.startswith("everflow"):
        return "everflow"
    if revenue_source.startswith("redtrack"):
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
        rows.append(_all_summary_from_account_rows(db, account_ids, start, end, label, account_rows))
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
    elif revenue_provider == "redtrack" and periods_to_fetch:
        cache_start = time.perf_counter()
        revenue_cache = _redtrack_monthly_revenue_cache(db, account_id, periods_to_fetch)
        logger.info(
            "pnl.months redtrack_cache account=%s months=%d duration_ms=%.1f status=ok",
            account_id,
            len(periods),
            (time.perf_counter() - cache_start) * 1000,
        )

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
        return _all_summary_from_account_rows(db, account_ids, start, end, label, account_rows)

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
        effective_to=body.effective_to,
        notes=body.notes,
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
