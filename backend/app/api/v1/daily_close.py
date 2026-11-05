from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1 import pnl
from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import DailyCloseVersion, User, normalize_account_id
from app.services import daily_close_service, proposal_service

router = APIRouter()


def _permitted_close_accounts(db, user):
    permitted = set(pnl._permitted_active_account_ids(db, user))
    return [a for a in daily_close_service.close_accounts() if normalize_account_id(a) in permitted]


@router.get("/latest")
def latest(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    accounts = _permitted_close_accounts(db, current_user)
    if not accounts:
        return {"accounts": [], "combined": None}
    rows = []
    for account_id in accounts:
        row = db.query(DailyCloseVersion).filter_by(account_id=account_id).order_by(DailyCloseVersion.day.desc(), DailyCloseVersion.version.desc()).first()
        if not row:
            daily_close_service.run_close(db)
            row = db.query(DailyCloseVersion).filter_by(account_id=account_id).order_by(DailyCloseVersion.day.desc(), DailyCloseVersion.version.desc()).first()
        if row:
            first = db.query(DailyCloseVersion).filter_by(account_id=account_id, day=row.day, version=1).first()
            payload = dict(row.payload or {})
            payload.update(account_id=account_id, version=row.version, revenue_as_of=row.revenue_as_of.isoformat() if row.revenue_as_of else None,
                           first_read={"revenue": (first.payload or {}).get("revenue") if first else None,
                                       "revenue_as_of": first.revenue_as_of.isoformat() if first and first.revenue_as_of else None})
            rows.append(payload)
    if not rows:
        return {"accounts": [], "combined": None}
    day = max(r["day"] for r in rows)
    same_day = [r for r in rows if r["day"] == day]
    if any(not r.get("available") for r in same_day):
        combined = {"available": False, "reason": "Everflow unavailable", "day": day}
    else:
        spend = sum(r.get("spend") or 0 for r in same_day); revenue = sum(r.get("revenue") or 0 for r in same_day)
        mtd = {key: sum((r.get("mtd") or {}).get(key) or 0 for r in same_day) for key in ("spend", "revenue", "profit")}
        mtd.update(days_elapsed=same_day[0]["mtd"]["days_elapsed"], days_in_month=same_day[0]["mtd"]["days_in_month"],
                   pace=sum((r.get("mtd") or {}).get("pace") or 0 for r in same_day),
                   last_month_profit=sum((r.get("mtd") or {}).get("last_month_profit") or 0 for r in same_day))
        combined = {"available": True, "day": day, "spend": round(spend, 2), "revenue": round(revenue, 2), "profit": round(revenue - spend, 2),
                    "roas": round(revenue / spend, 2) if spend else None, "leads": sum(r.get("leads") or 0 for r in same_day), "mtd": mtd,
                    "revenue_as_of": max(r.get("revenue_as_of") or "" for r in same_day),
                    "first_read": {"revenue": sum((r.get("first_read") or {}).get("revenue") or 0 for r in same_day)}}
    return {"accounts": same_day, "combined": combined}


class EventBody(BaseModel):
    event: str
    props: dict | None = None


@router.post("/event")
def event(body: EventBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    if body.event not in {"close_card_viewed", "close_copied"}:
        raise HTTPException(status_code=400, detail="Unsupported close event")
    proposal_service.log_event(db, body.event, None, current_user.email, **(body.props or {}))
    db.commit()
    return {"ok": True}
