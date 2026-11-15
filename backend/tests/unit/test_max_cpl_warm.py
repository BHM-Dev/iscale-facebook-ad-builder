"""Max CPL background warm: refresh before expiry, retry failures, never clobber a good result."""
from time import monotonic

import pytest

from app.services import max_cpl_service as m

KEY = ("act_1", 1.30, 30)
GOOD = {"available": True, "account_id": "act_1"}


@pytest.fixture(autouse=True)
def clean():
    m._CACHE.clear()
    yield
    m._CACHE.clear()


def _compute_returns(monkeypatch, value=None, exc=None):
    calls = []
    def fake(db, account_id, days, target_roas):
        calls.append(account_id)
        if exc:
            raise exc
        return value
    monkeypatch.setattr(m, "_compute", fake)
    return calls


def test_cold_cache_is_filled(monkeypatch):
    calls = _compute_returns(monkeypatch, GOOD)
    assert m.warm(None, "act_1") == "refreshed" and calls == ["act_1"]
    assert m._cached(KEY) == GOOD


def test_recent_good_result_is_left_alone(monkeypatch):
    calls = _compute_returns(monkeypatch, GOOD)
    m._CACHE[KEY] = (monotonic() - 600, m.TTL_SECONDS, GOOD)
    assert m.warm(None, "act_1") == "fresh" and calls == []


def test_aging_good_result_is_refreshed_before_expiry(monkeypatch):
    calls = _compute_returns(monkeypatch, {**GOOD, "v": 2})
    m._CACHE[KEY] = (monotonic() - 2400, m.TTL_SECONDS, GOOD)
    assert m.warm(None, "act_1") == "refreshed" and calls
    assert m._cached(KEY)["v"] == 2


def test_failure_does_not_replace_a_still_valid_good_result(monkeypatch):
    _compute_returns(monkeypatch, exc=RuntimeError("Meta code 2"))
    m._CACHE[KEY] = (monotonic() - 2400, m.TTL_SECONDS, GOOD)
    assert m.warm(None, "act_1") == "failed"
    assert m._cached(KEY) == GOOD


def test_failure_on_cold_cache_is_cached_briefly_and_retried(monkeypatch):
    calls = _compute_returns(monkeypatch, exc=RuntimeError("Meta code 2"))
    assert m.warm(None, "act_1") == "failed"
    assert m._CACHE[KEY][1] == m.FAILURE_TTL_SECONDS
    assert m.warm(None, "act_1") == "failed" and len(calls) == 2   # next run retries, not "fresh"
