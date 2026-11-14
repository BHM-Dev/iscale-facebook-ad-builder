"""Review N11: the warm job ran 24/7 with no per-offer isolation, and concurrent pulls of the
same BHM offer each hit Everflow."""
import threading
import time
from datetime import date, datetime

import app.services.bhm_everflow_service as bes
from app.api.v1 import pnl


class _FixedClock(datetime):
    hour_value = 3

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 14, cls.hour_value, 0, tzinfo=tz)


def test_warm_skips_overnight(monkeypatch):
    _FixedClock.hour_value = 3
    monkeypatch.setattr(pnl, "datetime", _FixedClock)
    monkeypatch.setattr(pnl, "_resolve_period", lambda p: (_ for _ in ()).throw(AssertionError("ran overnight")))
    pnl.warm_current_month_cache()


def test_one_failing_offer_does_not_stop_the_rest(monkeypatch):
    _FixedClock.hour_value = 10
    monkeypatch.setattr(pnl, "datetime", _FixedClock)
    monkeypatch.setattr(pnl, "_resolve_period", lambda p: (date(2026, 11, 1), date(2026, 11, 14), None))
    monkeypatch.setattr(pnl.EverflowService, "is_configured", lambda self: False)
    monkeypatch.setattr(pnl.BhmEverflowService, "is_configured", lambda self: True)
    monkeypatch.setattr(pnl, "_bhm_everflow_offer_map", lambda: {"act_1": ["A", "B"]})
    pulled = []

    def rows(self, s, e, offer_id, tz, refresh=False):
        pulled.append(offer_id)
        if offer_id == "A":
            raise RuntimeError("429")
        return []
    monkeypatch.setattr(pnl.BhmEverflowService, "_offer_rows", rows)
    pnl.warm_current_month_cache()
    assert pulled == ["A", "B"]


def test_concurrent_refreshes_share_one_everflow_pull(monkeypatch):
    bes._cache.clear()
    calls = []

    def fetch(self, *a):
        calls.append(1)
        time.sleep(0.2)
        return [{"x": 1}]
    monkeypatch.setattr(bes.BhmEverflowService, "_fetch_offer_rows", fetch)
    svc = bes.BhmEverflowService.__new__(bes.BhmEverflowService)
    out = []
    threads = [threading.Thread(target=lambda: out.append(svc._offer_rows(date(2026, 11, 1), date(2026, 11, 14), "9", 80, refresh=True))) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1 and len(out) == 4
