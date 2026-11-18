"""Live-range Meta spend is cached 5 min and prefetched in parallel; closed ranges and failures never are."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.api.v1 import pnl


class _Account:
    def __init__(self, calls, fail=False):
        self.calls, self.fail = calls, fail

    def get_insights(self, fields, params):
        self.calls.append(params["time_range"])
        if self.fail:
            raise RuntimeError("meta down")
        return [{"spend": "10.50"}]


@pytest.fixture
def meta(monkeypatch):
    calls, state = [], {"fail": False}
    monkeypatch.setattr(pnl, "_SPEND_CACHE", {})
    monkeypatch.setattr(pnl.FacebookService, "__init__", lambda self: None)
    monkeypatch.setattr(pnl.FacebookService, "_get_account", lambda self, a: _Account(calls, state["fail"]))
    return calls, state


def test_live_range_cached_until_refresh(meta):
    calls, _ = meta
    today = pnl.today_in_rt_tz()
    start = today.replace(day=1)
    assert pnl._spend_for_account("act_1", start, today) == Decimal("10.50")
    assert pnl._spend_for_account("1", start, today) == Decimal("10.50")   # same account, other spelling
    assert len(calls) == 1
    pnl._spend_for_account("act_1", start, today, refresh=True)
    assert len(calls) == 2


def test_closed_range_always_live(meta):
    calls, _ = meta
    end = pnl.today_in_rt_tz() - timedelta(days=1)
    pnl._spend_for_account("act_1", end, end)
    pnl._spend_for_account("act_1", end, end)
    assert len(calls) == 2


def test_failure_not_cached_and_prefetch_never_raises(meta):
    calls, state = meta
    today = pnl.today_in_rt_tz()
    state["fail"] = True
    pnl._prefetch_spend(["act_1", "act_2"], today, today)   # swallowed
    with pytest.raises(RuntimeError):
        pnl._spend_for_account("act_1", today, today)
    state["fail"] = False
    pnl._prefetch_spend(["act_1", "act_2"], today, today)
    n = len(calls)
    pnl._spend_for_account("act_2", today, today)
    assert len(calls) == n   # served from the prefetch
