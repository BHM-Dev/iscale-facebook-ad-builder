"""Approvals queue endpoints. See app/services/proposal_service.py and the brief in docs/briefs/."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.facebook import _assert_account_allowed
from app.core.deps import get_current_active_user, require_permission
from app.database import get_db
from app.models import ActionProposal, User, normalize_account_id
from app.services import proposal_service as ps

router = APIRouter()


def _viewer_accounts(user: User) -> Optional[set[str]]:
    allowed = user.allowed_account_ids()
    return None if allowed is None else {normalize_account_id(a) for a in allowed}


def _require_view(user: User) -> None:
    if not ps.can_view(user):
        raise HTTPException(status_code=403, detail="Proposals are in a shadow week and not visible yet.")


def _scoped(query, user: User):
    accounts = _viewer_accounts(user)
    return query if accounts is None else query.filter(ActionProposal.fb_account_id.in_(accounts))


@router.get("")
def list_open(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Open proposals for the viewer's accounts. Empty (not an error) for anyone outside the shadow list."""
    if not ps.can_view(current_user):
        return {"visible": False, "shadow": ps.shadow_mode(), "proposals": [], "accounts": {}}
    rows = _scoped(db.query(ActionProposal), current_user).filter(
        ActionProposal.status.in_(["open", "executing", "failed"])).order_by(ActionProposal.created_at.desc()).all()
    scope = _viewer_accounts(current_user)
    runs = {a: r for a, r in ps.LAST_RUN.items() if scope is None or a in scope}
    return {"visible": True, "shadow": ps.shadow_mode(), "proposals": [ps.serialize(p) for p in rows],
            "accounts": runs, "dismiss_reasons": list(ps.DISMISS_REASONS)}


@router.get("/history")
def history(account: Optional[str] = None, trigger: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
            db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    _require_view(current_user)
    q = _scoped(db.query(ActionProposal), current_user).filter(
        ActionProposal.status.in_(["executed", "dismissed", "expired", "stale"]))
    if account:
        q = q.filter(ActionProposal.fb_account_id == normalize_account_id(account))
    if trigger:
        q = q.filter(ActionProposal.trigger_key == trigger)
    return [ps.serialize(p) for p in q.order_by(ActionProposal.updated_at.desc()).limit(limit).all()]


@router.get("/stats")
def stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    _require_view(current_user)
    rows = _scoped(db.query(ActionProposal.trigger_key, ActionProposal.status, ActionProposal.dismiss_reason),
                   current_user).all()
    out = {}
    for trigger, status, reason in rows:
        s = out.setdefault(trigger, {"label": ps.TRIGGER_LABELS.get(trigger, trigger), "proposed": 0, "approved": 0,
                                     "dismissed": 0, "expired": 0, "dismiss_reasons": {}})
        s["proposed"] += 1
        if status in ("executed", "failed", "stale", "executing"):
            s["approved"] += 1
        elif status == "dismissed":
            s["dismissed"] += 1
            s["dismiss_reasons"][reason] = s["dismiss_reasons"].get(reason, 0) + 1
        elif status == "expired":
            s["expired"] += 1
    return out


class DismissBody(BaseModel):
    reason: str
    note: Optional[str] = None


def _load_for_decision(db: Session, proposal_id: str, user: User) -> ActionProposal:
    _require_view(user)
    p = db.query(ActionProposal).filter(ActionProposal.id == proposal_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    _assert_account_allowed(user, p.fb_account_id)
    return p


@router.post("/{proposal_id}/approve")
def approve(proposal_id: str, db: Session = Depends(get_db),
            current_user: User = Depends(require_permission("campaigns:write"))):
    """Re-checks the ad set live in Meta, then pauses or raises the budget. A changed ad set is
    marked stale and nothing is sent."""
    _load_for_decision(db, proposal_id, current_user)
    try:
        return ps.serialize(ps.approve(db, proposal_id, current_user.email))
    except ps.DecisionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/{proposal_id}/dismiss")
def dismiss(proposal_id: str, body: DismissBody, db: Session = Depends(get_db),
            current_user: User = Depends(require_permission("campaigns:write"))):
    _load_for_decision(db, proposal_id, current_user)
    try:
        return ps.serialize(ps.dismiss(db, proposal_id, current_user.email, body.reason, body.note))
    except ps.DecisionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


class EventBody(BaseModel):
    event: str
    proposal_id: Optional[str] = None
    props: Optional[dict] = None


_CLIENT_EVENTS = {"proposal_viewed", "proposal_evidence_expanded", "ads_manager_opened", "proposal_tab_viewed"}


@router.post("/events", status_code=204)
def client_event(body: EventBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """UI events (brief §6). Server-side events (created/approved/executed/...) are logged where they happen."""
    if body.event not in _CLIENT_EVENTS or not ps.can_view(current_user):
        return None
    props = body.props or {}
    if len(str(props)) > 2000:
        props = {"truncated": True}
    ps.log_event(db, body.event, body.proposal_id, current_user.email, props=props)
    db.commit()
    return None


@router.get("/shadow-report")
def shadow_report(account: Optional[str] = None, days: int = Query(7, ge=1, le=14),
                  db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Proposals vs. the pauses and budget raises people actually made in Meta (activity log)."""
    _require_view(current_user)
    accounts = [normalize_account_id(account)] if account else ps.proposal_accounts()
    out = []
    for a in accounts:
        _assert_account_allowed(current_user, a)
        try:
            out.append(ps.shadow_report(db, a, days))
        except Exception as exc:
            out.append({"account_id": a, "error": f"Couldn't read Meta's activity log: {str(exc)[:200]}"})
    return out


@router.post("/evaluate")
def evaluate_now(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Admin: run the evaluator now instead of waiting for the hourly job. Never writes to Meta."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admins only.")
    return ps.run_evaluation(db)
