"""Slack notification helpers for the Ad Builder.

Requires two env vars (both optional — notifications are silently skipped if absent):
  SLACK_BOT_TOKEN    — Bot token (xoxb-...)
  SLACK_ALERT_CHANNEL — Channel ID to post alerts to (default: C08G7PJJ6NB)
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SLACK_API_URL = "https://slack.com/api/chat.postMessage"
DEFAULT_CHANNEL = "C08G7PJJ6NB"
# Steve's Slack user ID — DMing a user ID opens a bot DM. Token rotation is his ops call.
STEVE_DM = "U6M6033G9"


def _token() -> Optional[str]:
    return os.getenv("SLACK_BOT_TOKEN")


def _channel() -> str:
    return os.getenv("SLACK_ALERT_CHANNEL", DEFAULT_CHANNEL)


def send_rule_action_alert(
    action: str,
    adset_name: str,
    fb_adset_id: str,
    reason: str,
    detail: Optional[str] = None,
) -> None:
    """Post a Slack message when a rules-engine rule fires — pause, notify, or a
    budget adjustment. Replaces the old pause-only send_auto_pause_alert as part of
    generalizing auto_pause_rules past pause-only (AdBuilder-BulkRules-Feature-Brief.md).

    Silently no-ops if SLACK_BOT_TOKEN is not configured.
    """
    token = _token()
    if not token:
        logger.debug("SLACK_BOT_TOKEN not set — skipping rule action alert")
        return

    copy = {
        'pause': (
            ":pause_button: *Auto-paused:*",
            "Rule fired and ad set has been paused on Meta. Re-enable the rule in the Ad Builder after reviewing.",
        ),
        'notify': (
            ":bell: *Rule triggered:*",
            "Notify-only rule — no change was made on Meta. Review and act manually if needed.",
        ),
        'increase_budget': (
            ":chart_with_upwards_trend: *Budget increased:*",
            "Rule fired and increased the budget on Meta. Rule has been disabled — re-enable it after reviewing.",
        ),
        'decrease_budget': (
            ":chart_with_downwards_trend: *Budget decreased:*",
            "Rule fired and decreased the budget on Meta. Rule has been disabled — re-enable it after reviewing.",
        ),
    }
    header, footer = copy.get(action, (f":robot_face: *Rule fired ({action}):*", ""))

    lines = [
        f"{header} {adset_name}",
        f">*Reason:* {reason}",
        f">*Ad Set ID:* `{fb_adset_id}`",
    ]
    if detail:
        lines.append(f">*Detail:* {detail}")
    if footer:
        lines.append(f">{footer}")

    try:
        resp = httpx.post(
            SLACK_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "channel": _channel(),
                "text": "\n".join(lines),
                "unfurl_links": False,
                "unfurl_media": False,
            },
            timeout=5,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Rule action Slack alert failed: %s", data.get("error"))
    except Exception as e:
        logger.warning("Rule action Slack alert error: %s", e)


def send_token_expiry_alert(days_left, expires_on: str, is_valid: bool) -> None:
    """DM Steve when FACEBOOK_ACCESS_TOKEN is expiring soon or already invalid.

    Target defaults to Steve's DM; override with SLACK_TOKEN_ALERT_CHANNEL.
    Silently no-ops if SLACK_BOT_TOKEN is not configured.
    """
    token = _token()
    if not token:
        logger.debug("SLACK_BOT_TOKEN not set — skipping token expiry alert")
        return

    if not is_valid:
        text = (
            ":rotating_light: *Ad Builder Meta token is INVALID / expired.*\n"
            ">Pushes, insights, and competitor research are all down until it's rotated.\n"
            ">Fix: regenerate `FACEBOOK_ACCESS_TOKEN` (Graph API Explorer → 60-day exchange), "
            "update the VPS `.env`, then force-recreate the backend."
        )
    else:
        n = int(days_left) if days_left is not None else "?"
        text = (
            f":warning: *Ad Builder Meta token expires in {n} day(s)* (on {expires_on}).\n"
            ">Rotate it before then or pushes, insights, and research go down together.\n"
            ">Graph API Explorer → 60-day exchange → update VPS `.env` → force-recreate backend."
        )

    channel = os.getenv("SLACK_TOKEN_ALERT_CHANNEL", STEVE_DM)
    try:
        resp = httpx.post(
            SLACK_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": channel, "text": text, "unfurl_links": False},
            timeout=5,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Token expiry alert failed: %s", data.get("error"))
    except Exception as e:
        logger.warning("Token expiry alert error: %s", e)


def send_check_summary(
    rules_evaluated: int,
    paused_count: int,
    errors: list,
    notified_count: int = 0,
    budget_adjusted_count: int = 0,
) -> None:
    """Post a summary when Check Now finds multiple issues or errors.

    Only fires if something notable happened (any action fired, or errors exist).
    Silently no-ops if SLACK_BOT_TOKEN is not configured.

    notified_count/budget_adjusted_count default to 0 so existing call sites (if
    any) don't break — but this generalization exists specifically because the
    original pause-only gate (`paused_count == 0 and not errors`) would otherwise
    suppress this whole roll-up on a run that fired only notify/budget rules —
    caught in pre-push review (code-auditor: real live budget changes could
    happen with zero Slack roll-up if nothing was also paused that same cycle).
    """
    token = _token()
    if not token:
        return
    fired = paused_count + notified_count + budget_adjusted_count
    if fired == 0 and not errors:
        return  # Nothing to report

    lines = [f":robot_face: *Rules engine check complete* — {rules_evaluated} rules evaluated"]
    if paused_count:
        lines.append(f">:pause_button: {paused_count} ad set(s) paused")
    if notified_count:
        lines.append(f">:bell: {notified_count} notify rule(s) fired")
    if budget_adjusted_count:
        lines.append(f">:moneybag: {budget_adjusted_count} budget rule(s) fired")
    if errors:
        lines.append(f">:warning: {len(errors)} error(s) — check logs")

    try:
        httpx.post(
            SLACK_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "channel": _channel(),
                "text": "\n".join(lines),
                "unfurl_links": False,
            },
            timeout=5,
        )
    except Exception as e:
        logger.warning("Slack summary error: %s", e)


def send_offer_performance_alert(alerts: list) -> None:
    """Post when an offer's just-closed hour falls well below its own trailing
    7-day baseline for that same hour — catches tracking/DB outages like
    Justin's 2026-09-09 crash, which silently zeroed an hour of conversions
    with nobody noticing until Joel/Abel caught it live.

    `alerts` is a list of dicts from offer_performance_service.check_offer_performance():
    {offer, hour_label, date, actual_count, actual_revenue, baseline_avg,
    pct_of_baseline, is_crater, pause_result?}. A crater (literal 0
    conversions) has already run the auto-pause path (live or dry-run
    depending on OFFER_PERFORMANCE_AUTO_PAUSE_ENABLED) by the time this posts.

    Format: the percentage of normal leads every line — that's the one number
    that actually says how bad it is — with the raw count/baseline and dollar
    figure as supporting detail, and a single, concrete next step instead of
    a hedge. Each alert is a self-contained block (severity emoji + offer +
    hour in its own bold line) so a multi-offer message never reads
    ambiguously if severities differ. Silently no-ops if SLACK_BOT_TOKEN is
    not configured or alerts is empty.
    """
    token = _token()
    if not token:
        logger.debug("SLACK_BOT_TOKEN not set — skipping offer performance alert")
        return
    if not alerts:
        return

    lines = [":bar_chart: *Everflow offer performance*"]
    for a in alerts:
        pct = a.get("pct_of_baseline", 0)
        emoji = ":rotating_light:" if a.get("is_crater") else ":warning:"
        lines.append(
            f"{emoji} *{a['offer']} — {a['hour_label']} ({a['date']}): {pct}% of normal*"
        )
        lines.append(
            f">{a['actual_count']} of ~{a['baseline_avg']} usual conversion(s) this hour "
            f"(${a['actual_revenue']:.2f} revenue)"
        )

        if a.get("is_crater"):
            pr = a.get("pause_result") or {}
            paused, errors = pr.get("paused") or [], pr.get("errors") or []
            excluded = pr.get("excluded_shared_accounts") or []
            if pr.get("dry_run"):
                accounts = ", ".join(pr.get("would_pause_accounts") or []) or "no mapped accounts"
                lines.append(f">*Auto-pause is OFF (scoped, not live)* — would have paused ad sets on {accounts}.")
                lines.append(">*Next step:* check Switchboard/Everflow tracking now.")
            elif pr.get("no_safe_accounts"):
                lines.append(">*Nothing auto-paused* — no account mapping found. Check `SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS`.")
            else:
                lines.append(f">*{len(paused)} ad set(s) auto-paused.* Does *not* auto-resume — reactivate manually once confirmed fixed.")
                if excluded:
                    lines.append(f">:warning: {len(excluded)} account(s) shared with another offer were *not* touched — needs a human call.")
                if errors:
                    lines.append(f">:warning: {len(errors)} ad set(s) couldn't be paused — check manually.")
        else:
            lines.append(">*Next step:* check Switchboard/Everflow tracking before assuming it's a real traffic drop.")

    try:
        resp = httpx.post(
            SLACK_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "channel": _channel(),
                "text": "\n".join(lines),
                "unfurl_links": False,
                "unfurl_media": False,
            },
            timeout=5,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Offer performance alert failed: %s", data.get("error"))
    except Exception as e:
        logger.warning("Offer performance alert error: %s", e)


def send_offer_performance_monitor_down_alert(error: str) -> None:
    """Post when the hourly offer-performance monitor itself can't reach
    Everflow — distinct from a real dip alert, since a monitor gone blind
    could otherwise mean an outage passes completely unnoticed (the exact
    failure mode it exists to catch, one level removed). Caller throttles
    this (offer_performance_service.py) so an extended outage doesn't spam.
    Silently no-ops if SLACK_BOT_TOKEN is not configured.
    """
    token = _token()
    if not token:
        logger.debug("SLACK_BOT_TOKEN not set — skipping offer performance monitor-down alert")
        return

    text = (
        ":warning: *Offer performance monitor couldn't reach Everflow* — "
        "it's blind until this clears, so a real dip wouldn't be caught right now.\n"
        f">*Error:* {error[:500]}"
    )

    try:
        resp = httpx.post(
            SLACK_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": _channel(), "text": text, "unfurl_links": False, "unfurl_media": False},
            timeout=5,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Offer performance monitor-down alert failed: %s", data.get("error"))
    except Exception as e:
        logger.warning("Offer performance monitor-down alert error: %s", e)


def send_drive_sync_alert(summary: str, detail: str = "") -> None:
    """Post a loud alert for Drive creative sync failures."""
    token = _token()
    if not token:
        logger.warning("Drive sync alert skipped because SLACK_BOT_TOKEN is not set: %s", summary)
        return

    text = f":warning: *Google Drive creative sync failed:* {summary}"
    if detail:
        text += f"\n> {detail[:1200]}"

    try:
        resp = httpx.post(
            SLACK_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "channel": _channel(),
                "text": text,
                "unfurl_links": False,
                "unfurl_media": False,
            },
            timeout=5,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Drive sync Slack alert failed: %s", data.get("error"))
    except Exception as e:
        logger.warning("Drive sync Slack alert error: %s", e)
