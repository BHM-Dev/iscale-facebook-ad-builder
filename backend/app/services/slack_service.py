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


def send_auto_pause_alert(
    adset_name: str,
    fb_adset_id: str,
    reason: str,
    rules_evaluated: int,
) -> None:
    """Post a Slack message when an auto-pause rule fires.

    Silently no-ops if SLACK_BOT_TOKEN is not configured.
    """
    token = _token()
    if not token:
        logger.debug("SLACK_BOT_TOKEN not set — skipping auto-pause alert")
        return

    text = (
        f":pause_button: *Auto-paused:* {adset_name}\n"
        f">*Reason:* {reason}\n"
        f">*Ad Set ID:* `{fb_adset_id}`\n"
        f">Rule fired and ad set has been paused on Meta. "
        f"Re-enable the rule in the Ad Builder after reviewing."
    )

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
            logger.warning("Slack alert failed: %s", data.get("error"))
    except Exception as e:
        logger.warning("Slack alert error: %s", e)


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
) -> None:
    """Post a summary when Check Now finds multiple issues or errors.

    Only fires if something notable happened (paused > 0 or errors exist).
    Silently no-ops if SLACK_BOT_TOKEN is not configured.
    """
    token = _token()
    if not token:
        return
    if paused_count == 0 and not errors:
        return  # Nothing to report

    lines = [f":robot_face: *Auto-pause check complete* — {rules_evaluated} rules evaluated"]
    if paused_count:
        lines.append(f">:pause_button: {paused_count} ad set(s) paused")
    if errors:
        lines.append(f">:warning: {len(errors)} error(s) fetching insights — check logs")

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
    {offer, hour_label, date, actual_count, actual_revenue, baseline_avg, is_crater,
    pause_result?}. A crater (literal 0 conversions) has already triggered an
    automatic pause of every active ad set on that offer's accounts by the
    time this posts — the message says so plainly, distinct from a soft dip
    where nothing was touched. Silently no-ops if SLACK_BOT_TOKEN is not
    configured or alerts is empty.
    """
    token = _token()
    if not token:
        logger.debug("SLACK_BOT_TOKEN not set — skipping offer performance alert")
        return
    if not alerts:
        return

    has_crater = any(a.get("is_crater") for a in alerts)
    header = (
        ":rotating_light: *0% CR — campaigns auto-paused*" if has_crater
        else ":rotating_light: *Offer performance dip detected*"
    )
    lines = [header]
    for a in alerts:
        if a.get("is_crater"):
            pr = a.get("pause_result") or {}
            paused, errors = pr.get("paused") or [], pr.get("errors") or []
            excluded = pr.get("excluded_shared_accounts") or []
            status_line = f"*{len(paused)} ad set(s) auto-paused.*"
            if excluded:
                status_line += (
                    f" :warning: {len(excluded)} account(s) mapped to *more than one offer* "
                    f"were deliberately *not* touched — needs a human call, could affect an unrelated offer."
                )
            elif pr.get("no_safe_accounts"):
                status_line = ":warning: *No account mapping found — nothing was auto-paused.* Check `SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS` config."
            if errors:
                status_line += f" :warning: {len(errors)} couldn't be paused — check manually."
            lines.append(
                f">*{a['offer']}* — {a['hour_label']} ({a['date']}): "
                f"0 conversions vs. ~{a['baseline_avg']} normal for this hour. {status_line}"
                "\n>This does *not* auto-resume. Confirm the tracking issue is resolved "
                "(Switchboard/Everflow, or the advertiser's own system), then reactivate manually."
            )
        else:
            lines.append(
                f">*{a['offer']}* — {a['hour_label']} ({a['date']}): "
                f"{a['actual_count']} conversion(s) (${a['actual_revenue']:.2f}) vs. "
                f"~{a['baseline_avg']} normal for this hour. Worth a quick check — "
                f"could be a tracking/DB issue upstream (Switchboard/Everflow) rather than a real traffic drop."
            )

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
