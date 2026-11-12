"""S7 (2026-11-01 review): a failed spend/revenue source must not produce a commission figure."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.api.v1 import pnl


def _entries(monkeypatch):
    common = dict(ad_account_id=None, category="people", allocation_method="spend", effective_from=date(2026, 7, 1),
                  effective_to=None, notes=None, vendor=None, source=None, created_at=None, updated_at=None)
    retainer = SimpleNamespace(id=1, label="Retainer", cost_type="fixed", amount=Decimal("3000"), profit_threshold=None, **common)
    commission = SimpleNamespace(id=2, label="Commission", cost_type="pct_of_profit", amount=Decimal("5"),
                                 profit_threshold=None, **common)
    monkeypatch.setattr(pnl, "_aggregate_cost_query", lambda *a: SimpleNamespace(all=lambda: [retainer, commission]))


def test_commission_is_computed_when_sources_loaded(monkeypatch):
    _entries(monkeypatch)
    costs, total = pnl._resolve_aggregate_costs(None, ["act_1"], date(2026, 11, 1), date(2026, 11, 30),
                                                Decimal("50000"), Decimal("60000"))
    commission = next(c for c in costs if c["cost_type"] == "pct_of_profit")
    assert commission["resolved_amount"] == 350.0 and not commission.get("withheld")   # 5% of (10,000 - 3,000)
    assert total == Decimal("3350.00")


def test_commission_is_withheld_when_a_source_failed(monkeypatch):
    _entries(monkeypatch)
    costs, total = pnl._resolve_aggregate_costs(None, ["act_1"], date(2026, 11, 1), date(2026, 11, 30),
                                                Decimal("16000"), Decimal("60000"), profit_known=False)
    commission = next(c for c in costs if c["cost_type"] == "pct_of_profit")
    assert commission["resolved_amount"] is None and commission["withheld"] is True
    assert total == Decimal("3000")     # the retainer still counts; no commission on an overstated profit


def test_all_summary_withholds_when_an_account_spend_is_missing(monkeypatch):
    seen = {}

    def fake_costs(db, ids, s, e, spend, revenue, profit_known=True):
        seen["k"] = profit_known
        return [], Decimal("0")

    monkeypatch.setattr(pnl, "_resolve_aggregate_costs", fake_costs)
    rows = [{"ad_account_id": "act_1", "spend": None, "revenue": 1000.0},
            {"ad_account_id": "act_2", "spend": 100.0, "revenue": 200.0}]
    out = pnl._all_summary_from_account_rows(None, ["act_1", "act_2"], date(2026, 11, 1), date(2026, 11, 30), "Nov", rows)
    assert seen["k"] is False and out["data_incomplete"] is True
    assert out["net_profit"] is None and out["margin"] is None     # not an overstated number
