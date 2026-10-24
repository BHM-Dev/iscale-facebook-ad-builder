"""P&L: revenue whose sub3 does not tie to a Meta ad set / campaign is third-party network traffic.

Steve, 2026-10-24: ignore anything that does not tie to the Meta campaigns. It must be reported
(`network_revenue`) but never added to revenue, profit, or the base for Abel's % of net profit.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import pnl
from app.models import FacebookAdSet, FacebookCampaign

OFFER = "Get Business Coverage"
ACCOUNT = "act_111"


class _FakeEverflow:
    rows = []

    def is_configured(self):
        return True

    def get_raw_conversions(self, start, end):
        return list(self.rows)

    @staticmethod
    def _offer_name(row):
        return row.get("offer", "")


def _db():
    engine = create_engine("sqlite://")
    FacebookAdSet.__table__.create(engine)
    FacebookCampaign.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    db.add(FacebookAdSet(id="a1", name="known adset", optimization_goal="LEAD_GENERATION", fb_adset_id="120000000000000001", fb_account_id=ACCOUNT, campaign_id="c-local"))
    db.add(FacebookCampaign(id="c1", name="scoped camp", objective="OUTCOME_LEADS", budget_type="ABO", fb_campaign_id="120000000000000777", fb_account_id=ACCOUNT))
    db.add(FacebookCampaign(id="c2", name="other camp", objective="OUTCOME_LEADS", budget_type="ABO", fb_campaign_id="120000000000000888", fb_account_id="act_999"))
    db.commit()
    return db


def test_non_meta_sub3_is_network_not_unknown(monkeypatch):
    monkeypatch.setattr(pnl, "EverflowService", _FakeEverflow)
    monkeypatch.setattr(pnl, "_everflow_account_ids", lambda: {ACCOUNT})
    monkeypatch.setattr(pnl, "_everflow_offer_names_for_account", lambda a: {OFFER})
    _FakeEverflow.rows = [
        {"offer": OFFER, "revenue": "100.00", "sub3": "120000000000000001"},   # known ad set -> per-account row, not here
        {"offer": OFFER, "revenue": "40.25", "sub3": "120000000000000777"},    # scoped campaign id -> ties to our Meta campaign -> counted
        {"offer": OFFER, "revenue": "33.10", "sub3": "{{adset.id}}"},          # literal macro -> third-party network traffic
        {"offer": OFFER, "revenue": "21.90", "sub3": ""},                      # blank -> network
        {"offer": OFFER, "revenue": "5.00", "sub3": "120000000000000888"},     # campaign of an out-of-scope account -> foreign
        {"offer": "Some Other Offer", "revenue": "999.00", "sub3": ""},        # not one of our offers -> ignored entirely
    ]
    unknown, ok, foreign, network = pnl._everflow_unknown_revenue(_db(), [ACCOUNT], date(2026, 10, 1), date(2026, 10, 31))
    assert ok is True
    assert unknown == Decimal("40.25")   # only revenue that ties to a scoped Meta campaign
    assert network == Decimal("55.00")   # 33.10 + 21.90, excluded from profit
    assert foreign == Decimal("5.00")


def test_network_revenue_is_reported_but_not_added_to_profit(monkeypatch):
    monkeypatch.setattr(pnl, "_resolve_aggregate_costs", lambda db, ids, s, e, spend, revenue: ([], Decimal("0")))
    rows = [{"ad_account_id": ACCOUNT, "spend": 100.0, "revenue": 150.0, "conversions": 3}]
    out = pnl._all_summary_from_account_rows(
        None, [ACCOUNT], date(2026, 10, 1), date(2026, 10, 31), "Oct", rows,
        unknown_revenue=Decimal("40.25"), unknown_ok=True, foreign_revenue=Decimal("5"), network_revenue=Decimal("55"),
    )
    assert out["revenue"] == 190.25          # 150 attributed + 40.25 campaign-tied; the $55 network is NOT in here
    assert out["network_revenue"] == 55.0    # but it is visible
    assert out["gross_profit"] == 90.25
