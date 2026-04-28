"""RedTrack reporting endpoints.

GET /api/v1/redtrack/status                  — is API key configured?
GET /api/v1/redtrack/report                  — full report grouped by ad set
GET /api/v1/redtrack/adset/{fb_adset_id}     — single ad set data
GET /api/v1/redtrack/campaigns               — list RedTrack campaigns (validation)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.services.redtrack_service import RedTrackService

logger = logging.getLogger(__name__)
router = APIRouter()


def _svc() -> RedTrackService:
    return RedTrackService()


@router.get("/status")
def get_status(current_user=Depends(get_current_user)):
    """Check whether REDTRACK_API_KEY is configured."""
    svc = _svc()
    configured = svc.is_configured()
    return {
        "configured": configured,
        "message": "RedTrack API key is set" if configured else "REDTRACK_API_KEY env var not set — add it to Railway",
    }


@router.get("/report")
def get_report(
    date_preset: str = Query("last_7d"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    """Full RedTrack report grouped by Meta ad set ID (sub2).

    Accepts either a date_preset (last_7d, today, last_30d, this_month, etc.)
    or explicit date_from / date_to in YYYY-MM-DD format.
    """
    svc = _svc()
    if not svc.is_configured():
        return {"configured": False, "data": {}}

    if date_from and date_to:
        data = svc.get_report_by_adset(date_from, date_to)
    else:
        data = svc.get_report_by_adset_preset(date_preset)

    return {
        "configured": True,
        "date_preset": date_preset,
        "date_from": date_from,
        "date_to": date_to,
        "adset_count": len(data),
        "data": data,
    }


@router.get("/report/sub1")
def get_report_sub1(
    date_preset: str = Query("last_7d"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    """RedTrack report grouped by sub1 (= Meta ad ID).

    sub1={{ad.id}} is already set in the tracking URL template.
    Accepts either date_preset or explicit date_from/date_to (YYYY-MM-DD).
    Returns dict keyed by fb_ad_id → metrics.
    """
    svc = _svc()
    if not svc.is_configured():
        return {"configured": False, "data": {}}

    if date_from and date_to:
        df, dt = date_from, date_to
    else:
        df, dt = svc.preset_to_dates(date_preset)

    data = svc.get_report_by_sub(df, dt, group_field="sub1")
    return {
        "configured": True,
        "date_preset": date_preset,
        "date_from": df,
        "date_to": dt,
        "ad_count": len(data),
        "data": data,
    }


@router.get("/adset/{fb_adset_id}")
def get_adset(
    fb_adset_id: str,
    date_preset: str = Query("last_7d"),
    current_user=Depends(get_current_user),
):
    """RedTrack data for a single Meta ad set ID."""
    svc = _svc()
    if not svc.is_configured():
        return {"configured": False, "data": None}

    data = svc.get_adset_data(fb_adset_id, date_preset)
    return {
        "configured": True,
        "fb_adset_id": fb_adset_id,
        "date_preset": date_preset,
        "data": data,  # None if no match in RedTrack
    }


@router.post("/sync")
def manual_sync(
    date_preset: str = Query("last_7d"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Manually trigger a RedTrack cache refresh for the given date preset.
    Same logic as the 30-min scheduler — call this to populate cache immediately.
    """
    svc = _svc()
    if not svc.is_configured():
        raise HTTPException(400, "REDTRACK_API_KEY not configured.")

    import uuid
    from datetime import date
    from app.models import RedTrackCache

    date_from_str, date_to_str = svc.preset_to_dates(date_preset)
    report = svc.get_report_by_adset(date_from_str, date_to_str)
    if not report:
        return {"synced": 0, "message": "RedTrack returned no data for this date range. Check sub2={{adset.id}} is in tracking URLs."}

    date_from = date.fromisoformat(date_from_str)
    date_to   = date.fromisoformat(date_to_str)

    # Upsert: wipe existing rows for this range, insert fresh
    db.query(RedTrackCache).filter(
        RedTrackCache.date_from == date_from,
        RedTrackCache.date_to   == date_to,
    ).delete()
    for fb_adset_id, metrics in report.items():
        db.add(RedTrackCache(
            id=str(uuid.uuid4()),
            fb_adset_id=fb_adset_id,
            date_from=date_from,
            date_to=date_to,
            **metrics,
        ))
    db.commit()

    return {
        "synced": len(report),
        "date_from": date_from_str,
        "date_to": date_to_str,
        "adset_ids": list(report.keys()),
        "message": f"Cache updated with {len(report)} ad sets from RedTrack.",
    }


@router.get("/debug")
def debug_redtrack(
    date_preset: str = Query("last_7d"),
    current_user=Depends(get_current_user),
):
    """Return raw RedTrack report grouped by sub2 for diagnosis."""
    import httpx, os
    api_key = os.getenv("REDTRACK_API_KEY", "")
    if not api_key:
        return {"error": "REDTRACK_API_KEY not set"}

    svc = _svc()
    date_from, date_to = svc.preset_to_dates(date_preset)

    try:
        r = httpx.get(
            "https://api.redtrack.io/report",
            params={"api_key": api_key, "date_from": date_from, "date_to": date_to, "group": "sub2"},
            timeout=15,
        )
        rows = r.json() if r.status_code == 200 else None
    except Exception as e:
        return {"error": str(e)}

    return {
        "status": r.status_code,
        "date_from": date_from,
        "date_to": date_to,
        "row_count": len(rows) if isinstance(rows, list) else None,
        "sample_row": rows[0] if isinstance(rows, list) and rows else None,
        "sub2_ids": [str(row.get("sub2", "")) for row in rows] if isinstance(rows, list) else [],
    }


@router.get("/campaigns")
def get_campaigns(current_user=Depends(get_current_user)):
    """List all RedTrack campaigns — used to validate API connection."""
    svc = _svc()
    if not svc.is_configured():
        raise HTTPException(400, "REDTRACK_API_KEY not configured. Add it to Railway env vars.")

    campaigns = svc.get_campaigns()
    return {
        "count": len(campaigns),
        "campaigns": campaigns,
    }
