from datetime import date
from decimal import Decimal

from app.api.v1 import dashboard as dash
from app.api.v1.dashboard import _brief_adset_rows, _brief_day_flags, _brief_daily_rows, _period_totals


def test_period_totals_preserves_unknown_revenue_instead_of_turning_it_into_zero():
    totals = _period_totals([
        {"spend": 100, "leads": 10, "revenue": None},
        {"spend": 50, "leads": 5, "revenue": None},
    ])

    assert totals == {"spend": 150.0, "leads": 15, "cpl": 10.0, "revenue": None, "revenue_per_lead": None, "roas": None}


def test_daily_rows_preserve_a_real_zero_revenue_when_exact_source_completed():
    rows = _brief_daily_rows(
        {"2026-10-20": {"date": "2026-10-20", "spend": 120, "leads": 8, "cpl": 15}},
        {}, True, date(2026, 10, 20), date(2026, 10, 20),
    )

    assert rows[0]["revenue"] == 0.0
    assert rows[0]["revenue_per_lead"] == 0.0
    assert rows[0]["roas"] == 0.0


def test_day_flags_need_material_spend_and_use_observed_rpl_not_fixed_cpl_target():
    totals = {"spend": 1000, "revenue_per_lead": 20}
    flags = _brief_day_flags([
        {"date": "2026-10-20", "spend": 90, "leads": 2, "cpl": 45, "revenue_per_lead": 1, "roas": 0.02},
        {"date": "2026-10-21", "spend": 200, "leads": 10, "cpl": 20, "revenue_per_lead": 10, "roas": 0.5},
    ], totals)

    assert [flag["date"] for flag in flags] == ["2026-10-21"]
    assert flags[0]["kind"] == "rpl_below_period"


def test_adset_rows_keep_campaign_economics_unallocated():
    rows = _brief_adset_rows(
        {"1": {"adset_name": "Current", "spend": 150, "leads": 5, "cpl": 30}},
        {"1": {"adset_name": "Prior", "spend": 100, "leads": 10, "cpl": 10}},
        {"1": {"campaign_name": "Commercial"}},
    )

    assert rows[0]["campaign_name"] == "Commercial"
    assert rows[0]["status"] == "UNKNOWN"
    assert rows[0]["spend_change_pct"] == 50.0
    assert "revenue" not in rows[0]


def test_daily_rows_handle_the_real_decimal_revenue_type_from_switchboard():
    # Regression: _exact_daily_billable_revenue returns Decimal sums while Meta spend is a float. `Decimal / float` raised
    # TypeError on every real day that had both, so the whole brief 502'd for any revenue-tracked account.
    rows = _brief_daily_rows(
        {"2026-10-20": {"date": "2026-10-20", "spend": 120.0, "leads": 8, "cpl": 15.0},
         "2026-10-21": {"date": "2026-10-21", "spend": 80.5, "leads": 0, "cpl": None}},
        {"2026-10-20": Decimal("300.25"), "2026-10-21": Decimal("0")},
        True, date(2026, 10, 20), date(2026, 10, 21),
    )
    assert rows[0]["revenue"] == 300.25
    assert rows[0]["roas"] == round(300.25 / 120.0, 2)
    assert rows[0]["revenue_per_lead"] == round(300.25 / 8, 2)
    assert rows[1]["roas"] == 0.0 and rows[1]["revenue_per_lead"] is None
    totals = _period_totals(rows)          # the rows feed the totals; they must stay float-clean end to end
    assert totals["revenue"] == 300.25 and totals["spend"] == 200.5
    assert isinstance(rows[0]["revenue"], float)


def test_refresh_inside_the_floor_returns_the_cached_answer_instead_of_recomputing(monkeypatch):
    cache = {}
    clock = {"now": 1000.0}
    monkeypatch.setattr(dash.time, "monotonic", lambda: clock["now"])
    cache[("acct",)] = (1000.0, 1000.0, {"answer": 1})
    clock["now"] = 1030.0                                    # 30 s later: a "Refresh" click
    assert dash._read_dashboard_cache(cache, ("acct",), 600, True, min_refresh_seconds=60) == {"answer": 1}   # throttled -> cached
    assert dash._read_dashboard_cache(cache, ("acct",), 600, True) is None                                    # other endpoints unchanged
    clock["now"] = 1075.0                                    # 75 s later: allowed to recompute
    assert dash._read_dashboard_cache(cache, ("acct",), 600, True, min_refresh_seconds=60) is None
    assert dash._read_dashboard_cache(cache, ("none",), 600, True, min_refresh_seconds=60) is None            # nothing cached yet


# ---- end-to-end: the REAL route function with realistic types (the helper-level tests above missed a second Decimal*float) ----
import json
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.encoders import jsonable_encoder

from app.services.redtrack_service import today_in_rt_tz


class _User:
    def __init__(self, pnl=True):
        self._pnl = pnl

    def has_permission(self, name):
        return self._pnl if name == "pnl:read" else False

    def allowed_account_ids(self):
        return None


def _wire_route(monkeypatch, *, low_revenue_day=None, status="exact_adset_attributed"):
    end = today_in_rt_tz() - timedelta(days=2)
    start = end - timedelta(days=5)                     # 6-day window
    prev_start = start - timedelta(days=6)

    class FakeFacebookService:
        def get_account_daily_insights(self, account, date_from, date_to):
            rows, cursor = [], date.fromisoformat(date_from)
            while cursor <= date.fromisoformat(date_to):
                rows.append({"date": str(cursor), "spend": 100.0, "leads": 8, "cpl": 12.5})   # floats/ints, like the real service
                cursor += timedelta(days=1)
            return rows

        def get_account_insights_bulk(self, ad_account_id=None, date_from=None, date_to=None, **kw):
            return {"120000000000000001": {"adset_name": "Ad Set A", "spend": 300.0, "leads": 20, "cpl": 15.0},
                    "120000000000000002": {"adset_name": "Ad Set B", "spend": 50.0, "leads": 0, "cpl": None}}

    def fake_revenue(db, account, s, e, refresh, began):
        if status != "exact_adset_attributed":
            return {"status": status, "daily": {}}
        daily, cursor = {}, s
        while cursor <= e:
            # Decimal sums, exactly what the real Switchboard path returns
            daily[str(cursor)] = Decimal("24.00") if str(cursor) == low_revenue_day else Decimal("240.00")
            cursor += timedelta(days=1)
        return {"status": "exact_adset_attributed", "daily": daily}

    monkeypatch.setattr(dash, "FacebookService", FakeFacebookService)
    monkeypatch.setattr(dash, "_daily_billable_revenue", fake_revenue)
    dash._performance_brief_cache.clear()
    return start, end


def _call(start, end, user):
    return dash.get_performance_brief(
        ad_account_id="act_521142087204815", date_from=str(start), date_to=str(end), refresh=False,
        db=MagicMock(), current_user=user,
    )


def test_performance_brief_endpoint_works_with_decimal_revenue_and_flags_the_weak_day(monkeypatch):
    start, end = _wire_route(monkeypatch, low_revenue_day=None)
    low_day = str(start + timedelta(days=3))
    start, end = _wire_route(monkeypatch, low_revenue_day=low_day)
    result = _call(start, end, _User(pnl=True))        # used to raise HTTPException 502 (TypeError swallowed by the route)
    payload = json.loads(json.dumps(jsonable_encoder(result)))
    assert payload["data_quality"]["revenue_status"] == "exact_adset_attributed"
    assert payload["totals"]["revenue"] == pytest.approx(5 * 240.0 + 24.0)
    assert all(isinstance(payload["totals"][k], float) for k in ("spend", "cpl", "revenue", "revenue_per_lead", "roas"))
    flags = payload["day_flags"]
    assert (low_day, "rpl_below_period") in {(f["date"], f["kind"]) for f in flags}   # the weak day is flagged — the line that raised Decimal*float
    assert not any(f["date"] != low_day and f["kind"] == "rpl_below_period" for f in flags)   # and only that day


def test_performance_brief_endpoint_without_pnl_permission_shows_unknown_revenue_not_zero(monkeypatch):
    start, end = _wire_route(monkeypatch, status="access_denied")
    payload = jsonable_encoder(_call(start, end, _User(pnl=False)))
    assert payload["totals"]["revenue"] is None and payload["totals"]["roas"] is None
    assert payload["totals"]["spend"] == pytest.approx(600.0)
