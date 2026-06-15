"""
Campaign Intelligence — structured niche profitability analysis.

GET /api/v1/intelligence/niche-profitability
  ?preset=weekends_mtd
  ?preset=custom&date_from=2026-06-01&date_to=2026-06-14
  ?ad_account_id=act_521142087204815

Supported presets: today, yesterday, last_3d, last_7d, last_14d, last_30d,
                   this_month, weekdays_mtd, weekends_mtd, custom
"""

import logging
import os
import re
from datetime import date, timedelta, datetime
from typing import Optional, Dict

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user, get_db
from app.models import User, FacebookAdSet
from app.services.redtrack_service import RedTrackService

logger = logging.getLogger(__name__)
router = APIRouter()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

_NON_NICHE_RE = re.compile(
    r'^(batch\s*\d+|v\d+|scale|retarget|broad|phase\s*\d+|test|duplicate|copy)$',
    re.IGNORECASE,
)


def _extract_niche(adset_name: str) -> str:
    if not adset_name:
        return "General"
    parts = [p.strip() for p in adset_name.split(" - ")]
    for part in parts[1:]:
        if part and not _NON_NICHE_RE.match(part) and not re.match(r'^\d{1,2}/\d{1,2}', part):
            return part
    if parts and not re.match(r'^\d{1,2}/\d{1,2}', parts[0]):
        return parts[0]
    return "General"


def _resolve_preset(preset: str, date_from: Optional[str], date_to: Optional[str]):
    """Return (date_from, date_to, day_filter, label)."""
    today = date.today()
    month_start = today.replace(day=1)
    if preset == "today":
        return str(today), str(today), "all", "Today"
    if preset == "yesterday":
        d = today - timedelta(days=1)
        return str(d), str(d), "all", "Yesterday"
    if preset == "last_3d":
        return str(today - timedelta(days=2)), str(today), "all", "Last 3 days"
    if preset == "last_7d":
        return str(today - timedelta(days=6)), str(today), "all", "Last 7 days"
    if preset == "last_14d":
        return str(today - timedelta(days=13)), str(today), "all", "Last 14 days"
    if preset == "this_month":
        return str(month_start), str(today), "all", "This month"
    if preset == "last_30d":
        return str(today - timedelta(days=29)), str(today), "all", "Last 30 days"
    if preset == "weekdays_mtd":
        return str(month_start), str(today), "weekday", "Weekdays MTD"
    if preset == "weekends_mtd":
        return str(month_start), str(today), "weekend", "Weekends MTD"
    if preset == "custom" and date_from and date_to:
        return date_from, date_to, "all", f"{date_from} – {date_to}"
    return str(today - timedelta(days=6)), str(today), "all", "Last 7 days"


def _fetch_meta_insights(ad_account_id: Optional[str], date_from: str, date_to: str, day_filter: str) -> dict:
    """
    Fetch Meta ad set insights. When day_filter is weekday/weekend, uses
    time_increment=1 to get daily rows, filters by day-of-week, then sums.
    Returns dict keyed by fb_adset_id -> { adset_name, spend, leads, impressions, cpl }.
    """
    from app.services.facebook_service import FacebookService
    from facebook_business.exceptions import FacebookRequestError

    svc = FacebookService()
    svc.initialize()

    fields = [
        'adset_id', 'adset_name', 'spend', 'impressions', 'actions',
    ]

    lead_types = {'lead', 'onsite_conversion.lead_grouped', 'offsite_conversion.fb_pixel_lead'}

    try:
        account = svc._get_account(ad_account_id)
        params: dict = {
            'time_range': {'since': date_from, 'until': date_to},
            'level': 'adset',
        }
        if day_filter != "all":
            params['time_increment'] = 1  # daily breakdown for DOW filtering

        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(account.get_insights, fields, params)
            try:
                results = future.result(timeout=30)
            except FuturesTimeout:
                raise RuntimeError("Meta API timeout — try again in a moment")

    except RuntimeError:
        raise
    except FacebookRequestError as e:
        body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
        msg = (body.get('error', {}) if isinstance(body, dict) else {}).get('message') or str(e)
        raise RuntimeError(f"Facebook API: {msg}")

    valid_dows = ({5, 6} if day_filter == "weekend" else {0, 1, 2, 3, 4}) if day_filter != "all" else None
    out: dict = {}

    for row in results:
        # Day-of-week filter
        if valid_dows is not None:
            date_start = str(row.get('date_start') or '')
            try:
                dow = datetime.strptime(date_start, '%Y-%m-%d').weekday()
            except (ValueError, TypeError):
                continue
            if dow not in valid_dows:
                continue

        fb_id = str(row.get('adset_id') or '')
        if not fb_id:
            continue

        spend = float(row.get('spend', 0) or 0)
        leads = sum(
            int(float(a.get('value', 0) or 0))
            for a in (row.get('actions') or [])
            if a.get('action_type') in lead_types
        )
        impressions = int(row.get('impressions', 0) or 0)

        if fb_id not in out:
            out[fb_id] = {
                'adset_name': str(row.get('adset_name') or ''),
                'spend': 0.0,
                'leads': 0,
                'impressions': 0,
            }
        out[fb_id]['spend'] = round(out[fb_id]['spend'] + spend, 2)
        out[fb_id]['leads'] += leads
        out[fb_id]['impressions'] += impressions

    for m in out.values():
        m['cpl'] = round(m['spend'] / m['leads'], 2) if m['leads'] > 0 else None

    return out


def _fetch_redtrack(date_from: str, date_to: str) -> dict:
    svc = RedTrackService()
    if not svc.is_configured():
        return {}
    try:
        return svc.get_report_by_adset(date_from, date_to)
    except Exception as e:
        logger.warning("RedTrack fetch failed: %s", e)
        return {}


def _assign_verdict(spend: float, revenue: float, join_status: str, day_filter: str = "all") -> str:
    """Return verdict string. When day_filter != 'all', directional_ prefix is used
    for action verdicts because RedTrack revenue is full-range, not day-filtered."""
    if join_status == "missing_redtrack":
        return "tracking_check"
    if spend < 50:
        return "insufficient_data"
    roi = (revenue - spend) / spend
    directional = day_filter != "all"
    if roi >= 0.25:
        return "directional_scale" if directional else "scale"
    if roi >= 0:
        return "directional_run" if directional else "run"
    if roi > -0.25:
        return "directional_watch" if directional else "watch"
    return "directional_pause" if directional else "pause"


def _assign_confidence(spend: float, leads: int):
    """Return (confidence, reason) tuple."""
    if spend >= 300 and leads >= 10:
        return "high", "Spend ≥ $300 and leads ≥ 10"
    if spend >= 100 or leads >= 5:
        return "medium", "Spend ≥ $100 or leads ≥ 5"
    return "low", "Limited spend or leads"


def _assign_suggested_action(verdict: str, confidence: str, roi: Optional[float]):
    """Return (suggested_action, label) tuple."""
    directional_map = {
        "directional_scale": ("directional_scale", "Directional scale"),
        "directional_run":   ("directional_hold",  "Directional hold"),
        "directional_watch": ("directional_watch",  "Directional watch"),
        "directional_pause": ("investigate",        "Investigate"),
    }
    if verdict in directional_map:
        return directional_map[verdict]
    if verdict == "scale":
        if confidence == "high":   return "scale_20", "Scale +20%"
        if confidence == "medium": return "scale_10", "Scale +10%"
        return "watch", "Watch"
    if verdict == "run":
        return "hold", "Hold"
    if verdict == "watch":
        if roi is not None and roi < -0.10:
            return "potential_cut", "Potential cut"
        return "watch", "Watch"
    if verdict == "pause":
        if confidence == "high":
            return "pause", "Pause"
        if confidence == "medium":
            return "review_pause", "Review pause"
        return "potential_cut", "Potential cut"
    if verdict == "tracking_check":
        return "audit_tracking", "Audit tracking"
    return "collect_data", "Collect data"


def _build_action_queue(rows: list) -> dict:
    scale_actions = {"scale_20", "scale_10", "directional_scale"}
    cut_actions   = {"pause", "review_pause", "potential_cut", "investigate"}
    watch_actions = {"watch", "hold", "directional_watch", "directional_hold"}

    conf_rank = {"high": 0, "medium": 1, "low": 2}
    # Severity order for cut/review actions
    cut_rank = {"pause": 0, "review_pause": 1, "potential_cut": 2, "investigate": 3}

    scale_rows = [r for r in rows if r['suggested_action'] in scale_actions]
    cut_rows   = [r for r in rows if r['suggested_action'] in cut_actions]
    watch_rows = [r for r in rows if r['suggested_action'] in watch_actions]
    track_rows = [r for r in rows if r['join_status'] in ("partial_redtrack", "missing_redtrack")
                                      or r['verdict'] == "tracking_check"]

    # scale: highest profit first, then ROI, then confidence
    scale_rows.sort(key=lambda r: (
        -(r['profit'] or 0),
        -(r['roi'] or 0),
        conf_rank.get(r['confidence'], 9),
    ))

    # cut/pause: hard pauses first, then most negative profit, then most negative ROI
    cut_rows.sort(key=lambda r: (
        cut_rank.get(r['suggested_action'], 9),
        (r['profit'] or 0),
        (r['roi'] or 0),
    ))

    # tracking: missing RT first, then partial RT sorted by spend desc
    track_rows.sort(key=lambda r: (
        0 if r['join_status'] == "missing_redtrack" else 1,
        -(r['spend'] or 0),
    ))

    # watch: most negative profit first, then spend desc
    watch_rows.sort(key=lambda r: (
        (r['profit'] or 0),
        -(r['spend'] or 0),
    ))

    return {
        "scale":          [f"{r['niche']} ({r['suggested_action_label']})" for r in scale_rows[:5]],
        "cut_or_pause":   [f"{r['niche']} ({r['suggested_action_label']})" for r in cut_rows[:5]],
        "watch":          [r['niche'] for r in watch_rows[:5]],
        "tracking_check": [r['niche'] for r in track_rows[:5]],
    }


def _build_tracking_warning(rows: list) -> dict:
    partial = sum(1 for r in rows if r['join_status'] == "partial_redtrack")
    missing = sum(1 for r in rows if r['join_status'] == "missing_redtrack")
    if partial == 0 and missing == 0:
        return {"has_warning": False, "partial_count": 0, "missing_count": 0, "message": ""}

    parts = []
    if partial:
        noun = "niches have" if partial > 1 else "niche has"
        parts.append(f"{partial} {noun} partial RedTrack match")
    if missing:
        verb = "are" if missing > 1 else "is"
        parts.append(f"{missing} {verb} missing RedTrack revenue")
    message = " and ".join(parts) + ". Treat ROI as directional until verified."
    return {"has_warning": True, "partial_count": partial, "missing_count": missing, "message": message}


def _aggregate_by_niche(meta_data: dict, rt_data: dict, day_filter: str, budget_map: dict) -> list:
    """Join Meta + RT by adset, aggregate by niche, assign verdicts, confidence, and actions."""
    niche_map: dict = {}

    for fb_id, m in meta_data.items():
        rt = rt_data.get(fb_id)
        revenue    = float(rt['revenue'])    if rt else 0.0
        conversions = int(rt['conversions']) if rt else 0
        adset_join = "matched" if rt is not None else "missing_redtrack"

        adset_spend = m['spend']
        adset_roi   = (revenue - adset_spend) / adset_spend if adset_spend > 0 else None

        niche = _extract_niche(m['adset_name'])
        if niche not in niche_map:
            niche_map[niche] = {
                'niche': niche,
                'spend': 0.0,
                'revenue': 0.0,
                'leads': 0,
                'redtrack_conversions': 0,
                'adset_count': 0,
                'missing_rt': 0,
                'daily_budget_cents': 0,
                'adsets': [],
            }
        b = niche_map[niche]
        b['spend']   = round(b['spend'] + adset_spend, 2)
        b['revenue'] = round(b['revenue'] + revenue, 2)
        b['leads']   += m['leads']
        b['redtrack_conversions'] += conversions
        b['adset_count'] += 1
        if adset_join == "missing_redtrack":
            b['missing_rt'] += 1

        budget = budget_map.get(fb_id)
        if budget:
            b['daily_budget_cents'] += budget

        b['adsets'].append({
            'name':    m['adset_name'],
            'spend':   adset_spend,
            'revenue': revenue,
            'roi':     adset_roi,
        })

    rows = []
    for niche, b in niche_map.items():
        spend = b['spend']
        if spend < 0.01:
            continue
        revenue = b['revenue']
        profit  = round(revenue - spend, 2)
        roi     = round(profit / spend, 4) if spend > 0 else None
        cpl     = round(spend / b['leads'], 2) if b['leads'] > 0 else None
        avg_spend_per_adset  = round(spend / b['adset_count'], 2) if b['adset_count'] > 0 else None
        current_daily_budget = round(b['daily_budget_cents'] / 100, 2) if b['daily_budget_cents'] > 0 else None

        if b['missing_rt'] == b['adset_count']:
            join_status = "missing_redtrack"
        elif b['missing_rt'] > 0:
            join_status = "partial_redtrack"
        else:
            join_status = "matched_rt_approximate" if day_filter != "all" else "matched"

        verdict    = _assign_verdict(spend, revenue, join_status, day_filter)
        confidence, confidence_reason = _assign_confidence(spend, b['leads'])
        suggested_action, suggested_action_label = _assign_suggested_action(verdict, confidence, roi)

        # Top / worst ad set by ROI (only among adsets with spend > 0 and rt match)
        scored = [a for a in b['adsets'] if a['roi'] is not None and a['spend'] > 0]
        top_adset    = None
        worst_adset  = None
        if scored:
            top   = max(scored, key=lambda a: a['roi'])
            worst = min(scored, key=lambda a: a['roi'])
            top_adset = {
                'name':    top['name'],
                'spend':   round(top['spend'],   2),
                'revenue': round(top['revenue'], 2),
                'roi':     round(top['roi'],     4),
            }
            if worst['name'] != top['name']:
                worst_adset = {
                    'name':    worst['name'],
                    'spend':   round(worst['spend'],   2),
                    'revenue': round(worst['revenue'], 2),
                    'roi':     round(worst['roi'],     4),
                }

        rows.append({
            'niche':                  niche,
            'spend':                  spend,
            'revenue':                revenue,
            'profit':                 profit,
            'roi':                    roi,
            'leads':                  b['leads'],
            'cpl':                    cpl,
            'redtrack_conversions':   b['redtrack_conversions'],
            'adset_count':            b['adset_count'],
            'verdict':                verdict,
            'is_directional':         day_filter != "all",
            'join_status':            join_status,
            'confidence':             confidence,
            'confidence_reason':      confidence_reason,
            'suggested_action':       suggested_action,
            'suggested_action_label': suggested_action_label,
            'current_daily_budget':   current_daily_budget,
            'active_adset_count':     b['adset_count'],
            'avg_spend_per_adset':    avg_spend_per_adset,
            'top_adset':              top_adset,
            'worst_adset':            worst_adset,
        })

    return sorted(rows, key=lambda r: r['spend'], reverse=True)


def _generate_summary(rows: list, preset_label: str, date_from: str, date_to: str,
                      day_filter: str, tracking_warning: dict, action_queue: dict) -> str:
    if not _client:
        return "AI summary unavailable — ANTHROPIC_API_KEY not configured."

    rt_approximate = day_filter != "all"

    table_rows = []
    for r in rows:
        roi_str = f"{r['roi']*100:+.0f}%" if r['roi'] is not None else "—"
        cpl_str = f"${r['cpl']:.2f}" if r['cpl'] else "—"
        table_rows.append(
            f"{r['niche']} | ${r['spend']:.0f} | ${r['revenue']:.0f} | "
            f"{'+'if r['profit']>=0 else ''}${r['profit']:.0f} | {roi_str} | {cpl_str} | "
            f"{r['verdict']} | {r['confidence']} | {r['suggested_action_label']}"
        )
    table = (
        "Niche | Spend | Revenue | Profit | ROI | CPL | Verdict | Confidence | Suggested Action\n"
        + "\n".join(table_rows)
    )

    def _queue_section(label: str, items: list) -> str:
        if not items:
            return f"{label}:\n- None"
        return f"{label}:\n" + "\n".join(f"- {item}" for item in items)

    queue_block = "\n\n".join([
        "DETERMINISTIC ACTION QUEUE (authoritative — do not contradict)",
        _queue_section("AUTHORIZED SCALE ACTIONS", action_queue.get("scale", [])),
        _queue_section("AUTHORIZED CUT/PAUSE ACTIONS", action_queue.get("cut_or_pause", [])),
        _queue_section("AUTHORIZED WATCH ITEMS", action_queue.get("watch", [])),
        _queue_section("AUTHORIZED TRACKING CHECKS", action_queue.get("tracking_check", [])),
    ])

    notes = []
    if rt_approximate:
        notes.append(
            f"RedTrack revenue for this view ({preset_label}) covers the full date range, "
            f"not filtered by {day_filter} only — ROI is approximate."
        )
    if tracking_warning.get("has_warning"):
        notes.append(tracking_warning["message"])

    prompt = (
        f"You are an expert Meta Ads analyst. Period: {preset_label} ({date_from} to {date_to}"
        + (f", {day_filter} days only" if day_filter != "all" else "")
        + ").\n\n"
        + table
        + "\n\nVerdicts: scale=ROI≥25% & spend≥$50 | run=ROI≥0% | watch=0%>ROI>-25% | pause=ROI≤-25% | "
        + "insufficient_data=spend<$50 | tracking_check=no RT revenue match\n\n"
        + queue_block
        + "\n\n"
        + ("\n".join(notes) + "\n\n" if notes else "")
        + "Write a 3–5 sentence plain-English executive summary. Lead with the biggest finding. "
        + "Name specific niches with dollar amounts. "
        + "You must not contradict the DETERMINISTIC ACTION QUEUE above. "
        + "Only recommend scale actions for niches listed under AUTHORIZED SCALE ACTIONS. "
        + "Only recommend review/cut/pause actions for niches listed under AUTHORIZED CUT/PAUSE ACTIONS. "
        + "Only name watch items from AUTHORIZED WATCH ITEMS. "
        + "Only name tracking-check niches from AUTHORIZED TRACKING CHECKS. "
        + "If a niche appears in the table but not in an authorized action section, you may mention its metrics but must not recommend an action for it. "
        + "Use exact niche names exactly as shown in the table or authorized queue; do not rewrite punctuation, symbols, emojis, capitalization, or ampersands. "
        + "Do not infer tracking issues from ROI, CPL, spend, or join status unless the niche is listed under AUTHORIZED TRACKING CHECKS. "
        + "Do not recommend a harder action than the action label shown in the authorized queue. "
        + "Use the action label as shown: Pause means buyer should pause; Review pause means buyer should investigate before pausing; Potential cut means flag for budget review; Investigate means check ad set and landing page layers. "
        + "Never say 'pause to save money' or imply an automated action; frame all cut/pause actions as buyer decisions that depend on context. "
        + "For Directional scale, Directional hold, Directional watch, or Investigate, do not invent a percentage; use the word directional or recommend investigating. "
        + "For directional rows, use cautious language and say directional. "
        + "If the tracking warning applies, mention it but only name niches from AUTHORIZED TRACKING CHECKS. "
        + "End with one concrete next action. Direct and specific. No padding. "
        + "Output plain text only — no markdown, no bullet points, no headers, no bold."
    )

    try:
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = "\n".join(b.text for b in response.content if hasattr(b, "text")).strip()
        summary = _sanitize_summary_actions(summary, day_filter)
        return _sanitize_summary_niche_names(summary, rows)
    except Exception as e:
        logger.error("Intelligence summary failed: %s", e)
        return f"Summary unavailable: {e}"


def _sanitize_summary_actions(summary: str, day_filter: str) -> str:
    """Enforce deterministic action language after LLM generation."""
    if day_filter == "all" or not summary:
        return summary

    # Day-filtered views use full-range RedTrack revenue, so UI actions are
    # intentionally directional. Do not let the LLM turn them into hard budget
    # percentages in the final prose.
    cleaned = summary
    action_percent_pattern = re.compile(
        r'\b(increas(?:e|ing)?|rais(?:e|ing)?|boost(?:ing)?|expand(?:ing)?'
        r'|scal(?:e|ing)?|cut(?:ting)?|reduc(?:e|ing)?|decreas(?:e|ing)?|lower(?:ing)?)\b'
        r'([^.\n]{0,120}?)[ \t]+by[ \t]+'
        r'\d+(?:[ \t]*(?:%|percent)|[ \t]*[-–—][ \t]*\d+[ \t]*(?:%|percent))',
        flags=re.IGNORECASE,
    )

    def _directional_replacement(match: re.Match) -> str:
        verb = match.group(1).lower()
        target = match.group(2).strip()
        return f"directionally {verb}" + (f" {target}" if target else "")

    cleaned = action_percent_pattern.sub(_directional_replacement, cleaned)
    return cleaned


def _sanitize_summary_niche_names(summary: str, rows: list) -> str:
    """Rewrite common LLM paraphrases back to exact table niche names."""
    if not summary:
        return summary

    cleaned = summary
    placeholders = {}
    niche_names = sorted(
        {str(r.get("niche") or "").strip() for r in rows if r.get("niche")},
        key=len,
        reverse=True,
    )

    for niche in niche_names:
        placeholder = f"__NICHE_NAME_{len(placeholders)}__"
        placeholders[placeholder] = niche
        cleaned = cleaned.replace(niche, placeholder)
        aliases = set()
        without_leading_symbols = re.sub(r'^[^\w]+', '', niche).strip()
        for candidate in {niche, without_leading_symbols}:
            if not candidate:
                continue
            if '&' in candidate:
                aliases.add(re.sub(r'\s*&\s*', ' and ', candidate).strip())
            if candidate != niche:
                aliases.add(candidate)

        for alias in sorted(aliases, key=len, reverse=True):
            if not alias or alias == niche:
                continue
            cleaned = re.sub(rf'\b{re.escape(alias)}\b', placeholder, cleaned, flags=re.IGNORECASE)

    for placeholder, niche in placeholders.items():
        cleaned = cleaned.replace(placeholder, niche)

    return cleaned


@router.get("/niche-profitability")
def niche_profitability(
    preset: str = Query("last_7d"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    ad_account_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    resolved_from, resolved_to, day_filter, preset_label = _resolve_preset(preset, date_from, date_to)

    try:
        meta_data = _fetch_meta_insights(ad_account_id, resolved_from, resolved_to, day_filter)
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    rt_data = _fetch_redtrack(resolved_from, resolved_to)

    # Budget lookup from local DB — no extra Meta API call
    adset_ids = list(meta_data.keys())
    budget_map: Dict[str, int] = {}
    if adset_ids:
        adset_rows = db.query(FacebookAdSet).filter(
            FacebookAdSet.fb_adset_id.in_(adset_ids)
        ).all()
        budget_map = {
            row.fb_adset_id: row.daily_budget
            for row in adset_rows
            if row.daily_budget
        }

    rows = _aggregate_by_niche(meta_data, rt_data, day_filter, budget_map)
    action_queue     = _build_action_queue(rows)
    tracking_warning = _build_tracking_warning(rows)
    summary = _generate_summary(rows, preset_label, resolved_from, resolved_to, day_filter, tracking_warning, action_queue)

    return {
        "question_set":      "niche_profitability",
        "preset":            preset,
        "date_from":         resolved_from,
        "date_to":           resolved_to,
        "day_filter":        day_filter,
        "preset_label":      preset_label,
        "action_queue":      action_queue,
        "tracking_warning":  tracking_warning,
        "summary":           summary,
        "rows":              rows,
    }
