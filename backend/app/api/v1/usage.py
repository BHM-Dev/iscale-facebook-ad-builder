"""Page-usage telemetry (Steve, 2026-11-18): which pages Joel and Abel actually open and how long they stay.

Stored in the existing proposal_events log (event='page_view'), so no new table. The client batches views
and sends at most one request a minute, so this never competes with a page's real data calls.
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import ProposalEvent, User
from app.services import proposal_service

router = APIRouter()

_ID_SEGMENT = re.compile(r"^(?:\d+|act_\d+|[0-9a-f]{8}-[0-9a-f-]{27,}|[0-9a-f]{24,})$", re.IGNORECASE)
MAX_DWELL_S = 4 * 3600


def normalize_path(path: str) -> str | None:
    """'/campaign-performance?x=1' -> '/campaign-performance'; ids become ':id'. None if not an app path."""
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        return None
    path = path.split("?", 1)[0].split("#", 1)[0]
    parts = [":id" if _ID_SEGMENT.match(p) else p for p in path.split("/") if p]
    clean = "/" + "/".join(parts)
    return clean[:80] if re.fullmatch(r"[/A-Za-z0-9_:\-.]*", clean) else None


class UsageEvent(BaseModel):
    event: str
    path: str = Field(..., max_length=300)
    dwell_s: int = 0   # clamped below; a negative value (clock change) must not reject the batch


class UsageBatch(BaseModel):
    events: list[UsageEvent] = Field(..., max_length=50)


@router.post("/events", status_code=204)
def record_usage(body: UsageBatch, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    for item in body.events:
        if item.event != "page_view":
            continue
        path = normalize_path(item.path)
        if not path:
            continue
        proposal_service.log_event(db, "page_view", None, current_user.email, path=path, dwell_s=max(0, min(item.dwell_s, MAX_DWELL_S)))
    db.commit()
    return None


@router.get("/summary")
def usage_summary(days: int = Query(14, ge=1, le=90), db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Admin: views, people and time per page over the last N days, plus each person's top pages."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admins only.")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.query(ProposalEvent.user_email, ProposalEvent.props).filter(
        ProposalEvent.event == "page_view", ProposalEvent.created_at >= since
    ).all()
    pages = defaultdict(lambda: {"views": 0, "dwell_s": 0, "users": set()})
    people = defaultdict(lambda: defaultdict(int))
    for email, props in rows:
        path = (props or {}).get("path")
        if not path:
            continue
        dwell = int((props or {}).get("dwell_s") or 0)
        page = pages[path]
        page["views"] += 1
        page["dwell_s"] += dwell
        page["users"].add(email or "unknown")
        people[email or "unknown"][path] += 1
    return {
        "days": days,
        "pages": sorted(
            ({"path": p, "views": v["views"], "minutes": round(v["dwell_s"] / 60, 1), "people": len(v["users"])} for p, v in pages.items()),
            key=lambda r: r["views"], reverse=True,
        ),
        "people": {
            email: sorted(({"path": p, "views": n} for p, n in counts.items()), key=lambda r: r["views"], reverse=True)[:8]
            for email, counts in people.items()
        },
    }
