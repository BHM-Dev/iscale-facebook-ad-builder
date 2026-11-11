"""Morning DM to Steve (2026-11-11): yesterday's close plus the budget raises worth making.

Joel doesn't open Campaign Performance, so its decisions come to Steve instead. Steve decides and
forwards. Steve's DM only, never a team channel. Read-only: it never writes to Meta or the database.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)
MAX_RAISES = 3


def _money(value, signed=False) -> str:
    if value is None:
        return "—"
    v = float(value)
    text = f"${abs(v):,.0f}"
    if signed:
        return ("+" if v >= 0 else "−") + text
    return ("−" if v < 0 else "") + text


def _esc(text) -> str:
    """Slack mrkdwn escaping: names/reasons must not create links or mentions (<!channel>)."""
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ads_manager(account_id: str, adset_id: str) -> str:
    return (f"https://adsmanager.facebook.com/adsmanager/manage/adsets?act={str(account_id).replace('act_', '')}"
            f"&selected_adset_ids={adset_id}")


def close_lines(close: dict, account_names: dict) -> list[str]:
    """Pure: the close section from assemble_latest()'s payload."""
    combined = (close or {}).get("combined")
    if not combined:
        return ["*Yesterday's close:* not computed yet."]
    day = datetime.strptime(combined["day"], "%Y-%m-%d").strftime("%a %b %-d")
    if not combined.get("available"):
        return [f"*{day} close:* revenue not in yet ({combined.get('reason', 'Everflow unavailable')})."]
    roas = f"{combined['roas']:.2f}x" if combined.get("roas") else "—"
    lines = [f"*{day} closed {_money(combined.get('profit'), signed=True)}* · {_money(combined.get('spend'))} spend · "
             f"{roas} · {combined.get('leads') or 0} leads"]
    mtd = combined.get("mtd") or {}
    if mtd.get("profit") is not None:
        lines.append(f"MTD {_money(mtd['profit'], signed=True)} · pacing {_money(mtd.get('pace'), signed=True)}"
                     f" vs last month {_money(mtd.get('last_month_profit'), signed=True)}")
    per = [f"{account_names.get(r.get('account_id'), r.get('account_id'))} {_money(r.get('profit'), signed=True)}"
           for r in close.get("accounts", []) if r.get("available")]
    if len(per) > 1:
        lines.append(" · ".join(per))
    if combined.get("partial"):
        lines.append(f"_Partial: missing {', '.join(combined.get('missing_accounts') or [])}_")
    return lines


def raise_lines(proposals: list) -> list[str]:
    """Pure: top open budget raises by 7-day profit."""
    raises = [p for p in proposals if p.action == "budget_increase"]
    raises.sort(key=lambda p: -float(((p.evidence or {}).get("totals_7d") or {}).get("profit") or 0))
    if not raises:
        return ["*Budget raises:* none today."]
    lines = [f"*Budget raises worth making ({len(raises)} open, top {min(MAX_RAISES, len(raises))}):*"]
    for p in raises[:MAX_RAISES]:
        params = p.action_params or {}
        frm, to = params.get("from_cents"), params.get("to_cents")
        budget = f"${frm / 100:,.0f} → ${to / 100:,.0f}/day" if frm and to else "+20%"
        why = _esc((p.evidence or {}).get("why", ""))
        # Ad set names like "VW-PLOW | SNOW PLOWING" contain "|", which Slack reads as the link separator.
        label = _esc(str(p.adset_name or p.fb_adset_id).replace("|", "·"))
        lines.append(f"• <{_ads_manager(p.fb_account_id, p.fb_adset_id)}|{label}>: {budget}. {why}")
    if len(raises) > MAX_RAISES:
        lines.append(f"…and {len(raises) - MAX_RAISES} more in the Proposals panel on Campaign Performance.")
    return lines


def build_digest(db) -> str:
    from app.api.v1.daily_close import assemble_latest
    from app.models import ActionProposal
    from app.services import daily_close_service
    from app.services.health_monitor import collect_problems

    accounts = daily_close_service.close_accounts()
    names = {"act_521142087204815": "RHO Commercial", "act_737291135429748": "RHO 4"}

    lines = close_lines(assemble_latest(db, accounts), names)
    lines.append("")
    open_rows = db.query(ActionProposal).filter(ActionProposal.status == "open").all()
    lines += raise_lines(open_rows)
    pauses = [p for p in open_rows if p.action == "pause"]
    if pauses:
        lines.append(f"_{len(pauses)} pause flag(s) open (visible only to you)._")
    try:
        problems = collect_problems(db)
    except Exception as exc:
        problems = {"health": f"health check crashed: {str(exc)[:120]}"}
    if problems:
        lines.append("")
        lines.append(":warning: *Data problems right now:* " + "; ".join(problems.values()))
    return "\n".join(lines)


def send_digest(db) -> bool:
    from app.services.slack_service import SLACK_API_URL, STEVE_DM, _token

    token = _token()
    if not token:
        logger.warning("Morning digest skipped: SLACK_BOT_TOKEN not set")
        return False
    text = ":sunrise: *[Ad Builder] Morning brief*\n" + build_digest(db)
    resp = httpx.post(SLACK_API_URL, headers={"Authorization": f"Bearer {token}"},
                      json={"channel": STEVE_DM, "text": text,   # Steve's DM only, by design
                            "unfurl_links": False, "unfurl_media": False}, timeout=15)
    try:
        ok = resp.status_code == 200 and resp.json().get("ok")
    except ValueError:
        ok = False
    if not ok:
        logger.warning("Morning digest post failed: %s", resp.text[:200])
    return bool(ok)
