"""RedTrack reporting endpoints.

GET /api/v1/redtrack/status                  — is API key configured?
GET /api/v1/redtrack/report                  — full report grouped by ad set
GET /api/v1/redtrack/adset/{fb_adset_id}     — single ad set data
GET /api/v1/redtrack/campaigns               — list RedTrack campaigns (validation)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_current_user
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
