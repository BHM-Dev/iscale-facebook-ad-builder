from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Brand, Product, GeneratedAd, WinningAd, FacebookCampaign
from app.services.facebook_service import FacebookService
from datetime import date, timedelta
from app.core.deps import get_current_active_user
from app.api.v1.facebook import _resolve_scoped_default_account

router = APIRouter()


def extract_niche(adset_name: str) -> str:
    import re
    if not adset_name:
        return "Unknown"
    NON_NICHE = re.compile(
        r'^(batch\s*\d+|v\d+|scale|retarget|broad|phase\s*\d+|test|duplicate|copy)$',
        re.IGNORECASE
    )
    parts = [p.strip() for p in adset_name.split(" - ")]
    # Try parts[1:] first (standard [Date] - [Niche] - [Batch] format)
    for part in parts[1:]:
        if part and not NON_NICHE.match(part) and not re.match(r'^\d{1,2}/\d{1,2}', part):
            return part
    # Fallback: if parts[0] looks like a niche (not a date), use it
    if parts and not re.match(r'^\d{1,2}/\d{1,2}', parts[0]):
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
    current_user=Depends(get_current_active_user),
):
    """
    Aggregate Meta ad set performance by niche for the Dashboard.
    Returns [] on Meta API failures so the Dashboard remains usable.
    """
    ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)
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
                    "cpl_total": 0.0,
                    "cpl_count": 0,
                },
            )

            bucket["adset_count"] += 1
            bucket["total_spend"] += float(row.get("spend") or 0)
            bucket["total_leads"] += int(row.get("leads") or 0)
            bucket["total_revenue"] += float(row.get("revenue") or 0)

            if row.get("cpl") is not None:
                bucket["cpl_total"] += float(row["cpl"])
                bucket["cpl_count"] += 1

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
                "avg_cpl": round(bucket["cpl_total"] / bucket["cpl_count"], 2) if bucket["cpl_count"] else None,
            })

        return sorted(summary, key=lambda item: item["total_spend"], reverse=True)
    except Exception:
        return []


@router.get('/trend')
def get_dashboard_trend(
    ad_account_id: str | None = Query(None),
    date_preset: str = Query('last_7d'),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    current_user=Depends(get_current_active_user),
):
    """Return a truthful daily Meta trend plus a comparable prior-period baseline."""
    ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)
    if date_from and date_to:
        start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    else:
        from app.services.redtrack_service import RedTrackService
        start_s, end_s = RedTrackService.preset_to_dates(date_preset)
        start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
    days = (end - start).days + 1
    previous_start = start - timedelta(days=days)
    previous_end = start - timedelta(days=1)
    try:
        svc = FacebookService()
        combined_daily = svc.get_account_daily_insights(ad_account_id, str(previous_start), str(end))
        by_date = {row['date']: row for row in combined_daily}
        def fill_dates(window_start, window_end):
            rows = []
            cursor = window_start
            while cursor <= window_end:
                key = str(cursor)
                rows.append(by_date.get(key, {'date': key, 'spend': None, 'leads': None, 'cpl': None}))
                cursor += timedelta(days=1)
            return rows
        current_daily = fill_dates(start, end)
        previous_daily = fill_dates(previous_start, previous_end)
        def totals(rows):
            spend = sum(row['spend'] or 0 for row in rows)
            leads = sum(row['leads'] or 0 for row in rows)
            return {'spend': round(spend, 2), 'leads': leads, 'cpl': round(spend / leads, 2) if leads else None}
        return {
            'date_from': str(start), 'date_to': str(end),
            'previous_date_from': str(previous_start), 'previous_date_to': str(previous_end),
            'daily': current_daily, 'totals': totals(current_daily), 'previous_totals': totals(previous_daily),
            'source': 'Meta Insights',
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'Daily trend unavailable: {exc}')
