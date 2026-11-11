"""P&L "By campaign" (2026-11-11): accounts grouped into advertiser campaigns; lines always sum to the totals."""
from decimal import Decimal

from app.api.v1 import pnl

COMMERCIAL, RHO4, DIN_AUTO, THS, STRAY = (
    "act_521142087204815", "act_737291135429748", "act_949433761196746", "act_287925406489877", "act_999")


def _row(account, spend, revenue, source="everflow_live"):
    return {"ad_account_id": account, "spend": spend, "revenue": revenue, "revenue_source": source}


def test_groups_accounts_and_places_extras_by_campaign():
    rows = [_row(COMMERCIAL, 1000.0, 1300.0), _row(RHO4, 200.0, 180.0), _row(DIN_AUTO, 100.0, 70.0),
            _row(THS, 50.0, 0.0, "not_tracked"), _row(STRAY, 10.0, 0.0, "none")]
    out = {c["key"]: c for c in pnl._campaign_breakdown(rows, Decimal("120.00"), {"commercial": Decimal("100"), "auto": Decimal("20")})}
    assert list(out) == ["commercial", "auto", "home_services", "other"]
    assert (out["commercial"]["spend"], out["commercial"]["revenue"], out["commercial"]["gross_profit"]) == (1200.0, 1580.0, 380.0)
    assert [a["ad_account_id"] for a in out["commercial"]["accounts"]] == [COMMERCIAL, RHO4]
    assert out["auto"]["revenue"] == 90.0
    ths = out["home_services"]
    assert ths["revenue_tracked"] is False and ths["gross_profit"] is None and ths["roas"] is None
    assert ths["spend"] == 50.0 and ths["data_incomplete"] is False
    total_rev = sum(c["revenue"] or 0 for c in out.values())
    assert round(total_rev, 2) == 1300 + 180 + 70 + 120


def test_unsplit_extras_get_their_own_line_and_cent_drift_does_not():
    rows = [_row(COMMERCIAL, 10.0, 20.0)]
    lines = pnl._campaign_breakdown(rows, Decimal("50.00"), {})            # month frozen before the split existed
    assert lines[-1]["key"] == pnl.UNPLACED_CAMPAIGN_KEY and lines[-1]["revenue"] == 50.0
    lines = pnl._campaign_breakdown(rows, Decimal("50.01"), {"commercial": Decimal("50.00")})
    assert [c["key"] for c in lines] == ["commercial"] and lines[0]["revenue"] == 70.01


def test_missing_spend_marks_the_line_incomplete_instead_of_guessing():
    out = pnl._campaign_breakdown([_row(COMMERCIAL, None, 20.0)], Decimal("0"), {})
    assert out[0]["spend"] is None and out[0]["gross_profit"] is None and out[0]["data_incomplete"] is True
