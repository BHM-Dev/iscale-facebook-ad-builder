import os
import json
from datetime import date, datetime, timedelta
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
from app.models import FacebookAdSet, PnlCostEntry, RedTrackCache, User, normalize_account_id
from app.services.everflow_service import EverflowService
from app.services.facebook_service import FacebookService
from app.services.redtrack_service import BASE_URL as REDTRACK_BASE_URL, RedTrackService, today_in_rt_tz

router = APIRouter()


CATEGORIES = {"labor", "tooling", "creative", "data", "other"}
COST_TYPES = {
    "one_off",
    "recurring_monthly",
    "pct_of_spend",
    "pct_of_revenue",
    "pct_of_gross_profit",
    "pct_of_profit",
}
ALLOCATIONS = {"by_spend", "even"}
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
    resolved = _resolve_scoped_default_account(current_user, ad_account_id)
    if not resolved:
        raise HTTPException(status_code=400, detail="ad_account_id is required for P&L.")
    return normalize_account_id(resolved)


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


def _redtrack_revenue(db: Session, account_id: str, start: date, end: date) -> tuple[Decimal, int, int, str, bool]:
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
    if not adset_ids:
        return Decimal("0"), 0, 0, "none", False

    try:
        report = _live_redtrack_report(start, end)
        filtered = {
            fb_adset_id: metrics
            for fb_adset_id, metrics in (report or {}).items()
            if fb_adset_id in adset_ids
        }
        revenue = sum((_money(metrics.get("revenue")) for metrics in filtered.values()), Decimal("0"))
        conversions = sum((int(metrics.get("conversions") or 0) for metrics in filtered.values()), 0)
        return revenue, conversions, len(adset_ids - set(filtered)), "live", False
    except Exception:
        pass

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
    if not rows:
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
            if current is None or row_span > current_span or (row_span == current_span and row.synced_at > current.synced_at):
                by_adset[row.fb_adset_id] = row
        rows = list(by_adset.values())
    mapped = {row.fb_adset_id for row in rows}
    revenue = sum((_money(row.revenue) for row in rows), Decimal("0"))
    conversions = sum((row.conversions or 0) for row in rows)
    source = "cache_exact" if exact_rows else ("cache_fallback" if rows else "none")
    return revenue, conversions, len(adset_ids - mapped), source, True


def _everflow_revenue_from_report(
    db: Session,
    account_id: str,
    report: dict,
) -> tuple[Decimal, int, int, str, bool, Decimal]:
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

    # Scope to THIS account's ad sets. The Everflow key is not account-scoped — it
    # returns every Meta-shaped sub3 it can see — so summing it unfiltered reports
    # the same total for every account in the allow-list. Mirrors _redtrack_revenue.
    filtered = {aid: metrics for aid, metrics in by_adset.items() if aid in adset_ids}

    # Revenue on Meta-shaped ad sets that aren't in this account's local ad-set
    # list. Real money, but not attributable here — surfaced separately rather
    # than silently added to this account or silently dropped.
    foreign = {aid: metrics for aid, metrics in by_adset.items() if aid not in adset_ids}
    foreign_revenue = sum((_money(m.get("revenue")) for m in foreign.values()), Decimal("0"))

    unattributed = _money(report.get("unattributed_revenue")) + foreign_revenue
    revenue = sum((_money(metrics.get("revenue")) for metrics in filtered.values()), Decimal("0"))
    events = sum((int(metrics.get("events") or 0) for metrics in filtered.values()), 0)
    return revenue, events, len(adset_ids - set(filtered)), "everflow_live", False, unattributed


def _everflow_revenue(db: Session, account_id: str, start: date, end: date) -> tuple[Decimal, int, int, str, bool, Decimal]:
    offer_names = _everflow_offer_names_for_account(account_id)
    if not offer_names:
        raise RuntimeError(f"{EVERFLOW_ACCOUNT_OFFERS_ENV} missing offer mapping for {account_id}")
    report = EverflowService().get_revenue_by_adset(start, end, offer_names=offer_names)
    return _everflow_revenue_from_report(db, account_id, report)


def _revenue_for_account(db: Session, account_id: str, start: date, end: date) -> tuple[Decimal, int, int, str, bool, Decimal]:
    if _revenue_provider_for_account(account_id) == "everflow":
        try:
            return _everflow_revenue(db, account_id, start, end)
        except Exception:
            return Decimal("0"), 0, 0, "everflow_unavailable", True, Decimal("0")

    revenue, conversions, unmapped, source, incomplete = _redtrack_revenue(db, account_id, start, end)
    redtrack_source = f"redtrack_{source}" if source != "none" else "none"
    return revenue, conversions, unmapped, redtrack_source, incomplete, Decimal("0")


def _everflow_monthly_revenue_cache(
    db: Session,
    account_id: str,
    start: date,
    end: date,
) -> dict[str, tuple[Decimal, int, int, str, bool, Decimal]]:
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


def _allocation_share(
    entry: PnlCostEntry,
    account_id: str,
    spend: Decimal,
    all_spend: dict[str, Decimal],
) -> tuple[Decimal, str]:
    if entry.ad_account_id:
        return Decimal("1"), "account"

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
    revenue_cache: dict[str, tuple[Decimal, int, int, str, bool, Decimal]] | None = None,
) -> dict:
    data_incomplete = False
    errors = []
    try:
        spend = spend_cache[account_id] if spend_cache and account_id in spend_cache else _spend_for_account(account_id, start, end)
    except Exception:
        spend = None
        data_incomplete = True
        errors.append("meta_spend_unavailable")

    if revenue_cache is not None:
        revenue, conversions, unmapped, revenue_source, revenue_incomplete, unattributed_revenue = revenue_cache.get(
            start.isoformat(),
            (Decimal("0"), 0, 0, "everflow_live", False, Decimal("0")),
        )
    else:
        revenue, conversions, unmapped, revenue_source, revenue_incomplete, unattributed_revenue = _revenue_for_account(db, account_id, start, end)
    if revenue_incomplete:
        data_incomplete = True
        errors.append("everflow_live_unavailable" if revenue_source == "everflow_unavailable" else "redtrack_live_unavailable")

    costs = []
    total_costs = None
    net_profit = None
    margin = None
    roas = None
    has_all_account_cost = _cost_query(db, account_id, start, end).filter(PnlCostEntry.ad_account_id.is_(None)).first() is not None
    if has_all_account_cost and spend_cache_incomplete:
        data_incomplete = True
        errors.append("all_account_spend_allocation_incomplete")

    if spend is not None and revenue is not None:
        all_spend = spend_cache
        if all_spend is None and has_all_account_cost:
            all_spend, allocation_incomplete = _spend_map(db, start, end, {account_id: spend})
            if allocation_incomplete:
                data_incomplete = True
                errors.append("all_account_spend_allocation_incomplete")
        costs, total_costs = _resolve_costs(db, account_id, start, end, spend, revenue, all_spend)
        net_profit = revenue - spend - total_costs
        margin = net_profit / revenue if revenue > 0 else None
        roas = revenue / spend if spend > 0 and revenue > 0 else None

    return {
        "ad_account_id": account_id,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "period_label": label,
        "spend": _float(spend) if spend is not None else None,
        "revenue": _float(revenue) if revenue is not None else None,
        "conversions": conversions,
        "other_costs": _float(total_costs) if total_costs is not None else None,
        "net_profit": _float(net_profit) if net_profit is not None else None,
        "margin": float(margin) if margin is not None else None,
        "roas": float(roas) if roas is not None else None,
        "revenue_source": revenue_source,
        "unattributed_revenue": _float(unattributed_revenue),
        "unmapped_adsets": unmapped,
        "data_incomplete": data_incomplete,
        "errors": errors,
        "has_costs": len(costs) > 0,
        "costs": costs,
    }


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
    return _summary(db, account_id, start, end, label)


@router.get("/months")
def get_months(
    ad_account_id: Optional[str] = Query(None),
    limit: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:read")),
):
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

    revenue_cache = None
    if _revenue_provider_for_account(account_id) == "everflow" and periods:
        try:
            earliest = min(s for s, _, _ in periods)
            latest = max(e for _, e, _ in periods)
            revenue_cache = _everflow_monthly_revenue_cache(db, account_id, earliest, latest)
        except Exception:
            revenue_cache = {
                s.isoformat(): (Decimal("0"), 0, 0, "everflow_unavailable", True, Decimal("0"))
                for s, _, _ in periods
            }

    for s, e, label in periods:
        # Don't pre-build a cross-account spend map here. _summary only needs one
        # when the period actually has an all-account cost to allocate; building it
        # unconditionally costs one Meta call per account per month (24+ calls for
        # a 6-month history on 4 accounts) even when nothing needs allocating.
        rows.append(_summary(db, account_id, s, e, label, revenue_cache=revenue_cache))
    return rows


@router.get("/costs")
def list_costs(
    ad_account_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:read")),
):
    account_id = _require_account(current_user, ad_account_id)
    start, end = _month_bounds(month)
    # _spend_for_account raises on Meta failure by design (so /summary can report
    # data_incomplete instead of a fake $0). The ledger is still worth rendering
    # without it — only the pct_of_spend rows degrade.
    try:
        spend = _spend_for_account(account_id, start, end)
    except Exception:
        spend = Decimal("0")
    revenue, _, _, _, _, _ = _revenue_for_account(db, account_id, start, end)
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
