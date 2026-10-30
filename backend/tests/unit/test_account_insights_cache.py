"""Shared cache in front of get_account_insights_bulk (2026-10-30)."""
import threading
import time

from app.services import facebook_service as fs


def _svc(monkeypatch, calls, delay=0.0):
    fs._ACCOUNT_INSIGHTS_CACHE.clear()
    svc = fs.FacebookService.__new__(fs.FacebookService)

    def fetch(self, ad_account_id, date_preset, date_from, date_to):
        calls.append((ad_account_id, date_preset, date_from, date_to))
        time.sleep(delay)
        return {"1": {"spend": 5.0}}

    monkeypatch.setattr(fs.FacebookService, "_fetch_account_insights_bulk", fetch)
    return svc


def test_second_read_is_cached_and_refresh_bypasses(monkeypatch):
    calls = []
    svc = _svc(monkeypatch, calls)
    svc.get_account_insights_bulk("act_1", date_preset="today")
    svc.get_account_insights_bulk("1", date_preset="today")          # same account, no act_ prefix
    assert len(calls) == 1
    svc.get_account_insights_bulk("act_1", date_preset="today", refresh=True)
    assert len(calls) == 2
    svc.get_account_insights_bulk("act_1", date_preset="yesterday")  # different range
    assert len(calls) == 3


def test_callers_cannot_mutate_the_cached_rows(monkeypatch):
    svc = _svc(monkeypatch, [])
    first = svc.get_account_insights_bulk("act_1", date_preset="today")
    first["1"]["rt_revenue"] = 99
    assert "rt_revenue" not in svc.get_account_insights_bulk("act_1", date_preset="today")["1"]


def test_concurrent_reads_fetch_once(monkeypatch):
    calls = []
    svc = _svc(monkeypatch, calls, delay=0.3)
    ts = [threading.Thread(target=svc.get_account_insights_bulk, args=("act_2",), kwargs={"date_preset": "today"}) for _ in range(4)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len(calls) == 1


def test_expired_entry_is_refetched(monkeypatch):
    calls = []
    svc = _svc(monkeypatch, calls)
    monkeypatch.setattr(fs, "ACCOUNT_INSIGHTS_CACHE_TTL_SECONDS", 0)
    svc.get_account_insights_bulk("act_3", date_preset="today")
    svc.get_account_insights_bulk("act_3", date_preset="today")
    assert len(calls) == 2
