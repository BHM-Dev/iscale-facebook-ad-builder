"""Loud failure for the money-decision data (Steve, 2026-11-10).

The 2026-11-10 Max CPL outage (Switchboard hanging) only showed as "unavailable" on a page; nobody was
told. This checks the revenue-dependent pieces every 30 minutes and DMs Steve once a problem has lasted
ALERT_AFTER, then once more when it recovers. Read-only: it never writes to Meta or to the database.

State is in memory (single uvicorn worker). A restart forgets it, so a still-broken check alerts again
ALERT_AFTER later; that is the intended failure mode (loud, not silent). Known gap: deploys less than an
hour apart during an outage keep resetting the timer.
"""
from __future__ import annotations

import logging
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ALERT_AFTER = timedelta(minutes=60)
PT = ZoneInfo("America/Los_Angeles")
CLOSE_DUE_PT = dtime(7, 30)   # the close job runs 00:15-06:15 PT

_STATE: dict[str, dict] = {}   # key -> {"since": datetime, "alerted": bool, "detail": str}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def collect_problems(db) -> dict[str, str]:
    """Return {check_key: human detail} for everything currently failing."""
    from app.models import DailyCloseVersion
    from app.services import daily_close_service, max_cpl_service, proposal_service

    problems: dict[str, str] = {}
    for account_id in proposal_service.proposal_accounts():
        try:
            result = max_cpl_service.compute_max_cpl(db, account_id)   # cached; also keeps the cache warm
            if not result.get("available"):
                problems[f"max_cpl:{account_id}"] = f"Max CPL unavailable for {account_id}: {result.get('reason')}"
        except Exception as exc:  # compute_max_cpl shouldn't raise; if it does, that's a problem too
            problems[f"max_cpl:{account_id}"] = f"Max CPL check crashed for {account_id}: {str(exc)[:160]}"

        run = proposal_service.LAST_RUN.get(account_id)
        if run and run.get("revenue_available") is not True:
            problems[f"proposals:{account_id}"] = (
                f"Proposal evaluator couldn't read revenue for {account_id} at {run.get('at')}: {run.get('error')}")

    now_pt = datetime.now(PT)
    if now_pt.time() >= CLOSE_DUE_PT:
        day = daily_close_service.closed_day()
        for account_id in daily_close_service.close_accounts():
            rows = db.query(DailyCloseVersion).filter(DailyCloseVersion.account_id == account_id,
                                                      DailyCloseVersion.day == day).all()
            if not any((r.payload or {}).get("available") for r in rows):
                # Key without the day: a close still missing at midnight must not read as "recovered".
                problems[f"close:{account_id}"] = (
                    f"No available daily close for {account_id} on {day}"
                    + (" (only revenue-unavailable versions)" if rows else " (nothing computed)"))
    return problems


def evaluate_transitions(problems: dict[str, str], now: datetime | None = None) -> list[tuple[str, str, str]]:
    """Pure state machine. Returns [(kind, key, detail)] with kind in {"alert", "recovered"}."""
    now = now or _now()
    out = []
    for key, detail in problems.items():
        st = _STATE.setdefault(key, {"since": now, "alerted": False, "detail": detail})
        st["detail"] = detail
        if not st["alerted"] and now - st["since"] >= ALERT_AFTER:
            st["alerted"] = True
            out.append(("alert", key, detail))
    for key in [k for k in _STATE if k not in problems]:
        st = _STATE.pop(key)
        if st["alerted"]:
            out.append(("recovered", key, st["detail"]))
    return out


def run_check(db) -> dict:
    from app.services.slack_service import send_drive_sync_alert

    problems = collect_problems(db)
    sent = 0
    for kind, key, detail in evaluate_transitions(problems):
        if kind == "alert":
            ok = send_drive_sync_alert(detail, detail="Failing for over an hour. Money decisions on this data "
                                       "(Max CPL, proposals, daily close) are degraded until it recovers.",
                                       headline="Revenue data problem")
        else:
            ok = send_drive_sync_alert(f"Recovered: {detail}", headline="Revenue data recovered")
        if kind == "alert" and not ok and key in _STATE:
            _STATE[key]["alerted"] = False     # Slack failed: try again next tick rather than go silent
        sent += bool(ok)
        logger.warning("Health monitor %s: %s", kind, detail)
    return {"failing": sorted(problems), "messages_sent": sent}
