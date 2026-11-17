"""In-app feedback: saved with page + context, DMed to Steve, admin status updates."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import feedback as fb

USER = SimpleNamespace(id="u1", email="joel@example.com", name="Joel")


def test_submit_saves_page_and_context_and_alerts_steve(monkeypatch):
    sent = {}
    import app.services.slack_service as slack
    monkeypatch.setattr(slack, "send_feedback_alert", lambda **kw: sent.update(kw) or True)
    db = MagicMock()
    out = fb.submit_feedback(fb.FeedbackIn(message="  Remix drawer won't open  ", page_path="campaign-performance",
                                           context={"ad_account_id": "act_1"}), db, USER)
    row = db.add.call_args[0][0]
    assert (row.page_path, row.message, row.user_email, row.context) == (
        "/campaign-performance", "Remix drawer won't open", "joel@example.com", {"ad_account_id": "act_1"})
    assert sent["page"] == "/campaign-performance" and sent["url"].endswith("/campaign-performance")
    assert out["message"] == "Remix drawer won't open"


def test_slack_failure_never_loses_the_feedback(monkeypatch):
    import app.services.slack_service as slack
    def boom(**kw):
        raise RuntimeError("slack down")
    monkeypatch.setattr(slack, "send_feedback_alert", boom)
    db = MagicMock()
    fb.submit_feedback(fb.FeedbackIn(message="it broke", page_path="/pnl"), db, USER)
    db.commit.assert_called_once()


def test_oversized_context_is_dropped_not_stored():
    db = MagicMock()
    fb.submit_feedback(fb.FeedbackIn(message="big", page_path="/", context={"x": "y" * 5000}), db, USER)
    assert db.add.call_args[0][0].context == {"truncated": True}


def test_message_limits():
    with pytest.raises(ValidationError):
        fb.FeedbackIn(message="", page_path="/")
    with pytest.raises(ValidationError):
        fb.FeedbackIn(message="x" * 4001, page_path="/")


def test_status_update_sets_and_clears_resolved_at():
    row = SimpleNamespace(id="f1", status="new", resolution_note=None, resolved_at=None, user_email=None,
                          page_path="/", message="m", screenshot_url=None, context={}, created_at=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = row
    fb.update_feedback("f1", fb.FeedbackUpdate(status="done", resolution_note="fixed in abc123"), db, USER)
    assert row.status == "done" and row.resolved_at is not None and row.resolution_note == "fixed in abc123"
    fb.update_feedback("f1", fb.FeedbackUpdate(status="in_progress"), db, USER)
    assert row.resolved_at is None
    with pytest.raises(HTTPException):
        fb.update_feedback("f1", fb.FeedbackUpdate(status="deleted"), db, USER)


def test_screenshot_link_must_be_https():
    db = MagicMock()
    for bad in ("javascript:alert(1)", "data:text/html,x", "/uploads/x.png", "http://example.com/x.png"):
        with pytest.raises(HTTPException):
            fb.submit_feedback(fb.FeedbackIn(message="bad link", page_path="/", screenshot_url=bad), db, USER)
    fb.submit_feedback(fb.FeedbackIn(message="fine link", page_path="/", screenshot_url="https://media.example.com/a.png"), db, USER)
    assert db.add.call_args[0][0].screenshot_url == "https://media.example.com/a.png"


def test_page_path_must_be_an_in_app_path():
    db = MagicMock()
    for bad in ("//evil.example.com", "https://evil.example.com/x", "/redirect?to=javascript://x"):
        with pytest.raises(HTTPException):
            fb.submit_feedback(fb.FeedbackIn(message="bad page", page_path=bad), db, USER)
