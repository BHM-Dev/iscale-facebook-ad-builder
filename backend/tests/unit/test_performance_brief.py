from datetime import date

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
