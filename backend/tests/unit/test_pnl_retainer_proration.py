"""Recurring-monthly costs: full months count 1, month-to-date counts 1,
other partial months prorate by day (2026-11-01 review)."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.api.v1.pnl import _overlap_months

TODAY = date(2026, 11, 15)


def _entry(frm=date(2026, 7, 1), to=None):
    return SimpleNamespace(effective_from=frm, effective_to=to)


def test_full_month_is_one():
    assert _overlap_months(_entry(), date(2026, 10, 1), date(2026, 10, 31), TODAY) == 1


def test_month_to_date_counts_full():
    assert _overlap_months(_entry(), date(2026, 11, 1), date(2026, 11, 15), TODAY) == 1


def test_cross_month_custom_range_prorates():
    # Oct 30-31 (2/31) + Nov 1-2 is current month from the 1st but ends before today -> 2/30
    got = _overlap_months(_entry(), date(2026, 10, 30), date(2026, 11, 2), TODAY)
    assert got == Decimal(2) / Decimal(31) + Decimal(2) / Decimal(30)
    assert got < 1


def test_rolling_week_prorates():
    got = _overlap_months(_entry(), date(2026, 11, 9), date(2026, 11, 15), TODAY)
    assert got == Decimal(7) / Decimal(30)


def test_multi_month_range():
    assert _overlap_months(_entry(), date(2026, 8, 1), date(2026, 10, 31), TODAY) == 3


def test_effective_from_mid_month_prorates():
    got = _overlap_months(_entry(frm=date(2026, 10, 16)), date(2026, 10, 1), date(2026, 10, 31), TODAY)
    assert got == Decimal(16) / Decimal(31)


def test_no_overlap_is_zero():
    assert _overlap_months(_entry(to=date(2026, 9, 30)), date(2026, 10, 1), date(2026, 10, 31), TODAY) == 0


def test_cost_ending_this_month_prorates_month_to_date():
    got = _overlap_months(_entry(to=date(2026, 11, 20)), date(2026, 11, 1), date(2026, 11, 30), TODAY)
    assert got == Decimal(20) / Decimal(30)
