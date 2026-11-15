"""Niche revenue is 'exact' only when every billable dollar lands in a niche bucket (11/01 review N12)."""
from app.api.v1.pnl import niche_revenue_status

KNOWN = {"a1", "a2"}
ROWS = {"a1": {}, "a2": {}}


def test_fully_attributed_is_exact():
    assert niche_revenue_status({"adsets": {"a1": {}}}, KNOWN, ROWS, {"a1": 50.0}) == "exact_adset_attributed"


def test_revenue_on_known_adset_without_meta_row_is_partial():
    # a2 earned revenue but had no spend in range, so no insights row -> it can't reach a niche bucket
    assert niche_revenue_status({"adsets": {"a2": {}}}, KNOWN, {"a1": {}}, {"a2": 25.0}) == "partial"


def test_zero_revenue_without_row_stays_exact():
    assert niche_revenue_status({"adsets": {"a2": {}}}, KNOWN, {"a1": {}}, {"a2": 0.0}) == "exact_adset_attributed"


def test_unknown_adset_or_unattributed_events_is_partial():
    assert niche_revenue_status({"adsets": {"zz": {}}}, KNOWN, ROWS, {}) == "partial"
    assert niche_revenue_status({"adsets": {}, "unattributed_events": 3}, KNOWN, ROWS, {}) == "partial"
