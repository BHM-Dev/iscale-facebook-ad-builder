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


def test_settled_unavailable_is_cached_long_and_warm_skips_it(monkeypatch):
    m._CACHE.clear()
    calls = []

    def compute(db, account_id, days, target_roas):
        calls.append(account_id)
        return m._unavailable(account_id, "No leads or revenue in the window", settled=True)

    monkeypatch.setattr(m, "_compute", compute)
    first = m.compute_max_cpl(None, "act_quiet")
    assert first["settled"] is True
    key = ("act_quiet", 1.30, 30)
    assert m._CACHE[key][1] == m.SETTLED_TTL_SECONDS
    assert m.warm(None, "act_quiet") == "fresh"      # no re-pull for a settled answer
    assert calls == ["act_quiet"]


def test_recent_accounts_are_remembered():
    m._RECENT.clear()
    m.note_request("act_1")
    assert m.recent_accounts() == ["act_1"]
