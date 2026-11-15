"""push-to-meta: a throttled campaign lookup must not lose the attribution row (11/01 review)."""
from unittest.mock import MagicMock

from facebook_business.exceptions import FacebookRequestError

from app.api.v1 import facebook as fb


def _db(local_row):
    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.first.return_value = local_row
    return db


def _throttled(*_a, **_k):
    raise FacebookRequestError("throttled", {}, 400, {}, '{"error":{"code":17}}')


def test_local_campaign_is_used_without_calling_meta(monkeypatch):
    meta = MagicMock(side_effect=AssertionError("Meta must not be called when the ad set is synced"))
    monkeypatch.setattr(fb, "AdSet", meta)
    assert fb._resolve_push_campaign_id(_db(("cmp_local",)), MagicMock(), "as1", "cmp_body") == "cmp_local"


def test_throttled_meta_lookup_returns_blank_instead_of_raising(monkeypatch):
    monkeypatch.setattr(fb, "AdSet", lambda *a, **k: MagicMock(api_get=_throttled))
    # unverified client value is not written into a revenue row
    assert fb._resolve_push_campaign_id(_db(None), MagicMock(), "as1", "cmp_body") is None


def test_meta_answering_without_campaign_uses_client_value(monkeypatch):
    monkeypatch.setattr(fb, "AdSet", lambda *a, **k: MagicMock(api_get=lambda **kw: {}))
    assert fb._resolve_push_campaign_id(_db(None), MagicMock(), "as1", "cmp_body") == "cmp_body"


def test_failing_rollback_does_not_escape(monkeypatch):
    db = MagicMock()
    db.query.side_effect = RuntimeError("connection gone")
    db.rollback.side_effect = RuntimeError("still gone")
    monkeypatch.setattr(fb, "AdSet", lambda *a, **k: MagicMock(api_get=_throttled))
    assert fb._resolve_push_campaign_id(db, MagicMock(), "as1", "x") is None


def test_meta_used_when_ad_set_not_synced_locally(monkeypatch):
    monkeypatch.setattr(fb, "AdSet", lambda *a, **k: MagicMock(api_get=lambda **kw: {"campaign_id": "cmp_meta"}))
    assert fb._resolve_push_campaign_id(_db(None), MagicMock(), "as1", "cmp_body") == "cmp_meta"


def test_local_db_error_still_reaches_meta(monkeypatch):
    db = MagicMock()
    db.query.side_effect = RuntimeError("db hiccup")
    monkeypatch.setattr(fb, "AdSet", lambda *a, **k: MagicMock(api_get=lambda **kw: {"campaign_id": "cmp_meta"}))
    assert fb._resolve_push_campaign_id(db, MagicMock(), "as1", None) == "cmp_meta"
    db.rollback.assert_called_once()
