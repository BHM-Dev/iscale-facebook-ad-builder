"""Approvals queue (2026-11-02): triggers, dedupe/expiry, approve re-check + execution, dismiss,
and the Meta activity-log shadow comparison."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import ActionProposal, AutoPauseRule, AutoPauseRuleLog, FacebookAdSet, ProposalEvent
from app.services import proposal_service as ps

TODAY = date(2026, 11, 2)
MAX = 500000
ACCT = "act_521142087204815"


def _series(per_day):
    """per_day: (spend, leads, revenue) tuples, oldest first, today last."""
    meta, rev = {}, {}
    n = len(per_day)
    for i, (s, l, r) in enumerate(per_day):
        d = (TODAY - timedelta(days=n - 1 - i)).isoformat()
        meta[d] = {"spend": float(s), "leads": l}
        if r:
            rev[d] = float(r)
    return meta, rev


def _eval(per_day, budget=7500, status="ACTIVE"):
    meta, rev = _series(per_day)
    return ps.evaluate({"a1": meta}, {"a1": rev}, {"a1": {"name": "Set", "status": status, "daily_budget_cents": budget}}, TODAY, MAX)


# ---------------------------------------------------------------- triggers

def test_no_revenue_spend_fires():
    out = _eval([(0, 0, 0)] * 4 + [(40, 2, 0), (40, 2, 0), (55, 3, 0)])
    assert len(out) == 1 and out[0]["action"] == "pause" and out[0]["trigger_keys"] == ["no_revenue_spend"]
    ev = out[0]["evidence"]
    assert [d["day"] for d in ev["days"]] == ["2026-10-31", "2026-11-01", "2026-11-02"]
    assert ev["days"][-1] == {"day": "2026-11-02", "spend": 55.0, "leads": 3, "revenue": 0.0, "profit": -55.0}
    assert ev["current"] == {"status": "ACTIVE", "daily_budget_cents": 7500}


def test_no_revenue_first_day_says_so():
    """Replay 2026-11-02: first-day no-revenue ad sets lost money over the next 7 days 93% of the
    time, so they stay proposed; the reason just mustn't claim 3 days of history."""
    first = _eval([(0, 0, 0)] * 6 + [(65, 0, 0)])
    assert first[0]["trigger_keys"] == ["no_revenue_spend"]
    assert first[0]["evidence"]["why"] == "Spent $65 today, its first spend in 7+ days, with no revenue yet"
    restarted = _eval([(0, 0, 0)] * 2 + [(40, 1, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (55, 0, 0)])
    assert restarted[0]["evidence"]["why"] == "Spent $55 today with no revenue in 3 days"
    steady = _eval([(0, 0, 0)] * 4 + [(40, 2, 0), (40, 2, 0), (55, 3, 0)])
    assert steady[0]["evidence"]["why"] == "Spent $55 today with no revenue in 3 days"


def test_no_revenue_needs_50_today_and_zero_revenue_for_3_days():
    assert _eval([(0, 0, 0)] * 4 + [(40, 2, 0), (40, 2, 0), (49, 3, 0)]) == []          # $49 today
    assert _eval([(0, 0, 0)] * 4 + [(40, 2, 5), (40, 2, 0), (55, 3, 0)]) == []          # $5 two days ago


def test_bad_cpl_with_good_revenue_is_never_proposed():
    # The replay showed CPL-spike pausing would have cut winners; there is no CPL trigger.
    out = _eval([(60, 6, 90)] * 6 + [(60, 1, 90)])
    assert all(c["action"] != "pause" for c in out)     # (it does qualify as a scale winner: 50% ROI)


def test_loss_3d_edges():
    assert _eval([(0, 0, 0)] * 4 + [(60, 2, 10), (60, 2, 10), (40, 2, 0)]) == []        # lost $140: below the bar
    out = _eval([(0, 0, 0)] * 4 + [(60, 2, 10), (60, 2, 0), (40, 2, 0)])                 # lost $150
    assert out[0]["trigger_keys"] == ["loss_3d"]


def test_both_pause_triggers_recorded_on_one_proposal():
    out = _eval([(0, 0, 0)] * 4 + [(60, 2, 0), (60, 2, 0), (60, 2, 0)])
    assert out[0]["trigger_keys"] == ["no_revenue_spend", "loss_3d"]


def test_scale_winner_raises_20_percent_capped_by_ceiling():
    days = [(40, 4, 70)] * 5 + [(40, 4, 0), (40, 4, 0)]   # 7d spend 280, revenue 350 -> ROI 25%: not enough
    assert _eval(days) == []
    days = [(40, 4, 80)] * 5 + [(40, 4, 0), (40, 4, 30)]  # spend 280, revenue 430 -> ROI 54%, 5 profitable days
    out = _eval(days, budget=7500)
    assert out[0]["action"] == "budget_increase" and out[0]["action_params"] == {"from_cents": 7500, "to_cents": 9000}
    capped = ps.evaluate(*[{"a1": x} for x in _series(days)], {"a1": {"name": "S", "status": "ACTIVE", "daily_budget_cents": 499000}}, TODAY, MAX)
    assert capped[0]["action_params"]["to_cents"] == MAX


def test_scale_needs_4_profitable_days_and_a_daily_budget():
    days = [(40, 4, 0)] * 4 + [(40, 4, 200)] * 3        # ROI high but only 3 profitable days
    assert _eval(days) == []
    good = [(40, 4, 80)] * 7
    assert _eval(good, budget=None) == []               # CBO / lifetime budget: nothing to raise


def test_only_live_active_ad_sets_are_considered():
    meta, rev = _series([(0, 0, 0)] * 4 + [(60, 2, 0)] * 3)
    assert ps.evaluate({"gone": meta}, {}, {}, TODAY, MAX) == []


# ---------------------------------------------------------------- persistence

@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for m in (FacebookAdSet, AutoPauseRule, AutoPauseRuleLog, ActionProposal, ProposalEvent):
        m.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _cand(aid="a1", action="pause", params=None, status="ACTIVE", budget=7500):
    return {"fb_adset_id": aid, "adset_name": "Set " + aid, "trigger_keys": ["loss_3d"], "action": action,
            "action_params": params or {"from_status": "ACTIVE", "to_status": "PAUSED"},
            "evidence": {"why": "x", "days": [], "totals_7d": {}, "current": {"status": status, "daily_budget_cents": budget}}}


LIVE = {"a1": {"status": "ACTIVE"}, "a2": {"status": "ACTIVE"}}


def test_one_open_proposal_per_ad_set_and_cooldown_after_decision(db):
    assert ps.apply_candidates(db, ACCT, [_cand()], LIVE)["created"] == 1
    assert ps.apply_candidates(db, ACCT, [_cand()], LIVE)["created"] == 0          # still open
    p = db.query(ActionProposal).one()
    ps.dismiss(db, p.id, "joel@x", "Still testing", None)
    assert ps.apply_candidates(db, ACCT, [_cand()], LIVE)["created"] == 0          # 3-day cooldown
    p.decided_at = datetime.now(timezone.utc) - timedelta(days=4)
    db.commit()
    assert ps.apply_candidates(db, ACCT, [_cand()], LIVE)["created"] == 1


def test_expiry_reasons(db):
    ps.apply_candidates(db, ACCT, [_cand("a1"), _cand("a2")], LIVE)
    ps.apply_candidates(db, ACCT, [], {"a2": {"status": "ACTIVE"}})
    reasons = {p.fb_adset_id: (p.status, p.status_reason) for p in db.query(ActionProposal)}
    assert reasons == {"a1": ("expired", "ad set no longer active"), "a2": ("expired", "condition cleared")}
    ps.apply_candidates(db, ACCT, [_cand("a1")], LIVE)
    p = db.query(ActionProposal).filter(ActionProposal.status == "open").one()
    p.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db.commit()
    ps.apply_candidates(db, ACCT, [_cand("a1")], LIVE)
    assert db.query(ActionProposal).filter(ActionProposal.id == p.id).one().status_reason == "timed out"


class FakeSvc:
    def __init__(self, live, fail=None):
        self.live, self.fail, self.calls, self.api = live, fail, [], None

    def get_adset_status(self, aid):
        return self.live

    def update_adset_status(self, aid, status):
        if self.fail:
            raise RuntimeError(self.fail)
        self.calls.append(("status", aid, status))


def _open(db, **kw):
    ps.apply_candidates(db, ACCT, [_cand(**kw)], LIVE)
    return db.query(ActionProposal).filter(ActionProposal.status == "open").one()


def test_approve_pause_executes_once(db):
    p = _open(db)
    svc = FakeSvc({"effective_status": "ACTIVE", "daily_budget": "7500"})
    assert ps.approve(db, p.id, "joel@x", svc=svc).status == "executed"
    assert svc.calls == [("status", "a1", "PAUSED")]
    with pytest.raises(ps.DecisionError) as e:              # double click / second tab
        ps.approve(db, p.id, "joel@x", svc=svc)
    assert e.value.status_code == 409 and svc.calls == [("status", "a1", "PAUSED")]
    events = [e.event for e in db.query(ProposalEvent).order_by(ProposalEvent.created_at)]
    assert "proposal_approved" in events and "proposal_executed" in events


def test_approve_goes_stale_when_ad_set_changed_and_sends_nothing(db):
    p = _open(db)
    svc = FakeSvc({"effective_status": "PAUSED", "daily_budget": "7500"})
    out = ps.approve(db, p.id, "joel@x", svc=svc)
    assert out.status == "stale" and "now PAUSED" in out.status_reason and svc.calls == []


def test_approve_budget_stale_when_budget_moved(db):
    p = _open(db, action="budget_increase", params={"from_cents": 7500, "to_cents": 9000})
    svc = FakeSvc({"effective_status": "ACTIVE", "daily_budget": "8000"})
    out = ps.approve(db, p.id, "abel@x", svc=svc)
    assert out.status == "stale" and "budget now $80.00/day" in out.status_reason


def test_approve_budget_executes_through_meta_and_mirrors_locally(db, monkeypatch):
    db.add(FacebookAdSet(id="local1", name="Set a1", fb_adset_id="a1", campaign_id="c", daily_budget=7500, optimization_goal="LEAD_GENERATION"))
    db.commit()
    p = _open(db, action="budget_increase", params={"from_cents": 7500, "to_cents": 9000})
    sent = []

    class FakeAdSet:
        def __init__(self, fbid, api):
            self.fbid = fbid

        def api_update(self, fields, params):
            sent.append((self.fbid, params))

    import facebook_business.adobjects.adset as adset_mod
    monkeypatch.setattr(adset_mod, "AdSet", FakeAdSet)
    out = ps.approve(db, p.id, "abel@x", svc=FakeSvc({"effective_status": "ACTIVE", "daily_budget": "7500"}))
    assert out.status == "executed" and sent == [("a1", {"daily_budget": 9000})]
    assert db.query(FacebookAdSet).one().daily_budget == 9000


def test_meta_error_marks_failed_and_retry_is_allowed(db):
    p = _open(db)
    out = ps.approve(db, p.id, "joel@x", svc=FakeSvc({"effective_status": "ACTIVE"}, fail="(#100) nope"))
    assert out.status == "failed" and "(#100)" in out.execution_result["error"]
    assert ps.approve(db, p.id, "joel@x", svc=FakeSvc({"effective_status": "ACTIVE"})).status == "executed"


def test_dismiss_needs_a_reason_and_a_note_for_other(db):
    p = _open(db)
    with pytest.raises(ps.DecisionError):
        ps.dismiss(db, p.id, "joel@x", "because", None)
    with pytest.raises(ps.DecisionError):
        ps.dismiss(db, p.id, "joel@x", "Other", "  ")
    out = ps.dismiss(db, p.id, "joel@x", "Revenue is lagging", None)
    assert (out.status, out.dismiss_reason, out.decided_by) == ("dismissed", "Revenue is lagging", "joel@x")


def test_shadow_visibility(monkeypatch):
    class U:
        email = "Steve@x.com"
    monkeypatch.setenv("PROPOSALS_SHADOW", "true")
    monkeypatch.setenv("PROPOSALS_SHADOW_VIEWERS", "steve@x.com")
    assert ps.can_view(U())
    U.email = "joel@x.com"
    assert not ps.can_view(U())
    monkeypatch.setenv("PROPOSALS_SHADOW", "false")
    assert ps.can_view(U())


# ---------------------------------------------------------------- shadow comparison

def _act(event_type, adset, actor, when, extra, object_type="CAMPAIGN"):
    # Shape of a real /act_{id}/activities row (RHO, verified 2026-11-02).
    return {"event_type": event_type, "event_time": when.strftime("%Y-%m-%dT%H:%M:%S+0000"), "actor_name": actor,
            "object_type": object_type, "object_id": adset, "object_name": "Set " + adset, "extra_data": json.dumps(extra)}


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def test_activity_log_parsing():
    rows = [
        _act("update_ad_set_run_status", "a1", "Marketingosjoel", NOW, {"old_value": "Active", "new_value": "Inactive", "type": "run_status"}),
        _act("update_ad_set_run_status", "a2", "Marketingosjoel", NOW, {"old_value": "Inactive", "new_value": "Active"}),
        _act("update_ad_set_budget", "a3", "Marketingosjoel", NOW, {
            "old_value": {"type": "payment_amount", "currency": "USD", "old_value": 6000},
            "new_value": {"type": "payment_amount", "currency": "USD", "new_value": 7200}}),
        _act("update_ad_set_run_status", "a4", "Meta", NOW, {"new_value": "Inactive"}),                  # system event
        _act("update_ad_run_status", "ad9", "Marketingosjoel", NOW, {"new_value": "Inactive"}, "ADGROUP"),  # an ad, not an ad set
    ]
    out = ps.human_adset_actions(ACCT, NOW - timedelta(days=1), rows=rows)
    assert [(a["fb_adset_id"], a["kind"]) for a in out] == [("a1", "pause"), ("a2", "activate"), ("a3", "budget_increase")]
    assert out[2]["from_cents"] == 6000 and out[2]["to_cents"] == 7200


def test_shadow_report_matches_and_excludes_rule_actions(db):
    ps.apply_candidates(db, ACCT, [_cand("a1"), _cand("a2", action="budget_increase", params={"from_cents": 5000, "to_cents": 6000})], LIVE)
    for p in db.query(ActionProposal):
        p.created_at = NOW - timedelta(hours=5)
    db.add(AutoPauseRuleLog(fb_adset_id="a7", action="pause", metric="cpl", threshold=50, result="success",
                            created_at=NOW - timedelta(hours=1)))
    db.commit()
    actions = ps.human_adset_actions(ACCT, NOW - timedelta(days=2), rows=[
        _act("update_ad_set_run_status", "a1", "Marketingosjoel", NOW - timedelta(hours=2), {"new_value": "Inactive"}),   # matches p(a1)
        _act("update_ad_set_run_status", "a5", "Marketingosjoel", NOW - timedelta(hours=3), {"new_value": "Inactive"}),   # no proposal
        _act("update_ad_set_run_status", "a7", "Steve Sun", NOW - timedelta(hours=1), {"new_value": "Inactive"}),         # a rule did it
    ])
    r = ps.shadow_report(db, ACCT, days=2, actions=actions)
    assert r["proposals"] == 2 and r["proposals_people_also_made"] == 1
    assert r["people_pauses"] == 2 and r["people_actions_excluded_as_rules"] == 1
    assert [x["adset_name"] for x in r["people_actions_without_proposal"]] == ["Set a5"]
    assert {x["adset_name"]: x["people_did_it"] for x in r["proposal_rows"]} == {"Set a1": True, "Set a2": False}


def test_interrupted_execution_is_released_as_failed(db):
    p = _open(db)
    p.status, p.decided_at = "executing", datetime.now(timezone.utc) - timedelta(minutes=20)
    db.commit()
    ps.apply_candidates(db, ACCT, [], LIVE)
    assert db.query(ActionProposal).filter(ActionProposal.id == p.id).one().status == "failed"


def test_transient_meta_states_are_not_stale(db):
    p = _open(db)
    svc = FakeSvc({"effective_status": "WITH_ISSUES", "daily_budget": "7500"})
    assert ps.approve(db, p.id, "joel@x", svc=svc).status == "executed"


def test_failed_proposals_expire_instead_of_lingering(db):
    p = _open(db)
    p.status, p.created_at = "failed", datetime.now(timezone.utc) - timedelta(hours=25)
    db.commit()
    ps.apply_candidates(db, ACCT, [_cand()], LIVE)
    assert db.query(ActionProposal).filter(ActionProposal.id == p.id).one().status == "expired"


def test_expiry_never_overwrites_a_claimed_proposal(db):
    p = _open(db)
    # Someone clicks Approve after the evaluator read the row but before it expired it.
    real_query = db.query

    def query(*a, **k):
        q = real_query(*a, **k)
        if a and a[0] is ActionProposal and not getattr(query, "done", False):
            query.done = True
            rows = q.filter(ActionProposal.status.in_(["open", "failed"])).all()
            real_query(ActionProposal).filter(ActionProposal.id == p.id).update({ActionProposal.status: "executing"})
            class Stub:
                def filter(self, *x, **y): return self
                def all(self): return rows
            return Stub()
        return q
    db.query = query
    ps.apply_candidates(db, ACCT, [], {})          # would expire it ("no longer active")
    db.query = real_query
    assert db.query(ActionProposal).filter(ActionProposal.id == p.id).one().status == "executing"
