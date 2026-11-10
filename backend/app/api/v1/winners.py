"""Read-only winning-creative performance endpoint."""
from datetime import date
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.facebook import _resolve_scoped_default_account
from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import normalize_account_id
from app.services.winners_service import get_winner_base_rows, rank_winner_rows

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
def get_winners(
    ad_account_id: Optional[str] = Query(None),
    date_preset: str = Query("last_14d"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    group_by: Literal["creative", "concept", "headline"] = Query("creative"),
    min_leads: int = Query(10, ge=1, le=10000),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    account_id = _resolve_scoped_default_account(current_user, ad_account_id)
    if not account_id:
        raise HTTPException(status_code=400, detail="Select an ad account.")
    if bool(date_from) != bool(date_to):
        raise HTTPException(status_code=400, detail="date_from and date_to must be provided together.")
    if date_from and date_to:
        try:
            start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Dates must use YYYY-MM-DD.") from exc
        if start > end:
            raise HTTPException(status_code=400, detail="date_from must be on or before date_to.")
        # Explicit dates are the Meta contract; the placeholder preset must not
        # produce a separate cache entry for the same range.
        date_preset = "custom"
    try:
        payload, cache_hit = get_winner_base_rows(
            db, normalize_account_id(account_id), date_preset, date_from, date_to, group_by
        )
    except Exception as exc:
        logger.exception("Could not load winning ads for %s", normalize_account_id(account_id))
        raise HTTPException(status_code=502, detail="Could not load winning ads right now.") from exc

    rows = rank_winner_rows(payload["rows"], min_leads, payload["max_cpl_available"])
    # Revenue and profit follow the same permission as the P&L; without it the page still ranks by leads/CPL.
    if not current_user.has_permission("pnl:read"):
        for row in rows:
            for field in ("est_revenue", "est_profit", "rt_revenue"):
                row[field] = None
    ranked_count = sum(1 for row in rows if row["enough_data"])
    return {
        **{key: value for key, value in payload.items() if key != "rows"},
        "ad_account_id": normalize_account_id(account_id),
        "min_leads": min_leads,
        "ranked_count": ranked_count,
        "total_count": len(rows),
        "cache_hit": cache_hit,
        "rows": rows,
    }
