from types import SimpleNamespace

import app.api.v1.auto_pause as auto_pause


def _call(monkeypatch, db, insight_rows):
    class _FakeService:
        def get_account_ads_insights_bulk(self, **kwargs):
            return {"adset1": [dict(row) for row in insight_rows]}

    monkeypatch.setattr(auto_pause, "FacebookService", _FakeService)
    monkeypatch.setattr(auto_pause, "_resolve_scoped_default_account", lambda user, acct: acct)
    monkeypatch.setattr(auto_pause, "_read_insights_bulk_cache", lambda key, refresh: None)
    monkeypatch.setattr(auto_pause, "_write_insights_bulk_cache", lambda *a, **k: None)
    return auto_pause.get_ads_bulk(
        ad_account_id="act_1", date_preset="last_7d", date_from=None, date_to=None,
        include_all=False, include_status=False, db=db, current_user=None,
    )


class _Query:
    def __init__(self, rows=None, error=None):
        self.rows, self.error = rows or [], error

    def join(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def all(self):
        if self.error:
            raise self.error
        return self.rows


class _DB:
    def __init__(self, query):
        self._query = query
        self.rolled_back = False

    def query(self, *a, **k):
        return self._query

    def rollback(self):
        self.rolled_back = True


def _row(ad_id, account, source_type="drive", category="Brand / Package"):
    return SimpleNamespace(
        fb_ad_id=ad_id, creative_name=f"{ad_id}.mp4", source_type=source_type,
        source_category=category, fb_account_id=account,
    )


def test_launch_context_is_merged_only_for_exact_id_in_the_scoped_account(monkeypatch):
    db = _DB(_Query([_row("a1", "1"), _row("a2", "act_999")]))
    result = _call(monkeypatch, db, [{"ad_id": "a1"}, {"ad_id": "a2"}, {"ad_id": "a3"}])
    by_id = {row["ad_id"]: row for row in result["adset1"]}
    assert by_id["a1"]["launch_context"] == {
        "source_type": "drive", "source_category": "Brand / Package", "source_file_name": "a1.mp4",
    }
    assert "launch_context" not in by_id["a2"]  # same Meta id but another account's local row
    assert "launch_context" not in by_id["a3"]  # never launched from the app


def test_a_failing_lookup_still_returns_meta_rows(monkeypatch):
    for error in (Exception("db down"), RuntimeError("column does not exist")):
        db = _DB(_Query(error=error))
        result = _call(monkeypatch, db, [{"ad_id": "a1", "spend": 5}])
        assert result["adset1"] == [{"ad_id": "a1", "spend": 5}]
        assert db.rolled_back
