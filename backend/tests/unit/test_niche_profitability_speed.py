"""niche-profitability fetches Meta and RedTrack in parallel and pulls each key once (2026-10-30)."""
import threading
import time

from app.api.v1 import intelligence as intel


def _setup(monkeypatch, calls):
    intel._NICHE_PROFITABILITY_RESULT_CACHE.clear()
    monkeypatch.setattr(intel, "_resolve_scoped_default_account", lambda user, acct: acct)

    def meta(*a):
        calls.append("meta"); time.sleep(0.6); return {}

    def rt(*a):
        calls.append("rt"); time.sleep(0.6); return {}

    monkeypatch.setattr(intel, "_fetch_meta_insights", meta)
    monkeypatch.setattr(intel, "_fetch_redtrack", rt)


def test_meta_and_redtrack_run_in_parallel(monkeypatch):
    calls = []
    _setup(monkeypatch, calls)
    t = time.monotonic()
    out = intel.niche_profitability(preset="last_7d", date_from=None, date_to=None, ad_account_id="act_1",
                                    refresh=False, current_user=None, db=None)
    assert time.monotonic() - t < 1.0          # serial would be ~1.2s
    assert sorted(calls) == ["meta", "rt"] and out["rows"] == []


def test_concurrent_requests_for_one_key_fetch_once(monkeypatch):
    calls = []
    _setup(monkeypatch, calls)
    kw = dict(preset="last_7d", date_from=None, date_to=None, ad_account_id="act_2", refresh=False,
              current_user=None, db=None)
    threads = [threading.Thread(target=intel.niche_profitability, kwargs=kw) for _ in range(3)]
    for th in threads: th.start()
    for th in threads: th.join()
    assert calls.count("meta") == 1
