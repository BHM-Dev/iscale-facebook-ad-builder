from types import SimpleNamespace
from decimal import Decimal

import pytest

import app.api.v1.dashboard as dashboard
from app.api.v1.dashboard import _exact_daily_billable_revenue
from app.services.everflow_service import EverflowService


def test_daily_revenue_uses_only_configured_offer_and_exact_sub3_adset_mapping():
    result = _exact_daily_billable_revenue(
        rows=[
            {"offer": "Mapped Offer", "revenue": "20.25", "sub3": "adset-1", "conversion_date": "2026-09-20"},
            {"offer": "Mapped Offer", "revenue": "99.99", "sub2": "adset-1", "conversion_date": "2026-09-20"},
            {"offer": "Mapped Offer", "revenue": "88.88", "sub3": "other-adset", "conversion_date": "2026-09-20"},
            {"offer": "Other Offer", "revenue": "77.77", "sub3": "adset-1", "conversion_date": "2026-09-20"},
            {"offer": "Mapped Offer", "revenue": "10.10", "sub3": "adset-1", "conversion_date": "2026-09-21"},
        ],
        offer_names={"Mapped Offer"},
        scoped_adset_ids={"adset-1"},
    )

    assert result == {"2026-09-20": Decimal("20.25"), "2026-09-21": Decimal("10.10")}


def test_daily_revenue_fails_closed_on_invalid_exact_mapped_revenue():
    with pytest.raises(ValueError, match="invalid revenue"):
        _exact_daily_billable_revenue(
            rows=[{"offer": "Mapped Offer", "revenue": "not-money", "sub3": "adset-1", "conversion_date": "2026-09-20"}],
            offer_names={"Mapped Offer"},
            scoped_adset_ids={"adset-1"},
        )


def test_conversion_date_buckets_utc_timestamp_in_everflow_eastern_calendar():
    # 03:00 UTC on Jul 1 is still Jun 30 in Switchboard's reporting timezone.
    assert EverflowService._conversion_date({"conversion_unix_timestamp": "1782874800"}).isoformat() == "2026-06-30"


def test_trend_returns_exact_revenue_and_revenue_per_meta_lead(monkeypatch):
    class FakeFacebookService:
        def get_account_daily_insights(self, account_id, date_from, date_to):
            assert account_id == "act_1"
            return [
                {"date": "2026-09-19", "spend": 50, "leads": 2, "cpl": 25},
                {"date": "2026-09-20", "spend": 100, "leads": 4, "cpl": 25},
            ]

    monkeypatch.setattr(dashboard, "FacebookService", FakeFacebookService)
    monkeypatch.setattr(
        dashboard,
        "_daily_billable_revenue",
        lambda db, account_id, start, end: {
            "status": "exact_adset_attributed",
            "daily": {"2026-09-20": 140.0},
            "cached": False,
        },
    )
    user = SimpleNamespace(
        allowed_account_ids=lambda: None,
        has_permission=lambda permission: permission == "pnl:read",
    )

    result = dashboard.get_dashboard_trend(
        ad_account_id="act_1",
        date_from="2026-09-20",
        date_to="2026-09-20",
        db=object(),
        current_user=user,
    )

    assert result["daily"] == [{
        "date": "2026-09-20", "spend": 100, "leads": 4, "cpl": 25,
        "revenue": 140.0, "revenue_per_lead": 35.0,
    }]
    assert result["totals"]["revenue"] == 140.0
    assert result["totals"]["revenue_per_lead"] == 35.0
