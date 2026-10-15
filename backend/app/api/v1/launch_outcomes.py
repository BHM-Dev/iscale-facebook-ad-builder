"""Launch outcome reporting from the bulk launcher.

The launcher POSTs one record when a run ends. Anything other than a clean
success DMs Steve once (alerted_at makes a replay idempotent-safe).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import require_permission
from app.database import get_db
from app.models import LaunchOutcome, User
from app.services.slack_service import send_launch_alert

logger = logging.getLogger(__name__)
router = APIRouter()

_OUTCOMES = {"success", "partial", "failed", "rate_limited", "ambiguous"}


class LaunchOutcomeIn(BaseModel):
    outcome: str
    attempted: int = Field(0, ge=0, le=1000)
    created: int = Field(0, ge=0, le=1000)
    failed: int = Field(0, ge=0, le=1000)
    ad_account_id: Optional[str] = Field(None, max_length=64)
    campaign_name: Optional[str] = Field(None, max_length=300)
    adset_name: Optional[str] = Field(None, max_length=300)
    errors: Optional[List[str]] = None
    meta: Optional[Dict[str, Any]] = None


@router.post("")
def report_launch_outcome(
    body: LaunchOutcomeIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("campaigns:write")),
):
    outcome = body.outcome if body.outcome in _OUTCOMES else "failed"
    errors = [str(e)[:500] for e in (body.errors or [])[:20]]
    row = LaunchOutcome(
        user_email=getattr(current_user, "email", None),
        ad_account_id=body.ad_account_id,
        campaign_name=body.campaign_name,
        adset_name=body.adset_name,
        outcome=outcome,
        attempted=body.attempted,
        created=body.created,
        failed=body.failed,
        errors=errors or None,
        meta=body.meta if body.meta and len(str(body.meta)) <= 2000 else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    if outcome != "success":
        who = row.user_email or "unknown user"
        summary = (
            f"{outcome} launch by {who}: {row.created}/{row.attempted} ads created"
            f" ({row.campaign_name or 'campaign ?'} / {row.adset_name or 'ad set ?'}, {row.ad_account_id or 'acct ?'})."
        )
        detail = " | ".join(errors[:3])
        recent = db.query(LaunchOutcome.id).filter(
            LaunchOutcome.user_email == row.user_email,
            LaunchOutcome.outcome == outcome,
            LaunchOutcome.alerted_at > datetime.now(timezone.utc) - timedelta(minutes=10),
        ).first()
        if recent:
            return {"id": row.id}
        if send_launch_alert(summary, detail):
            row.alerted_at = datetime.now(timezone.utc)
            db.commit()
    return {"id": row.id}
