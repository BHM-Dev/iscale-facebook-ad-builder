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
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user, get_db, require_permission
from app.api.v1.facebook import _resolve_scoped_default_account
from app.models import User, FacebookAdSet, normalize_account_id
from app.services.redtrack_service import RedTrackService, today_in_rt_tz
from app.services.everflow_service import CONVERSION_DATE_FIELDS, DEFAULT_TIMEZONE_ID, EVERFLOW_TZ_BY_ID, EverflowService

logger = logging.getLogger(__name__)
router = APIRouter()

_NON_NICHE_RE = re.compile(
    r'^(batch\s*\d+(?:\s*[-|/]?\s*capi)?|v\d+|scale|retarget|broad|phase\s*\d+|test|duplicate|copy|capi)$',
    re.IGNORECASE,
)

BEST_TIMES_TIMEZONE_ID = 90
BEST_TIMES_TZ = EVERFLOW_TZ_BY_ID[BEST_TIMES_TIMEZONE_ID]
REDTRACK_TZ_VALID = True
try:
    REDTRACK_TZ = ZoneInfo(os.getenv('REDTRACK_TIMEZONE', 'America/Los_Angeles'))
except Exception:
    REDTRACK_TZ_VALID = False
    REDTRACK_TZ = ZoneInfo('America/Los_Angeles')
BEST_TIMES_DAYPARTS = tuple(
    {"key": f"block-{hour:02d}", "label": f"{hour % 12 or 12}{'a' if hour < 12 else 'p'}–{(hour + 2) % 12 or 12}{'a' if (hour + 2) % 24 < 12 else 'p'}", "start": hour, "end": hour + 2}
    for hour in range(0, 24, 2)
)
# Canonical Everflow offer names do not always equal RedTrack's operational
# offer labels. Keep aliases explicit: loose substring matching can blend a
# similarly named but commercially distinct offer into timing recommendations.
REDTRACK_OFFER_LABEL_ALIASES = {
    'get business coverage': {
        'commercial insurance get business coverage gbc v2',
        'commercial insurance get business coverage gbc v2 capi',
    },
}
_DATE_LABEL_RE = re.compile(
    r'^(?:(?:\d{1,2}[/.]\d{1,2}(?:[/.]\d{2,4})?)|'
    r'(?:\d{1,4}[-/]\d{1,2}[-/]\d{1,4}))'
    r'(?:\s+\d{1,2}:\d{2}(?:\s*[AP]M)?)?$',
    re.IGNORECASE,
)
_MONTH_DATE_LABEL_RE = re.compile(
    r'^(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
    r'jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|'
    r'nov(?:ember)?|dec(?:ember)?)\.?\s+\d{1,2}(?:,?\s+\d{2,4})?$',
    re.IGNORECASE,
)


def _is_date_label(value: str) -> bool:
    """Recognize a standalone date segment without hiding numeric niches.

    Candidate name segments are already split on ``" - "``. Requiring the
    entire segment to be date-shaped keeps ``24/7 Emergency Plumbing``,
    ``3/4 Ton Trucking``, and ``1.2 Acre Homes`` as real niches.
    """
    normalized = value.strip()
    return bool(_DATE_LABEL_RE.fullmatch(normalized) or _MONTH_DATE_LABEL_RE.fullmatch(normalized))


def _extract_niche(adset_name: str, campaign_name: str = "") -> str:
    """Extract a niche from the ad set, falling back to its campaign name.

    Some CAPI and Painting ad sets are named only ``BATCH 2`` (or a CAPI
    variant), while the campaign still carries the real niche. Keep the
    fallback here so every caller that uses the intelligence extractor gets
    the same attribution behavior.
    """
    def candidate(name: str) -> Optional[str]:
        if not name:
            return None
        parts = [p.strip() for p in name.split(" - ")]
        for part in parts[1:]:
            if part and not _NON_NICHE_RE.match(part) and not _is_date_label(part):
                return part
        if parts and not _is_date_label(parts[0]) and not _NON_NICHE_RE.match(parts[0]):
            return parts[0]
        return None

    return candidate(adset_name) or candidate(campaign_name) or "General"


def _resolve_preset(
    preset: str,
    date_from: Optional[str],
    date_to: Optional[str],
    calendar_timezone: ZoneInfo = REDTRACK_TZ,
):
    """Return (date_from, date_to, day_filter, label)."""
    # Keep preset boundaries in the same advertiser/reporting timezone used by
    # RedTrack timestamp bucketing.  The VPS clock may already be on the next
    # UTC date while the account is still on the prior Pacific date.
    today = datetime.now(tz=calendar_timezone).date()
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


def _clamp_geography_day_filter_window(
    resolved_from: str,
    resolved_to: str,
    day_filter: str,
) -> tuple[str, str, str]:
    """Limit geography's weekday/weekend window without changing shared presets."""
    if day_filter not in {"weekday", "weekend"}:
        return resolved_from, resolved_to, ""

    start = date.fromisoformat(resolved_from)
    end = date.fromisoformat(resolved_to)
    month_start = end.replace(day=1)
    clamped_start = max(start, month_start, end - timedelta(days=13))
    label = "Weekdays (last 14d)" if day_filter == "weekday" else "Weekends (last 14d)"
    return str(clamped_start), resolved_to, label


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
        'adset_id', 'adset_name', 'campaign_name', 'spend', 'impressions', 'actions',
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
                'campaign_name': str(row.get('campaign_name') or ''),
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

    track_rows = [r for r in rows if r['join_status'] in ("partial_redtrack", "missing_redtrack")
                                      or r['verdict'] == "tracking_check"]
    # A niche with unreliable RedTrack data shouldn't also show a confident
    # scale/pause/watch recommendation in a separate lane — that reads as the
    # tool contradicting itself. Tracking check takes priority.
    tracked_niches = {r['niche'] for r in track_rows}
    scale_rows = [r for r in rows if r['suggested_action'] in scale_actions and r['niche'] not in tracked_niches]
    cut_rows   = [r for r in rows if r['suggested_action'] in cut_actions and r['niche'] not in tracked_niches]
    watch_rows = [r for r in rows if r['suggested_action'] in watch_actions and r['niche'] not in tracked_niches]

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

    def _money(value: float) -> str:
        value = value or 0
        return f"-${abs(value):,.0f}" if value < 0 else f"${value:,.0f}"

    def action_item(row: dict) -> dict:
        roi = f"{row['roi'] * 100:+.0f}%" if row.get('roi') is not None else "ROI unavailable"
        spend = _money(row.get('spend', 0))
        profit = _money(row.get('profit', 0))
        confidence = row.get('confidence', 'unknown')
        action = row.get('suggested_action', '')
        if action in scale_actions:
            reason = f"{roi} ROI on {spend} spend · {confidence} confidence"
        elif action in cut_actions or action in watch_actions:
            reason = f"{roi} ROI, {profit} profit · {confidence} confidence"
        else:
            status = (row.get('join_status') or 'tracking check').replace('_redtrack', ' RedTrack').replace('_', ' ')
            reason = f"{spend} spend · {status}"
        if row.get('is_directional') and action in scale_actions | cut_actions | watch_actions:
            reason = f"Directional · {reason}"
        return {
            "niche": row['niche'],
            "action_label": row['suggested_action_label'],
            "reason": reason,
        }

    return {
        "scale":          [action_item(r) for r in scale_rows[:5]],
        "cut_or_pause":   [action_item(r) for r in cut_rows[:5]],
        "watch":          [action_item(r) for r in watch_rows[:5]],
        "tracking_check": [action_item(r) for r in track_rows[:5]],
        # True counts before the display cap above — the summary headline
        # must not report "5 niches queued to scale" as if that were the
        # total when there are actually more past the display limit.
        "counts": {
            "scale":          len(scale_rows),
            "cut_or_pause":   len(cut_rows),
            "watch":          len(watch_rows),
            "tracking_check": len(track_rows),
        },
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

        niche = _extract_niche(m['adset_name'], m.get('campaign_name', ''))
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


def _everflow_offers_for_account(ad_account_id: Optional[str]) -> Optional[set[str]]:
    """Return the configured offer allow-list, or None when revenue is untracked."""
    if not ad_account_id:
        return None
    def canonical(value) -> str:
        value = str(value).strip()
        return f"act_{value[4:]}" if value.lower().startswith("act_") else normalize_account_id(value)

    account_id = canonical(ad_account_id).lower()
    configured_accounts = {
        canonical(value).lower() for value in os.getenv("SWITCHBOARD_EVERFLOW_AD_ACCOUNT_IDS", "").split(",") if value.strip()
    }
    if account_id not in configured_accounts:
        return None
    try:
        mapping = json.loads(os.getenv("SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS", "{}"))
    except json.JSONDecodeError:
        logger.warning("Invalid SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS JSON")
        return set()
    normalized_mapping = {
        canonical(key).lower(): value for key, value in mapping.items()
    } if isinstance(mapping, dict) else {}
    offers = normalized_mapping.get(account_id, [])
    return {str(value).strip() for value in offers if str(value).strip()}


def _parse_hour_value(value) -> Optional[int]:
    if isinstance(value, dict):
        value = value.get("hour") or value.get("value") or value.get("name")
    if isinstance(value, list):
        value = value[0] if value else None
    match = re.search(r"(?:^|\D)(\d{1,2})(?::\d{2})?", str(value or ""))
    if not match:
        return None
    hour = int(match.group(1))
    return hour if 0 <= hour <= 23 else None


_ACCOUNT_TIMEZONE_CACHE: dict[str, tuple[str, float]] = {}
_ACCOUNT_TIMEZONE_CACHE_TTL_SECONDS = 6 * 60 * 60
# Hourly Meta insight breakdowns expand to day × hour × ad set rows. Reusing
# a completed result makes returning to the panel immediate; manual Refresh
# bypasses this short-lived cache.
_BEST_TIMES_RESULT_CACHE: dict[tuple[str, str, str, str], tuple[dict, float]] = {}
_BEST_TIMES_RESULT_CACHE_TTL_SECONDS = 15 * 60
# Geography is a delivery diagnostic and can be revisited several times while
# a buyer compares campaigns. Reuse the same completed account-level Meta read
# briefly instead of turning a table scan into repeated region-breakdown calls.
_GEOGRAPHY_RESULT_CACHE: dict[tuple[str, str, str, str], tuple[dict, float]] = {}
_GEOGRAPHY_RESULT_CACHE_TTL_SECONDS = 5 * 60

_NICHE_PROFITABILITY_RESULT_CACHE: dict[tuple[str, str, str, str], tuple[dict, float]] = {}
_NICHE_PROFITABILITY_RESULT_CACHE_TTL_SECONDS = 5 * 60


def _get_cached_best_times(cache_key: tuple[str, str, str, str]) -> Optional[dict]:
    cached = _BEST_TIMES_RESULT_CACHE.get(cache_key)
    if cached and (time.monotonic() - cached[1]) < _BEST_TIMES_RESULT_CACHE_TTL_SECONDS:
        return cached[0]
    _BEST_TIMES_RESULT_CACHE.pop(cache_key, None)
    return None


def _get_cached_niche_profitability(cache_key: tuple[str, str, str, str]) -> Optional[dict]:
    cached = _NICHE_PROFITABILITY_RESULT_CACHE.get(cache_key)
    if cached and (time.monotonic() - cached[1]) < _NICHE_PROFITABILITY_RESULT_CACHE_TTL_SECONDS:
        return cached[0]
    _NICHE_PROFITABILITY_RESULT_CACHE.pop(cache_key, None)
    return None


def _get_cached_geography(cache_key: tuple[str, str, str, str]) -> Optional[dict]:
    cached = _GEOGRAPHY_RESULT_CACHE.get(cache_key)
    if cached and (time.monotonic() - cached[1]) < _GEOGRAPHY_RESULT_CACHE_TTL_SECONDS:
        return cached[0]
    _GEOGRAPHY_RESULT_CACHE.pop(cache_key, None)
    return None


def _build_geography_watchlist(rows: list[dict]) -> dict:
    """Turn state delivery rows into conservative, campaign-level review items.

    This does not attempt state revenue or causal attribution. A state appears
    only when it clears the same spend/lead/CPL guardrail as the campaign-row
    diagnostic, so the queue remains a short list of investigations.
    """
    campaigns: dict[str, dict] = {}
    for row in rows:
        campaign_id = str(row.get('campaign_id') or '').strip()
        if not campaign_id:
            continue
        campaign = campaigns.setdefault(campaign_id, {
            'campaign_id': campaign_id,
            'campaign_name': str(row.get('campaign_name') or campaign_id),
            'states': [],
            'total_spend': Decimal('0'),
            'total_leads': 0,
        })
        spend = Decimal(str(row.get('spend') or 0))
        leads = int(row.get('leads') or 0)
        campaign['total_spend'] += spend
        campaign['total_leads'] += leads
        campaign['states'].append({
            'state': str(row.get('state') or ''),
            'spend': float(spend),
            'leads': leads,
            'cpl': row.get('cpl'),
            'ctr': row.get('ctr'),
        })

    watchlist = []
    for campaign in campaigns.values():
        total_spend = campaign['total_spend']
        total_leads = campaign['total_leads']
        blended_cpl = (total_spend / total_leads) if total_leads else None
        flagged_states = []
        for state in campaign['states']:
            cpl = Decimal(str(state['cpl'])) if state['cpl'] is not None else None
            is_dragging = bool(
                blended_cpl is not None
                and state['spend'] >= 50
                and state['leads'] >= 2
                and cpl is not None
                and cpl >= blended_cpl * Decimal('1.5')
            )
            # The difference from blended CPL is an investigation priority,
            # not a claim of recoverable profit or a targeting instruction.
            excess_cost = max(Decimal('0'), Decimal(str(state['spend'])) - (Decimal(state['leads']) * blended_cpl)) if is_dragging else Decimal('0')
            state['is_dragging'] = is_dragging
            state['excess_cost'] = float(excess_cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            if is_dragging:
                flagged_states.append(state)
        if not flagged_states:
            continue
        flagged_states.sort(key=lambda item: (-item['excess_cost'], -item['spend'], item['state']))
        campaign['states'].sort(key=lambda item: (-item['spend'], item['state']))
        campaign['blended_cpl'] = float(blended_cpl.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) if blended_cpl is not None else None
        campaign['total_spend'] = float(total_spend.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        campaign['flagged_state_count'] = len(flagged_states)
        campaign['flagged_states'] = flagged_states
        campaign['priority_excess_cost'] = sum(item['excess_cost'] for item in flagged_states)
        watchlist.append(campaign)

    watchlist.sort(key=lambda item: (-item['priority_excess_cost'], -item['total_spend'], item['campaign_name'].casefold()))
    return {
        'campaigns': watchlist,
        'flagged_campaign_count': len(watchlist),
        'flagged_state_count': sum(item['flagged_state_count'] for item in watchlist),
    }


def _platform_geo_value(row: dict) -> str:
    """Return a vendor geo field normalized to the Geography state label."""
    for field in ('region', 'state', 'geo_region'):
        value = str(row.get(field) or '').strip()
        if value:
            return value
    return ''


def _state_key(value: str) -> str:
    """Case/whitespace-insensitive key for joining state labels across vendors.

    Meta, RedTrack, and Everflow each report their own geo string with no
    guarantee of matching format. This only catches casing/whitespace drift
    (e.g. "california" vs "California") — it does NOT reconcile a full-name
    vs. abbreviation mismatch ("CA" vs "California"), which would still
    silently split one real state into two rows. Confirmed live 2026-09-23
    that Meta returns full state names; RedTrack/Everflow's actual format is
    unverified in this codebase — spot-check live data for exactly this
    before fully trusting per-state ROAS.
    """
    return value.strip().casefold()


def _platform_geography_watchlist(
    redtrack_rows: list[dict],
    everflow_rows: list[dict],
    adset_map: dict[str, dict],
    offer_names: Optional[set[str]] = None,
    day_filter: str = 'all',
    meta_spend_rows: Optional[list[dict]] = None,
) -> dict:
    """Build state performance from RedTrack/Everflow conversion geo.

    Available for every Meta ad account, not just ones on the Switchboard
    Everflow allow-list (Steve's call, 2026-09-23) — RedTrack is a real,
    directional revenue source here even where no Everflow offer mapping
    exists, unlike the P&L page's stricter "Everflow-only" billing rule.
    RedTrack provides the most useful attribution grain for the conversion
    timestamp and ``sub2`` Meta ad-set join. Everflow is the billable revenue
    corroborator and uses ``sub3`` for the same join.

    Spend is Meta's own account-wide region breakdown (``meta_spend_rows``,
    from FacebookService.get_account_campaign_state_insights), NOT RedTrack's
    ad-set cost — RedTrack has no state-level spend from Meta to begin with;
    a ``region,sub2`` cost report can only be RedTrack splitting an ad set's
    total cost evenly across whatever states it saw clicks in, which would
    hide real state-level CPM differences rather than surface them (Steve's
    call, 2026-09-23, after confirming live that Meta's own region breakdown
    returns real, varying per-state spend for this account without issue —
    the earlier account-wide+per-day timeout was a scale problem, not a
    restricted-category block). Revenue stays RedTrack/Everflow — Meta
    doesn't see post-click conversions at all, and has repeatedly undercounted
    real revenue in this account's history. ROAS = revenue / Meta spend.

    Meta's region breakdown is campaign-level, not ad-set-level, so spend
    (and ROAS/profit) are only ever computed at the state/campaign grain —
    there is no reliable Meta spend to attribute to an individual ad set here.
    """
    allowed_offers = {name.casefold() for name in offer_names or set() if name}
    campaigns: dict[str, dict] = {}
    redtrack_state_rows = 0
    everflow_state_rows = 0
    meta_spend_rows_count = 0

    def campaign_bucket(campaign_id: str, campaign_name: str) -> dict:
        return campaigns.setdefault(campaign_id, {
            'campaign_id': campaign_id,
            'campaign_name': campaign_name or campaign_id,
            'states': {},
            'total_conversions': 0,
            'total_revenue': Decimal('0'),
        })

    def state_bucket(campaign: dict, state: str) -> dict:
        return campaign['states'].setdefault(_state_key(state), {
            'state': state,
            'conversions': 0,
            'revenue': Decimal('0'),
            'redtrack_conversions': 0,
            'redtrack_revenue': Decimal('0'),
            'everflow_conversions': 0,
            'everflow_revenue': Decimal('0'),
            'spend': Decimal('0'),
            'adset_ids': set(),
            'adsets': {},
        })

    def campaign_for(adset_id: str) -> Optional[dict]:
        identity = adset_map.get(adset_id)
        if not identity:
            return None
        campaign_id = str(identity.get('campaign_id') or '').strip()
        if not campaign_id:
            return None
        return identity

    def campaign_state_for(adset_id: str, state: str) -> Optional[dict]:
        identity = campaign_for(adset_id)
        if not identity or not state:
            return None
        campaign_id = str(identity['campaign_id'])
        campaign = campaign_bucket(campaign_id, identity.get('campaign_name'))
        state_metrics = state_bucket(campaign, state)
        adset = state_metrics['adsets'].setdefault(adset_id, {
            'adset_id': adset_id,
            'adset_name': (adset_map.get(adset_id) or {}).get('adset_name') or adset_id,
            'conversions': 0,
            'revenue': Decimal('0'),
            'redtrack_conversions': 0,
            'redtrack_revenue': Decimal('0'),
            'everflow_conversions': 0,
            'everflow_revenue': Decimal('0'),
        })
        return {'campaign': campaign, 'state': state_metrics, 'adset': adset}

    def add_row(
        source: str,
        row: dict,
        adset_id: str,
        state: str,
        revenue: Decimal,
    ) -> None:
        nonlocal redtrack_state_rows, everflow_state_rows
        identity = campaign_for(adset_id)
        if not identity or not state:
            return
        if source == 'redtrack':
            redtrack_state_rows += 1
        else:
            everflow_state_rows += 1
        target = campaign_state_for(adset_id, state)
        if not target:
            return
        state_metrics = target['state']
        adset_metrics = target['adset']
        state_metrics['conversions'] += 1
        state_metrics['revenue'] += revenue
        state_metrics[f'{source}_conversions'] += 1
        state_metrics[f'{source}_revenue'] += revenue
        state_metrics['adset_ids'].add(adset_id)
        adset_metrics['conversions'] += 1
        adset_metrics['revenue'] += revenue
        adset_metrics[f'{source}_conversions'] += 1
        adset_metrics[f'{source}_revenue'] += revenue

    for row in meta_spend_rows or []:
        campaign_id = str(row.get('campaign_id') or '').strip()
        state = str(row.get('state') or '').strip()
        if not campaign_id or not state:
            continue
        try:
            spend = Decimal(str(row.get('spend') or 0))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not spend.is_finite() or spend < 0:
            continue
        meta_spend_rows_count += 1
        campaign = campaign_bucket(campaign_id, row.get('campaign_name'))
        state_metrics = state_bucket(campaign, state)
        state_metrics['spend'] += spend

    for row in redtrack_rows:
        adset_id = _redtrack_adset_id(row, set(adset_map))
        when = _redtrack_datetime(row, REDTRACK_TZ)
        if not adset_id or not when or not _day_filter_allows(when.weekday(), day_filter):
            continue
        if allowed_offers and not _redtrack_offer_matches(row, allowed_offers):
            # Rows without an offer label remain usable when the ad-set ID is
            # an exact account match; the Meta ad-set boundary is authoritative.
            has_offer = any(row.get(field) not in (None, '') for field in ('offer_name', 'offer', 'offerName'))
            if has_offer:
                continue
        add_row('redtrack', row, adset_id, _platform_geo_value(row), _redtrack_revenue(row))

    for row in everflow_rows:
        if allowed_offers and EverflowService._offer_name(row).casefold() not in allowed_offers:
            continue
        adset_id = str(row.get('sub3') or '').strip()
        when = _conversion_datetime(row, EVERFLOW_TZ_BY_ID[DEFAULT_TIMEZONE_ID])
        if not adset_id or not when or not _day_filter_allows(when.weekday(), day_filter):
            continue
        add_row('everflow', row, adset_id, _platform_geo_value(row), Decimal(str(row.get('revenue') or 0)))

    output_campaigns = []
    for campaign in campaigns.values():
        states = []
        for state in campaign['states'].values():
            # RedTrack and Everflow describe the same conversion stream. Do
            # not sum their revenue: Everflow is the billable source when it
            # has a matching state, while RedTrack is the attribution
            # corroborator and fallback when Everflow is unavailable. Pick
            # BOTH conversions and revenue from the SAME source per state —
            # picking them independently (conversions from whichever source
            # has any, revenue from whichever source is preferred) could pair
            # one vendor's conversion count with the other vendor's revenue,
            # implying a per-conversion revenue that matches neither source.
            if state['everflow_conversions']:
                state['conversions'] = state['everflow_conversions']
                state['revenue'] = state['everflow_revenue']
            else:
                state['conversions'] = state['redtrack_conversions']
                state['revenue'] = state['redtrack_revenue']
            # Per-adset conversions/revenue only — Meta's region breakdown is
            # campaign-level, so there's no real per-adset Meta spend to
            # divide into an adset-level ROAS without a heavier, unproven
            # adset+region Insights query. State-level spend/ROAS above is
            # the trustworthy number; these rows are conversions/revenue
            # detail only.
            adset_metrics_by_id = state.get('adsets', {})
            state['adsets'] = []
            for adset in adset_metrics_by_id.values() if isinstance(adset_metrics_by_id, dict) else []:
                if adset['everflow_conversions']:
                    adset['conversions'] = adset['everflow_conversions']
                    adset['revenue'] = adset['everflow_revenue']
                else:
                    adset['conversions'] = adset['redtrack_conversions']
                    adset['revenue'] = adset['redtrack_revenue']
                adset['revenue'] = float(adset['revenue'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
                state['adsets'].append(adset)
            state['adsets'].sort(key=lambda item: (-item['revenue'], -item['conversions'], item['adset_name'].casefold()))
            state['spend'] = float(state['spend'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            state['roas'] = round(float(state['revenue']) / state['spend'], 2) if state['spend'] > 0 else None
            state['profit'] = round(float(state['revenue']) - state['spend'], 2)
            state['revenue'] = float(state['revenue'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            state['redtrack_revenue'] = float(state['redtrack_revenue'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            state['everflow_revenue'] = float(state['everflow_revenue'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            state['adset_count'] = len(state.pop('adset_ids'))
            state['is_dragging'] = False
            state['excess_cost'] = 0
            states.append(state)
        if not states:
            continue
        states.sort(key=lambda item: (-item['spend'], -item['revenue'], item['state']))
        campaign['states'] = states
        campaign['flagged_states'] = states
        campaign['flagged_state_count'] = len(states)
        campaign['total_conversions'] = sum(item['conversions'] for item in states)
        campaign['total_revenue'] = round(sum(item['revenue'] for item in states), 2)
        campaign['total_spend'] = round(sum(item['spend'] for item in states), 2)
        campaign['total_roas'] = round(campaign['total_revenue'] / campaign['total_spend'], 2) if campaign['total_spend'] > 0 else None
        campaign['total_profit'] = round(campaign['total_revenue'] - campaign['total_spend'], 2)
        campaign['total_leads'] = campaign['total_conversions']
        campaign['blended_cpl'] = None
        campaign['priority_excess_cost'] = campaign['total_revenue']
        output_campaigns.append(campaign)

    output_campaigns.sort(key=lambda item: (-item['total_revenue'], item['campaign_name'].casefold()))
    revenue_sources = []
    if redtrack_state_rows:
        revenue_sources.append('RedTrack')
    if everflow_state_rows:
        revenue_sources.append('Everflow')
    source_label = ' + '.join(revenue_sources) if revenue_sources else 'RedTrack / Everflow'
    if meta_spend_rows_count:
        source_label += ' (revenue) + Meta (spend)'
    return {
        'campaigns': output_campaigns,
        'flagged_campaign_count': len(output_campaigns),
        'flagged_state_count': sum(item['flagged_state_count'] for item in output_campaigns),
        'source_mode': 'platform',
        'source_label': source_label,
        'source_rows': {
            'redtrack': redtrack_state_rows,
            'everflow': everflow_state_rows,
            'meta_spend': meta_spend_rows_count,
        },
    }


def _fetch_platform_geography(
    ad_account_id: Optional[str],
    date_from: str,
    date_to: str,
    day_filter: str,
) -> Optional[dict]:
    """Fetch vendor geo rows plus the Meta ad-set identity map.

    Returns None when the identity read fails, allowing the caller to retain
    Meta's region-breakdown fallback for non-restricted categories.
    """
    from app.services.facebook_service import FacebookService

    meta_service = FacebookService()
    redtrack = RedTrackService()
    everflow = EverflowService()
    if not redtrack.is_configured() and not everflow.is_configured():
        return None
    with ThreadPoolExecutor(max_workers=4) as executor:
        adsets_future = executor.submit(meta_service.get_adsets, ad_account_id)
        redtrack_future = executor.submit(redtrack.get_raw_conversions, date_from, date_to) if redtrack.is_configured() else None
        everflow_future = executor.submit(everflow.get_raw_conversions, date_from, date_to, DEFAULT_TIMEZONE_ID) if everflow.is_configured() else None
        # Spend is Meta's own account-wide region breakdown, not RedTrack's —
        # see _platform_geography_watchlist's docstring for why. This is the
        # same call the pre-revenue Geography diagnostic used, confirmed live
        # (2026-09-23) to return real per-state spend for a real HEC/Special-
        # Ad-Category account without error; a genuinely large account-wide +
        # per-day (weekday/weekend) pull can still time out on scale, which is
        # exactly why that combination is already capped to 14 days elsewhere.
        meta_spend_future = executor.submit(
            meta_service.get_account_campaign_state_insights,
            ad_account_id=ad_account_id,
            date_from=date_from,
            date_to=date_to,
            day_filter=day_filter,
        )
        try:
            adsets = adsets_future.result()
        except Exception as exc:
            logger.warning('Platform geography identity read failed: %s', exc)
            return None

        adset_map = {}
        for adset in adsets or []:
            adset_id = str(adset.get('id') or '').strip()
            campaign = adset.get('campaign') or {}
            campaign_id = str(adset.get('campaign_id') or '').strip()
            if adset_id and campaign_id:
                adset_map[adset_id] = {
                    'campaign_id': campaign_id,
                    'campaign_name': campaign.get('name') or campaign_id,
                    'adset_name': adset.get('name') or adset_id,
                }
        # Degrade per-source rather than discarding both: one vendor's API
        # hiccup shouldn't drop a working second source's real revenue. Track
        # failures explicitly — an empty row list can also mean "no
        # conversions this period," which is a valid result, not a failure.
        redtrack_rows, redtrack_failed = [], False
        if redtrack_future:
            try:
                redtrack_rows = redtrack_future.result()
            except Exception as exc:
                logger.warning('Platform geography RedTrack read failed: %s', exc)
                redtrack_failed = True
        everflow_rows, everflow_failed = [], False
        if everflow_future:
            try:
                everflow_rows = everflow_future.result()
            except Exception as exc:
                logger.warning('Platform geography Everflow read failed: %s', exc)
                everflow_failed = True
        # Meta spend is orthogonal to the RedTrack/Everflow revenue sources —
        # a spend-fetch failure/timeout degrades to "no spend/ROAS this load"
        # rather than forcing the whole feature back to Meta's delivery-only
        # diagnostic (that fallback exists for when there's no conversion
        # data at all, not for a spend-side hiccup).
        try:
            meta_spend_rows = meta_spend_future.result()
        except Exception as exc:
            logger.warning('Platform geography Meta spend read failed: %s', exc)
            meta_spend_rows = []
        configured_sources = bool(redtrack_future) + bool(everflow_future)
        failed_sources = redtrack_failed + everflow_failed
        if configured_sources and failed_sources == configured_sources:
            # Every configured source failed outright — fall back to Meta's
            # delivery-only diagnostic instead of returning an empty result
            # that looks identical to "nothing to review this period."
            return None

    return {
        'redtrack_rows': redtrack_rows,
        'everflow_rows': everflow_rows,
        'meta_spend_rows': meta_spend_rows,
        'adset_map': adset_map,
        'source_configured': redtrack.is_configured() or everflow.is_configured(),
    }


def _get_account_timezone_cached(account, ad_account_id: Optional[str]) -> Optional[str]:
    """Cache the Meta account's timezone_name — it never changes in practice.

    Best Times previously called account.api_get() unconditionally on every
    request. This codebase has a documented history of tripping Meta's
    account-level rate limit ("User request limit reached", code 17) from
    repeated insights/account calls in a short window — an uncached call on
    the hot path adds to that risk for no benefit, since a Meta ad account's
    timezone is effectively fixed after creation.
    """
    import time
    cache_key = str(ad_account_id or '')
    cached = _ACCOUNT_TIMEZONE_CACHE.get(cache_key)
    if cached and (time.monotonic() - cached[1]) < _ACCOUNT_TIMEZONE_CACHE_TTL_SECONDS:
        return cached[0]
    timezone_name = account.api_get(fields=['timezone_name']).get('timezone_name')
    if timezone_name:
        _ACCOUNT_TIMEZONE_CACHE[cache_key] = (timezone_name, time.monotonic())
    return timezone_name


def _fetch_best_times_meta(ad_account_id: Optional[str], date_from: str, date_to: str, day_filter: str = 'all') -> dict:
    """Fetch Meta spend/leads at day × hour × ad set grain."""
    from app.services.facebook_service import FacebookService
    from facebook_business.exceptions import FacebookRequestError

    svc = FacebookService()
    svc.initialize()
    fields = [
    'adset_id', 'adset_name', 'campaign_id', 'campaign_name', 'date_start', 'spend', 'actions',
    ]
    params = {
        'time_range': {'since': date_from, 'until': date_to},
        'time_increment': 1,
        'level': 'adset',
        # Graph otherwise defaults to a tiny page. Hourly data across a
        # month can span thousands of rows, so the default turns one report
        # into hundreds of sequential cursor requests before we see a result.
        'limit': 1000,
        'breakdowns': ['hourly_stats_aggregated_by_advertiser_time_zone'],
    }
    try:
        account = svc._get_account(ad_account_id)
        account_timezone = _get_account_timezone_cached(account, ad_account_id)
        if not account_timezone:
            raise RuntimeError('Best Times could not verify the Meta ad account timezone.')
        try:
            if ZoneInfo(str(account_timezone)) != BEST_TIMES_TZ:
                raise RuntimeError(
                    f'Best Times requires a Pacific Meta ad account; this account reports {account_timezone}.'
                )
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(
                f'Best Times could not validate the Meta ad account timezone ({account_timezone}).'
            ) from exc
        results = account.get_insights(fields, params)
    except FacebookRequestError as exc:
        body = exc.body() if hasattr(exc, 'body') and callable(exc.body) else {}
        error = body.get('error', {}) if isinstance(body, dict) else {}
        raise RuntimeError(f"Facebook API: {error.get('message') or str(exc)}") from exc

    lead_types = {'lead', 'onsite_conversion.lead_grouped', 'offsite_conversion.fb_pixel_lead'}
    rows = []
    adsets = {}
    valid_dows = ({5, 6} if day_filter == 'weekend' else {0, 1, 2, 3, 4}) if day_filter != 'all' else None
    for row in results:
        fb_id = str(row.get('adset_id') or '').strip()
        date_value = str(row.get('date_start') or '')
        if not fb_id or not date_value:
            continue
        if valid_dows is not None:
            try:
                if datetime.strptime(date_value, '%Y-%m-%d').weekday() not in valid_dows:
                    continue
            except ValueError:
                continue
        hour = _parse_hour_value(row.get('hourly_stats_aggregated_by_advertiser_time_zone'))
        if hour is None:
            # Some SDK versions expose the breakdown under a slightly different
            # key shape; accept a direct `hour` value for test doubles and future
            # Graph response variants without changing the source grain.
            hour = _parse_hour_value(row.get('hour'))
        if hour is None:
            continue
        leads = sum(
            int(float(action.get('value', 0) or 0))
            for action in (row.get('actions') or [])
            if action.get('action_type') in lead_types
        )
        adsets[fb_id] = {
            'adset_name': str(row.get('adset_name') or ''),
            'campaign_id': str(row.get('campaign_id') or ''),
            'campaign_name': str(row.get('campaign_name') or ''),
        }
        rows.append({
            'adset_id': fb_id,
            'date': date_value,
            'hour': hour,
            'spend': Decimal(str(row.get('spend') or 0)),
            'leads': leads,
        })
    return {'rows': rows, 'adsets': adsets}


def _conversion_datetime(row: dict, timezone: ZoneInfo) -> Optional[datetime]:
    # Reuse the same field list get_revenue_by_adset/_conversion_month already
    # trust for this API — a narrower list here would silently drop revenue
    # for rows whose only populated timestamp field isn't in it.
    for field in CONVERSION_DATE_FIELDS:
        value = row.get(field)
        if value in (None, ''):
            continue
        if str(value).isdigit():
            try:
                timestamp = int(value)
                if len(str(abs(timestamp))) >= 13:
                    timestamp //= 1000
                return datetime.fromtimestamp(timestamp, tz=timezone)
            except (OverflowError, OSError, ValueError):
                continue
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            continue
        return parsed.astimezone(timezone) if parsed.tzinfo else parsed.replace(tzinfo=timezone)
    return None


def _redtrack_datetime(row: dict, timezone: ZoneInfo) -> Optional[datetime]:
    for field in ('conv_time', 'track_time', 'conversion_time', 'created_at'):
        value = row.get(field)
        if value in (None, ''):
            continue
        if str(value).isdigit():
            try:
                timestamp = int(value)
                if len(str(abs(timestamp))) >= 13:
                    timestamp //= 1000
                return datetime.fromtimestamp(timestamp, tz=timezone)
            except (OverflowError, OSError, ValueError):
                continue
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            continue
        return parsed.astimezone(timezone) if parsed.tzinfo else parsed.replace(tzinfo=REDTRACK_TZ).astimezone(timezone)
    return None


def _day_filter_allows(day_of_week: int, day_filter: str) -> bool:
    if day_filter == 'weekday':
        return day_of_week < 5
    if day_filter == 'weekend':
        return day_of_week >= 5
    return True


def _redtrack_revenue(row: dict) -> Decimal:
    for field in ('payout', 'value', 'revenue', 'total_revenue', 'pub_revenue', 'amount'):
        value = row.get(field)
        if value in (None, ''):
            continue
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if parsed.is_finite() and parsed != 0:
            return parsed
    return Decimal('0')


def _redtrack_offer_matches(row: dict, allowed_offers: set[str]) -> bool:
    """Match RedTrack's descriptive offer label to the configured billing offer.

    Everflow mappings intentionally use the canonical billing name (for
    example ``Get Business Coverage``), while RedTrack exposes the operational
    offer label (``Commercial Insurance - Get Business Coverage - GBC - V2``).
    Exact-only matching discarded valid timing rows for that account. A
    whole-phrase containment match accepts the canonical name embedded in a
    RedTrack label without treating unrelated offers such as HVAC or
    Commercial Auto as a match.
    """
    for field in ('offer_name', 'offer', 'offerName'):
        value = row.get(field)
        if value not in (None, ''):
            if isinstance(value, dict):
                value = value.get('name') or value.get('offer_name') or value.get('label') or value.get('id')
            redtrack_label = re.sub(r'[^a-z0-9]+', ' ', str(value).casefold()).strip()
            allowed_labels = set()
            for offer in allowed_offers:
                canonical = re.sub(r'[^a-z0-9]+', ' ', offer.casefold()).strip()
                if canonical:
                    allowed_labels.add(canonical)
                    allowed_labels.update(REDTRACK_OFFER_LABEL_ALIASES.get(canonical, set()))
            return redtrack_label in allowed_labels
    return True


def _redtrack_adset_id(row: dict, known_adsets: set[str]) -> str:
    """Return the RedTrack field value that actually matches a Meta ad set.

    RedTrack exports can include both publisher-prefixed and plain sub fields.
    Prefer the candidate that is present in the current Meta insight payload;
    choosing the first populated field can discard valid rows when ``p_sub2``
    is populated with a non-Meta value while ``sub2`` contains the ad-set ID.
    """
    candidates = []
    for field in ('p_sub2', 'sub2', 'p_sub2_value', 'sub2_value'):
        value = str(row.get(field) or '').strip()
        if value and value not in candidates:
            candidates.append(value)
    for candidate in candidates:
        if candidate in known_adsets:
            return candidate
    return candidates[0] if candidates else ''


def _build_best_times(
    meta_payload: dict,
    conversions: list[dict],
    offer_names: Optional[set[str]],
    include_metadata: bool = False,
    redtrack_rows: Optional[list[dict]] = None,
    day_filter: str = 'all',
):
    tz = BEST_TIMES_TZ
    tracked = offer_names is not None and bool(offer_names)
    adsets = meta_payload['adsets']
    niche_by_adset = {
        adset_id: _extract_niche(values['adset_name'], values['campaign_name'])
        for adset_id, values in adsets.items()
    }
    aggregate: dict[tuple[str, int, int], dict] = {}
    adset_aggregate: dict[tuple[str, int, int], dict] = {}
    for row in meta_payload['rows']:
        if not _day_filter_allows(datetime.strptime(row['date'], '%Y-%m-%d').weekday(), day_filter):
            continue
        niche = niche_by_adset.get(row['adset_id'], 'General')
        key = (niche, datetime.strptime(row['date'], '%Y-%m-%d').weekday(), row['hour'])
        cell = aggregate.setdefault(key, {'spend': Decimal('0'), 'leads': 0, 'revenue': Decimal('0')})
        cell['spend'] += row['spend']
        cell['leads'] += row['leads']
        adset_key = (row['adset_id'], datetime.strptime(row['date'], '%Y-%m-%d').weekday(), row['hour'])
        adset_cell = adset_aggregate.setdefault(adset_key, {'spend': Decimal('0'), 'leads': 0, 'revenue': Decimal('0')})
        adset_cell['spend'] += row['spend']
        adset_cell['leads'] += row['leads']

    attribution_method = 'everflow_adset_id'
    attribution_warning = None
    redtrack_usable = False
    excluded_conversion_count = 0
    excluded_revenue = Decimal('0')
    if tracked and redtrack_rows:
        # RedTrack supplies the reliable Meta attribution grain and timestamp.
        # Everflow supplies the authoritative billable total; scale the
        # RedTrack distribution to that total so niche/hour dollars reconcile.
        allowed = {name.casefold() for name in offer_names}
        redtrack_total = Decimal('0')
        redtrack_aggregate: dict[tuple[str, int, int], Decimal] = {}
        dropped_count = 0
        dropped_revenue = Decimal('0')
        excluded_redtrack_count = 0
        known_adsets = set(adsets)
        scoped_redtrack_rows = [
            row for row in redtrack_rows
            if _redtrack_adset_id(row, known_adsets) in known_adsets
        ]
        # Raw RedTrack conversions are account-wide. Rows whose ad-set IDs are
        # absent from this Meta account are intentionally out of scope, not
        # missing revenue for the selected account.
        explicit_offer_rows = [
            row for row in scoped_redtrack_rows
            if any(row.get(field) not in (None, '') for field in ('offer_name', 'offer', 'offerName'))
        ]
        matching_redtrack_rows = [row for row in explicit_offer_rows if _redtrack_offer_matches(row, allowed)]
        mismatched_redtrack_rows = [row for row in explicit_offer_rows if not _redtrack_offer_matches(row, allowed)]
        unlabeled_redtrack_rows = [
            row for row in scoped_redtrack_rows
            if not any(row.get(field) not in (None, '') for field in ('offer_name', 'offer', 'offerName'))
        ]
        offer_labels_mismatch = bool(explicit_offer_rows) and not matching_redtrack_rows
        # Raw RedTrack conversions are account-wide. An unlabeled row cannot
        # be proven to belong to this Everflow offer, so never let it shape a
        # daypart recommendation for the selected offer.
        rows_for_attribution = matching_redtrack_rows
        # A different RedTrack offer is deliberately outside this account's
        # Everflow billing scope. It is a normal scope exclusion, not missing
        # attribution for this timing result.
        excluded_redtrack_count = len(mismatched_redtrack_rows)
        for row in rows_for_attribution:
            adset_id = _redtrack_adset_id(row, known_adsets)
            when = _redtrack_datetime(row, tz)
            amount = _redtrack_revenue(row)
            if not adset_id or adset_id not in known_adsets:
                # Meta ad-set IDs are account-scoped, so this excludes other
                # RedTrack accounts without blending their rows into billing.
                continue
            # RedTrack and Everflow can use different offer labels. The Meta
            # ad-set scope above is the account boundary; Everflow remains the
            # authoritative, offer-filtered billing source.
            if not when or amount <= 0:
                dropped_count += 1
                dropped_revenue += amount
                continue
            if not _day_filter_allows(when.weekday(), day_filter):
                continue
            key = (adset_id, when.weekday(), when.hour)
            redtrack_aggregate[key] = redtrack_aggregate.get(key, Decimal('0')) + amount
            redtrack_total += amount

        scoped_adsets = known_adsets
        billing_rows = []
        for row in conversions:
            if EverflowService._offer_name(row).casefold() not in allowed:
                continue
            when = _conversion_datetime(row, tz)
            if day_filter != 'all' and (when is None or not _day_filter_allows(when.weekday(), day_filter)):
                continue
            billing_rows.append(row)
        matched_billing_rows = [row for row in billing_rows if str(row.get('sub3') or '').strip() in scoped_adsets]
        billing_total = sum((Decimal(str(row.get('revenue') or 0)) for row in matched_billing_rows), Decimal('0'))
        unmatched_billing_rows = [row for row in billing_rows if row not in matched_billing_rows]
        for row in unmatched_billing_rows:
            adset_id = str(row.get('sub3') or '').strip()
            revenue = Decimal(str(row.get('revenue') or 0))
            # These rows cannot shape a timing recommendation: they have no
            # selected-period Meta delivery and their ad-set ID is not in the
            # active delivery scope.  Exclude them transparently rather than
            # letting stale/orphaned billing rows suppress useful guidance
            # for the ad sets that *do* have verified Meta + RedTrack scope.
            # The visible recommendation remains explicitly directional.
            excluded_conversion_count += 1
            excluded_revenue += revenue
        if redtrack_total > 0 and billing_total > 0:
            scale = billing_total / redtrack_total
            for (adset_id, day_of_week, hour), amount in redtrack_aggregate.items():
                revenue = amount * scale
                niche = niche_by_adset.get(adset_id, 'General')
                aggregate.setdefault((niche, day_of_week, hour), {'spend': Decimal('0'), 'leads': 0, 'revenue': Decimal('0')})['revenue'] += revenue
                adset_aggregate.setdefault((adset_id, day_of_week, hour), {'spend': Decimal('0'), 'leads': 0, 'revenue': Decimal('0')})['revenue'] += revenue
            attribution_method = 'redtrack_attribution_everflow_billing_allocated'
            attribution_warning = 'Everflow billing revenue is allocated across RedTrack-attributed ad sets and hours; use this as a directional timing signal.'
            if scoped_redtrack_rows and not matching_redtrack_rows and not unlabeled_redtrack_rows:
                attribution_warning += ' RedTrack offer labels did not match the Everflow offer name, so direct Everflow ad-set attribution was used.'
            elif mismatched_redtrack_rows:
                attribution_warning += f' {excluded_redtrack_count} RedTrack rows for other offers were excluded.'
            if unlabeled_redtrack_rows:
                attribution_warning += f' {len(unlabeled_redtrack_rows)} unlabeled RedTrack rows were excluded because their offer scope could not be verified.'
            if dropped_count:
                attribution_warning += f' {dropped_count} conversion rows were excluded from the allocation basis.'
            if excluded_conversion_count:
                attribution_warning += (
                    f' {excluded_conversion_count} Everflow conversion rows totaling '
                    f'${excluded_revenue.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)} were excluded because their ad sets had no Meta delivery in this selected period.'
                )
            redtrack_usable = True
        else:
            attribution_warning = 'RedTrack returned no usable revenue rows; fell back to direct Everflow ad-set attribution.'
            attribution_method = 'everflow_adset_id_redtrack_unavailable'
            # Direct Everflow matching below becomes the completeness test.
            # RedTrack rows that cannot shape the timing distribution are not
            # billable rows and must not be reported as unmatched revenue.
    if tracked and not redtrack_usable:
        allowed = {name.casefold() for name in offer_names}
        attribution_method = 'everflow_adset_id_redtrack_unavailable'
        attribution_warning = attribution_warning or 'RedTrack timing attribution was unavailable; showing direct Everflow ad-set matches without timing confidence.'
        dropped_count = 0
        dropped_revenue = Decimal('0')
        for row in conversions:
            offer = EverflowService._offer_name(row).casefold()
            if offer not in allowed:
                continue
            adset_id = str(row.get('sub3') or '').strip()
            niche = niche_by_adset.get(adset_id)
            when = _conversion_datetime(row, tz)
            if not niche or not when:
                # Adset absent from this window's Meta fetch (paused, zero-spend
                # day, or an hour-parse failure) or an unparseable timestamp.
                # Not counted anywhere else in the response — log it so a gap
                # is visible rather than silently understating a niche's ROI.
                dropped_count += 1
                dropped_revenue += Decimal(str(row.get('revenue') or 0))
                continue
            if not _day_filter_allows(when.weekday(), day_filter):
                continue
            key = (niche, when.weekday(), when.hour)
            aggregate.setdefault(key, {'spend': Decimal('0'), 'leads': 0, 'revenue': Decimal('0')})['revenue'] += Decimal(str(row.get('revenue') or 0))
            adset_aggregate.setdefault((adset_id, when.weekday(), when.hour), {'spend': Decimal('0'), 'leads': 0, 'revenue': Decimal('0')})['revenue'] += Decimal(str(row.get('revenue') or 0))
        if dropped_count:
            attribution_warning = f'{attribution_warning} {dropped_count} Everflow conversion rows totaling ${dropped_revenue.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)} could not be assigned.'
            logger.warning(
                "Best Times: dropped %d Everflow conversion(s) totaling $%s — unmatched adset or unparseable timestamp",
                dropped_count, dropped_revenue.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            )

    result_attribution_incomplete = bool(tracked and (not redtrack_usable or dropped_count > 0))

    def serialize_cells(source: dict, entity_id: str):
        cells = []
        for day_of_week in range(7):
            for hour in range(24):
                value = source.get((entity_id, day_of_week, hour), {'spend': Decimal('0'), 'leads': 0, 'revenue': Decimal('0')})
                spend = value['spend'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                revenue = value['revenue'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if tracked else None
                roi = ((revenue - spend) / spend).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP) if tracked and spend > 0 else None
                confidence, reason = _assign_confidence(float(spend), value['leads'])
                cells.append({
                    'day_of_week': day_of_week,
                    'hour': hour,
                    'spend': float(spend),
                    'leads': value['leads'],
                    'revenue': float(revenue) if revenue is not None else None,
                    'profit': float((revenue - spend).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) if revenue is not None else None,
                    'roi': float(roi) if roi is not None else None,
                    'confidence': confidence if tracked else 'low',
                    'confidence_reason': reason if tracked else 'Revenue source is not tracked for this account',
                })
        return cells

    def build_timing_summary(cells):
        """Return scan-friendly 2-hour blocks and a stable schedule recommendation."""
        blocks = []
        for group_label, day_indexes in (('Mon–Fri', range(5)), ('Sat–Sun', range(5, 7))):
            for part in BEST_TIMES_DAYPARTS:
                day_rows = []
                for day in day_indexes:
                    matching = [cell for cell in cells if cell['day_of_week'] == day and part['start'] <= cell['hour'] < part['end']]
                    spend = sum(cell['spend'] for cell in matching)
                    revenue_known = any(cell['revenue'] is not None for cell in matching)
                    revenue = sum((cell['revenue'] or 0) for cell in matching) if revenue_known else None
                    if spend > 0 and revenue is not None:
                        day_rows.append({'spend': spend, 'revenue': revenue, 'profit': revenue - spend})
                spend = sum(row['spend'] for row in day_rows)
                revenue = sum(row['revenue'] for row in day_rows) if tracked and day_rows else None
                profit = revenue - spend if revenue is not None else None
                evidence_days = len(day_rows)
                positive_days = sum(1 for row in day_rows if row['profit'] > 0)
                consistency_rate = positive_days / evidence_days if evidence_days else None
                minimum_days = 3 if group_label == 'Mon–Fri' else 2
                enough_evidence = (
                    tracked and not result_attribution_incomplete and revenue is not None
                    and spend >= 100 and revenue >= 25 and evidence_days >= minimum_days
                )
                stable_positive = enough_evidence and profit > 0 and consistency_rate >= 0.6
                stable_negative = enough_evidence and profit < 0 and consistency_rate <= 0.4
                status = 'unavailable'
                reason = 'Insufficient attributable evidence'
                if enough_evidence:
                    if stable_positive and profit / spend >= 0.1:
                        status, reason = 'run', f"Positive in {positive_days} of {evidence_days} {group_label.lower()} evidence buckets."
                    elif stable_negative and profit / spend <= -0.1:
                        status, reason = 'avoid', f"Negative in {evidence_days - positive_days} of {evidence_days} {group_label.lower()} evidence buckets."
                    elif profit > 0:
                        status, reason = 'inconsistent', f"Profitable overall, but positive in only {positive_days} of {evidence_days} {group_label.lower()} evidence buckets."
                    else:
                        status, reason = 'hold', 'No repeatable material advantage yet.'
                if not tracked:
                    reason = 'Revenue source is not tracked for this account.'
                confidence = 'low'
                if enough_evidence and consistency_rate is not None:
                    if evidence_days >= minimum_days and consistency_rate >= 0.75 and spend >= 500 and revenue >= 100:
                        confidence = 'high'
                    elif consistency_rate >= 0.6:
                        confidence = 'medium'
                blocks.append({
                    'key': f"{group_label}:{part['key']}",
                    'group': group_label,
                    'label': part['label'],
                    'start': part['start'],
                    'end': part['end'],
                    'spend': round(spend, 2),
                    'revenue': round(revenue, 2) if revenue is not None else None,
                    'profit': round(profit, 2) if profit is not None else None,
                    'roi': round(profit / spend, 4) if profit is not None and spend > 0 else None,
                    'positive_bucket_count': positive_days,
                    'evidence_bucket_count': evidence_days,
                    'consistency_rate': round(consistency_rate, 4) if consistency_rate is not None else None,
                    'confidence': confidence,
                    'status': status,
                    'reason': reason,
                })

        if not tracked or result_attribution_incomplete:
            return {'status': 'unavailable', 'confidence': 'low', 'blocks': blocks, 'run_windows': [], 'avoid_windows': [], 'reason': 'Timing recommendations are unavailable until revenue attribution is complete.'}

        run_blocks = [block for block in blocks if block['status'] == 'run']
        avoid_blocks = [block for block in blocks if block['status'] == 'avoid']

        def make_windows(selected):
            windows = []
            for group in ('Mon–Fri', 'Sat–Sun'):
                group_blocks = sorted((block for block in selected if block['group'] == group), key=lambda block: block['start'])
                for block in group_blocks:
                    if windows and windows[-1]['group'] == group and windows[-1]['end_hour'] == block['start']:
                        windows[-1]['end_hour'] = block['end']
                    else:
                        windows.append({'group': group, 'start_hour': block['start'], 'end_hour': block['end']})
            return windows

        avoid_windows = make_windows(avoid_blocks)
        best = max(run_blocks, key=lambda block: block['profit'], default=None)
        if not best:
            profitable_inconsistent = [block for block in blocks if block['status'] == 'inconsistent']
            reason = profitable_inconsistent[0]['reason'] if profitable_inconsistent else 'No time block has enough repeatable evidence to recommend a schedule.'
            return {'status': 'none', 'confidence': 'low', 'blocks': blocks, 'run_windows': [], 'avoid_windows': avoid_windows, 'reason': reason}

        run_windows = make_windows(run_blocks)
        run_label = ' · '.join(f"{window['group']} · {window['start_hour'] % 12 or 12}{' AM' if window['start_hour'] < 12 else ' PM'}–{window['end_hour'] % 12 or 12}{' AM' if window['end_hour'] % 24 < 12 else ' PM'} PT" for window in run_windows[:2])
        return {
            'status': 'run',
            'confidence': best['confidence'],
            'blocks': blocks,
            'run_windows': run_windows,
            'avoid_windows': avoid_windows,
            'label': run_label,
            'profit': round(sum(block['profit'] for block in run_blocks), 2),
            'roi': round(sum(block['profit'] for block in run_blocks) / sum(block['spend'] for block in run_blocks), 4) if sum(block['spend'] for block in run_blocks) > 0 else None,
            'positive_bucket_count': best['positive_bucket_count'],
            'evidence_bucket_count': best['evidence_bucket_count'],
            'reason': f"{best['reason']} Confidence is {best['confidence']}.",
        }

    niches = sorted({key[0] for key in aggregate})
    output = []
    for niche in niches:
        niche_cells = serialize_cells(aggregate, niche)
        niche_timing = build_timing_summary(niche_cells)
        output.append({
            'niche': niche,
            'revenue_source': 'everflow' if tracked else 'not_tracked',
            'cells': niche_cells,
            'timing_blocks': niche_timing['blocks'],
            'recommendation': niche_timing,
        })

    campaign_aggregate: dict[tuple[str, int, int], dict] = {}
    campaign_adsets: dict[str, list[str]] = {}
    campaign_metadata: dict[str, dict] = {}
    # Do not send 168 empty cells for every archived/zero-delivery ad set.
    # The selector is for reviewing the period being analyzed, so only ad
    # sets with delivery or attributable revenue belong in this response.
    relevant_adsets = {
        adset_id for (adset_id, _day_of_week, _hour), value in adset_aggregate.items()
        if value['spend'] > 0 or value['revenue'] > 0
    }
    for adset_id in relevant_adsets:
        values = adsets[adset_id]
        campaign_id = values.get('campaign_id') or values.get('campaign_name') or 'unknown-campaign'
        campaign_adsets.setdefault(campaign_id, []).append(adset_id)
        campaign_metadata[campaign_id] = {
            'campaign_id': values.get('campaign_id') or None,
            'campaign_name': values.get('campaign_name') or 'Unnamed campaign',
        }
    for (adset_id, day_of_week, hour), value in adset_aggregate.items():
        values = adsets.get(adset_id, {})
        campaign_id = values.get('campaign_id') or values.get('campaign_name') or 'unknown-campaign'
        cell = campaign_aggregate.setdefault((campaign_id, day_of_week, hour), {'spend': Decimal('0'), 'leads': 0, 'revenue': Decimal('0')})
        cell['spend'] += value['spend']
        cell['leads'] += value['leads']
        cell['revenue'] += value['revenue']
    campaigns = []
    for campaign_id, metadata in campaign_metadata.items():
        campaign_cells = serialize_cells(campaign_aggregate, campaign_id)
        campaign_timing = build_timing_summary(campaign_cells)
        adset_summaries = []
        for adset_id in campaign_adsets[campaign_id]:
            adset_cells = serialize_cells(adset_aggregate, adset_id)
            adset_timing = build_timing_summary(adset_cells)
            adset_summaries.append({
                'adset_id': adset_id,
                'adset_name': adsets[adset_id].get('adset_name') or 'Unnamed ad set',
                'revenue_source': 'everflow' if tracked else 'not_tracked',
                'cells': adset_cells,
                'timing_blocks': adset_timing['blocks'],
                'recommendation': adset_timing,
            })
        campaigns.append({
            **metadata,
            'revenue_source': 'everflow' if tracked else 'not_tracked',
            'cells': campaign_cells,
            'timing_blocks': campaign_timing['blocks'],
            'recommendation': campaign_timing,
            'adsets': adset_summaries,
        })
    campaigns.sort(key=lambda item: item['campaign_name'].casefold())
    result = {
        'niches': output,
        'campaigns': campaigns,
        'dropped_conversion_count': dropped_count if tracked else 0,
        'dropped_revenue': float(dropped_revenue.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) if tracked else 0,
        'excluded_conversion_count': excluded_conversion_count if tracked else 0,
        'excluded_revenue': float(excluded_revenue.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) if tracked else 0,
        # Direct Everflow fallback can reconcile billing by ad set, but it
        # cannot identify Meta delivery hours. Do not present that fallback as
        # timing-complete even when every billing row matches.
        'attribution_complete': not tracked or (redtrack_usable and dropped_count == 0),
        'attribution_allocated': attribution_method.endswith('_allocated'),
        'attribution_method': attribution_method,
        'attribution_warning': attribution_warning,
    }
    return result if include_metadata else output


def _build_summary(action_queue: dict) -> str:
    """Build one factual headline from the already-sorted action queue."""
    lane_phrases = []
    for key, phrase in (
        ('scale', 'queued to scale'),
        ('cut_or_pause', 'flagged for cut/pause review'),
        ('watch', 'on watch'),
        ('tracking_check', 'need tracking checks'),
    ):
        count = action_queue.get('counts', {}).get(key, len(action_queue.get(key, [])))
        if count:
            lane_phrases.append(f"{count} niche{'s' if count != 1 else ''} {phrase}")

    if not lane_phrases:
        return "No immediate niche actions are queued for this period."

    first_item = next(
        item for key in ('scale', 'cut_or_pause', 'watch', 'tracking_check')
        for item in action_queue.get(key, [])
    )
    return f"{'; '.join(lane_phrases)}; start with {first_item['niche']} ({first_item['action_label']})."


@router.get("/niche-profitability")
def niche_profitability(
    preset: str = Query("last_7d"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    ad_account_id: Optional[str] = Query(None),
    refresh: bool = Query(False),
    current_user: User = Depends(require_permission("pnl:read")),
    db: Session = Depends(get_db),
):
    ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)
    resolved_from, resolved_to, day_filter, preset_label = _resolve_preset(preset, date_from, date_to)

    # Cached like geography/best-times: the panel now prefetches this in the
    # background on every account/date change (not just when opened), so an
    # uncached live Meta call here risks the same per-account rate limit
    # ("User request limit reached", code 17) already seen on
    # act_521142087204815.
    cache_key = (str(ad_account_id or ''), resolved_from, resolved_to, day_filter)
    cached = None if refresh else _get_cached_niche_profitability(cache_key)
    if cached is not None:
        return cached

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
    summary = _build_summary(action_queue)

    result = {
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
    _NICHE_PROFITABILITY_RESULT_CACHE[cache_key] = (result, time.monotonic())
    return result


@router.get('/geography-watchlist')
def geography_watchlist(
    preset: str = Query('last_7d'),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    ad_account_id: Optional[str] = Query(None),
    refresh: bool = Query(False),
    current_user: User = Depends(require_permission('pnl:read')),
):
    """Return state-delivery investigations grouped by campaign.

    Prefers RedTrack/Everflow conversion-geo (real revenue, see
    _platform_geography_watchlist) when either is configured, falling back to
    Meta's region-breakdown delivery-only diagnostic otherwise. Either way the
    result is intentionally a review queue, never an automatic exclusion
    recommendation.
    """
    from app.services.facebook_service import FacebookService

    ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)
    resolved_from, resolved_to, day_filter, preset_label = _resolve_preset(preset, date_from, date_to)
    if day_filter != "all":
        resolved_from, resolved_to, preset_label = _clamp_geography_day_filter_window(
            resolved_from, resolved_to, day_filter
        )
    # Keep day_filter in the key so weekday and weekend results never share a
    # cached payload. The clamped dates also scope the cache to the effective
    # 14-day geography window.
    cache_key = (str(ad_account_id or ''), resolved_from, resolved_to, day_filter)
    result = None if refresh else _get_cached_geography(cache_key)
    source = 'Meta Insights delivery breakdown'
    revenue_available = False
    if result and result.get('source_mode') == 'platform':
        source = result.get('source_label') or source
        revenue_available = True
    try:
        if result is None:
            platform_geo = _fetch_platform_geography(
                ad_account_id, resolved_from, resolved_to, day_filter
            )
            if platform_geo and platform_geo['source_configured']:
                offer_names = _everflow_offers_for_account(ad_account_id)
                result = _platform_geography_watchlist(
                    platform_geo['redtrack_rows'],
                    platform_geo['everflow_rows'],
                    platform_geo['adset_map'],
                    offer_names=offer_names,
                    day_filter=day_filter,
                    meta_spend_rows=platform_geo.get('meta_spend_rows', []),
                )
                source = result['source_label']
                revenue_available = True
            else:
                rows = FacebookService().get_account_campaign_state_insights(
                    ad_account_id=ad_account_id,
                    date_from=resolved_from,
                    date_to=resolved_to,
                    day_filter=day_filter,
                )
                result = _build_geography_watchlist(rows)
            _GEOGRAPHY_RESULT_CACHE[cache_key] = (result, time.monotonic())
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc

    return {
        'question_set': 'geography_watchlist',
        'preset': preset,
        'preset_label': preset_label,
        'date_from': resolved_from,
        'date_to': resolved_to,
        'day_filter': day_filter,
        'source': source,
        'revenue_available': revenue_available,
        **result,
    }


@router.get("/best-times")
def best_times(
    preset: str = Query("last_30d"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    ad_account_id: Optional[str] = Query(None),
    niche: Optional[str] = Query(None),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("pnl:read")),
):
    """Return exact or directional revenue timing by niche and advertiser-local hour."""
    ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)
    resolved_from, resolved_to, _day_filter, preset_label = _resolve_preset(
        preset, date_from, date_to, calendar_timezone=BEST_TIMES_TZ
    )
    offer_names = _everflow_offers_for_account(ad_account_id)
    cache_key = (str(ad_account_id or ''), resolved_from, resolved_to, _day_filter)
    result = None if refresh else _get_cached_best_times(cache_key)
    try:
        if result is None:
            redtrack_warning = None
            redtrack = RedTrackService() if offer_names else None
            can_fetch_redtrack = bool(redtrack and redtrack.is_configured() and REDTRACK_TZ_VALID and REDTRACK_TZ == BEST_TIMES_TZ)
            if redtrack and not redtrack.is_configured():
                redtrack_warning = 'RedTrack is not configured for this environment; showing direct Everflow ad-set matches instead.'
            elif redtrack and (not REDTRACK_TZ_VALID or REDTRACK_TZ != BEST_TIMES_TZ):
                redtrack_warning = 'RedTrack timezone does not match the required Pacific Best Times timezone; timing recommendations are unavailable until REDTRACK_TIMEZONE is corrected.'

            # The three upstream reads are independent. Parallelizing them
            # changes first-load latency from their combined duration to the
            # slowest individual source without changing the calculation.
            with ThreadPoolExecutor(max_workers=3) as executor:
                meta_future = executor.submit(_fetch_best_times_meta, ad_account_id, resolved_from, resolved_to, _day_filter)
                everflow_future = executor.submit(EverflowService().get_raw_conversions, resolved_from, resolved_to, timezone_id=BEST_TIMES_TIMEZONE_ID) if offer_names else None
                redtrack_future = executor.submit(redtrack.get_raw_conversions, resolved_from, resolved_to) if can_fetch_redtrack else None
                meta_payload = meta_future.result()
                conversions = everflow_future.result() if everflow_future else []
                redtrack_rows = []
                if redtrack_future:
                    try:
                        redtrack_rows = redtrack_future.result()
                        if not redtrack_rows:
                            redtrack_warning = 'RedTrack returned no rows; showing direct Everflow ad-set matches instead.'
                    except Exception as exc:
                        logger.warning("Best Times RedTrack attribution unavailable; using Everflow adset IDs: %s", exc)
                        redtrack_warning = 'RedTrack attribution was unavailable; showing direct Everflow ad-set matches instead.'

            result = _build_best_times(meta_payload, conversions, offer_names, include_metadata=True, redtrack_rows=redtrack_rows, day_filter=_day_filter)
            if redtrack_warning:
                existing_warning = result.get('attribution_warning')
                result['attribution_warning'] = ' '.join(part for part in (redtrack_warning, existing_warning) if part)
                result['attribution_method'] = 'everflow_adset_id_redtrack_unavailable'
            _BEST_TIMES_RESULT_CACHE[cache_key] = (result, time.monotonic())
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        logger.exception("Best Times failed for %s", ad_account_id)
        raise HTTPException(502, f"Best Times data unavailable: {exc}") from exc

    niches = result['niches']
    if niche:
        niches = [row for row in niches if row['niche'].casefold() == niche.casefold()]
    return {
        'question_set': 'best_times',
        'preset': preset,
        'preset_label': preset_label,
        'date_from': resolved_from,
        'date_to': resolved_to,
        'timezone_id': BEST_TIMES_TIMEZONE_ID,
        'timezone': str(EVERFLOW_TZ_BY_ID[BEST_TIMES_TIMEZONE_ID]),
        'dayparts': list(BEST_TIMES_DAYPARTS),
        'niches': niches,
        'campaigns': result['campaigns'],
        'dropped_conversion_count': result['dropped_conversion_count'],
        'dropped_revenue': result['dropped_revenue'],
        'excluded_conversion_count': result['excluded_conversion_count'],
        'excluded_revenue': result['excluded_revenue'],
        'attribution_complete': result['attribution_complete'],
        'attribution_method': result['attribution_method'],
        'attribution_warning': result['attribution_warning'],
        'attribution_allocated': result['attribution_allocated'],
    }
