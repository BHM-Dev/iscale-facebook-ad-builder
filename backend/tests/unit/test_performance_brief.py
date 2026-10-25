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
