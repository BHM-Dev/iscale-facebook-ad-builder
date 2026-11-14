"""Review N2: account rows and the all-accounts extras must be frozen from one consistent pass."""
from datetime import date
from decimal import Decimal

from app.api.v1 import pnl

MACRO = "{{adset.id}}"


def test_pinned_recovery_gives_every_call_the_same_answer(monkeypatch):
    answers = iter(["111111111111111", "222222222222222"])     # a second lookup would place it elsewhere

    def fake_unpinned(db, rows):
        adset = next(answers)
        return [{**r, "sub3": adset} for r in rows]
    monkeypatch.setattr(pnl, "_recover_macro_adsets_unpinned", fake_unpinned)
    row = {"sub3": MACRO, "sub5": "click-1", "revenue": 50}
    with pnl.pinned_recovery():
        first = pnl._recover_macro_adsets(None, [row])
        second = pnl._recover_macro_adsets(None, [dict(row)])
    assert first[0]["sub3"] == second[0]["sub3"] == "111111111111111"


def test_pinned_recovery_remembers_a_miss(monkeypatch):
    calls = []

    def fake_unpinned(db, rows):
        calls.append(len(rows))
        return rows                                  # not recoverable
    monkeypatch.setattr(pnl, "_recover_macro_adsets_unpinned", fake_unpinned)
    row = {"sub3": MACRO, "sub5": "click-2"}
    with pnl.pinned_recovery():
        pnl._recover_macro_adsets(None, [row])
        out = pnl._recover_macro_adsets(None, [dict(row)])
    assert calls == [1] and out[0]["sub3"] == MACRO


def _one_pass_setup(monkeypatch, eligible=True, extras_ok=True, frozen=False):
    writes = []
    monkeypatch.setattr(pnl, "_closed_full_month", lambda s, e, grace_days=0: True)
    monkeypatch.setattr(pnl, "_extras_snapshot_frozen", lambda db, a, s: frozen)
    monkeypatch.setattr(pnl, "_snapshot_for_account_month", lambda db, a, s: None)
    monkeypatch.setattr(pnl, "_summary", lambda db, a, s, e, l, include_costs=True: {"account": a})
    monkeypatch.setattr(pnl, "_all_extras_for_period", lambda *a, **k: (Decimal("5"), extras_ok, Decimal("0"), Decimal("0")))
    monkeypatch.setattr(pnl, "_snapshot_eligible", lambda row: eligible)
    monkeypatch.setattr(pnl, "_write_month_snapshot", lambda db, a, *x: writes.append(a))
    monkeypatch.setattr(pnl, "_account_snapshots_complete", lambda db, scope, s: True)
    monkeypatch.setattr(pnl, "_write_all_extras_snapshot", lambda *a, **k: writes.append("extras"))
    return writes


def test_one_pass_writes_accounts_then_extras(monkeypatch):
    writes = _one_pass_setup(monkeypatch)
    rows, extras = pnl._freeze_month_in_one_pass(None, ["act_1", "act_2"], date(2026, 10, 1), date(2026, 10, 31), "Oct", None, {})
    assert writes == ["act_1", "act_2", "extras"] and extras[0] == Decimal("5")


def test_one_pass_writes_nothing_if_any_account_ineligible(monkeypatch):
    writes = _one_pass_setup(monkeypatch, eligible=False)
    pnl._freeze_month_in_one_pass(None, ["act_1"], date(2026, 10, 1), date(2026, 10, 31), "Oct", None, {})
    assert writes == []


def test_one_pass_writes_nothing_if_extras_incomplete(monkeypatch):
    writes = _one_pass_setup(monkeypatch, extras_ok=False)
    pnl._freeze_month_in_one_pass(None, ["act_1"], date(2026, 10, 1), date(2026, 10, 31), "Oct", None, {})
    assert writes == []


def test_one_pass_skips_already_frozen_month(monkeypatch):
    _one_pass_setup(monkeypatch, frozen=True)
    assert pnl._freeze_month_in_one_pass(None, ["act_1"], date(2026, 10, 1), date(2026, 10, 31), "Oct", None, {}) is None


def test_one_pass_never_overwrites_an_existing_account_snapshot(monkeypatch):
    writes = _one_pass_setup(monkeypatch)
    monkeypatch.setattr(pnl, "_snapshot_for_account_month", lambda db, a, s: object() if a == "act_2" else None)
    assert pnl._freeze_month_in_one_pass(None, ["act_1", "act_2"], date(2026, 10, 1), date(2026, 10, 31), "Oct", None, {}) is None
    assert writes == []
