from datetime import date
from decimal import Decimal

from app.services import daily_close_service as service


def test_close_topline_comes_from_pnl_and_unavailable_has_no_profit(monkeypatch):
    monkeypatch.setattr(service.pnl, "_spend_for_account", lambda *args: Decimal("123.45"))
    monkeypatch.setattr(service.pnl, "_revenue_for_account", lambda *args: (Decimal("234.56"), 0, 0, "everflow_live", False, Decimal("0"), {}))
    monkeypatch.setattr(service, "_adset_rows", lambda *args: [])
    monkeypatch.setattr(service.proposal_service, "revenue_by_adset_day", lambda *args: {})
    result = service.compute_close(object(), "act_1", date(2026, 11, 3))
    assert result["spend"] == 123.45 and result["revenue"] == 234.56
    assert result["profit"] == 111.11 and result["roas"] == 1.9

    monkeypatch.setattr(service.pnl, "_revenue_for_account", lambda *args: (Decimal("0"), 0, 0, "everflow_unavailable", True, Decimal("0"), {}))
    unavailable = service.compute_close(object(), "act_1", date(2026, 11, 3))
    assert unavailable["available"] is False
    assert unavailable["revenue"] is None and unavailable["profit"] is None and unavailable["roas"] is None
