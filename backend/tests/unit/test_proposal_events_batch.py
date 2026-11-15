"""Batched proposal UI events: one request for all proposal_viewed events on panel load."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.api.v1 import proposals as route


def _setup(monkeypatch, can_view=True, actions=None):
    logged = []
    monkeypatch.setattr(route.ps, "can_view", lambda u: can_view)
    monkeypatch.setattr(route.ps, "visible_actions", lambda u: actions)
    monkeypatch.setattr(route.ps, "log_event", lambda db, ev, pid, email, props=None: logged.append((ev, pid)))
    return logged


def _body(*events):
    return route.EventBatchBody(events=[route.EventBody(**e) for e in events])


USER = SimpleNamespace(email="u@example.com")


def test_batch_logs_each_event_and_commits_once(monkeypatch):
    logged = _setup(monkeypatch)
    db = MagicMock()
    route.client_events_batch(_body({"event": "proposal_viewed", "proposal_id": "p1"},
                                    {"event": "proposal_viewed", "proposal_id": "p2"},
                                    {"event": "not_a_client_event"}), db, USER)
    assert logged == [("proposal_viewed", "p1"), ("proposal_viewed", "p2")]
    db.commit.assert_called_once()


def test_batch_respects_visibility(monkeypatch):
    logged = _setup(monkeypatch, can_view=False)
    route.client_events_batch(_body({"event": "proposal_viewed", "proposal_id": "p1"}), MagicMock(), USER)
    assert logged == []


def test_batch_skips_proposal_types_the_user_cannot_see(monkeypatch):
    logged = _setup(monkeypatch, actions={"raise_budget"})
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [("pause",), ("raise_budget",)]
    route.client_events_batch(_body({"event": "proposal_viewed", "proposal_id": "hidden"},
                                    {"event": "proposal_viewed", "proposal_id": "shown"}), db, USER)
    assert logged == [("proposal_viewed", "shown")]


def test_batch_is_capped():
    with pytest.raises(ValidationError):
        route.EventBatchBody(events=[{"event": "proposal_viewed"}] * 101)
