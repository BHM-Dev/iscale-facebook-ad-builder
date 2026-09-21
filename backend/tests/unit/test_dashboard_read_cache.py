import app.api.v1.dashboard as dashboard
from app.api.v1 import auto_pause


def test_dashboard_cache_is_account_range_scoped_and_refresh_bypasses(monkeypatch):
    cache = {}
    monkeypatch.setattr(dashboard.time, "monotonic", lambda: 100.0)
    dashboard._write_dashboard_cache(cache, ("act_1", "today"), {"rows": [1]}, request_started_at=99.0)

    cached = dashboard._read_dashboard_cache(cache, ("act_1", "today"), 60, refresh=False)
    assert cached == {"rows": [1]}
    cached["rows"].append(2)
    assert dashboard._read_dashboard_cache(cache, ("act_1", "today"), 60, refresh=False) == {"rows": [1]}
    assert dashboard._read_dashboard_cache(cache, ("act_2", "today"), 60, refresh=False) is None
    assert dashboard._read_dashboard_cache(cache, ("act_1", "today"), 60, refresh=True) is None


def test_dashboard_cache_uses_short_ttl_when_range_includes_redtrack_today(monkeypatch):
    monkeypatch.setattr(
        "app.services.redtrack_service.today_in_rt_tz",
        lambda: __import__("datetime").date(2026, 9, 21),
    )
    assert dashboard._dashboard_cache_ttl("last_7d", "2026-09-21") == dashboard.DASHBOARD_LIVE_CACHE_TTL_SECONDS
    assert dashboard._dashboard_cache_ttl("yesterday", "2026-09-20") == dashboard.DASHBOARD_HISTORICAL_CACHE_TTL_SECONDS


def test_meta_dashboard_caches_return_copies_and_refresh_bypasses(monkeypatch):
    monkeypatch.setattr(auto_pause.time, "monotonic", lambda: 100.0)
    auto_pause._insights_bulk_cache.clear()
    auto_pause._write_insights_bulk_cache(("act_1", "2026-09-21", "2026-09-21"), {"1": {"spend": 10}}, request_started_at=99.0)
    cached_insights = auto_pause._read_insights_bulk_cache(("act_1", "2026-09-21", "2026-09-21"), refresh=False)
    cached_insights["1"]["spend"] = 99
    assert auto_pause._read_insights_bulk_cache(("act_1", "2026-09-21", "2026-09-21"), refresh=False)["1"]["spend"] == 10
    assert auto_pause._read_insights_bulk_cache(("act_1", "2026-09-21", "2026-09-21"), refresh=True) is None

def test_older_request_cannot_overwrite_a_newer_dashboard_response(monkeypatch):
    cache = {}
    monkeypatch.setattr(dashboard.time, "monotonic", lambda: 100.0)
    dashboard._write_dashboard_cache(cache, ("act_1", "today"), {"source": "new"}, request_started_at=20.0)
    dashboard._write_dashboard_cache(cache, ("act_1", "today"), {"source": "old"}, request_started_at=10.0)

    assert dashboard._read_dashboard_cache(cache, ("act_1", "today"), 60, refresh=False) == {"source": "new"}


def test_trend_refresh_forces_the_billable_revenue_pull(monkeypatch):
    class FakeFacebookService:
        def get_account_daily_insights(self, *args):
            return []

    seen = []
    monkeypatch.setattr(dashboard, "FacebookService", FakeFacebookService)
    monkeypatch.setattr(
        dashboard,
        "_daily_billable_revenue",
        lambda *args, refresh=False, request_started_at=None: seen.append(refresh) or {"status": "unavailable", "daily": {}},
    )
    dashboard._trend_cache.clear()
    user = type("User", (), {
        "allowed_account_ids": lambda self: None,
        "has_permission": lambda self, permission: permission == "pnl:read",
    })()

    dashboard.get_dashboard_trend(
        ad_account_id="act_force_refresh",
        date_from="2026-09-20",
        date_to="2026-09-20",
        refresh=True,
        db=object(),
        current_user=user,
    )

    assert seen == [True]
