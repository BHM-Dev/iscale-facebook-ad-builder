"""Read-only daily close snapshots. Nothing in this module writes to Meta or Slack."""
import calendar
import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from app.api.v1 import pnl
from app.models import DailyCloseVersion, normalize_account_id
from app.services import proposal_service
from app.services.facebook_service import FacebookService

logger = logging.getLogger(__name__)
CLOSE_ACCOUNTS = ["act_521142087204815", "act_737291135429748"]
PT = ZoneInfo("America/Los_Angeles")


def close_accounts():
    raw = os.getenv("DAILY_CLOSE_ACCOUNT_IDS", "")
    return [normalize_account_id(x) for x in raw.split(",") if x.strip()] or CLOSE_ACCOUNTS


def closed_day() -> date:
    """Yesterday in Pacific time. P&L revenue is PT-bucketed and both RHO accounts run on PT, so the
    closed day is always derived from PT, never from the server clock or another timezone."""
    return datetime.now(PT).date() - timedelta(days=1)


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
        result.append({"adset_id": str(row.get("adset_id") or ""), "name": row.get("adset_name") or "",
                       "spend": float(row.get("spend") or 0), "leads": proposal_service.count_leads(row.get("actions"))})
    return [r for r in result if r["adset_id"]]


def _last_month_profit(db, account_id, day, previous_payload):
    prior = ((previous_payload or {}).get("mtd") or {}).get("last_month_profit")
    if prior is not None:
        return Decimal(str(prior))
    _, prev_start, prev_end = _month_bounds(day)
    prev_rev = pnl._revenue_for_account(db, account_id, prev_start, prev_end)
    if prev_rev[4]:          # revenue unavailable: never read that as $0, and don't persist a wrong number
        return None
    return prev_rev[0] - pnl._spend_for_account(account_id, prev_start, prev_end)


def compute_close(db, account_id: str, day: date, previous_payload: dict | None = None) -> dict:
    spend = pnl._spend_for_account(account_id, day, day)
    revenue, _, _, source, unavailable, _, _ = pnl._revenue_for_account(db, account_id, day, day)
    days_in_month = calendar.monthrange(day.year, day.month)[1]
    base = {"available": not unavailable, "day": day.isoformat(), "spend": _money(spend), "revenue_source": source}
    if unavailable:
        base.update(reason="Everflow unavailable", revenue=None, profit=None, roas=None, leads=None,
                    movers={"up": [], "down": []}, movers_unavailable=True,
                    mtd={"spend": None, "revenue": None, "profit": None, "days_elapsed": day.day,
                         "days_in_month": days_in_month, "pace": None, "last_month_profit": None})
        return base

    rows = _adset_rows(account_id, day)
    movers, movers_unavailable = [], False
    try:
        rev_by_adset = proposal_service.revenue_by_adset_day(db, account_id, day, day, float(spend))
        for row in rows:
            ad_revenue = sum(rev_by_adset.get(row["adset_id"], {}).values())
            movers.append({"adset_id": row["adset_id"], "name": row["name"], "profit": _money(ad_revenue - row["spend"]),
                           "spend": _money(row["spend"]), "revenue": _money(ad_revenue)})
    except Exception:  # movers are colour only; a second Everflow failure must not drop the topline
        logger.exception("Daily close movers unavailable for %s %s", account_id, day)
        movers, movers_unavailable = [], True

    mtd_start, _, _ = _month_bounds(day)
    mtd_spend = pnl._spend_for_account(account_id, mtd_start, day)
    mtd_rev = pnl._revenue_for_account(db, account_id, mtd_start, day)
    if mtd_rev[4]:
        mtd = {"spend": _money(mtd_spend), "revenue": None, "profit": None, "pace": None}
    else:
        mtd_profit = _money(mtd_rev[0]) - _money(mtd_spend)
        mtd = {"spend": _money(mtd_spend), "revenue": _money(mtd_rev[0]), "profit": _money(mtd_profit),
               "pace": _money(mtd_profit / day.day * days_in_month)}
    last_month = _last_month_profit(db, account_id, day, previous_payload)
    mtd.update(days_elapsed=day.day, days_in_month=days_in_month,
               last_month_profit=_money(last_month) if last_month is not None else None)

    spend_r, revenue_r = _money(spend), _money(revenue)
    base.update(revenue=revenue_r, profit=_money(revenue_r - spend_r),
                roas=_money(revenue_r / spend_r) if spend_r else None,
                leads=sum(r["leads"] for r in rows),
                movers={"up": sorted(movers, key=lambda x: x["profit"], reverse=True)[:3],
                        "down": sorted(movers, key=lambda x: x["profit"])[:3]},
                movers_unavailable=movers_unavailable, mtd=mtd)
    return base


def run_close(db, account_ids=None):
    """Write the next version of yesterday's (PT) close per account. An unavailable result is not
    stored once an available version exists for that day, so an Everflow blip at 05:15 can't replace
    a good 04:15 close."""
    results = {}
    day = closed_day()
    for account_id in account_ids or close_accounts():
        try:
            latest = (db.query(DailyCloseVersion).filter_by(account_id=account_id, day=day)
                      .order_by(DailyCloseVersion.version.desc()).first())
            payload = compute_close(db, account_id, day, latest.payload if latest else None)
            if not payload.get("available"):
                has_good = any((r.payload or {}).get("available") for r in
                               db.query(DailyCloseVersion).filter_by(account_id=account_id, day=day).all())
                if has_good:
                    results[account_id] = {"skipped": "revenue unavailable; kept the last available version"}
                    continue
            version = (latest.version + 1) if latest else 1
            db.add(DailyCloseVersion(account_id=account_id, day=day, version=version,
                                     revenue_as_of=datetime.now(timezone.utc), payload=payload))
            db.commit()
            results[account_id] = {"version": version, "available": payload.get("available")}
        except Exception:
            db.rollback()
            logger.exception("Daily close failed for %s", account_id)
    return results
