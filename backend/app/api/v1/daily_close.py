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


def _latest_for(db, account_id):
    """Newest available version of the account's most recent closed day (or the newest version if none
    is available), plus that day's first available read for the "since first read" delta.
    Read-only: this endpoint never computes a close. The scheduler does, from 00:15 PT."""
    newest = (db.query(DailyCloseVersion).filter_by(account_id=account_id)
              .order_by(DailyCloseVersion.day.desc(), DailyCloseVersion.version.desc()).first())
    if not newest:
        return None
    versions = (db.query(DailyCloseVersion).filter_by(account_id=account_id, day=newest.day)
                .order_by(DailyCloseVersion.version.asc()).all())
    available = [v for v in versions if (v.payload or {}).get("available")]
    row = available[-1] if available else versions[-1]
    first = available[0] if available else None
    payload = dict(row.payload or {})
    payload.update(account_id=account_id, version=row.version,
                   revenue_as_of=row.revenue_as_of.isoformat() if row.revenue_as_of else None,
                   first_read={"revenue": (first.payload or {}).get("revenue") if first else None,
                               "revenue_as_of": first.revenue_as_of.isoformat() if first and first.revenue_as_of else None})
    return payload


def _sum_or_none(values):
    values = list(values)
    return None if any(v is None for v in values) else round(sum(values), 2)


@router.get("/latest")
def latest(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    return assemble_latest(db, _permitted_close_accounts(db, current_user))


def assemble_latest(db, accounts):
    """Latest close per account plus the combined total; shared by the card and the morning DM."""
    if not accounts:
        return {"accounts": [], "combined": None}
    rows = [r for r in (_latest_for(db, a) for a in accounts) if r]
    if not rows:
        return {"accounts": [], "combined": None, "pending": True}
    day = max(r["day"] for r in rows)
    same_day = [r for r in rows if r["day"] == day]
    missing = [a for a in accounts if a not in {r["account_id"] for r in same_day}]
    if any(not r.get("available") for r in same_day):
        combined = {"available": False, "reason": "Everflow unavailable", "day": day}
    else:
        spend = round(sum(r["spend"] for r in same_day), 2)
        revenue = round(sum(r["revenue"] for r in same_day), 2)
        mtds = [r.get("mtd") or {} for r in same_day]
        mtd = {k: _sum_or_none(m.get(k) for m in mtds) for k in ("spend", "revenue", "profit", "pace", "last_month_profit")}
        mtd.update(days_elapsed=mtds[0].get("days_elapsed"), days_in_month=mtds[0].get("days_in_month"))
        movers = [m for r in same_day for m in (r.get("movers") or {}).get("up", []) + (r.get("movers") or {}).get("down", [])]
        unique = {m["adset_id"]: m for m in movers}.values()
        combined = {"available": True, "day": day, "spend": spend, "revenue": revenue, "profit": round(revenue - spend, 2),
                    "roas": round(revenue / spend, 2) if spend else None, "leads": sum(r.get("leads") or 0 for r in same_day),
                    "mtd": mtd, "revenue_as_of": max(r.get("revenue_as_of") or "" for r in same_day),
                    "first_read": {"revenue": _sum_or_none((r.get("first_read") or {}).get("revenue") for r in same_day)},
                    "movers": {"up": sorted(unique, key=lambda m: m["profit"], reverse=True)[:3],
                               "down": sorted(unique, key=lambda m: m["profit"])[:3]},
                    "movers_unavailable": any(r.get("movers_unavailable") for r in same_day)}
    combined["partial"] = bool(missing)
    combined["missing_accounts"] = missing
    return {"accounts": same_day, "combined": combined}


class EventBody(BaseModel):
    event: str
    props: dict | None = None


_EVENT_PROPS = {"day", "version", "level", "matched", "group_by", "count"}


@router.post("/event")
def event(body: EventBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    if body.event not in {
        "close_card_viewed", "close_copied", "close_details_opened",
        "naming_preset_saved", "naming_name_overridden", "naming_launch",
        "winners_viewed", "winners_relaunch", "winners_iterate",
    }:
        raise HTTPException(status_code=400, detail="Unsupported close event")
    props = {k: str(v)[:40] for k, v in (body.props or {}).items() if k in _EVENT_PROPS}
    proposal_service.log_event(db, body.event, None, current_user.email, **props)
    db.commit()
    return {"ok": True}
