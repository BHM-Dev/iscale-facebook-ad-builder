import logging
import time
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Brand, Product, GeneratedAd, WinningAd, FacebookCampaign, FacebookAdSet
from app.services.facebook_service import FacebookService
from app.services.everflow_service import EverflowService
from datetime import date, timedelta
from app.core.deps import get_current_active_user
from app.api.v1.facebook import _resolve_scoped_default_account

router = APIRouter()
logger = logging.getLogger(__name__)


# A trend refresh can otherwise make several raw Everflow calls for the same
# account/range (especially while Joel switches between the trend tabs). This
# is deliberately a short, bounded read cache: it never persists revenue or
# changes P&L's authoritative calculation.
TREND_REVENUE_CACHE_TTL_SECONDS = 300
TREND_REVENUE_CACHE_MAX_ENTRIES = 24
_trend_revenue_cache: dict[tuple, tuple[float, float, dict]] = {}
# Daily Trend already uses the RedTrack Pacific calendar for its date presets.
# Use that same calendar for the Switchboard pull so a displayed day has one
# reporting boundary. P&L intentionally stays in Everflow Eastern and is not
# changed by this dashboard-only choice.
TREND_TIMEZONE_ID = 90

# These are read-through, process-local caches for the Dashboard's expensive
# aggregate Meta calls. They deliberately stay small and short-lived: a normal
# reload feels immediate, while Refresh and Sync can always request a new pull.
DASHBOARD_LIVE_CACHE_TTL_SECONDS = 60
DASHBOARD_HISTORICAL_CACHE_TTL_SECONDS = 300
DASHBOARD_CACHE_MAX_ENTRIES = 48
_niche_summary_cache: dict[tuple, tuple[float, float, list[dict]]] = {}
_trend_cache: dict[tuple, tuple[float, float, dict]] = {}


def _dashboard_cache_ttl(date_preset: str, date_to: str | None) -> int:
    """Use the shorter TTL whenever a range includes the current RT calendar day."""
    from app.services.redtrack_service import today_in_rt_tz

    if date_preset == "today" or date_to == today_in_rt_tz().isoformat():
        return DASHBOARD_LIVE_CACHE_TTL_SECONDS
    return DASHBOARD_HISTORICAL_CACHE_TTL_SECONDS


def _read_dashboard_cache(cache: dict, key: tuple, ttl_seconds: int, refresh: bool):
    if refresh:
        return None
    now = time.monotonic()
    entry = cache.get(key)
    if entry and now - entry[0] < ttl_seconds:
        return deepcopy(entry[2])
    if entry:
        cache.pop(key, None)
    return None


def _write_dashboard_cache(cache: dict, key: tuple, value, request_started_at: float) -> None:
    # A slower request that began before a manual Refresh must never overwrite
    # the newer answer after it returns.
    existing = cache.get(key)
    if existing and existing[1] > request_started_at:
        return
    cache[key] = (time.monotonic(), request_started_at, deepcopy(value))
    # Bound memory and remove expired values opportunistically. Using insertion
    # order is sufficient here; values are short-lived request results, not a
    # persistent cache.
    if len(cache) > DASHBOARD_CACHE_MAX_ENTRIES:
        for stale_key, _ in sorted(cache.items(), key=lambda item: item[1][0])[:len(cache) - DASHBOARD_CACHE_MAX_ENTRIES]:
            cache.pop(stale_key, None)


def _exact_daily_billable_revenue(
    rows: list[dict],
    offer_names: set[str],
    scoped_adset_ids: set[str],
) -> dict[str, Decimal]:
    """Bucket only billable rows with the current P&L's exact sub3 mapping.

    A numeric Meta ID in another sub, a campaign ID, or an unexpanded macro is
    useful audit evidence but not safe account revenue. Daily reporting follows
    the same exact-ad-set rule as P&L so it cannot make a campaign look more
    profitable by allocating ambiguous Switchboard events.
    """
    allowed_offers = {name.casefold() for name in offer_names if name}
    daily: dict[str, Decimal] = {}
    for row in rows:
        if EverflowService._offer_name(row).casefold() not in allowed_offers:
            continue
        if str(row.get("sub3") or "").strip() not in scoped_adset_ids:
            continue
        raw_revenue = row.get("revenue")
        try:
            if raw_revenue in (None, ""):
                raise InvalidOperation
            revenue = Decimal(str(raw_revenue))
            if not revenue.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("Switchboard returned an exact-mapped conversion with invalid revenue") from exc
        day = EverflowService._conversion_date(row, TREND_TIMEZONE_ID).isoformat()
        daily[day] = daily.get(day, Decimal("0")) + revenue
    # Preserve raw precision until period totals are computed. FastAPI encodes
    # Decimals for the response, while the frontend formats dollars to cents.
    return daily


def _daily_billable_revenue(
    db: Session,
    account_id: str,
    start: date,
    end: date,
    refresh: bool = False,
    request_started_at: float | None = None,
) -> dict:
    """Return daily Switchboard revenue or an explicit unavailable state.

    Importing these two policy helpers keeps this dashboard surface tied to the
    P&L's deliberately strict account/offer configuration instead of silently
    inventing a second revenue-attribution contract.
    """
    from app.api.v1.pnl import _everflow_offer_names_for_account, _revenue_provider_for_account

    if _revenue_provider_for_account(account_id) != "everflow":
        return {"status": "not_tracked", "daily": {}}
    offer_names = _everflow_offer_names_for_account(account_id)
    if not offer_names:
        return {"status": "unavailable", "daily": {}}

    adset_ids = {
        str(value)
        for (value,) in db.query(FacebookAdSet.fb_adset_id)
        .filter(FacebookAdSet.fb_account_id == account_id, FacebookAdSet.fb_adset_id.isnot(None))
        .all()
        if value
    }
    if not adset_ids:
        # A local Meta sync gap must not be presented as $0 billable revenue.
        # New or externally-created ad sets can have spend before this app has
        # recorded their IDs, so exact attribution is not possible yet.
        return {"status": "needs_adset_sync", "daily": {}, "cached": False}

    # Include current attribution inputs in the cache key. A Meta sync or an
    # offer-map change therefore cannot keep serving a stale $0/incomplete
    # result for the cache TTL.
    cache_key = (
        account_id,
        start.isoformat(),
        end.isoformat(),
        tuple(sorted(adset_ids)),
        tuple(sorted(name.casefold() for name in offer_names)),
    )
    now = time.monotonic()
    request_started_at = request_started_at if request_started_at is not None else now
    for key, (created_at, _, _) in list(_trend_revenue_cache.items()):
        if now - created_at >= TREND_REVENUE_CACHE_TTL_SECONDS:
            _trend_revenue_cache.pop(key, None)
    cached = _trend_revenue_cache.get(cache_key)
    if cached and not refresh:
        return {**cached[2], "cached": True}

    service = EverflowService()
    if not service.is_configured():
        return {"status": "unavailable", "daily": {}}
    try:
        daily = _exact_daily_billable_revenue(
            service.get_raw_conversions(start, end, timezone_id=TREND_TIMEZONE_ID),
            offer_names,
            adset_ids,
        )
    except Exception as exc:  # Never render a source outage as a clean $0.
        logger.warning("Dashboard trend revenue unavailable account=%s: %s", account_id, exc)
        return {"status": "unavailable", "daily": {}}

    payload = {"status": "exact_adset_attributed", "daily": daily, "cached": False}
    if len(_trend_revenue_cache) >= TREND_REVENUE_CACHE_MAX_ENTRIES:
        oldest_key = min(_trend_revenue_cache, key=lambda key: _trend_revenue_cache[key][0])
        _trend_revenue_cache.pop(oldest_key, None)
    existing = _trend_revenue_cache.get(cache_key)
    if not existing or existing[1] <= request_started_at:
        _trend_revenue_cache[cache_key] = (now, request_started_at, payload)
    return payload


def extract_niche(adset_name: str) -> str:
    import re
    if not adset_name:
        return "Unknown"
    NON_NICHE = re.compile(
        r'^(batch\s*\d+|v\d+|scale|retarget|broad|phase\s*\d+|test|duplicate|copy)$',
        re.IGNORECASE
    )
    DATE_LIKE = re.compile(r'^(?:\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}-\d{4})')
    parts = [p.strip() for p in adset_name.split(" - ")]
    # Try parts[1:] first (standard [Date] - [Niche] - [Batch] format)
    for part in parts[1:]:
        if part and not NON_NICHE.match(part) and not DATE_LIKE.match(part):
            return part
    # Fallback: if parts[0] looks like a niche (not a date), use it
    if parts and not DATE_LIKE.match(parts[0]):
        return parts[0]
    return "General"

@router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """
    Get aggregated statistics for the dashboard.
    """
    brands_count = db.query(Brand).count()
    products_count = db.query(Product).count()
    generated_ads_count = db.query(GeneratedAd).count()
    templates_count = db.query(WinningAd).count()
    campaigns_count = db.query(FacebookCampaign).count()

    return {
        "brands_count": brands_count,
        "products_count": products_count,
        "generated_ads_count": generated_ads_count,
        "templates_count": templates_count,
        "campaigns_count": campaigns_count
    }


@router.get("/niche-summary")
def get_niche_summary(
    ad_account_id: str | None = Query(None),
    date_preset: str = Query("last_7d"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    refresh: bool = Query(False),
    current_user=Depends(get_current_active_user),
):
    """
    Aggregate Meta ad set performance by niche for the Dashboard.
    Returns a 502 when Meta data cannot be loaded so the Dashboard can distinguish
    an unavailable summary from a valid period with no data.
    """
    ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)
    cache_key = (ad_account_id, date_preset, date_from, date_to)
    cached = _read_dashboard_cache(
        _niche_summary_cache,
        cache_key,
        _dashboard_cache_ttl(date_preset, date_to),
        refresh,
    )
    if cached is not None:
        return cached
    request_started_at = time.monotonic()
    try:
        svc = FacebookService()
        insights = svc.get_account_insights_bulk(
            ad_account_id=ad_account_id,
            date_preset=date_preset,
            date_from=date_from,
            date_to=date_to,
        )

        by_niche = {}
        for row in insights.values():
            adset_name = row.get("adset_name") or ""
            niche = extract_niche(adset_name)
            bucket = by_niche.setdefault(
                niche,
                {
                    "niche": niche,
                    "adset_count": 0,
                    "total_spend": 0.0,
                    "total_leads": 0,
                    "total_revenue": 0.0,
                },
            )

            bucket["adset_count"] += 1
            bucket["total_spend"] += float(row.get("spend") or 0)
            bucket["total_leads"] += int(row.get("leads") or 0)
            bucket["total_revenue"] += float(row.get("revenue") or 0)

        summary = []
        for bucket in by_niche.values():
            total_spend = bucket["total_spend"]
            total_revenue = bucket["total_revenue"]
            avg_roas = round(total_revenue / total_spend, 2) if total_spend > 0 and total_revenue > 0 else None
            summary.append({
                "niche": bucket["niche"],
                "adset_count": bucket["adset_count"],
                "total_spend": round(total_spend, 2),
                "total_leads": bucket["total_leads"],
                "total_revenue": round(total_revenue, 2),
                "avg_roas": avg_roas,
                "avg_cpl": round(total_spend / bucket["total_leads"], 2) if bucket["total_leads"] > 0 else None,
            })

        response = sorted(summary, key=lambda item: item["total_spend"], reverse=True)
        _write_dashboard_cache(_niche_summary_cache, cache_key, response, request_started_at)
        return response
    except Exception as exc:
        logger.exception("Dashboard niche summary failed")
        raise HTTPException(status_code=502, detail="Niche summary unavailable") from exc


@router.get('/trend')
def get_dashboard_trend(
    ad_account_id: str | None = Query(None),
    date_preset: str = Query('last_7d'),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """Return a truthful daily Meta trend plus a comparable prior-period baseline."""
    ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)
    try:
        if bool(date_from) != bool(date_to):
            raise ValueError('incomplete date range')
        if date_from and date_to:
            start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        else:
            from app.services.redtrack_service import RedTrackService
            start_s, end_s = RedTrackService.preset_to_dates(date_preset)
            start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
        if start > end:
            raise ValueError('reversed date range')
        if (end - start).days > 30:
            raise ValueError('date range exceeds 31 days')
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='Invalid date range')
    days = (end - start).days + 1
    previous_start = start - timedelta(days=days)
    previous_end = start - timedelta(days=1)
    cache_key = (ad_account_id, str(start), str(end), current_user.has_permission("pnl:read"))
    cached = _read_dashboard_cache(
        _trend_cache,
        cache_key,
        _dashboard_cache_ttl(date_preset, str(end)),
        refresh,
    )
    if cached is not None:
        return cached
    request_started_at = time.monotonic()
    try:
        svc = FacebookService()
        combined_daily = svc.get_account_daily_insights(ad_account_id, str(previous_start), str(end))
        by_date = {row['date']: row for row in combined_daily}
        # Billable revenue is protected by the same permission as the P&L
        # surface. Dashboard access alone must not become a way to bypass it.
        revenue = (
            _daily_billable_revenue(
                db,
                ad_account_id,
                start,
                end,
                refresh=refresh,
                request_started_at=request_started_at,
            )
            if current_user.has_permission("pnl:read")
            else {"status": "access_denied", "daily": {}}
        )
        revenue_daily = revenue["daily"]
        revenue_available = revenue["status"] == "exact_adset_attributed"
        def fill_dates(window_start, window_end, include_revenue=False):
            rows = []
            cursor = window_start
            while cursor <= window_end:
                key = str(cursor)
                meta = by_date.get(key, {'date': key, 'spend': None, 'leads': None, 'cpl': None})
                row = {
                    **meta,
                    # $0 is a real result when the source completed and found
                    # no exact-mapped payout that day. Prior-period revenue is
                    # intentionally omitted: this endpoint only fetches the
                    # visible chart window to keep dashboard refresh fast.
                    'revenue': revenue_daily.get(key, 0.0) if revenue_available and include_revenue else None,
                }
                row['revenue_per_lead'] = (
                    round(row['revenue'] / row['leads'], 2)
                    if row['revenue'] is not None and row['leads'] else None
                )
                rows.append(row)
                cursor += timedelta(days=1)
            return rows
        current_daily = fill_dates(start, end, include_revenue=True)
        previous_daily = fill_dates(previous_start, previous_end)
        def totals(rows):
            spend = sum(row['spend'] or 0 for row in rows)
            leads = sum(row['leads'] or 0 for row in rows)
            has_revenue = any(row['revenue'] is not None for row in rows)
            total_revenue = (
                sum((Decimal(str(row['revenue'] or 0)) for row in rows), Decimal("0"))
                if has_revenue else None
            )
            return {
                'spend': round(spend, 2),
                'leads': leads,
                'cpl': round(spend / leads, 2) if leads else None,
                'revenue': round(total_revenue, 2) if total_revenue is not None else None,
                'revenue_per_lead': round(total_revenue / leads, 2) if total_revenue is not None and leads else None,
            }
        response = {
            'date_from': str(start), 'date_to': str(end),
            'previous_date_from': str(previous_start), 'previous_date_to': str(previous_end),
            'daily': current_daily, 'totals': totals(current_daily), 'previous_totals': totals(previous_daily),
            'source': 'Meta Insights + Switchboard Everflow',
            'revenue_attribution': {
                'status': revenue['status'],
                'source': 'Switchboard Everflow',
                'timezone': 'America/Los_Angeles',
                'rule': 'Exact Meta ad set ID in Everflow sub3; mapped offer only.',
                'cached': bool(revenue.get('cached')),
            },
        }
        _write_dashboard_cache(_trend_cache, cache_key, response, request_started_at)
        return response
    except Exception as exc:
        logger.exception('Dashboard daily trend failed')
        raise HTTPException(status_code=502, detail='Daily trend unavailable') from exc
