"""Rules Engine — CRUD + enforcement endpoint.

Generalized 2026-09 from pause-only to a small MVP action set (pause / notify /
increase_budget / decrease_budget) per AdBuilder-BulkRules-Feature-Brief.md. Endpoint
paths and module name kept as "auto_pause"/"auto-pause" — renaming either is a bigger,
separate change (every frontend call site + the scheduler job name) not worth bundling
into this generalization.

Endpoints
---------
GET    /api/v1/auto-pause/rules                  — list all rules (optionally filter by adset_id)
POST   /api/v1/auto-pause/rules                  — create a rule for ONE ad set
POST   /api/v1/auto-pause/rules/bulk              — create the same rule for MULTIPLE ad sets at once
DELETE /api/v1/auto-pause/rules/{rule_id}        — delete a rule
PATCH  /api/v1/auto-pause/rules/{rule_id}        — enable/disable/edit a rule
GET    /api/v1/auto-pause/rules/{rule_id}/logs   — this rule's audit-log history
GET    /api/v1/auto-pause/insights/{fb_adset_id} — live insights for one ad set
POST   /api/v1/auto-pause/check                  — evaluate all active rules now (also called by scheduler)
"""

import logging
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user
from app.models import AutoPauseRule, AutoPauseRuleLog, FacebookAdSet, normalize_account_id
from app.services.facebook_service import FacebookService
from app.services.slack_service import send_check_summary, send_rule_action_alert
from app.api.v1.facebook import _assert_adset_allowed, _assert_account_allowed, _assert_campaign_allowed, _resolve_scoped_default_account

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_ACTIONS = {
    'pause', 'notify', 'increase_budget', 'decrease_budget',
    'duplicate', 'increase_bid', 'decrease_bid',
}
# Actions that use the shared `budget_adjust_pct` column — reused for bid percent too
# (Phase 2: same shape, same server-side floor/ceiling validation, no reason for two
# separate percent columns per AdBuilder-BulkRules-Feature-Brief.md §8.1/§8.3).
PERCENT_ACTIONS = {'increase_budget', 'decrease_budget', 'increase_bid', 'decrease_bid'}
# Minimum time between Slack notifications for the same still-breached notify rule.
# Without this, a metric that stays breached for days pings the channel every
# 30-minute scheduler cycle indefinitely — real alert-fatigue risk flagged in
# pre-push review, right when a budget-rule alert on the same channel matters most.
NOTIFY_COOLDOWN_HOURS = 4
NOTIFY_COOLDOWN = timedelta(hours=NOTIFY_COOLDOWN_HOURS)
# Repeat-enabled Duplicate rules stay active (unlike every other action, which
# disables itself after firing once) — without a cooldown this would create a
# brand-new real ad set (and, unless "empty" is chosen, a full new batch of ads)
# on Meta every single 30-minute check for as long as the breach persists.
# Caught in pre-push review (code-auditor: comment claimed "same cooldown
# pattern as notify" but no gate actually existed). 24h, not 4h like notify —
# duplicating ad-set structure is a much heavier action than a Slack ping.
DUPLICATE_REPEAT_COOLDOWN_HOURS = 24
DUPLICATE_REPEAT_COOLDOWN = timedelta(hours=DUPLICATE_REPEAT_COOLDOWN_HOURS)

# Dashboard reads this endpoint on every page load. Keep its merged Meta +
# RedTrack result briefly so navigating around the app does not repeatedly hit
# Meta for the exact same account and range. Refresh/Sync explicitly bypass it.
INSIGHTS_BULK_CACHE_TTL_SECONDS = 60
INSIGHTS_BULK_CACHE_MAX_ENTRIES = 32
_insights_bulk_cache: dict[tuple, tuple[float, float, dict]] = {}


def _read_insights_bulk_cache(key: tuple, refresh: bool):
    if refresh:
        return None
    entry = _insights_bulk_cache.get(key)
    if entry and time.monotonic() - entry[0] < INSIGHTS_BULK_CACHE_TTL_SECONDS:
        return deepcopy(entry[2])
    if entry:
        _insights_bulk_cache.pop(key, None)
    return None


def _write_insights_bulk_cache(key: tuple, value: dict, request_started_at: float) -> None:
    existing = _insights_bulk_cache.get(key)
    if existing and existing[1] > request_started_at:
        return
    _insights_bulk_cache[key] = (time.monotonic(), request_started_at, deepcopy(value))
    if len(_insights_bulk_cache) > INSIGHTS_BULK_CACHE_MAX_ENTRIES:
        for stale_key, _ in sorted(_insights_bulk_cache.items(), key=lambda item: item[1][0])[:len(_insights_bulk_cache) - INSIGHTS_BULK_CACHE_MAX_ENTRIES]:
            _insights_bulk_cache.pop(stale_key, None)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    adset_id: str                          # internal DB id
    scope: str = 'adset'                   # 'adset' | 'ad'
    fb_ad_id: Optional[str] = None        # raw Meta ad id when scope == 'ad'
    ad_name: Optional[str] = None
    metric: str = 'cpl'                    # 'cpl' | 'cpa' | 'ctr'
    operator: str = 'greater_than'         # 'greater_than' | 'less_than'
    threshold: int                         # e.g. 50 for $50 CPL
    min_spend: int = 20                    # minimum $ spent before rule fires
    action: str = 'pause'                  # 'pause' | 'notify' | 'increase_budget' | 'decrease_budget' | 'duplicate' | 'increase_bid' | 'decrease_bid'
    budget_adjust_pct: Optional[int] = None  # required for budget/bid actions, e.g. 20 = 20%
    # Duplicate-only fields — defaults match Birch's own Duplicate action, verified
    # live rather than guessed (AdBuilder-BulkRules-Feature-Brief.md §8.2).
    duplicate_all_ads: bool = True
    duplicate_name_suffix: str = '- Copy'
    duplicate_append_number: bool = False
    duplicate_pause_original: bool = False
    duplicate_repeat: bool = False
    ad_account_id: Optional[str] = None   # passed through to Meta API

class BulkRuleCreate(BaseModel):
    """Same rule fields, applied to N ad sets at once — one AutoPauseRule row is
    created per adset_id. Keeps the existing one-row-per-adset schema (no new
    filter/query model to invent) while giving the frontend a Birch-style
    "applies to N ad sets" bulk-create flow."""
    adset_ids: List[str]
    scope: str = 'adset'
    fb_ad_id: Optional[str] = None
    ad_name: Optional[str] = None
    metric: str = 'cpl'
    operator: str = 'greater_than'
    threshold: int
    min_spend: int = 20
    action: str = 'pause'
    budget_adjust_pct: Optional[int] = None
    duplicate_all_ads: bool = True
    duplicate_name_suffix: str = '- Copy'
    duplicate_append_number: bool = False
    duplicate_pause_original: bool = False
    duplicate_repeat: bool = False

class RulePatch(BaseModel):
    is_active: Optional[bool] = None
    metric: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[int] = None
    min_spend: Optional[int] = None
    action: Optional[str] = None
    budget_adjust_pct: Optional[int] = None
    duplicate_all_ads: Optional[bool] = None
    duplicate_name_suffix: Optional[str] = None
    duplicate_append_number: Optional[bool] = None
    duplicate_pause_original: Optional[bool] = None
    duplicate_repeat: Optional[bool] = None
    scope: Optional[str] = None
    fb_ad_id: Optional[str] = None
    ad_name: Optional[str] = None


# Server-side ceiling on budget_adjust_pct — the frontend's max="100" is a UI-only
# constraint. Anyone hitting these endpoints directly could otherwise set an
# unbounded multiplier (e.g. 5000%) on an unattended rule that re-evaluates every
# 30 minutes against a live ad account. Caught in pre-push review.
MAX_BUDGET_ADJUST_PCT = 100


def _validate_action(action: str, budget_adjust_pct: Optional[int], scope: str = 'adset') -> None:
    if scope not in {'adset', 'ad'}:
        raise HTTPException(400, "scope must be 'adset' or 'ad'")
    if action not in VALID_ACTIONS:
        raise HTTPException(400, f"action must be one of {sorted(VALID_ACTIONS)}")
    if scope == 'ad' and action not in {'pause', 'notify'}:
        raise HTTPException(400, "ad-scoped rules only support pause or notify actions")
    if action in PERCENT_ACTIONS:
        if not budget_adjust_pct or budget_adjust_pct <= 0:
            raise HTTPException(400, "budget_adjust_pct must be a positive integer (e.g. 20 for 20%) for budget/bid actions")
        if budget_adjust_pct > MAX_BUDGET_ADJUST_PCT:
            raise HTTPException(400, f"budget_adjust_pct must be at most {MAX_BUDGET_ADJUST_PCT}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _evaluate_rule(metric_value: float, operator: str, threshold: float) -> bool:
    """Return True if the rule threshold is breached."""
    if operator == 'greater_than':
        return metric_value > threshold
    if operator == 'less_than':
        return metric_value < threshold
    return False


def _get_metric_value(insights: dict, metric: str) -> Optional[float]:
    if metric == 'cpl':
        return insights.get('cpl')
    if metric == 'cpa':
        return insights.get('cpl')      # alias
    if metric == 'ctr':
        return insights.get('ctr')
    if metric == 'roas':
        return insights.get('roas')
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/rules")
def list_rules(
    adset_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(AutoPauseRule)
    if adset_id:
        q = q.filter(AutoPauseRule.adset_id == adset_id)
    # Scoped users only see rules on ad sets within their assigned accounts —
    # otherwise the list leaks other accounts' adset names / thresholds.
    allowed = current_user.allowed_account_ids()
    if allowed is not None:
        q = q.join(FacebookAdSet, AutoPauseRule.adset_id == FacebookAdSet.id).filter(
            FacebookAdSet.fb_account_id.in_(list(allowed))
        )
    rules = q.order_by(AutoPauseRule.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "adset_id": r.adset_id,
            "adset_name": r.adset.name if r.adset else None,
            "fb_adset_id": r.adset.fb_adset_id if r.adset else None,
            "scope": r.scope or 'adset',
            "fb_ad_id": r.fb_ad_id,
            "ad_name": r.ad_name,
            "metric": r.metric,
            "operator": r.operator,
            "threshold": r.threshold,
            "min_spend": r.min_spend,
            "action": r.action,
            "budget_adjust_pct": r.budget_adjust_pct,
            "duplicate_all_ads": r.duplicate_all_ads,
            "duplicate_name_suffix": r.duplicate_name_suffix,
            "duplicate_append_number": r.duplicate_append_number,
            "duplicate_pause_original": r.duplicate_pause_original,
            "duplicate_repeat": r.duplicate_repeat,
            "is_active": r.is_active,
            "created_at": r.created_at,
            "last_checked_at": r.last_checked_at,
            "triggered_at": r.triggered_at,
            "trigger_reason": r.trigger_reason,
        }
        for r in rules
    ]


def _validate_metric_operator(metric: str, operator: str) -> None:
    valid_metrics = {'cpl', 'cpa', 'ctr', 'roas'}
    valid_operators = {'greater_than', 'less_than'}
    if metric not in valid_metrics:
        raise HTTPException(400, f"metric must be one of {valid_metrics}")
    if operator not in valid_operators:
        raise HTTPException(400, f"operator must be one of {valid_operators}")


@router.post("/rules", status_code=201)
def create_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _validate_metric_operator(body.metric, body.operator)
    _validate_action(body.action, body.budget_adjust_pct, body.scope)
    if body.scope == 'ad' and not body.fb_ad_id:
        raise HTTPException(400, "fb_ad_id is required for ad-scoped rules")

    # Verify adset exists
    adset = db.query(FacebookAdSet).filter(FacebookAdSet.id == body.adset_id).first()
    if not adset:
        raise HTTPException(404, "Ad set not found")
    if current_user.allowed_account_ids() is not None:
        _assert_account_allowed(current_user, adset.fb_account_id)

    rule = AutoPauseRule(
        adset_id=body.adset_id,
        scope=body.scope,
        fb_ad_id=body.fb_ad_id if body.scope == 'ad' else None,
        ad_name=body.ad_name if body.scope == 'ad' else None,
        metric=body.metric,
        operator=body.operator,
        threshold=body.threshold,
        min_spend=body.min_spend,
        action=body.action,
        budget_adjust_pct=body.budget_adjust_pct if body.action in PERCENT_ACTIONS else None,
        duplicate_all_ads=body.duplicate_all_ads if body.action == 'duplicate' else None,
        duplicate_name_suffix=body.duplicate_name_suffix if body.action == 'duplicate' else None,
        duplicate_append_number=body.duplicate_append_number if body.action == 'duplicate' else None,
        duplicate_pause_original=body.duplicate_pause_original if body.action == 'duplicate' else None,
        duplicate_repeat=body.duplicate_repeat if body.action == 'duplicate' else None,
        is_active=True,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "message": "Rule created"}


@router.post("/rules/bulk", status_code=201)
def create_rules_bulk(
    body: BulkRuleCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create the same rule for every ad set in adset_ids. All-or-nothing: any
    unknown/disallowed ad set id fails the whole batch before any row is written,
    rather than silently creating rules for a partial list."""
    _validate_metric_operator(body.metric, body.operator)
    _validate_action(body.action, body.budget_adjust_pct, body.scope)

    if not body.adset_ids:
        raise HTTPException(400, "adset_ids must contain at least one ad set")
    if body.scope == 'ad':
        raise HTTPException(400, "bulk creation is only supported for ad-set-scoped rules")

    adsets = db.query(FacebookAdSet).filter(FacebookAdSet.id.in_(body.adset_ids)).all()
    found_ids = {a.id for a in adsets}
    missing = set(body.adset_ids) - found_ids
    if missing:
        raise HTTPException(404, f"Ad set(s) not found: {sorted(missing)}")
    if current_user.allowed_account_ids() is not None:
        for adset in adsets:
            _assert_account_allowed(current_user, adset.fb_account_id)

    created_ids = []
    for adset_id in body.adset_ids:
        rule = AutoPauseRule(
            adset_id=adset_id,
            scope='adset',
            metric=body.metric,
            operator=body.operator,
            threshold=body.threshold,
            min_spend=body.min_spend,
            action=body.action,
            budget_adjust_pct=body.budget_adjust_pct if body.action in PERCENT_ACTIONS else None,
            duplicate_all_ads=body.duplicate_all_ads if body.action == 'duplicate' else None,
            duplicate_name_suffix=body.duplicate_name_suffix if body.action == 'duplicate' else None,
            duplicate_append_number=body.duplicate_append_number if body.action == 'duplicate' else None,
            duplicate_pause_original=body.duplicate_pause_original if body.action == 'duplicate' else None,
            duplicate_repeat=body.duplicate_repeat if body.action == 'duplicate' else None,
            is_active=True,
        )
        db.add(rule)
        db.flush()  # populate rule.id before commit, without a separate round trip per row
        created_ids.append(rule.id)
    db.commit()
    return {"created": len(created_ids), "rule_ids": created_ids, "message": f"{len(created_ids)} rule(s) created"}


@router.get("/rules/{rule_id}/logs")
def get_rule_logs(
    rule_id: str,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rule = db.query(AutoPauseRule).filter(AutoPauseRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule not found")
    if current_user.allowed_account_ids() is not None:
        _assert_account_allowed(current_user, rule.adset.fb_account_id if rule.adset else None)
    logs = (
        db.query(AutoPauseRuleLog)
        .filter(AutoPauseRuleLog.rule_id == rule_id)
        .order_by(AutoPauseRuleLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": l.id,
            "scope": rule.scope or 'adset',
            "fb_ad_id": rule.fb_ad_id,
            "ad_name": rule.ad_name,
            "action": l.action,
            "metric": l.metric,
            "metric_value": float(l.metric_value) if l.metric_value is not None else None,
            "threshold": l.threshold,
            "spend": float(l.spend) if l.spend is not None else None,
            "result": l.result,
            "detail": l.detail,
            "created_at": l.created_at,
        }
        for l in logs
    ]


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    body: RulePatch,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rule = db.query(AutoPauseRule).filter(AutoPauseRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule not found")
    if current_user.allowed_account_ids() is not None:
        _assert_account_allowed(current_user, rule.adset.fb_account_id if rule.adset else None)
    if body.is_active is not None:
        rule.is_active = body.is_active
    # metric/operator were accepted by the frontend's edit form and silently
    # dropped here — RulePatch never declared these two fields, so Pydantic's
    # default extra="ignore" discarded them with no error, and the edit still
    # returned a "Rule updated" success toast. A genuinely silent data-loss bug
    # on the very feature meant to replace delete-and-recreate. Caught in
    # pre-push review; validated the same way create_rule validates them.
    if body.metric is not None or body.operator is not None:
        new_metric = body.metric if body.metric is not None else rule.metric
        new_operator = body.operator if body.operator is not None else rule.operator
        _validate_metric_operator(new_metric, new_operator)
        rule.metric = new_metric
        rule.operator = new_operator
    if body.threshold is not None:
        rule.threshold = body.threshold
    if body.min_spend is not None:
        rule.min_spend = body.min_spend
    # action/budget_adjust_pct are validated together — if either is being changed,
    # re-validate against the resulting combination, not just the new field alone
    # (e.g. patching budget_adjust_pct to null on a rule whose action is still
    # increase_budget must be rejected, not silently accepted).
    duplicate_fields_touched = any(f is not None for f in (
        body.duplicate_all_ads, body.duplicate_name_suffix,
        body.duplicate_append_number, body.duplicate_pause_original, body.duplicate_repeat,
    ))
    # Gate on scope OR fb_ad_id/ad_name alone, not just scope — a PATCH that only
    # retargets an existing ad-scoped rule to a different ad (fb_ad_id changed,
    # scope unchanged) previously matched neither this branch nor the
    # action/budget/duplicate branch below, so the API returned 200 while
    # rule.fb_ad_id silently kept its old value — the next _run_check would
    # evaluate/pause the WRONG ad while the operator believed they'd
    # retargeted it (pre-push review, HIGH — real spend-risk bug, not a
    # hypothetical, since it doesn't need scope to also change to trigger).
    scope_or_target_touched = body.scope is not None or body.fb_ad_id is not None or body.ad_name is not None
    if scope_or_target_touched and not (body.action is not None or body.budget_adjust_pct is not None or duplicate_fields_touched):
        new_scope = body.scope if body.scope is not None else (rule.scope or 'adset')
        _validate_action(rule.action, rule.budget_adjust_pct, new_scope)
        if new_scope == 'ad' and not (body.fb_ad_id or rule.fb_ad_id):
            raise HTTPException(400, "fb_ad_id is required for ad-scoped rules")
        rule.scope = new_scope
        if body.fb_ad_id is not None:
            rule.fb_ad_id = body.fb_ad_id
        if body.ad_name is not None:
            rule.ad_name = body.ad_name
    if body.action is not None or body.budget_adjust_pct is not None or duplicate_fields_touched:
        new_action = body.action if body.action is not None else rule.action
        new_pct = body.budget_adjust_pct if body.budget_adjust_pct is not None else rule.budget_adjust_pct
        new_scope = body.scope if body.scope is not None else (rule.scope or 'adset')
        _validate_action(new_action, new_pct, new_scope)
        if new_scope == 'ad' and not (body.fb_ad_id or rule.fb_ad_id):
            raise HTTPException(400, "fb_ad_id is required for ad-scoped rules")
        rule.action = new_action
        rule.scope = new_scope
        if body.fb_ad_id is not None:
            rule.fb_ad_id = body.fb_ad_id
        if body.ad_name is not None:
            rule.ad_name = body.ad_name
        rule.budget_adjust_pct = new_pct if new_action in PERCENT_ACTIONS else None
        if new_action == 'duplicate':
            rule.duplicate_all_ads = body.duplicate_all_ads if body.duplicate_all_ads is not None else (rule.duplicate_all_ads if rule.duplicate_all_ads is not None else True)
            rule.duplicate_name_suffix = body.duplicate_name_suffix if body.duplicate_name_suffix is not None else (rule.duplicate_name_suffix or '- Copy')
            rule.duplicate_append_number = body.duplicate_append_number if body.duplicate_append_number is not None else (rule.duplicate_append_number or False)
            rule.duplicate_pause_original = body.duplicate_pause_original if body.duplicate_pause_original is not None else (rule.duplicate_pause_original or False)
            rule.duplicate_repeat = body.duplicate_repeat if body.duplicate_repeat is not None else (rule.duplicate_repeat or False)
        else:
            rule.duplicate_all_ads = None
            rule.duplicate_name_suffix = None
            rule.duplicate_append_number = None
            rule.duplicate_pause_original = None
            rule.duplicate_repeat = None
    db.commit()
    return {"message": "Rule updated"}


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rule = db.query(AutoPauseRule).filter(AutoPauseRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule not found")
    if current_user.allowed_account_ids() is not None:
        _assert_account_allowed(current_user, rule.adset.fb_account_id if rule.adset else None)
    db.delete(rule)
    db.commit()


@router.get("/insights/{fb_adset_id}")
def get_insights(
    fb_adset_id: str,
    date_preset: str = Query("last_7d"),
    ad_account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Fetch live Meta Insights + cached RedTrack data for one ad set."""
    svc = FacebookService()
    svc.initialize()  # ensure svc.api is set so the resolver's Meta fallback works
    _assert_adset_allowed(current_user, fb_adset_id, db, svc)
    try:
        meta = svc.get_adset_insights(fb_adset_id, date_preset=date_preset)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    # Attach cached RedTrack data if available
    from app.models import RedTrackCache
    from datetime import date
    from app.services.redtrack_service import RedTrackService
    date_from_str, date_to_str = RedTrackService.preset_to_dates(date_preset)
    rt_row = (
        db.query(RedTrackCache)
        .filter(
            RedTrackCache.fb_adset_id == fb_adset_id,
            RedTrackCache.date_from == date.fromisoformat(date_from_str),
            RedTrackCache.date_to == date.fromisoformat(date_to_str),
        )
        .first()
    )
    rt = None
    if rt_row:
        rt = {
            "conversions":   rt_row.conversions,
            "revenue":       float(rt_row.revenue)  if rt_row.revenue  is not None else None,
            "cost":          float(rt_row.cost)      if rt_row.cost     is not None else None,
            "profit":        float(rt_row.profit)    if rt_row.profit   is not None else None,
            "roas":          float(rt_row.roas)      if rt_row.roas     is not None else None,
            "cpl":           float(rt_row.cpl)       if rt_row.cpl      is not None else None,
            "clicks":        rt_row.clicks,
            "quality_rate":  float(rt_row.quality_rate) if rt_row.quality_rate is not None else None,
            "synced_at":     rt_row.synced_at.isoformat() if rt_row.synced_at else None,
        }

    return {**meta, "redtrack": rt}


@router.get("/insights-bulk")
def get_insights_bulk(
    ad_account_id: Optional[str] = Query(None),
    date_preset: str = Query("last_7d"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Fetch Meta Insights for ALL ad sets in a single API call, merged with
    cached RedTrack data. Returns a dict keyed by fb_adset_id.

    Accepts either date_preset OR explicit date_from/date_to (YYYY-MM-DD).
    Use this instead of calling /insights/{id} per row — dramatically faster.
    """
    ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)
    # Resolve before the Meta pull so an identical account/range can be served
    # from the short-lived cache without making any external request.
    from app.models import RedTrackCache
    from datetime import date
    from app.services.redtrack_service import RedTrackService
    if date_from and date_to:
        date_from_str, date_to_str = date_from, date_to
    else:
        date_from_str, date_to_str = RedTrackService.preset_to_dates(date_preset)

    cache_key = (ad_account_id, date_from_str, date_to_str)
    cached = _read_insights_bulk_cache(cache_key, refresh)
    if cached is not None:
        return cached
    request_started_at = time.monotonic()

    svc = FacebookService()
    try:
        bulk = svc.get_account_insights_bulk(
            ad_account_id=ad_account_id,
            date_preset=date_preset,
            date_from=date_from,
            date_to=date_to,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    # Attach all RedTrack cache rows in one query

    base_rt_query = (
        db.query(RedTrackCache)
        .filter(
            RedTrackCache.date_from == date.fromisoformat(date_from_str),
            RedTrackCache.date_to   == date.fromisoformat(date_to_str),
        )
    )
    cache_has_rows = base_rt_query.first() is not None
    rt_query = base_rt_query

    scoped_rt_adset_ids = None
    norm_account = normalize_account_id(ad_account_id) if ad_account_id else None
    if norm_account:
        local_ids = {
            row[0] for row in (
                db.query(FacebookAdSet.fb_adset_id)
                .filter(
                    FacebookAdSet.fb_account_id == norm_account,
                    FacebookAdSet.fb_adset_id.isnot(None),
                )
                .all()
            )
            if row[0]
        }
        scoped_rt_adset_ids = local_ids | set(bulk.keys())
        rt_query = rt_query.filter(RedTrackCache.fb_adset_id.in_(scoped_rt_adset_ids or ["__none__"]))

    rt_rows = rt_query.all()

    # Cache miss — fetch live from RedTrack and persist for future loads.
    # Wrapped in try/except: RT is supplementary — a RedTrack API error must
    # never crash the insights-bulk endpoint and wipe out Meta stats.
    if not cache_has_rows:
        try:
            rt_svc = RedTrackService()
            if rt_svc.is_configured():
                import uuid, logging as _log
                _logger = _log.getLogger(__name__)
                live = rt_svc.get_report_by_adset(date_from_str, date_to_str)
                if live:
                    _logger.info("RT live fetch for %s→%s: %d rows; caching.", date_from_str, date_to_str, len(live))
                    d_from = date.fromisoformat(date_from_str)
                    d_to   = date.fromisoformat(date_to_str)
                    # Wipe any stale rows for this range then insert fresh
                    db.query(RedTrackCache).filter(
                        RedTrackCache.date_from == d_from,
                        RedTrackCache.date_to   == d_to,
                    ).delete()
                    for fb_adset_id, metrics in live.items():
                        db.add(RedTrackCache(
                            id=str(uuid.uuid4()),
                            fb_adset_id=fb_adset_id,
                            date_from=d_from,
                            date_to=d_to,
                            **metrics,
                        ))
                    db.commit()
                    # Re-query so rt_rows is populated for the merge below
                    rt_query = (
                        db.query(RedTrackCache)
                        .filter(
                            RedTrackCache.date_from == d_from,
                            RedTrackCache.date_to   == d_to,
                        )
                    )
                    if scoped_rt_adset_ids is not None:
                        rt_query = rt_query.filter(RedTrackCache.fb_adset_id.in_(scoped_rt_adset_ids or ["__none__"]))
                    rt_rows = rt_query.all()
        except Exception as _rt_exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "RT live fetch failed for %s→%s (non-fatal): %s",
                date_from_str, date_to_str, _rt_exc
            )
            # rt_rows stays empty — Meta data still returned, RT column shows blank

    rt_by_adset = {}
    for rt in rt_rows:
        rt_by_adset[rt.fb_adset_id] = {
            "conversions":  rt.conversions,
            "revenue":      float(rt.revenue)      if rt.revenue      is not None else None,
            "cost":         float(rt.cost)          if rt.cost         is not None else None,
            "profit":       float(rt.profit)        if rt.profit       is not None else None,
            "roas":         float(rt.roas)          if rt.roas         is not None else None,
            "cpl":          float(rt.cpl)           if rt.cpl          is not None else None,
            "clicks":       rt.clicks,
            "quality_rate": float(rt.quality_rate)  if rt.quality_rate is not None else None,
            "synced_at":    rt.synced_at.isoformat() if rt.synced_at   else None,
        }

    # Merge redtrack into each bulk row; also include adsets with no Meta spend
    result = {}
    for fb_adset_id, meta in bulk.items():
        result[fb_adset_id] = {**meta, "redtrack": rt_by_adset.get(fb_adset_id)}

    # Include RT-only adsets (edge case: RT has data, Meta row missing due to 0 spend)
    for fb_adset_id, rt in rt_by_adset.items():
        if fb_adset_id not in result:
            result[fb_adset_id] = {
                "spend": 0, "leads": 0, "cpl": None,
                "impressions": 0, "reach": 0, "frequency": 0,
                "clicks": 0, "ctr": 0, "revenue": None, "roas": None,
                "date_preset": date_preset,
                "redtrack": rt,
            }

    _write_insights_bulk_cache(cache_key, result, request_started_at)
    return result


@router.get('/state-performance')
def get_state_performance(
    campaign_id: str = Query(..., min_length=1),
    ad_account_id: Optional[str] = Query(None),
    date_preset: str = Query('last_7d'),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Read-only Meta state breakdown for one campaign and date window.

    Revenue is intentionally absent: the app's attribution sources are not
    state-granular, so this endpoint must not suggest state-level ROAS/profit.
    """
    ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)
    _assert_account_allowed(current_user, ad_account_id)
    _assert_campaign_allowed(current_user, campaign_id, db)
    if bool(date_from) != bool(date_to):
        raise HTTPException(400, 'Provide both date_from and date_to for a custom range.')
    try:
        states = FacebookService().get_campaign_state_insights(
            campaign_id=campaign_id,
            ad_account_id=ad_account_id,
            date_preset=date_preset,
            date_from=date_from,
            date_to=date_to,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc

    total_spend = sum(row['spend'] for row in states)
    total_leads = sum(row['leads'] for row in states)
    blended_cpl = round(total_spend / total_leads, 2) if total_leads else None
    # A flag is evidence, never an automatic state exclusion. Require meaningful
    # spend and a 50% CPL gap so one low-volume lead cannot look like a verdict.
    for row in states:
        row['spend_share'] = round(row['spend'] / total_spend, 4) if total_spend else 0
        row['is_dragging'] = bool(
            blended_cpl is not None
            and row['spend'] >= 50
            and row['leads'] >= 2
            and row['cpl'] is not None
            and row['cpl'] >= blended_cpl * 1.5
        )
    return {
        'campaign_id': campaign_id,
        'date_preset': date_preset,
        'date_from': date_from,
        'date_to': date_to,
        'source': 'Meta Insights delivery breakdown',
        'revenue_available': False,
        'blended_cpl': blended_cpl,
        'total_spend': round(total_spend, 2),
        'total_leads': total_leads,
        'states': states,
    }


@router.get("/ads-bulk")
def get_ads_bulk(
    ad_account_id: Optional[str] = Query(None),
    date_preset: str = Query("last_7d"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    include_all: bool = Query(False),
    current_user=Depends(get_current_user),
):
    """Fetch Meta Insights for ALL ads in a single API call.

    Accepts either date_preset OR explicit date_from/date_to (YYYY-MM-DD).
    Returns a dict keyed by fb_adset_id → list of ads sorted by spend desc:
      { fb_adset_id: [ { ad_id, ad_name, spend, leads, cpl, impressions, clicks, ctr, roas } ] }
    """
    ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)
    svc = FacebookService()
    try:
        result = svc.get_account_ads_insights_bulk(
            ad_account_id=ad_account_id,
            date_preset=date_preset,
            date_from=date_from,
            date_to=date_to,
        )
        if include_all:
            # Insights omits ads with no delivery in the requested period. Add
            # the ACTIVE/PAUSED inventory so a paused or zero-spend ad can still
            # be selected as a rule target; its metrics remain zero/null until it
            # has delivery. This is one account-level metadata call, not one call
            # per ad or ad set.
            for ad in svc.get_account_ads_with_creative(ad_account_id=ad_account_id, include_empty=True):
                adset_id = ad.get('fb_adset_id')
                ad_id = ad.get('fb_ad_id')
                if not adset_id or not ad_id:
                    continue
                rows = result.setdefault(adset_id, [])
                if any(row.get('ad_id') == ad_id for row in rows):
                    continue
                rows.append({
                    'ad_id': ad_id,
                    'ad_name': ad.get('ad_name') or ad_id,
                    'spend': 0,
                    'leads': 0,
                    'cpl': None,
                    'impressions': 0,
                    'clicks': 0,
                    'ctr': 0,
                    'roas': None,
                })
            for rows in result.values():
                rows.sort(key=lambda row: row.get('spend', 0), reverse=True)
        return result
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/insights-raw/{fb_adset_id}")
def get_insights_raw(
    fb_adset_id: str,
    date_preset: str = Query("last_7d"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the unprocessed Meta Insights API response for debugging.
    Shows every action type, action_value, and field exactly as Meta returns it.
    """
    from facebook_business.adobjects.adset import AdSet
    from facebook_business.exceptions import FacebookRequestError

    svc = FacebookService()
    svc.initialize()
    _assert_adset_allowed(current_user, fb_adset_id, db, svc)

    adset = AdSet(fbid=fb_adset_id)
    fields = [
        'spend', 'impressions', 'reach', 'frequency',
        'clicks', 'ctr',
        'actions', 'action_values',
        'cost_per_action_type',
        'purchase_roas',
    ]
    try:
        results = adset.get_insights(fields=fields, params={'date_preset': date_preset})
    except FacebookRequestError as e:
        body = e.body() if hasattr(e, 'body') and callable(e.body) else {}
        raise HTTPException(400, str(body))

    if not results:
        return {"message": "No data returned for this ad set / date range", "fb_adset_id": fb_adset_id}

    row = dict(results[0])
    return {
        "fb_adset_id": fb_adset_id,
        "date_preset": date_preset,
        "raw": row,
        # Pull out the key arrays for easy reading
        "actions": row.get("actions", []),
        "action_values": row.get("action_values", []),
        "cost_per_action_type": row.get("cost_per_action_type", []),
        "purchase_roas": row.get("purchase_roas", []),
    }


@router.post("/check")
def check_and_enforce(
    ad_account_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Evaluate all active rules. Pause ad sets that breach their threshold.
    Returns a summary of actions taken.

    The manual HTTP trigger is superuser-only: _run_check evaluates rules
    system-wide (across all accounts), so a scoped user must not be able to
    pause ad sets outside their accounts. The APScheduler path calls _run_check
    directly and is unaffected.
    """
    if not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Only admins can run the enforcement check manually.")
    return _run_check(db, ad_account_id=ad_account_id)


def _run_check(db: Session, ad_account_id: Optional[str] = None) -> dict:
    """Core enforcement logic — called by endpoint and by APScheduler.

    Uses a bulk Meta API call per account instead of one call per rule to
    avoid N×latency when many rules are active.
    """
    rules_query = db.query(AutoPauseRule).filter(AutoPauseRule.is_active == True)
    if ad_account_id:
        rules_query = rules_query.join(
            FacebookAdSet, AutoPauseRule.adset_id == FacebookAdSet.id
        ).filter(FacebookAdSet.fb_account_id == normalize_account_id(ad_account_id))
    rules = rules_query.all()

    paused = []
    notified = []
    budget_adjusted = []
    bid_adjusted = []
    duplicated = []
    skipped = []
    errors = []
    now = datetime.now(timezone.utc)

    svc = FacebookService()

    # Auto-pause rules can span multiple Meta ad accounts, but a single bulk
    # insights call only ever covers ONE account (Meta's Insights API is
    # account-scoped). The scheduler's production path (main.py's
    # scheduled_check) calls _run_check(db) with no ad_account_id at all —
    # previously that meant every rule outside the service's single
    # configured default account was silently skipped as "not in bulk
    # results" and never actually evaluated, every 30 minutes, forever
    # (audit finding 2026-08-21). Fetch bulk insights once per DISTINCT
    # account represented among the active rules instead of once total.
    if ad_account_id:
        target_accounts = [ad_account_id]
    else:
        target_accounts = sorted({
            rule.adset.fb_account_id
            for rule in rules
            if rule.adset and rule.adset.fb_account_id
        })
        if any(rule.adset and not rule.adset.fb_account_id for rule in rules):
            # A rule whose adset has no recorded account can't be resolved to
            # a specific one — fall back to the service's configured default
            # account rather than silently dropping it.
            target_accounts.append(None)
        if not target_accounts:
            target_accounts = [None]

    bulk_insights = {}
    bulk_ads_insights = {}
    failed_accounts = set()
    failed_ads_accounts = set()
    for account in target_accounts:
        try:
            bulk_insights.update(svc.get_account_insights_bulk(ad_account_id=account))
        except Exception as e:
            logger.error("Bulk insights fetch failed for account %s: %s", account or "(default)", e)
            failed_accounts.add(account)
    # `rules` is already filtered to `ad_account_id`'s own rules when that param
    # is given (see rules_query above), so checking it directly here — rather
    # than unconditionally using [ad_account_id] — is enough to tell whether
    # this account actually has any ad-scoped rules at all. The prior version
    # fired a full extra get_account_ads_insights_bulk call on every
    # per-account check regardless, which is exactly the kind of avoidable API
    # volume that caused the 09-13 Marketing API Access Tier rejection
    # (project_adbuilder_meta_app_review_rejection) — pre-push review, MEDIUM.
    has_ad_scoped_rule = any((rule.scope or 'adset') == 'ad' for rule in rules)
    ad_rule_accounts = (
        sorted({
            rule.adset.fb_account_id
            for rule in rules
            if (rule.scope or 'adset') == 'ad' and rule.adset and rule.adset.fb_account_id
        }) if not ad_account_id
        else ([ad_account_id] if has_ad_scoped_rule else [])
    )
    if has_ad_scoped_rule and any((rule.scope or 'adset') == 'ad' and rule.adset and not rule.adset.fb_account_id for rule in rules):
        ad_rule_accounts.append(None)
    if ad_rule_accounts:
        for account in ad_rule_accounts:
            try:
                bulk_ads_insights.update(svc.get_account_ads_insights_bulk(ad_account_id=account))
            except Exception as e:
                logger.error("Bulk ad insights fetch failed for account %s: %s", account or "(default)", e)
                failed_ads_accounts.add(account)

    for rule in rules:
        adset = rule.adset
        if not adset or not adset.fb_adset_id:
            skipped.append({"rule_id": rule.id, "reason": "no fb_adset_id"})
            continue

        rule_scope = rule.scope or 'adset'

        if rule_scope == 'ad' and rule.action not in {'pause', 'notify'}:
            msg = f"Action {rule.action!r} is not supported for ad-scoped rules"
            rule.is_active = False
            rule.trigger_reason = f"Disabled — {msg}"
            errors.append({"rule_id": rule.id, "adset": adset.name, "ad": rule.ad_name or rule.fb_ad_id, "error": msg})
            db.commit()
            continue

        # Skip if already paused locally. Pausing the parent makes an ad-level
        # rule non-actionable too, and avoids an unnecessary Meta call.
        if adset.status == 'PAUSED':
            rule.last_checked_at = now
            skipped.append({"rule_id": rule.id, "adset": adset.name, "reason": "already paused"})
            continue

        rule_account = adset.fb_account_id or None
        try:
            if rule_scope == 'ad':
                ad_matches = bulk_ads_insights.get(adset.fb_adset_id, [])
                insights = next((item for item in ad_matches if item.get('ad_id') == rule.fb_ad_id), None)
                if insights is None:
                    reason = "ad insights unavailable" if rule_account in failed_ads_accounts else "ad not in bulk results"
                    skipped.append({"rule_id": rule.id, "adset": adset.name, "ad": rule.ad_name or rule.fb_ad_id, "reason": reason})
                    continue
            else:
                insights = bulk_insights.get(adset.fb_adset_id)
            if insights is None:
                if rule_account in failed_accounts:
                    # That account's bulk fetch failed outright — fall back to
                    # a live per-adset call rather than skipping the rule.
                    insights = svc.get_adset_insights(adset.fb_adset_id)
                else:
                    skipped.append({"rule_id": rule.id, "adset": adset.name, "reason": "not in bulk results"})
                    continue
        except Exception as e:
            logger.error("Insights fetch failed for %s: %s", adset.fb_adset_id, e)
            errors.append({"rule_id": rule.id, "adset": adset.name, "error": str(e)})
            continue

        rule.last_checked_at = now
        spend = insights.get('spend', 0)

        # Don't fire until minimum spend threshold is met
        if spend < rule.min_spend:
            skipped.append({
                "rule_id": rule.id,
                "adset": adset.name,
                "reason": f"spend ${spend} < min ${rule.min_spend}"
            })
            db.commit()
            continue

        metric_value = _get_metric_value(insights, rule.metric)
        if metric_value is None:
            skipped.append({
                "rule_id": rule.id,
                "adset": adset.name,
                "reason": f"no {rule.metric} data yet"
            })
            db.commit()
            continue

        breached = _evaluate_rule(metric_value, rule.operator, rule.threshold)

        if breached:
            op_label = '>' if rule.operator == 'greater_than' else '<'
            reason = (
                f"{rule.metric.upper()} ${metric_value:.2f} "
                f"{op_label} threshold ${rule.threshold} "
                f"(spend ${spend:.2f})"
            )

            def _log(result: str, detail: Optional[str] = None):
                # Append-only audit trail across ALL action types — distinct from
                # rule.triggered_at/trigger_reason below, which only remember the
                # most recent fire per rule and get overwritten on the next one.
                db.add(AutoPauseRuleLog(
                    rule_id=rule.id,
                    adset_id=adset.id,
                    fb_adset_id=adset.fb_adset_id,
                    action=rule.action,
                    metric=rule.metric,
                    metric_value=metric_value,
                    threshold=rule.threshold,
                    spend=spend,
                    result=result,
                    detail=detail,
                ))

            if rule.action == 'pause':
                try:
                    if rule_scope == 'ad':
                        svc.update_ad_status(rule.fb_ad_id, 'PAUSED')
                        detail = f"Ad paused ({rule.ad_name or rule.fb_ad_id})"
                    else:
                        svc.update_adset_status(adset.fb_adset_id, 'PAUSED')
                        adset.status = 'PAUSED'
                        detail = 'Ad set paused'
                    rule.triggered_at = now
                    rule.trigger_reason = reason
                    rule.is_active = False   # disable rule after firing (prevent re-fire)
                    _log('success', detail)
                    db.commit()
                    paused.append({"adset": adset.name, "ad": rule.ad_name or rule.fb_ad_id if rule_scope == 'ad' else None, "fb_adset_id": adset.fb_adset_id, "fb_ad_id": rule.fb_ad_id if rule_scope == 'ad' else None, "scope": rule_scope, "reason": reason})
                    logger.info("AUTO-PAUSED %s %s — %s", 'ad' if rule_scope == 'ad' else 'adset', rule.fb_ad_id if rule_scope == 'ad' else adset.fb_adset_id, reason)
                    # detail (computed above) distinguishes "Ad paused (name)" from
                    # "Ad set paused" — omitting it here meant every ad-scoped pause
                    # alert read as a generic ad-set pause with no way to tell Joel
                    # actually paused one ad, not the whole set (pre-push review, HIGH).
                    send_rule_action_alert(action='pause', adset_name=adset.name, fb_adset_id=adset.fb_adset_id, reason=reason, detail=detail)
                except Exception as e:
                    _log('error', str(e))
                    db.commit()
                    errors.append({"adset": adset.name, "error": str(e)})

            elif rule.action == 'notify':
                # Notify-only: no state change on the ad set or the rule itself, so
                # it can notify again on the next check if the breach continues —
                # unlike pause/budget actions, re-firing here is the intended
                # behavior, not something to guard against. But with no cooldown at
                # all, a breach that persists for days pings Slack every 30 minutes
                # forever — real alert-fatigue risk (pre-push review P1) right when
                # a budget-rule alert on the same channel actually matters. Skip
                # re-notifying within NOTIFY_COOLDOWN inside a still-active breach;
                # last_checked_at is still updated above so the rule visibly isn't stalled.
                cooled_down = rule.triggered_at is None or (now - rule.triggered_at) >= NOTIFY_COOLDOWN
                if cooled_down:
                    rule.triggered_at = now
                    rule.trigger_reason = reason
                    # Same reasoning as the pause branch above — without this, an
                    # ad-scoped notify alert is indistinguishable from an ad-set one.
                    notify_detail = f"Ad: {rule.ad_name or rule.fb_ad_id}" if rule_scope == 'ad' else None
                    _log('success', 'Notification sent')
                    db.commit()
                    notified.append({"adset": adset.name, "ad": rule.ad_name or rule.fb_ad_id if rule_scope == 'ad' else None, "fb_adset_id": adset.fb_adset_id, "fb_ad_id": rule.fb_ad_id if rule_scope == 'ad' else None, "scope": rule_scope, "reason": reason})
                    logger.info("NOTIFY rule fired for adset %s — %s", adset.name, reason)
                    send_rule_action_alert(action='notify', adset_name=adset.name, fb_adset_id=adset.fb_adset_id, reason=reason, detail=notify_detail)
                else:
                    skipped.append({
                        "rule_id": rule.id, "adset": adset.name,
                        "reason": f"notify cooldown active ({NOTIFY_COOLDOWN_HOURS}h) — still breached: {reason}"
                    })
                    db.commit()

            elif rule.action in ('increase_budget', 'decrease_budget', 'increase_bid', 'decrease_bid'):
                # Bid actions share this branch with budget actions — same percent-adjust
                # shape, same {level, field, old_cents, new_cents} result, same reporting.
                # Not worth a separate ~30-line copy for what's otherwise identical logic
                # (Phase 2, AdBuilder-BulkRules-Feature-Brief.md §8.1).
                is_bid = rule.action in ('increase_bid', 'decrease_bid')
                percent_change = rule.budget_adjust_pct if rule.action in ('increase_budget', 'increase_bid') else -rule.budget_adjust_pct
                try:
                    if is_bid:
                        adjust_result = svc.adjust_adset_bid_by_percent(adset.fb_adset_id, percent_change)
                    else:
                        adjust_result = svc.adjust_adset_budget_by_percent(adset.fb_adset_id, percent_change)
                    # Explicit about WHERE the money moved — never let a campaign-level
                    # (CBO) adjustment read identically to an ad-set-level one. This
                    # only fires when the ad set is the sole active one in its CBO
                    # campaign (facebook_service.py refuses otherwise), but Joel should
                    # still see that it was the shared campaign budget that changed,
                    # not something scoped just to this ad set.
                    scope_note = (
                        " (CBO campaign budget, shared with this ad set)"
                        if adjust_result['level'] == 'campaign' else ""
                    )
                    detail = (
                        f"{adjust_result['level']} {adjust_result['field']}{scope_note} "
                        f"${adjust_result['old_cents'] / 100:.2f} → ${adjust_result['new_cents'] / 100:.2f}"
                    )
                    rule.triggered_at = now
                    rule.trigger_reason = reason
                    # Disable after firing, same as pause — an unattended rule that
                    # kept compounding a budget/bid change every 30 minutes without a
                    # human look would be a real money-risk, not a convenience.
                    rule.is_active = False
                    _log('success', detail)
                    db.commit()
                    (bid_adjusted if is_bid else budget_adjusted).append(
                        {"adset": adset.name, "fb_adset_id": adset.fb_adset_id, "reason": reason, "detail": detail}
                    )
                    logger.info("%s %s adset %s — %s (%s)", 'BID' if is_bid else 'BUDGET', rule.action, adset.name, reason, detail)
                    send_rule_action_alert(action=rule.action, adset_name=adset.name, fb_adset_id=adset.fb_adset_id, reason=reason, detail=detail)
                except Exception as e:
                    # A bid rule against an ad set with no bid_amount set (most BHM ad
                    # sets run LOWEST_COST_WITHOUT_CAP — see adjust_adset_bid_by_percent's
                    # docstring) is a PERMANENT condition, not a transient API hiccup —
                    # without this check it would retry silently every 30 minutes
                    # forever, showing a green "Active" pill with no visible error state
                    # short of clicking into fire history (joel-perspective P0). Detect
                    # the specific refusal message and disable the rule instead of
                    # leaving it spinning; anything else (a real transient Meta error,
                    # rate limit, etc.) still retries as before.
                    permanent = 'no bid_amount set' in str(e) or 'no budget field' in str(e)
                    if permanent:
                        rule.is_active = False
                        rule.trigger_reason = f"Disabled — not actionable: {e}"
                    _log('error', str(e))
                    db.commit()
                    errors.append({"adset": adset.name, "error": str(e)})

            elif rule.action == 'duplicate':
                # Repeat-enabled duplicate rules stay active (is_active never flips
                # to False below), so — unlike every other action here — this branch
                # must gate on a real cooldown or it creates a brand-new real ad set
                # (and, unless "empty" is chosen, a full new batch of ads) on Meta
                # every single 30-minute check for as long as the breach persists.
                # Mirrors notify's cooldown structure exactly (a prior version of
                # this comment claimed that without actually implementing it —
                # caught in pre-push review). One-shot (non-repeat) rules have no
                # `triggered_at` yet the first time they breach, so this never blocks
                # their one real fire; only a repeat rule that already fired within
                # the window gets skipped.
                cooled_down = not rule.duplicate_repeat or rule.triggered_at is None or \
                    (now - rule.triggered_at) >= DUPLICATE_REPEAT_COOLDOWN
                if not cooled_down:
                    skipped.append({
                        "rule_id": rule.id, "adset": adset.name,
                        "reason": f"duplicate repeat cooldown active ({DUPLICATE_REPEAT_COOLDOWN_HOURS}h) — still breached: {reason}"
                    })
                    db.commit()
                else:
                    try:
                        dup_result = svc.duplicate_adset(
                            adset.fb_adset_id,
                            name_suffix=rule.duplicate_name_suffix or '- Copy',
                            append_number=bool(rule.duplicate_append_number),
                            duplicate_all_ads=rule.duplicate_all_ads if rule.duplicate_all_ads is not None else True,
                            pause_original=bool(rule.duplicate_pause_original),
                        )
                        ad_count = len(dup_result['created_ad_ids'])
                        detail = f"new ad set '{dup_result['new_adset_name']}' ({dup_result['new_fb_adset_id']}), {ad_count} ad(s)"
                        if dup_result['errors']:
                            # The new ad set (and whichever ads DID succeed) are real and
                            # already exist on Meta — say so explicitly rather than let a
                            # partial failure read as if nothing happened.
                            detail += f" — {len(dup_result['errors'])} ad(s) failed to duplicate: {'; '.join(dup_result['errors'])}"
                        if dup_result['original_paused']:
                            detail += " — original ad set paused"
                        rule.triggered_at = now
                        rule.trigger_reason = reason
                        # One-shot by default (disable after firing, matching pause/budget/
                        # bid) unless duplicate_repeat is set.
                        if not rule.duplicate_repeat:
                            rule.is_active = False
                        # requested_ads is what duplicate_adset was actually asked to
                        # create (0 for an intentionally "empty" duplicate) — only the
                        # all-ads case where every single ad failed (a fully-empty
                        # result Joel did NOT ask for, e.g. every ad was a lead-gen
                        # format get_ad_creative_for_duplication can't yet read) is a
                        # real error. Caught in pre-push review: the prior version only
                        # flagged this for the internal log, while the API response
                        # (and the frontend's "success" toast + violet section) still
                        # counted it as a normal duplicate — Joel would see "Duplicated
                        # 1 ad set" for a duplication that produced zero real ads.
                        fully_failed = bool(dup_result['errors']) and not dup_result['created_ad_ids'] and rule.duplicate_all_ads
                        _log('error' if fully_failed else 'success', detail)
                        db.commit()
                        if fully_failed:
                            errors.append({"adset": adset.name, "error": detail})
                        else:
                            duplicated.append({"adset": adset.name, "fb_adset_id": adset.fb_adset_id, "reason": reason, "detail": detail})
                        logger.info("DUPLICATE adset %s — %s (%s)", adset.name, reason, detail)
                        send_rule_action_alert(action='duplicate', adset_name=adset.name, fb_adset_id=adset.fb_adset_id, reason=reason, detail=detail)
                    except Exception as e:
                        _log('error', str(e))
                        db.commit()
                        errors.append({"adset": adset.name, "error": str(e)})

            else:
                # Defense in depth — VALID_ACTIONS/_validate_action should make this
                # unreachable via the API, but a bad direct DB write or a future bug
                # could still leave an out-of-set action value here. Without this
                # branch that rule would breach every cycle forever with nothing
                # logged, no error surfaced, no Slack alert, and never get disabled —
                # a completely invisible dead rule. Caught in pre-push review.
                unknown_msg = f"Unknown rule action {rule.action!r} — not evaluated"
                _log('error', unknown_msg)
                db.commit()
                errors.append({"adset": adset.name, "error": unknown_msg})
                logger.error("Rule %s has unknown action %r", rule.id, rule.action)
        else:
            db.commit()

    send_check_summary(
        rules_evaluated=len(rules),
        paused_count=len(paused),
        errors=errors,
        notified_count=len(notified),
        budget_adjusted_count=len(budget_adjusted),
        bid_adjusted_count=len(bid_adjusted),
        duplicated_count=len(duplicated),
    )

    return {
        "checked_at": now.isoformat(),
        "rules_evaluated": len(rules),
        "paused": paused,
        "notified": notified,
        "budget_adjusted": budget_adjusted,
        "bid_adjusted": bid_adjusted,
        "duplicated": duplicated,
        "skipped": skipped,
        "errors": errors,
    }
