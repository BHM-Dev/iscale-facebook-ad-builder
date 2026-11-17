"""In-app feedback (Steve, 2026-11-17).

Anyone signed in can send feedback from the page they're on; the page, their account and a few context fields are
captured automatically. Each submission is stored and DMed to Steve. Admins list and update it at /feedback, and
Claude Code sessions pick open items up from the same table (no automatic API spend).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user, get_current_superuser, get_db
from app.core.user_rate_limit import per_user_limit
from app.models import AppFeedback, User

router = APIRouter()

STATUSES = ("new", "in_progress", "done", "wont_fix")
feedback_limit = per_user_limit("feedback", 20, 600, "That's a lot of feedback in a few minutes — wait a bit and send the rest.")
APP_URL = "https://adbuilder.velocitymx.io"


class FeedbackIn(BaseModel):
    message: str = Field(..., min_length=3, max_length=4000)
    page_path: str = Field(..., min_length=1, max_length=500)
    screenshot_url: Optional[str] = Field(None, max_length=1000)
    context: Optional[Dict[str, Any]] = None


def _safe_screenshot_url(url: Optional[str]) -> Optional[str]:
    """Only an https link (our upload returns an R2 https URL). Anything else -- javascript:, data:, a relative
    path -- would be rendered as a link in an admin's session, so it is refused."""
    if not url:
        return None
    url = url.strip()
    if not url.lower().startswith("https://") or any(c.isspace() for c in url):
        raise HTTPException(400, "The screenshot link isn't valid. Remove the screenshot and try again.")
    return url


class FeedbackUpdate(BaseModel):
    status: Optional[str] = None
    resolution_note: Optional[str] = Field(None, max_length=4000)


def _out(row: AppFeedback) -> Dict[str, Any]:
    return {
        "id": row.id, "user_email": row.user_email, "page_path": row.page_path, "message": row.message,
        "screenshot_url": row.screenshot_url, "context": row.context or {}, "status": row.status,
        "resolution_note": row.resolution_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


@router.post("", dependencies=[Depends(feedback_limit)])
def submit_feedback(body: FeedbackIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    context = body.context or {}
    if len(str(context)) > 4000:
        context = {"truncated": True}
    page = body.page_path if body.page_path.startswith("/") else f"/{body.page_path}"
    if page.startswith("//") or "://" in page:
        raise HTTPException(400, "The page address isn't valid.")
    row = AppFeedback(
        user_id=current_user.id, user_email=current_user.email, page_path=page[:500],
        message=body.message.strip(), screenshot_url=_safe_screenshot_url(body.screenshot_url), context=context,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    try:
        from app.services.slack_service import send_feedback_alert
        send_feedback_alert(
            who=current_user.name or current_user.email, page=row.page_path, message=row.message,
            screenshot_url=row.screenshot_url, url=f"{APP_URL}{row.page_path}",
        )
    except Exception as exc:
        # The feedback is saved either way and shows in the inbox; log so a silent Slack outage is visible.
        logging.getLogger(__name__).warning("Feedback %s saved but the Slack DM failed: %s", row.id, exc)
    return _out(row)


@router.get("")
def list_feedback(
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
) -> List[Dict[str, Any]]:
    query = db.query(AppFeedback)
    if status:
        if status not in STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
        query = query.filter(AppFeedback.status == status)
    return [_out(r) for r in query.order_by(AppFeedback.created_at.desc()).limit(limit).all()]


@router.patch("/{feedback_id}")
def update_feedback(feedback_id: str, body: FeedbackUpdate, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_superuser)):
    row = db.query(AppFeedback).filter(AppFeedback.id == feedback_id).first()
    if not row:
        raise HTTPException(404, "Feedback not found")
    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
        row.status = body.status
        row.resolved_at = datetime.now(timezone.utc) if body.status in ("done", "wont_fix") else None
    if body.resolution_note is not None:
        row.resolution_note = body.resolution_note.strip() or None
    db.commit()
    db.refresh(row)
    return _out(row)
