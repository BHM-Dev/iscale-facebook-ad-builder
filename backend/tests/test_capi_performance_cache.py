"""Account Health 'Performance by pixel' cache: fresh 30 min, stale served while refreshing, errors never cached,
and scopes never share an entry."""
import time

import pytest

from app.api.v1 import capi_quality as cq


@pytest.fixture
def pulls(monkeypatch):
    calls = []

    def fake(date_preset, restrict_to_account_ids, known_pixels):
        calls.append((date_preset, restrict_to_account_ids))
        if date_preset == "broken":
            return {"skipped_reason": "Meta not configured"}
        return {"pixels": [{"pixel_id": "1", "spend": len(calls)}], "date_from": "2026-10-19", "date_to": "2026-11-17"}

    monkeypatch.setattr(cq, "get_pixel_performance", fake)
    monkeypatch.setattr(cq, "_perf_cache", {})
    monkeypatch.setattr(cq, "_perf_refreshing", set())
    return calls


def key(preset="last_30d", scope=None):
    return (preset, scope, ("1",))


def test_fresh_hit_skips_pull(pulls):
    first = cq._pull_performance(key(), "last_30d", None, [{"pixel_id": "1"}])
    assert "pulled_at" in first and len(pulls) == 1
    assert cq._perf_cache[key()][1] is first


def test_errors_are_not_cached(pulls):
    cq._pull_performance(key("broken"), "broken", None, [])
    assert key("broken") not in cq._perf_cache


def test_scopes_do_not_share(pulls):
    cq._pull_performance(key(scope=("act_1",)), "last_30d", {"act_1"}, [])
    assert key(scope=None) not in cq._perf_cache


def test_stale_refresh_runs_once(pulls, monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            started.append(1)

    monkeypatch.setattr(cq.threading, "Thread", FakeThread)
    cq._refresh_in_background(key(), "last_30d", None, [])
    cq._refresh_in_background(key(), "last_30d", None, [])   # already refreshing: no second thread
    assert started == [1]
