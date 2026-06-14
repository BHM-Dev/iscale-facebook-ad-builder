"""
Campaign Intelligence — structured niche profitability analysis.

GET /api/v1/intelligence/niche-profitability
  ?preset=weekends_mtd
  ?preset=custom&date_from=2026-06-01&date_to=2026-06-14
  ?ad_account_id=act_521142087204815

Supported presets: today, yesterday, last_7d, this_month, last_30d,
                   weekdays_mtd, weekends_mtd, custom
"""

import logging
import os
import re
from datetime import date, timedelta, datetime
from typing import Optional

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_current_active_user
from app.models import User
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
    if preset == "last_7d":
        return str(today - timedelta(days=6)), str(today), "all", "Last 7 days"
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


def _assign_verdict(spend: float, revenue: float, join_status: str) -> str:
    if join_status == "missing_redtrack":
        return "tracking_check"
    if spend < 50:
        return "insufficient_data"
    if spend <= 0:
        return "insufficient_data"
    roi = (revenue - spend) / spend
    if roi >= 0.25:
        return "scale"
    if roi >= 0:
        return "run"
    if roi > -0.25:
        return "watch"
    return "pause"


def _aggregate_by_niche(meta_data: dict, rt_data: dict, day_filter: str) -> list:
    """Join Meta + RT by adset, aggregate by niche, assign verdicts."""
    niche_map: dict = {}

    for fb_id, m in meta_data.items():
        rt = rt_data.get(fb_id)
        revenue = float(rt['revenue']) if rt else 0.0
        conversions = int(rt['conversions']) if rt else 0
        adset_join = "matched" if rt is not None else "missing_redtrack"

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
            }
        b = niche_map[niche]
        b['spend'] = round(b['spend'] + m['spend'], 2)
        b['revenue'] = round(b['revenue'] + revenue, 2)
        b['leads'] += m['leads']
        b['redtrack_conversions'] += conversions
        b['adset_count'] += 1
        if adset_join == "missing_redtrack":
            b['missing_rt'] += 1

    rows = []
    for niche, b in niche_map.items():
        spend = b['spend']
        if spend < 0.01:
            continue
        revenue = b['revenue']
        profit = round(revenue - spend, 2)
        roi = round(profit / spend, 4) if spend > 0 else None
        cpl = round(spend / b['leads'], 2) if b['leads'] > 0 else None

        if b['missing_rt'] == b['adset_count']:
            join_status = "missing_redtrack"
        elif b['missing_rt'] > 0:
            join_status = "partial_redtrack"
        else:
            join_status = "matched_rt_approximate" if day_filter != "all" else "matched"

        verdict = _assign_verdict(spend, revenue, join_status)
        rows.append({
            'niche': niche,
            'spend': spend,
            'revenue': revenue,
            'profit': profit,
            'roi': roi,
            'leads': b['leads'],
            'cpl': cpl,
            'redtrack_conversions': b['redtrack_conversions'],
            'adset_count': b['adset_count'],
            'verdict': verdict,
            'join_status': join_status,
        })

    return sorted(rows, key=lambda r: r['spend'], reverse=True)


def _generate_summary(rows: list, preset_label: str, date_from: str, date_to: str, day_filter: str) -> str:
    if not _client:
        return "AI summary unavailable — ANTHROPIC_API_KEY not configured."

    has_missing_rt = any(r['join_status'] in ("missing_redtrack", "partial_redtrack") for r in rows)
    rt_approximate = day_filter != "all"

    table_rows = []
    for r in rows:
        roi_str = f"{r['roi']*100:+.0f}%" if r['roi'] is not None else "—"
        cpl_str = f"${r['cpl']:.2f}" if r['cpl'] else "—"
        table_rows.append(
            f"{r['niche']} | ${r['spend']:.0f} | ${r['revenue']:.0f} | "
            f"{'+'if r['profit']>=0 else ''}${r['profit']:.0f} | {roi_str} | {cpl_str} | {r['verdict']}"
        )
    table = "Niche | Spend | Revenue | Profit | ROI | CPL | Verdict\n" + "\n".join(table_rows)

    notes = []
    if has_missing_rt:
        notes.append(
            "Some niches show Meta spend but no matched RedTrack revenue. "
            "Treat those as tracking/revenue checks before pausing on ROI alone."
        )
    if rt_approximate:
        notes.append(
            f"RedTrack revenue for this view ({preset_label}) covers the full date range, "
            f"not filtered by {day_filter} only — ROI is approximate."
        )

    prompt = (
        f"You are an expert Meta Ads analyst. Period: {preset_label} ({date_from} to {date_to}"
        + (f", {day_filter} days only" if day_filter != "all" else "")
        + ").\n\n"
        + table
        + "\n\nVerdicts: scale=ROI≥25% & spend≥$50 | run=ROI≥0% | watch=0%>ROI>-25% | pause=ROI≤-25% | "
        + "insufficient_data=spend<$50 | tracking_check=no RT revenue match\n\n"
        + ("\n".join(notes) + "\n\n" if notes else "")
        + "Write a 3–5 sentence plain-English executive summary. Lead with the biggest finding. "
        + "Name specific niches with dollar amounts. Flag tracking_check niches. "
        + "End with one concrete next action. Direct and specific. No padding."
    )

    try:
        response = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return "\n".join(b.text for b in response.content if hasattr(b, "text")).strip()
    except Exception as e:
        logger.error("Intelligence summary failed: %s", e)
        return f"Summary unavailable: {e}"


@router.get("/niche-profitability")
def niche_profitability(
    preset: str = Query("last_7d"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    ad_account_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_active_user),
):
    resolved_from, resolved_to, day_filter, preset_label = _resolve_preset(preset, date_from, date_to)

    try:
        meta_data = _fetch_meta_insights(ad_account_id, resolved_from, resolved_to, day_filter)
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    rt_data = _fetch_redtrack(resolved_from, resolved_to)

    rows = _aggregate_by_niche(meta_data, rt_data, day_filter)
    summary = _generate_summary(rows, preset_label, resolved_from, resolved_to, day_filter)

    return {
        "question_set": "niche_profitability",
        "preset": preset,
        "date_from": resolved_from,
        "date_to": resolved_to,
        "day_filter": day_filter,
        "preset_label": preset_label,
        "summary": summary,
        "rows": rows,
    }
