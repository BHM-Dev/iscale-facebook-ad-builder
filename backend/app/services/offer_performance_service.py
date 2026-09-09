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

# Scoped out, not shipped live (Steve, 2026-09-09): the capability — pausing
# every active ad set on an offer's accounts when it hits 0% CR — is fully
# built and reviewed, but stays a dry-run (alert-only, no Meta write) until
# this is explicitly set to a truthy value. Flip on deliberately when ready,
# don't infer readiness from this code existing.
AUTO_PAUSE_ENABLED = os.getenv("OFFER_PERFORMANCE_AUTO_PAUSE_ENABLED", "").strip().lower() in ("1", "true", "yes")

# De-dup: never alert twice for the same (offer, date, hour) — a scheduler
# misfire-recovery, a process restart mid-hour, or someone manually invoking
# check_offer_performance() for verification (confirmed real failure mode,
# 2026-09-09 — a manual test run duplicated a real alert the schedule had
# already sent for the same hour) would otherwise double-post to a channel
# people actually watch. Module-level, resets on restart — losing this on a
# restart risks one possible duplicate, not a correctness problem.
_alerted_hours: dict[str, tuple[str, int]] = {}


def _maybe_alert_fetch_failure(error: str) -> None:
    global _last_fetch_failure_alert
    now = datetime.now()
    if _last_fetch_failure_alert is not None and (now - _last_fetch_failure_alert) < timedelta(hours=FETCH_FAILURE_ALERT_COOLDOWN_HOURS):
        return
    _last_fetch_failure_alert = now
    slack_service.send_offer_performance_monitor_down_alert(error)


def _parsed_offer_config() -> dict:
    raw = os.getenv("SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS", "")
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _account_offer_map() -> dict[str, list[str]]:
    """account_id -> list of offer names, normalized (str-or-list, trimmed)."""
    result: dict[str, list[str]] = {}
    for account_id, values in _parsed_offer_config().items():
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        result[account_id] = [str(v).strip() for v in values if str(v).strip()]
    return result


def _accounts_for_offer(offer_name: str) -> tuple[list[str], list[str]]:
    """Which Meta account IDs run this Switchboard offer, for auto-pause scoping.

    Returns (safe_account_ids, excluded_shared_account_ids). An account
    mapped to MORE THAN ONE offer is deliberately excluded from the pause
    target list — today's config never does this, but nothing enforces that
    staying true, and pausing a shared account on one offer's outage would
    silently halt spend for a completely unrelated, healthy offer with no one
    having decided that tradeoff. Fail closed: log/alert the exclusion loudly
    rather than guess which offer "owns" a shared account.
    """
    account_offers = _account_offer_map()
    safe, excluded = [], []
    for account_id, offers in account_offers.items():
        if offer_name not in offers:
            continue
        if len(offers) > 1:
            excluded.append(account_id)
        else:
            safe.append(account_id)
    return safe, excluded


def _pause_all_active_adsets(account_ids: list[str]) -> dict:
    """Emergency stop: pause every currently-ACTIVE ad set on these accounts.

    Pulls LIVE from Meta, not the local FacebookAdSet cache — that cache has
    known sync gaps (rate-limit-driven, see
    project_adbuilder_pnl_everflow_billable_revenue.md memory), and an
    emergency stop must not miss an ad set just because local sync lagged.

    Never auto-resumes anything — that's a deliberate, separate human action.
    A flapping auto-pause/auto-resume loop on a still-broken tracking pipe
    would be worse than staying paused an extra hour.
    """
    from app.services.facebook_service import FacebookService

    svc = FacebookService()
    paused = []
    errors = []
    for account_id in account_ids:
        try:
            adsets = svc.get_adsets(ad_account_id=account_id)
        except Exception as exc:
            errors.append({"account_id": account_id, "error": f"could not list ad sets: {exc}"})
            continue
        for a in adsets:
            if a.get("status") != "ACTIVE":
                continue
            fb_adset_id = str(a.get("id") or "")
            if not fb_adset_id:
                continue
            try:
                svc.update_adset_status(fb_adset_id, "PAUSED")
                paused.append({"account_id": account_id, "fb_adset_id": fb_adset_id, "name": a.get("name")})
            except Exception as exc:
                errors.append({"account_id": account_id, "fb_adset_id": fb_adset_id, "name": a.get("name"), "error": str(exc)})
    return {"paused": paused, "errors": errors}


def _offer_names() -> set[str]:
    """Union of every offer name configured across all accounts.

    Built from the same _account_offer_map() as _accounts_for_offer, so the
    two can never quietly disagree on what counts as a configured offer name.
    """
    names: set[str] = set()
    for offers in _account_offer_map().values():
        names.update(offers)
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

        this_hour_key = (check_date.isoformat(), check_hour)
        if _alerted_hours.get(offer) == this_hour_key:
            logger.info("offer_performance: already alerted %s for %s — skipping duplicate", offer, this_hour_key)
            continue
        _alerted_hours[offer] = this_hour_key

        # A hard zero (literal 0% CR against a real baseline) escalates past
        # alerting to an automatic stop — Steve, 2026-09-09: "if we ever drop
        # to a 0% CR we need to auto pause all campaigns" so a real tracking
        # outage stops wasting spend immediately rather than waiting for
        # someone to see the Slack alert. Softer dips (>0 but still ≤25% of
        # baseline) stay alert-only — this is deliberately conservative,
        # scoped to the literal-zero case Steve named.
        is_crater = actual["count"] == 0

        alerts.append({
            "offer": offer,
            "hour_label": f"{check_hour_start.strftime('%-I%p').lower()} ET",
            "date": check_date.isoformat(),
            "actual_count": actual["count"],
            "actual_revenue": float(actual["revenue"]),
            "baseline_avg": round(baseline_avg, 1),
            "is_crater": is_crater,
        })

        if is_crater:
            # Never let a failure in the pause path (or even a bug in
            # _accounts_for_offer itself) abort this loop and skip the final
            # send_offer_performance_alert() below — that would silently drop
            # the Slack alert for every offer's finding in this run, not just
            # this one, which is the exact "monitor goes blind" failure mode
            # this whole file exists to prevent.
            try:
                account_ids, excluded = _accounts_for_offer(offer)
                if excluded:
                    logger.warning(
                        "offer_performance: %s config maps account(s) %s to multiple offers — "
                        "excluded from auto-pause, needs a human decision",
                        offer, excluded,
                    )
                if not AUTO_PAUSE_ENABLED:
                    # Scoped out, not shipped live — Steve, 2026-09-09: he
                    # wanted the auto-pause CAPABILITY designed, not turned on
                    # yet. Alert-only until OFFER_PERFORMANCE_AUTO_PAUSE_ENABLED
                    # is explicitly set true; no Meta write happens here.
                    alerts[-1]["pause_result"] = {
                        "paused": [], "errors": [], "excluded_shared_accounts": excluded,
                        "dry_run": True, "would_pause_accounts": account_ids,
                    }
                    logger.warning(
                        "offer_performance: 0%% CR on %s — auto-pause is DISABLED "
                        "(dry run only), would have targeted accounts %s",
                        offer, account_ids,
                    )
                elif account_ids:
                    pause_result = _pause_all_active_adsets(account_ids)
                    pause_result["excluded_shared_accounts"] = excluded
                    alerts[-1]["pause_result"] = pause_result
                    logger.warning(
                        "offer_performance: 0%% CR on %s — auto-paused %d ad set(s) across %s, %d error(s): %s",
                        offer, len(pause_result["paused"]), account_ids, len(pause_result["errors"]), pause_result,
                    )
                else:
                    alerts[-1]["pause_result"] = {
                        "paused": [], "errors": [], "excluded_shared_accounts": excluded,
                        "no_safe_accounts": True,
                    }
                    logger.warning(
                        "offer_performance: 0%% CR on %s but no safe account mapping found "
                        "(excluded shared accounts: %s) — nothing auto-paused",
                        offer, excluded,
                    )
            except Exception as exc:
                logger.error("offer_performance: auto-pause path failed for %s: %s", offer, exc)
                alerts[-1]["pause_result"] = {"paused": [], "errors": [{"error": f"pause path crashed: {exc}"}]}

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
