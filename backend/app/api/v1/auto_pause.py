"""Auto-Pause Rules — CRUD + enforcement endpoint.

Endpoints
---------
GET    /api/v1/auto-pause/rules                  — list all rules (optionally filter by adset_id)
POST   /api/v1/auto-pause/rules                  — create a rule
DELETE /api/v1/auto-pause/rules/{rule_id}        — delete a rule
PATCH  /api/v1/auto-pause/rules/{rule_id}        — enable/disable a rule
GET    /api/v1/auto-pause/insights/{fb_adset_id} — live insights for one ad set
POST   /api/v1/auto-pause/check                  — evaluate all active rules now (also called by scheduler)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user
from app.models import AutoPauseRule, FacebookAdSet
from app.services.facebook_service import FacebookService
from app.services.slack_service import send_auto_pause_alert, send_check_summary

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    adset_id: str                          # internal DB id
    metric: str = 'cpl'                    # 'cpl' | 'cpa' | 'ctr'
    operator: str = 'greater_than'         # 'greater_than' | 'less_than'
    threshold: int                         # e.g. 50 for $50 CPL
    min_spend: int = 20                    # minimum $ spent before rule fires
    ad_account_id: Optional[str] = None   # passed through to Meta API

class RulePatch(BaseModel):
    is_active: Optional[bool] = None
    threshold: Optional[int] = None
    min_spend: Optional[int] = None


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
    rules = q.order_by(AutoPauseRule.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "adset_id": r.adset_id,
            "adset_name": r.adset.name if r.adset else None,
            "fb_adset_id": r.adset.fb_adset_id if r.adset else None,
            "metric": r.metric,
            "operator": r.operator,
            "threshold": r.threshold,
            "min_spend": r.min_spend,
            "is_active": r.is_active,
            "created_at": r.created_at,
            "last_checked_at": r.last_checked_at,
            "triggered_at": r.triggered_at,
            "trigger_reason": r.trigger_reason,
        }
        for r in rules
    ]


@router.post("/rules", status_code=201)
def create_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Validate metric and operator
    valid_metrics = {'cpl', 'cpa', 'ctr', 'roas'}
    valid_operators = {'greater_than', 'less_than'}
    if body.metric not in valid_metrics:
        raise HTTPException(400, f"metric must be one of {valid_metrics}")
    if body.operator not in valid_operators:
        raise HTTPException(400, f"operator must be one of {valid_operators}")

    # Verify adset exists
    adset = db.query(FacebookAdSet).filter(FacebookAdSet.id == body.adset_id).first()
    if not adset:
        raise HTTPException(404, "Ad set not found")

    rule = AutoPauseRule(
        adset_id=body.adset_id,
        metric=body.metric,
        operator=body.operator,
        threshold=body.threshold,
        min_spend=body.min_spend,
        is_active=True,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "message": "Rule created"}


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
    if body.is_active is not None:
        rule.is_active = body.is_active
    if body.threshold is not None:
        rule.threshold = body.threshold
    if body.min_spend is not None:
        rule.min_spend = body.min_spend
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


@router.get("/insights-raw/{fb_adset_id}")
def get_insights_raw(
    fb_adset_id: str,
    date_preset: str = Query("last_7d"),
    current_user=Depends(get_current_user),
):
    """Return the unprocessed Meta Insights API response for debugging.
    Shows every action type, action_value, and field exactly as Meta returns it.
    """
    from facebook_business.adobjects.adset import AdSet
    from facebook_business.exceptions import FacebookRequestError

    svc = FacebookService()
    svc.initialize()

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
    Returns a summary of actions taken."""
    return _run_check(db, ad_account_id=ad_account_id)


def _run_check(db: Session, ad_account_id: Optional[str] = None) -> dict:
    """Core enforcement logic — called by endpoint and by APScheduler."""
    rules = db.query(AutoPauseRule).filter(AutoPauseRule.is_active == True).all()

    paused = []
    skipped = []
    errors = []
    now = datetime.now(timezone.utc)

    svc = FacebookService()

    for rule in rules:
        adset = rule.adset
        if not adset or not adset.fb_adset_id:
            skipped.append({"rule_id": rule.id, "reason": "no fb_adset_id"})
            continue

        # Skip if already paused locally
        if adset.status == 'PAUSED':
            rule.last_checked_at = now
            skipped.append({"rule_id": rule.id, "adset": adset.name, "reason": "already paused"})
            continue

        try:
            insights = svc.get_adset_insights(adset.fb_adset_id)
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
            try:
                svc.update_adset_status(adset.fb_adset_id, 'PAUSED')
                adset.status = 'PAUSED'
                rule.triggered_at = now
                rule.trigger_reason = reason
                rule.is_active = False   # disable rule after firing (prevent re-fire)
                db.commit()
                paused.append({"adset": adset.name, "fb_adset_id": adset.fb_adset_id, "reason": reason})
                logger.info("AUTO-PAUSED adset %s — %s", adset.name, reason)
                send_auto_pause_alert(
                    adset_name=adset.name,
                    fb_adset_id=adset.fb_adset_id,
                    reason=reason,
                    rules_evaluated=len(rules),
                )
            except Exception as e:
                errors.append({"adset": adset.name, "error": str(e)})
        else:
            db.commit()

    send_check_summary(
        rules_evaluated=len(rules),
        paused_count=len(paused),
        errors=errors,
    )

    return {
        "checked_at": now.isoformat(),
        "rules_evaluated": len(rules),
        "paused": paused,
        "skipped": skipped,
        "errors": errors,
    }
