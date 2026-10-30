"""Steve, 2026-10-30: closed months are fixed unless he asks for a re-fetch — including the single-month view."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.api.v1 import pnl


def test_closed_month_is_served_from_its_snapshot_without_external_calls(monkeypatch):
    snap = SimpleNamespace(spend=Decimal("100"), revenue=Decimal("150"), conversions=3, unmapped_adsets=0,
                           revenue_source="everflow_live", unattributed_revenue=Decimal("0"), event_breakdown=[], synced_at=None)
    monkeypatch.setattr(pnl, "_snapshot_for_account_month", lambda db, a, s: snap)
    monkeypatch.setattr(pnl, "_closed_full_month", lambda s, e, grace_days=0: True)

    def no_external(*a, **k):
        raise AssertionError("a closed month with a snapshot must not call Meta or Everflow")

    monkeypatch.setattr(pnl, "_spend_for_account", no_external)
    monkeypatch.setattr(pnl, "_revenue_for_account", no_external)
    row = pnl._account_summary_frozen_if_closed(None, "act_1", date(2026, 9, 1), date(2026, 9, 30), "September 2026", None)
    assert (row["spend"], row["revenue"], row["from_snapshot"]) == (100.0, 150.0, True)


def test_current_month_stays_live(monkeypatch):
    called = []
    monkeypatch.setattr(pnl, "_closed_full_month", lambda s, e, grace_days=0: False)
    monkeypatch.setattr(pnl, "_summary", lambda *a, **k: called.append(k) or {"from_snapshot": False})
    pnl._account_summary_frozen_if_closed(None, "act_1", date(2026, 10, 1), date(2026, 10, 30), "MTD", None)
    assert called == [{}]     # no snapshot passed
