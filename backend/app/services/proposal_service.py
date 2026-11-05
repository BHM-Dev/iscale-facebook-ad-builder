"""Approvals queue: evidence-backed pause / budget-raise proposals that a person approves.

Spec: docs/briefs/AdBuilder-Approvals-Queue-Brief.md. Thresholds come from a replay of RHO's real
30 days (2026-09-30..10-29): CPL-based pausing would have cut ad sets that then made +$11.3k in 3
days, so every trigger here is revenue-based (Switchboard billable revenue minus Meta spend).

Nothing in this module writes to Meta except `approve()`, which only runs on a person's click,
re-checks the ad set live first, and goes through the same budget guards as the budget editor.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import ActionProposal, AutoPauseRuleLog, FacebookAdSet, ProposalEvent, normalize_account_id

logger = logging.getLogger(__name__)

# ---- Triggers (brief §3.4). Change only with Joel/Abel's sign-off. ----
NO_REV_MIN_SPEND_TODAY = 50.0        # spent >= $50 today ...
NO_REV_LOOKBACK_DAYS = 3             # ... and $0 revenue over the last 3 days
LOSS_DAYS = 3
LOSS_MIN_SPEND = 150.0               # 3-day spend >= $150 ...
LOSS_MIN_LOSS = 150.0                # ... and 3-day profit <= -$150
SCALE_DAYS = 7
SCALE_MIN_SPEND = 200.0
SCALE_MIN_ROI = 0.50
SCALE_MIN_PROFITABLE_DAYS = 4
SCALE_RAISE = 0.20

REDECIDE_COOLDOWN = timedelta(days=3)    # don't re-propose an ad set for 3 days after a decision
OPEN_TTL = timedelta(hours=24)
EXECUTING_TIMEOUT = timedelta(minutes=15)
DISMISS_REASONS = ("Revenue is lagging", "Still testing", "Handled it myself", "Wrong call", "Other")
TRIGGER_LABELS = {"no_revenue_spend": "Spending, no revenue", "loss_3d": "3-day loss", "scale_winner": "Scale winner"}
LEAD_TYPES = {"lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"}

# Last evaluation per account, for the panel ("revenue source unavailable" etc.). Process memory only.
LAST_RUN: dict[str, dict] = {}


# ---------------------------------------------------------------- config

def enabled() -> bool:
    return os.getenv("PROPOSALS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def shadow_mode() -> bool:
    return os.getenv("PROPOSALS_SHADOW", "true").strip().lower() not in {"0", "false", "no", "off"}


def shadow_viewers() -> set[str]:
    return {e.strip().lower() for e in os.getenv("PROPOSALS_SHADOW_VIEWERS", "").split(",") if e.strip()}


def can_view(user) -> bool:
    """Shadow week: only the listed viewers see proposals. After go-live, anyone with account access."""
    if not shadow_mode():
        return True
    return (getattr(user, "email", "") or "").lower() in shadow_viewers()


def proposal_accounts() -> list[str]:
    """Accounts the evaluator covers: explicit env list, else every Switchboard-revenue account."""
    from app.api.v1 import pnl
    raw = os.getenv("PROPOSALS_ACCOUNT_IDS", "")
    ids = [normalize_account_id(a) for a in raw.split(",") if a.strip()] or sorted(pnl._everflow_account_ids())
    # Profit triggers need billable revenue; an account without a source never gets proposals.
    return [a for a in ids if pnl._revenue_provider_for_account(a) == "everflow"]


# ---------------------------------------------------------------- data

def _day(d) -> str:
    return d.isoformat() if isinstance(d, date) else str(d)


def fetch_inputs(db: Session, account_id: str, days: int = SCALE_DAYS + 1):
    """Daily per-ad-set spend/leads (Meta), live ACTIVE ad sets (Meta) and billable revenue by
    ad set by day (Switchboard sub3). Raises RevenueUnavailable if revenue can't be read."""
    from app.api.v1 import pnl
    from app.services.facebook_service import FacebookService

    svc = FacebookService()
    svc.initialize()
    account = svc._get_account(account_id)
    until = account_today(account)
    since = until - timedelta(days=days)
    rows = list(account.get_insights(fields=["adset_id", "adset_name", "spend", "actions"], params={
        "time_range": {"since": since.isoformat(), "until": until.isoformat()},
        "level": "adset", "time_increment": 1, "limit": 500,
    }))
    meta: dict[str, dict[str, dict]] = {}
    names: dict[str, str] = {}
    for r in rows:
        aid = str(r.get("adset_id") or "")
        if not aid:
            continue
        names[aid] = str(r.get("adset_name") or "")
        leads = sum(int(float(a.get("value") or 0)) for a in (r.get("actions") or []) if a.get("action_type") in LEAD_TYPES)
        meta.setdefault(aid, {})[str(r.get("date_start"))] = {"spend": float(r.get("spend") or 0), "leads": leads}

    live: dict[str, dict] = {}
    for a in account.get_ad_sets(fields=["id", "name", "effective_status", "daily_budget", "lifetime_budget"],
                                 params={"effective_status": ["ACTIVE"], "limit": 500}):
        a = dict(a)
        live[str(a["id"])] = {
            "name": a.get("name"), "status": a.get("effective_status"),
            "daily_budget_cents": int(a["daily_budget"]) if a.get("daily_budget") else None,
            "lifetime_budget_cents": int(a["lifetime_budget"]) if a.get("lifetime_budget") else None,
        }

    total_spend = sum(v["spend"] for s in meta.values() for v in s.values())
    revenue = revenue_by_adset_day(db, account_id, since, until, total_spend)
    return meta, revenue, live, names, until


class RevenueUnavailable(RuntimeError):
    pass


def revenue_by_adset_day(db: Session, account_id: str, since: date, until: date,
                         total_spend: float = 0.0) -> dict[str, dict[str, float]]:
    """Return Switchboard revenue keyed by Meta ad set and Pacific-bucketed day.

    This is deliberately shared by proposals, Max CPL, and Daily Close so all
    ad-set revenue uses the same offer filtering and macro recovery rules.
    """
    from app.api.v1 import pnl
    from app.services.everflow_service import EverflowService

    try:
        offers = pnl._everflow_offer_names_for_account(account_id)
        if not offers:
            raise RuntimeError("no Switchboard offer mapping")
        ef = EverflowService()
        conv = pnl._recover_macro_adsets(db, ef.get_raw_conversions(since, until))
    except Exception as exc:  # never treat missing revenue as $0
        raise RevenueUnavailable(str(exc)) from exc
    revenue: dict[str, dict[str, float]] = {}
    for c in conv:
        if ef._offer_name(c) not in offers:
            continue
        aid = str(c.get("sub3") or "")
        if aid:
            d = _day(ef._conversion_date(c))
            revenue.setdefault(aid, {})[d] = revenue.get(aid, {}).get(d, 0.0) + float(c.get("revenue") or 0)
    if total_spend >= 500 and not any(revenue.values()):
        raise RevenueUnavailable(f"no revenue rows for ${total_spend:,.0f} of spend; refusing to read that as $0")
    return revenue


def account_today(account) -> date:
    """Today in the ad account's own timezone: Meta buckets insights by it, and the server runs on UTC."""
    from zoneinfo import ZoneInfo
    try:
        tz = dict(account.api_get(fields=["timezone_name"])).get("timezone_name")
        return datetime.now(ZoneInfo(tz)).date() if tz else date.today()
    except Exception:
        logger.warning("Proposal evaluator: couldn't read the account timezone; using server date")
        return date.today()


# ---------------------------------------------------------------- triggers (pure)

def _window(series: dict, today: date, n: int):
    s = l = r = 0.0
    for i in range(n):
        x = series.get(_day(today - timedelta(days=i)), {})
        s += x.get("spend", 0.0); l += x.get("leads", 0); r += x.get("rev", 0.0)
    return s, l, r


def evaluate(meta: dict, revenue: dict, live: dict, today: date, max_daily_cents: int) -> list[dict]:
    """Return proposal candidates. Only live ACTIVE ad sets; pause beats raise on conflict."""
    out = []
    for aid, info in live.items():
        series = {d: {**v, "rev": revenue.get(aid, {}).get(d, 0.0)} for d, v in meta.get(aid, {}).items()}
        for d, rv in revenue.get(aid, {}).items():
            series.setdefault(d, {"spend": 0.0, "leads": 0, "rev": rv})
        today_spend = series.get(_day(today), {}).get("spend", 0.0)
        s3, _, r3 = _window(series, today, LOSS_DAYS)
        _, _, rev_lookback = _window(series, today, NO_REV_LOOKBACK_DAYS)
        s7, l7, r7 = _window(series, today, SCALE_DAYS)
        triggers = []
        if today_spend >= NO_REV_MIN_SPEND_TODAY and rev_lookback == 0:
            # Say what the data is: an ad set new (or restarted) today has one day of history, not three.
            spent_before = any(v.get("spend", 0.0) > 0 for d, v in series.items() if d < _day(today))
            why = (f"Spent ${today_spend:,.0f} today, its first spend in {SCALE_DAYS}+ days, with no revenue yet"
                   if not spent_before else f"Spent ${today_spend:,.0f} today with no revenue in {NO_REV_LOOKBACK_DAYS} days")
            triggers.append(("no_revenue_spend", why))
        if s3 >= LOSS_MIN_SPEND and (r3 - s3) <= -LOSS_MIN_LOSS:
            triggers.append(("loss_3d", f"Lost ${s3 - r3:,.0f} over the last {LOSS_DAYS} days on ${s3:,.0f} spend"))
        action, params = None, None
        if triggers:
            action, params = "pause", {"from_status": "ACTIVE", "to_status": "PAUSED"}
        else:
            budget = info.get("daily_budget_cents")
            profitable = sum(1 for i in range(SCALE_DAYS)
                             if (lambda x: x.get("rev", 0.0) - x.get("spend", 0.0))(series.get(_day(today - timedelta(days=i)), {})) > 0)
            if (budget and s7 >= SCALE_MIN_SPEND and (r7 - s7) / s7 >= SCALE_MIN_ROI
                    and profitable >= SCALE_MIN_PROFITABLE_DAYS):
                to = min(int(round(budget * (1 + SCALE_RAISE))), max_daily_cents)
                if to > budget:
                    roi = (r7 - s7) / s7
                    triggers.append(("scale_winner", f"7-day ROI {roi:.0%} on ${s7:,.0f} spend, profitable {profitable} of {SCALE_DAYS} days"))
                    action, params = "budget_increase", {"from_cents": budget, "to_cents": to}
        if not action:
            continue
        days = [{"day": _day(today - timedelta(days=i)), **{k: round(v, 2) if isinstance(v, float) else v for k, v in
                 {"spend": series.get(_day(today - timedelta(days=i)), {}).get("spend", 0.0),
                  "leads": series.get(_day(today - timedelta(days=i)), {}).get("leads", 0),
                  "revenue": series.get(_day(today - timedelta(days=i)), {}).get("rev", 0.0)}.items()}}
                for i in (2, 1, 0)]
        for d in days:
            d["profit"] = round(d["revenue"] - d["spend"], 2)
        out.append({
            "fb_adset_id": aid, "adset_name": info.get("name"), "trigger_keys": [t for t, _ in triggers],
            "action": action, "action_params": params,
            "evidence": {
                "why": "; ".join(w for _, w in triggers), "days": days,
                "totals_7d": {"spend": round(s7, 2), "leads": int(l7), "revenue": round(r7, 2), "profit": round(r7 - s7, 2)},
                "current": {"status": info.get("status"), "daily_budget_cents": info.get("daily_budget_cents")},
                "as_of": _day(today),
            },
        })
    return out


# ---------------------------------------------------------------- persistence

def log_event(db: Session, event: str, proposal_id: str | None = None, user_email: str | None = None, **props) -> None:
    db.add(ProposalEvent(proposal_id=proposal_id, event=event, user_email=user_email, props=props or None))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def apply_candidates(db: Session, account_id: str, candidates: list[dict], live: dict) -> dict:
    """Create new proposals, expire stale open ones. Returns counts."""
    now = _now()
    by_adset = {c["fb_adset_id"]: c for c in candidates}
    created = expired = 0
    # An approve interrupted mid-call (deploy/restart) would sit in 'executing' forever. Release it as
    # failed; Retry re-checks the ad set live first, so a pause that did land comes back as stale.
    for p in db.query(ActionProposal).filter(ActionProposal.fb_account_id == account_id,
                                             ActionProposal.status == "executing").all():
        if p.decided_at and now - _aware(p.decided_at) > EXECUTING_TIMEOUT:
            p.status, p.execution_result = "failed", {"error": "Interrupted before Meta confirmed. Check Ads Manager; Retry re-checks live first."}
            log_event(db, "proposal_failed", p.id, reason="interrupted")
    open_rows = db.query(ActionProposal).filter(
        ActionProposal.fb_account_id == account_id, ActionProposal.status.in_(["open", "failed"])).all()
    open_ids = set()
    for p in open_rows:
        cand = by_adset.get(p.fb_adset_id)
        reason = None
        if p.status == "failed":
            # A person approved this and Meta didn't confirm: keep it in front of them (with Retry)
            # rather than quietly expiring it; drop it only once it's a day old.
            if now - _aware(p.created_at) > OPEN_TTL:
                reason = "timed out"
        elif p.fb_adset_id not in live:
            reason = "ad set no longer active"
        elif cand is None or cand["action"] != p.action:
            reason = "condition cleared"
        elif now - _aware(p.created_at) > OPEN_TTL:
            reason = "timed out"
        if reason:
            # Guarded on status: a person may have claimed it (open -> executing) since the SELECT.
            n = db.query(ActionProposal).filter(ActionProposal.id == p.id, ActionProposal.status == p.status) \
                .update({ActionProposal.status: "expired", ActionProposal.status_reason: reason}, synchronize_session=False)
            if n == 1:
                log_event(db, "proposal_expired", p.id, reason=reason)
                expired += 1
                continue
        open_ids.add(p.fb_adset_id)
    recent = {r[0] for r in db.query(ActionProposal.fb_adset_id).filter(
        ActionProposal.fb_account_id == account_id,
        ActionProposal.status.in_(["executed", "dismissed", "stale", "executing"]),
        ActionProposal.decided_at >= now - REDECIDE_COOLDOWN).all()}
    for aid, c in by_adset.items():
        if aid in open_ids or aid in recent:
            continue
        p = ActionProposal(fb_account_id=account_id, fb_adset_id=aid, adset_name=c["adset_name"],
                           trigger_key=c["trigger_keys"][0], trigger_keys=c["trigger_keys"], action=c["action"],
                           action_params=c["action_params"], evidence=c["evidence"], status="open")
        db.add(p)
        db.flush()
        log_event(db, "proposal_created", p.id, trigger=p.trigger_key, action=p.action)
        created += 1
    db.commit()
    return {"created": created, "expired": expired, "open": len(open_ids) + created}


def run_evaluation(db: Session) -> dict:
    """Scheduler entry point: evaluate every covered account. Never writes to Meta."""
    from app.api.v1.facebook import MAX_DAILY_BUDGET_CENTS
    results = {}
    for account_id in proposal_accounts():
        started = time.monotonic()
        try:
            meta, revenue, live, _, today = fetch_inputs(db, account_id)
            cands = evaluate(meta, revenue, live, today, MAX_DAILY_BUDGET_CENTS)
            counts = apply_candidates(db, account_id, cands, live)
            LAST_RUN[account_id] = {"at": _now().isoformat(), "revenue_available": True, **counts,
                                    "seconds": round(time.monotonic() - started, 1)}
        except RevenueUnavailable as exc:
            db.rollback()
            # Keep open proposals as they are (no expiry on a blind run) and create nothing.
            LAST_RUN[account_id] = {"at": _now().isoformat(), "revenue_available": False, "error": str(exc)[:200]}
            log_event(db, "evaluation_skipped", None, account=account_id, reason="revenue unavailable")
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Proposal evaluation failed for %s", account_id)
            LAST_RUN[account_id] = {"at": _now().isoformat(), "revenue_available": None, "error": str(exc)[:200]}
        results[account_id] = LAST_RUN[account_id]
    return results


# ---------------------------------------------------------------- decisions

class DecisionError(Exception):
    def __init__(self, status_code: int, detail):
        super().__init__(str(detail))
        self.status_code, self.detail = status_code, detail


def _claim(db: Session, proposal_id: str) -> ActionProposal:
    """open|failed -> executing, exactly once (a double click or two tabs can't both execute)."""
    n = db.query(ActionProposal).filter(ActionProposal.id == proposal_id, ActionProposal.status.in_(["open", "failed"])) \
        .update({ActionProposal.status: "executing"}, synchronize_session=False)
    db.commit()
    p = db.query(ActionProposal).filter(ActionProposal.id == proposal_id).first()
    if not p:
        raise DecisionError(404, "Proposal not found")
    if n != 1:
        raise DecisionError(409, f"This proposal is already {p.status}.")
    return p


def approve(db: Session, proposal_id: str, user_email: str, svc=None) -> ActionProposal:
    """Live re-check, then execute through the existing guarded Meta paths."""
    from fastapi import HTTPException
    from facebook_business.adobjects.adset import AdSet
    from app.api.v1.facebook import _enforce_budget_sanity
    from app.services.facebook_service import FacebookService

    p = _claim(db, proposal_id)
    log_event(db, "proposal_approved", p.id, user_email)
    p.decided_by, p.decided_at = user_email, _now()
    db.commit()
    try:
        if svc is None:
            svc = FacebookService()
            svc.initialize()
        live = svc.get_adset_status(p.fb_adset_id)
        live_status = live.get("effective_status") or live.get("status")
        live_budget = int(live["daily_budget"]) if live.get("daily_budget") else None
        expected = (p.evidence or {}).get("current", {})
        changed = []
        # IN_PROCESS / WITH_ISSUES are transient states of a running ad set, not a person's change.
        running = {"ACTIVE", "IN_PROCESS", "WITH_ISSUES"}
        if not (expected.get("status") == "ACTIVE" and live_status in running) and live_status != expected.get("status"):
            changed.append(f"now {live_status}")
        if p.action == "budget_increase" and live_budget != (p.action_params or {}).get("from_cents"):
            changed.append(f"budget now ${(live_budget or 0) / 100:,.2f}/day")
        if changed:
            p.status, p.status_reason = "stale", "ad set changed since the proposal (" + ", ".join(changed) + ")"
            log_event(db, "proposal_stale", p.id, user_email, live_status=live_status, live_budget_cents=live_budget)
            db.commit()
            return p
        if p.action == "pause":
            svc.update_adset_status(p.fb_adset_id, "PAUSED")
            result = {"status": "PAUSED"}
        else:
            to = int(p.action_params["to_cents"])
            _enforce_budget_sanity(live_budget, to, False, "Ad set")
            AdSet(fbid=p.fb_adset_id, api=svc.api).api_update(fields=[], params={"daily_budget": to})
            local = db.query(FacebookAdSet).filter(FacebookAdSet.fb_adset_id == p.fb_adset_id).first()
            if local:
                local.daily_budget = to
            result = {"daily_budget_cents": to, "previous_daily_budget_cents": live_budget}
        p.status, p.execution_result = "executed", result
        log_event(db, "proposal_executed", p.id, user_email, **result)
        db.commit()
        return p
    except HTTPException as exc:
        msg = exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail)
        return _fail(db, p, user_email, msg)
    except Exception as exc:
        logger.exception("Proposal %s execution failed", proposal_id)
        return _fail(db, p, user_email, str(exc)[:500])


def _fail(db: Session, p: ActionProposal, user_email: str, message: str) -> ActionProposal:
    db.rollback()
    p = db.query(ActionProposal).filter(ActionProposal.id == p.id).first()
    p.status, p.execution_result = "failed", {"error": message}
    log_event(db, "proposal_failed", p.id, user_email, error=message)
    db.commit()
    return p


def dismiss(db: Session, proposal_id: str, user_email: str, reason: str, note: str | None) -> ActionProposal:
    if reason not in DISMISS_REASONS:
        raise DecisionError(400, f"Pick a reason: {', '.join(DISMISS_REASONS)}")
    if reason == "Other" and not (note or "").strip():
        raise DecisionError(400, "Add a note for 'Other'.")
    n = db.query(ActionProposal).filter(ActionProposal.id == proposal_id, ActionProposal.status.in_(["open", "failed"])) \
        .update({ActionProposal.status: "dismissed", ActionProposal.dismiss_reason: reason,
                 ActionProposal.dismiss_note: (note or "").strip() or None, ActionProposal.decided_by: user_email,
                 ActionProposal.decided_at: _now()}, synchronize_session=False)
    if n != 1:
        db.rollback()
        p = db.query(ActionProposal).filter(ActionProposal.id == proposal_id).first()
        raise DecisionError(404 if not p else 409, "Proposal not found" if not p else f"This proposal is already {p.status}.")
    log_event(db, "proposal_dismissed", proposal_id, user_email, reason=reason)
    db.commit()
    return db.query(ActionProposal).filter(ActionProposal.id == proposal_id).first()


def serialize(p: ActionProposal) -> dict:
    return {
        "id": p.id, "fb_account_id": p.fb_account_id, "fb_adset_id": p.fb_adset_id, "adset_name": p.adset_name,
        "trigger_key": p.trigger_key, "trigger_keys": p.trigger_keys or [p.trigger_key],
        "trigger_labels": [TRIGGER_LABELS.get(t, t) for t in (p.trigger_keys or [p.trigger_key])],
        "action": p.action, "action_params": p.action_params, "evidence": p.evidence, "status": p.status,
        "status_reason": p.status_reason, "decided_by": p.decided_by,
        "decided_at": p.decided_at.isoformat() if p.decided_at else None,
        "dismiss_reason": p.dismiss_reason, "dismiss_note": p.dismiss_note, "execution_result": p.execution_result,
        "outcome_3d": p.outcome_3d, "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ---------------------------------------------------------------- shadow comparison (Meta activity log)

_ACTIVITY_CACHE: dict[tuple, tuple[float, list]] = {}
_ACTIVITY_LOCK = threading.Lock()
ACTIVITY_CACHE_TTL = 600


def _parse_extra(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}


def _cents(v):
    """Budget values arrive nested, e.g. {"type":"payment_amount","old_value":6000,...}."""
    if isinstance(v, dict):
        for k in ("old_value", "new_value", "value", "amount"):
            if isinstance(v.get(k), (int, float)):
                return int(v[k])
        return None
    return int(v) if isinstance(v, (int, float)) else None


def human_adset_actions(account_id: str, since: datetime, until: datetime | None = None, svc=None, rows=None) -> list[dict]:
    """Ad-set pauses / re-activations / budget changes from Meta's activity log.

    Verified against RHO's live log 2026-11-02: an ad set is object_type CAMPAIGN (legacy naming),
    changes are JSON strings in extra_data, application_name is the same for every human change so
    people are told apart by actor_name, and Meta's own system events have actor_name "Meta"."""
    if rows is None:
        key = (account_id, int(since.timestamp()) // ACTIVITY_CACHE_TTL)
        with _ACTIVITY_LOCK:
            hit = _ACTIVITY_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < ACTIVITY_CACHE_TTL:
            rows = hit[1]
        else:
            if svc is None:
                from app.services.facebook_service import FacebookService
                svc = FacebookService()
                svc.initialize()
            rows = [dict(r) for r in svc._get_account(account_id).get_activities(
                fields=["event_type", "event_time", "actor_name", "object_type", "object_id", "object_name", "extra_data"],
                params={"since": int(since.timestamp()), "limit": 500})]
            with _ACTIVITY_LOCK:
                _ACTIVITY_CACHE[key] = (time.monotonic(), rows)
    out = []
    for r in rows:
        if r.get("object_type") != "CAMPAIGN" or r.get("actor_name") in (None, "", "Meta"):
            continue
        et = r.get("event_type")
        ts = datetime.fromisoformat(str(r.get("event_time")).replace("+0000", "+00:00"))
        if until and ts > until:
            continue
        ex = _parse_extra(r.get("extra_data"))
        if et == "update_ad_set_run_status":
            new = str(ex.get("new_value") or "")
            kind = "pause" if new == "Inactive" else "activate" if new == "Active" else None
            if not kind:
                continue
            item = {"kind": kind}
        elif et == "update_ad_set_budget":
            old, new = _cents(ex.get("old_value")), _cents(ex.get("new_value"))
            if old is None or new is None or old == new:
                continue
            item = {"kind": "budget_increase" if new > old else "budget_decrease", "from_cents": old, "to_cents": new}
        else:
            continue
        item.update({"fb_adset_id": str(r.get("object_id")), "adset_name": r.get("object_name"),
                     "actor": r.get("actor_name"), "at": ts})
        out.append(item)
    return out


def shadow_report(db: Session, account_id: str, days: int = 7, actions: list[dict] | None = None) -> dict:
    """Proposals vs what people actually did in Meta, same ad set, same direction, within 24h."""
    since = _now() - timedelta(days=days)
    if actions is None:
        actions = human_adset_actions(account_id, since)
    # Auto-pause rule actions run through the app's token (they show as the token owner), so drop
    # any action that matches a rule log entry on the same ad set within 10 minutes.
    rule_hits = db.query(AutoPauseRuleLog.fb_adset_id, AutoPauseRuleLog.created_at).filter(
        AutoPauseRuleLog.created_at >= since, AutoPauseRuleLog.result == "success").all()
    rule_index: dict[str, list[datetime]] = {}
    for aid, ts in rule_hits:
        if aid:
            rule_index.setdefault(str(aid), []).append(_aware(ts))
    queue_ids = {r[0] for r in db.query(ActionProposal.fb_adset_id).filter(
        ActionProposal.fb_account_id == account_id, ActionProposal.status == "executed",
        ActionProposal.decided_at >= since).all()}

    def by_rule(a):
        return any(abs((a["at"] - t).total_seconds()) <= 600 for t in rule_index.get(a["fb_adset_id"], []))

    human = [a for a in actions if not by_rule(a)]
    proposals = db.query(ActionProposal).filter(ActionProposal.fb_account_id == account_id,
                                                ActionProposal.created_at >= since).all()
    want = {"pause": "pause", "budget_increase": "budget_increase"}
    matched_actions = set()
    rows = []
    for p in proposals:
        created = _aware(p.created_at)
        hit = next((i for i, a in enumerate(human) if a["fb_adset_id"] == p.fb_adset_id and a["kind"] == want[p.action]
                    and timedelta(0) <= a["at"] - created <= timedelta(hours=24)), None)
        if hit is not None:
            matched_actions.add(hit)
        rows.append({"proposal_id": p.id, "adset_name": p.adset_name, "action": p.action, "trigger": p.trigger_key,
                     "created_at": created.isoformat(), "status": p.status,
                     "people_did_it": hit is not None, "by": human[hit]["actor"] if hit is not None else None})
    unproposed = [{"adset_name": a["adset_name"], "kind": a["kind"], "actor": a["actor"], "at": a["at"].isoformat(),
                   "via_queue": a["fb_adset_id"] in queue_ids}
                  for i, a in enumerate(human) if i not in matched_actions and a["kind"] in ("pause", "budget_increase")]
    pauses = [a for a in human if a["kind"] == "pause"]
    raises = [a for a in human if a["kind"] == "budget_increase"]
    return {
        "account_id": account_id, "days": days,
        "proposals": len(rows), "proposals_people_also_made": sum(1 for r in rows if r["people_did_it"]),
        "people_pauses": len(pauses), "people_budget_increases": len(raises),
        "people_actions_excluded_as_rules": len(actions) - len(human),
        "by_actor": {k: sum(1 for a in human if a["actor"] == k) for k in sorted({a["actor"] for a in human})},
        "proposal_rows": sorted(rows, key=lambda r: r["created_at"], reverse=True)[:200],
        "people_actions_without_proposal": sorted(unproposed, key=lambda r: r["at"], reverse=True)[:200],
    }
