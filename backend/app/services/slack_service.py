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
