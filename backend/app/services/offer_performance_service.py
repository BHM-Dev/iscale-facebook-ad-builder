"""Hourly offer-performance monitor — catches Everflow conversion-flow outages.

Built 2026-09-09 after Justin's (the advertiser's) database crashed for an
unknown window and silently zeroed out an hour of conversions on "Get
Business Coverage" — nobody noticed until Joel/Abel caught degraded
performance live and had to ask around. This exists to catch that kind of
gap automatically instead of relying on someone watching the dashboard.

Deliberately offer-scoped, not account-scoped: this only answers "is the
tracking/conversion pipe healthy for this offer," not "which Meta account
gets billing credit" — that's pnl.py's job, and depends on local ad-set sync
completeness this doesn't need. Reads whichever offers are currently
configured in SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS, so it automatically covers
new offers as they're added there — no code change needed.

No DB table: the trailing baseline is recomputed fresh from Everflow on every
run. Simpler, and avoids yet another migration for a monitor that only needs
a rolling window, never history beyond it.
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from app.services import slack_service
from app.services.everflow_service import DEFAULT_TIMEZONE_ID, EVERFLOW_TZ_BY_ID, EverflowService

logger = logging.getLogger(__name__)

# Only alert for hours where there's normally enough volume that a real
# outage is distinguishable from ordinary quiet — flagging a 3am hour whose
# own baseline is 1 conversion is noise, not signal.
MIN_BASELINE_TO_MONITOR = 3
# How far below its own baseline counts as a real dip vs normal hour-to-hour
# noise. Validated against the 2026-09-09 incident: 8am ET baseline ~4.6,
# actual 0 — comfortably below this ratio.
ALERT_THRESHOLD_RATIO = 0.25
BASELINE_DAYS = 7
# Throttle for the "monitor itself is failing" alert — an extended Everflow
# outage would otherwise fire this 24x/day. Module-level, so it resets on a
# process restart; losing that state just means one extra alert, not a
# correctness problem (this whole service is stateless by design).
FETCH_FAILURE_ALERT_COOLDOWN_HOURS = 4
_last_fetch_failure_alert: datetime | None = None


def _maybe_alert_fetch_failure(error: str) -> None:
    global _last_fetch_failure_alert
    now = datetime.now()
    if _last_fetch_failure_alert is not None and (now - _last_fetch_failure_alert) < timedelta(hours=FETCH_FAILURE_ALERT_COOLDOWN_HOURS):
        return
    _last_fetch_failure_alert = now
    slack_service.send_offer_performance_monitor_down_alert(error)


def _offer_names() -> set[str]:
    """Union of every offer name configured across all accounts.

    Mirrors pnl.py's _everflow_offer_names_for_account parsing (trim,
    str-or-list, dict-type guard) so the two never quietly disagree on what
    counts as a configured offer name — this file is deliberately broader
    (every account's offers, not one), but the per-value parsing rules match.
    """
    raw = os.getenv("SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS", "")
    if not raw.strip():
        return set()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    if not isinstance(parsed, dict):
        return set()
    names: set[str] = set()
    for values in parsed.values():
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        names.update(str(v).strip() for v in values if str(v).strip())
    return names


def check_offer_performance() -> dict:
    """Run one hourly check. Posts to Slack only if an anomaly is found.

    Returns a summary dict (used by the scheduler's log line and available
    for a future manual "check now" endpoint).
    """
    offer_names = _offer_names()
    if not offer_names:
        return {"checked": False, "reason": "no offers configured in SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS"}

    svc = EverflowService()
    if not svc.is_configured():
        return {"checked": False, "reason": "SWITCHBOARD_EVERFLOW_API_KEY not configured"}

    tz = EVERFLOW_TZ_BY_ID[DEFAULT_TIMEZONE_ID]
    now = datetime.now(tz=tz)
    # Evaluate the hour that just closed, not the in-progress one — the
    # scheduler fires a few minutes past the hour specifically so this hour's
    # conversions (and their postbacks) have had time to land.
    check_hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    check_date = check_hour_start.date()
    check_hour = check_hour_start.hour

    range_start = check_date - timedelta(days=BASELINE_DAYS)

    try:
        rows = svc.get_raw_conversions(range_start, check_date, timezone_id=DEFAULT_TIMEZONE_ID)
    except Exception as exc:
        logger.warning("offer_performance: Everflow fetch failed: %s", exc)
        # A monitor that goes silently blind when its OWN data source fails is
        # the exact failure mode it exists to catch, one level removed — alert
        # on this too, just throttled so an extended outage doesn't spam 24x/day.
        _maybe_alert_fetch_failure(str(exc))
        return {"checked": False, "reason": f"fetch failed: {exc}"}

    # counts[offer][(date_iso, hour)] = {"count": int, "revenue": Decimal}
    counts: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"count": 0, "revenue": Decimal("0")}))
    for row in rows:
        offer = ((row.get("relationship") or {}).get("offer") or {}).get("name")
        if offer not in offer_names:
            continue
        ts = row.get("conversion_unix_timestamp")
        if not ts:
            continue
        dt = datetime.fromtimestamp(int(ts), tz=tz)
        slot = counts[offer][(dt.date().isoformat(), dt.hour)]
        slot["count"] += 1
        slot["revenue"] += Decimal(str(row.get("revenue") or 0))

    alerts = []
    for offer in sorted(offer_names):
        offer_counts = counts.get(offer, {})
        baseline_days = [range_start + timedelta(days=i) for i in range(BASELINE_DAYS)]
        baseline_vals = [offer_counts.get((d.isoformat(), check_hour), {"count": 0})["count"] for d in baseline_days]
        baseline_avg = sum(baseline_vals) / len(baseline_vals) if baseline_vals else 0.0

        if baseline_avg < MIN_BASELINE_TO_MONITOR:
            continue  # Not enough normal volume in this hour to judge an outage

        actual = offer_counts.get((check_date.isoformat(), check_hour), {"count": 0, "revenue": Decimal("0")})
        if actual["count"] > baseline_avg * ALERT_THRESHOLD_RATIO:
            continue  # Within normal range

        alerts.append({
            "offer": offer,
            "hour_label": f"{check_hour_start.strftime('%-I%p').lower()} ET",
            "date": check_date.isoformat(),
            "actual_count": actual["count"],
            "actual_revenue": float(actual["revenue"]),
            "baseline_avg": round(baseline_avg, 1),
        })

    if alerts:
        slack_service.send_offer_performance_alert(alerts)
        logger.warning(
            "offer_performance: %d alert(s) for %s hour %d: %s",
            len(alerts), check_date.isoformat(), check_hour, alerts,
        )
    else:
        logger.info(
            "offer_performance: checked %s hour %d across %d offer(s), no anomalies",
            check_date.isoformat(), check_hour, len(offer_names),
        )

    return {"checked": True, "date": check_date.isoformat(), "hour": check_hour, "alerts": alerts}
