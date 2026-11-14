"""Review S8: resync-all used to write account snapshots one by one, so a later failure left
the month half re-fetched. Nothing may be written unless every source came back complete."""
import pytest
from fastapi import HTTPException

from app.api.v1 import pnl


def _setup(monkeypatch, rows, extras_ok=True):
    writes = []
    monkeypatch.setattr(pnl, "_require_account", lambda u, a: "all")
    monkeypatch.setattr(pnl, "_permitted_active_account_ids", lambda db, u: list(rows))
    monkeypatch.setattr(pnl, "_summary", lambda db, a, s, e, l, include_costs=True: dict(rows[a]))
    monkeypatch.setattr(pnl, "_write_month_snapshot", lambda db, a, s, e, row, u: writes.append(a))
    monkeypatch.setattr(pnl, "_all_extras_for_period", lambda *a, **k: (0, extras_ok, 0, 0))
    monkeypatch.setattr(pnl, "_all_summary_from_account_rows", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(pnl, "_closed_full_month", lambda s, e, grace_days=0: True)
    monkeypatch.setattr(pnl, "_account_snapshots_complete", lambda db, scope, s: True)
    monkeypatch.setattr(pnl, "_write_all_extras_snapshot", lambda db, scope, *a, **k: writes.append("extras"))
    return writes


def test_second_account_incomplete_writes_nothing(monkeypatch):
    writes = _setup(monkeypatch, {"act_1": {"data_incomplete": False}, "act_2": {"data_incomplete": True, "errors": ["meta"]}})
    with pytest.raises(HTTPException):
        pnl.resync_month("2026-09", "all", db=None, current_user=None)
    assert writes == []


def test_extras_incomplete_writes_nothing(monkeypatch):
    writes = _setup(monkeypatch, {"act_1": {"data_incomplete": False}}, extras_ok=False)
    with pytest.raises(HTTPException):
        pnl.resync_month("2026-09", "all", db=None, current_user=None)
    assert writes == []


def test_all_complete_writes_every_account(monkeypatch):
    writes = _setup(monkeypatch, {"act_1": {"data_incomplete": False}, "act_2": {"data_incomplete": False}})
    assert pnl.resync_month("2026-09", "all", db=None, current_user=None) == {"ok": True}
    assert writes == ["act_1", "act_2", "extras"]   # extras frozen after the accounts
