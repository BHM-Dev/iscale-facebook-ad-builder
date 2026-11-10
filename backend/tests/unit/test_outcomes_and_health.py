"""Proposal outcomes (3 days after as_of) and the health monitor's alert/recovery state machine."""
from datetime import date, datetime, timedelta, timezone

from app.services import health_monitor as hm
from app.services.proposal_service import outcome_for


def test_outcome_sums_the_three_days_after_as_of_only():
    series = {
        "2026-11-05": {"spend": 999.0, "leads": 9, "rev": 0.0},     # proposal day: excluded
        "2026-11-06": {"spend": 100.0, "leads": 3, "rev": 150.0},
        "2026-11-07": {"spend": 100.0, "leads": 2},                 # no revenue row that day
        "2026-11-08": {"spend": 50.0, "leads": 1, "rev": 40.0},
        "2026-11-09": {"spend": 500.0, "leads": 5, "rev": 900.0},   # day 4: excluded
    }
    out = outcome_for(series, date(2026, 11, 5), "open", "t")
    assert out["window"] == ["2026-11-06", "2026-11-08"]
    assert (out["spend"], out["leads"], out["revenue"], out["profit"]) == (250.0, 6, 190.0, -60.0)
    assert out["status_at_measure"] == "open"


def test_health_alerts_once_after_an_hour_then_on_recovery():
    hm._STATE.clear()
    t0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    problem = {"max_cpl:act_1": "Max CPL unavailable"}
    assert hm.evaluate_transitions(problem, t0) == []                                  # just started
    assert hm.evaluate_transitions(problem, t0 + timedelta(minutes=30)) == []          # not an hour yet
    assert hm.evaluate_transitions(problem, t0 + timedelta(minutes=60)) == [("alert", "max_cpl:act_1", "Max CPL unavailable")]
    assert hm.evaluate_transitions(problem, t0 + timedelta(minutes=90)) == []          # no repeat
    assert hm.evaluate_transitions({}, t0 + timedelta(minutes=120)) == [("recovered", "max_cpl:act_1", "Max CPL unavailable")]


def test_a_blip_shorter_than_an_hour_never_alerts():
    hm._STATE.clear()
    t0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    assert hm.evaluate_transitions({"close:a": "x"}, t0) == []
    assert hm.evaluate_transitions({}, t0 + timedelta(minutes=30)) == []               # silent recovery
    assert hm._STATE == {}


def test_failed_slack_send_retries_next_tick(monkeypatch):
    import app.services.slack_service as slack
    hm._STATE.clear()
    t0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    hm.evaluate_transitions({"max_cpl:a": "down"}, t0)
    hm._STATE["max_cpl:a"]["since"] = t0 - timedelta(hours=2)
    monkeypatch.setattr(hm, "collect_problems", lambda db: {"max_cpl:a": "down"})
    sends = []
    monkeypatch.setattr(slack, "send_drive_sync_alert", lambda *a, **k: sends.append(1) and False)
    hm.run_check(None)
    assert hm._STATE["max_cpl:a"]["alerted"] is False       # send failed: not marked
    monkeypatch.setattr(slack, "send_drive_sync_alert", lambda *a, **k: True)
    assert hm.run_check(None)["messages_sent"] == 1          # retried and delivered
    assert hm._STATE["max_cpl:a"]["alerted"] is True
