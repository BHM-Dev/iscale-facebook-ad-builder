"""FACEBOOK_ACCESS_TOKEN expiry monitor.

The Ad Builder's core Meta token is a personal (USER) token that expires every
~60 days. When it lapses, every Meta call fails at once — pushes, insights, and
research all go down together (this happened once already). This module checks
the *live* token's expiry via Meta's debug_token endpoint so we can warn ahead
of time instead of discovering it through an outage.

It reads the same token the app actually runs on (FACEBOOK_ACCESS_TOKEN) plus
the app credentials already in the environment — no new secrets, no duplicated
token that could drift out of sync with the deployed one.
"""
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com"


def check_token_expiry() -> dict:
    """Check the live FACEBOOK_ACCESS_TOKEN's validity and time to expiry.

    Returns a dict:
      checked       — False if we couldn't run the check (missing env / API error)
      is_valid      — bool | None
      never_expires — True when expires_at == 0 (e.g. a system-user token)
      expires_at    — unix timestamp (0 = never)
      days_left     — float | None (None when never_expires or not checked)
      error         — str | None
    """
    result = {
        "checked": False, "is_valid": None, "never_expires": False,
        "expires_at": 0, "days_left": None, "error": None,
    }

    token = os.getenv("FACEBOOK_ACCESS_TOKEN") or os.getenv("VITE_FACEBOOK_ACCESS_TOKEN")
    app_id = os.getenv("FACEBOOK_APP_ID")
    app_secret = os.getenv("FACEBOOK_APP_SECRET")
    if not (token and app_id and app_secret):
        result["error"] = "missing FACEBOOK_ACCESS_TOKEN / FACEBOOK_APP_ID / FACEBOOK_APP_SECRET"
        return result

    try:
        resp = httpx.get(
            f"{GRAPH}/debug_token",
            params={"input_token": token, "access_token": f"{app_id}|{app_secret}"},
            timeout=10,
        )
        data = (resp.json() or {}).get("data", {})
        expires_at = int(data.get("expires_at", 0) or 0)
        never = expires_at == 0
        result.update({
            "checked": True,
            "is_valid": bool(data.get("is_valid")),
            "never_expires": never,
            "expires_at": expires_at,
            "days_left": None if never else (expires_at - time.time()) / 86400.0,
        })
    except Exception as e:  # network / parse — never raise into the scheduler
        result["error"] = str(e)
        logger.warning("Token expiry check failed: %s", e)

    return result
