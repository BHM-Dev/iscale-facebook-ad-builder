"""Read-only daily close snapshots. Nothing in this module writes to Meta or Slack."""
import calendar
import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.api.v1 import pnl
from app.models import DailyCloseVersion, normalize_account_id
from app.services import proposal_service
from app.services.facebook_service import FacebookService

logger = logging.getLogger(__name__)
CLOSE_ACCOUNTS = ["act_521142087204815", "act_737291135429748"]


def close_accounts():
    raw = os.getenv("DAILY_CLOSE_ACCOUNT_IDS", "")
    return [normalize_account_id(x) for x in raw.split(",") if x.strip()] or CLOSE_ACCOUNTS


def _money(value):
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _month_bounds(day):
    first = day.replace(day=1)
    previous_last = first - timedelta(days=1)
    return first, previous_last.replace(day=1), previous_last


def _adset_rows(account_id, day):
    svc = FacebookService()
    svc.initialize()
    account = svc._get_account(account_id)
    rows = account.get_insights(fields=["adset_id", "adset_name", "spend", "actions"], params={
        "time_range": {"since": day.isoformat(), "until": day.isoformat()}, "level": "adset", "limit": 500,
    })
    result = []
    for row in rows:
        leads = sum(int(float(a.get("value") or 0)) for a in (row.get("actions") or []) if a.get("action_type") in proposal_service.LEAD_TYPES)
        result.append({"adset_id": str(row.get("adset_id") or ""), "name": row.get("adset_name") or "", "spend": float(row.get("spend") or 0), "leads": leads})
    return [r for r in result if r["adset_id"]]


def compute_close(db, account_id: str, day: date, previous_payload: dict | None = None) -> dict:
    spend = pnl._spend_for_account(account_id, day, day)
    revenue_row = pnl._revenue_for_account(db, account_id, day, day)
    revenue, _, _, source, unavailable, _, _ = revenue_row
    base = {"available": not unavailable, "day": day.isoformat(), "spend": _money(spend), "revenue_source": source}
    if unavailable:
        base.update(reason="Everflow unavailable", revenue=None, profit=None, roas=None, leads=None, movers={"up": [], "down": []})
        # Keep the month fields structurally present without inventing revenue.
        base["mtd"] = {"spend": None, "revenue": None, "profit": None, "days_elapsed": day.day,
                        "days_in_month": calendar.monthrange(day.year, day.month)[1], "pace": None, "last_month_profit": None}
        return base

    rows = _adset_rows(account_id, day)
    rev_by_adset = proposal_service.revenue_by_adset_day(db, account_id, day, day, float(spend))
    movers = []
    for row in rows:
        ad_revenue = sum(rev_by_adset.get(row["adset_id"], {}).values())
        movers.append({"adset_id": row["adset_id"], "name": row["name"], "profit": _money(ad_revenue - row["spend"]),
                       "spend": _money(row["spend"]), "revenue": _money(ad_revenue)})
    mtd_start, prev_start, prev_end = _month_bounds(day)
    mtd_spend = pnl._spend_for_account(account_id, mtd_start, day)
    mtd_rev_row = pnl._revenue_for_account(db, account_id, mtd_start, day)
    mtd_revenue = mtd_rev_row[0]
    if previous_payload and previous_payload.get("mtd", {}).get("last_month_profit") is not None:
        last_month_profit = Decimal(str(previous_payload["mtd"]["last_month_profit"]))
    else:
        prev_rev_row = pnl._revenue_for_account(db, account_id, prev_start, prev_end)
        last_month_profit = prev_rev_row[0] - pnl._spend_for_account(account_id, prev_start, prev_end)
    mtd_profit = mtd_revenue - mtd_spend
    days_in_month = calendar.monthrange(day.year, day.month)[1]
    base.update(revenue=_money(revenue), profit=_money(revenue - spend), roas=_money(revenue / spend) if spend else None,
                leads=sum(r["leads"] for r in rows), movers={"up": sorted(movers, key=lambda x: x["profit"], reverse=True)[:3],
                "down": sorted(movers, key=lambda x: x["profit"])[:3]},
                mtd={"spend": _money(mtd_spend), "revenue": _money(mtd_revenue), "profit": _money(mtd_profit),
                     "days_elapsed": day.day, "days_in_month": days_in_month, "pace": _money(mtd_profit / day.day * days_in_month),
                     "last_month_profit": _money(last_month_profit)})
    return base


def run_close(db):
    results = {}
    for account_id in close_accounts():
        try:
            svc = FacebookService()
            svc.initialize()
            account = svc._get_account(account_id)
            day = proposal_service.account_today(account) - timedelta(days=1)
            latest = db.query(DailyCloseVersion).filter_by(account_id=account_id, day=day).order_by(DailyCloseVersion.version.desc()).first()
            payload = compute_close(db, account_id, day, latest.payload if latest else None)
            version = (latest.version + 1) if latest else 1
            row = DailyCloseVersion(account_id=account_id, day=day, version=version, revenue_as_of=datetime.now(timezone.utc), payload=payload)
            db.add(row); db.commit()
            results[account_id] = payload
        except Exception:
            db.rollback()
            logger.exception("Daily close failed for %s", account_id)
    return results
