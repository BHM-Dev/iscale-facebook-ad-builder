from datetime import date
from decimal import Decimal

from app.services import daily_close_service as service

AVAIL = (Decimal("234.56"), 0, 0, "everflow_live", False, Decimal("0"), {})
UNAVAIL = (Decimal("0"), 0, 0, "everflow_unavailable", True, Decimal("0"), {})


def _base(monkeypatch, revenue=lambda db, a, s, e: AVAIL):
    monkeypatch.setattr(service.pnl, "_spend_for_account", lambda *args: Decimal("123.45"))
    monkeypatch.setattr(service.pnl, "_revenue_for_account", revenue)
    monkeypatch.setattr(service, "_adset_rows", lambda *args: [{"adset_id": "1", "name": "A", "spend": 50.0, "leads": 3}])
    monkeypatch.setattr(service.proposal_service, "revenue_by_adset_day", lambda *args: {"1": {"2026-11-03": 80.0}})


def test_close_topline_comes_from_pnl(monkeypatch):
    _base(monkeypatch)
    result = service.compute_close(object(), "act_1", date(2026, 11, 3))
    assert result["spend"] == 123.45 and result["revenue"] == 234.56
    assert result["profit"] == 111.11 and result["roas"] == 1.9 and result["leads"] == 3
    assert result["movers"]["up"][0]["profit"] == 30.0


def test_unavailable_day_has_no_profit(monkeypatch):
    _base(monkeypatch, revenue=lambda *a: UNAVAIL)
    result = service.compute_close(object(), "act_1", date(2026, 11, 3))
    assert result["available"] is False
    assert result["revenue"] is None and result["profit"] is None and result["roas"] is None


def test_unavailable_mtd_and_last_month_are_none_not_zero(monkeypatch):
    day = date(2026, 11, 3)
    _base(monkeypatch, revenue=lambda db, a, s, e: AVAIL if s == e == day else UNAVAIL)
    result = service.compute_close(object(), "act_1", day)
    assert result["available"] is True
    assert result["mtd"]["revenue"] is None and result["mtd"]["profit"] is None and result["mtd"]["pace"] is None
    assert result["mtd"]["last_month_profit"] is None


def test_none_last_month_is_not_reused(monkeypatch):
    _base(monkeypatch)
    result = service.compute_close(object(), "act_1", date(2026, 11, 3), {"mtd": {"last_month_profit": None}})
    assert result["mtd"]["last_month_profit"] == 111.11      # recomputed, not frozen at None


def test_movers_failure_keeps_topline(monkeypatch):
    _base(monkeypatch)
    def boom(*a):
        raise service.proposal_service.RevenueUnavailable("x")
    monkeypatch.setattr(service.proposal_service, "revenue_by_adset_day", boom)
    result = service.compute_close(object(), "act_1", date(2026, 11, 3))
    assert result["available"] is True and result["profit"] == 111.11
    assert result["movers"] == {"up": [], "down": []} and result["movers_unavailable"] is True
