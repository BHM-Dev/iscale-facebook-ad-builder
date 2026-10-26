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
OUTSIDE_OFFER = "Fast Auto Quote.org"
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

    @staticmethod
    def _conversion_date(row):
        from app.services.everflow_service import EverflowService as _Real
        return _Real._conversion_date(row)


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
    monkeypatch.setattr(pnl, "_everflow_offer_names_for_account", lambda a: {OFFER, OUTSIDE_OFFER, "Fast Business Quote"})
    _FakeEverflow.rows = [
        {"offer": OFFER, "revenue": "100.00", "sub3": "120000000000000001"},   # known ad set -> per-account row, not here
        {"offer": OFFER, "revenue": "40.25", "sub3": "120000000000000777"},    # scoped campaign id -> ties to our Meta campaign -> counted
        {"offer": OFFER, "revenue": "33.10", "sub3": "{{adset.id}}"},          # literal macro -> our own Meta click, macro unexpanded -> counted
        {"offer": OUTSIDE_OFFER, "revenue": "21.90", "sub3": ""},              # blank on an outside-traffic offer -> network
        {"offer": OFFER, "revenue": "12.00", "sub3": ""},                      # blank on an all-internal offer -> counted
        {"offer": "Fast Business Quote", "revenue": "8.00", "sub3": "ThankYouPage"},  # ditto
        {"offer": OFFER, "revenue": "5.00", "sub3": "120000000000000888"},     # campaign of an out-of-scope account -> foreign
        {"offer": "Some Other Offer", "revenue": "999.00", "sub3": ""},        # not one of our offers -> ignored entirely
    ]
    unknown, ok, foreign, network = pnl._everflow_unknown_revenue(_db(), [ACCOUNT], date(2026, 10, 1), date(2026, 10, 31))
    assert ok is True
    assert unknown == Decimal("93.35")   # 40.25 scoped campaign + 33.10 macro + 12.00 + 8.00 on all-internal offers
    assert network == Decimal("21.90")   # no-Meta-id revenue on Fast Auto Quote only, excluded from profit
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


# ---- frozen all-accounts extras (Steve, 2026-10-25: paid months are frozen, no more re-pulling) ----------------
from datetime import date as _date  # noqa: E402

from app.models import PnlMonthSnapshot  # noqa: E402


def _snap_db(*frozen_accounts_for_months):
    """sqlite with the snapshot table; per-account snapshots (the precondition for freezing extras) for the given months."""
    engine = create_engine("sqlite://")
    PnlMonthSnapshot.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    for account, month_start in frozen_accounts_for_months:
        db.add(PnlMonthSnapshot(ad_account_id=account, month=month_start, date_from=month_start, date_to=month_start))
    db.commit()
    return db


def _patch_pull(monkeypatch, results, today=_date(2026, 10, 25)):
    calls = []

    def fake(db, ids, start, end):
        calls.append((start, end))
        return results.pop(0)

    monkeypatch.setattr(pnl, "_everflow_unknown_revenue", fake)
    monkeypatch.setattr(pnl, "today_in_rt_tz", lambda: today)
    return calls


SEP = (_date(2026, 9, 1), _date(2026, 9, 30))
OCT = (_date(2026, 10, 1), _date(2026, 10, 31))
FROZEN_SEP = [(ACCOUNT, SEP[0]), ("act_222", SEP[0])]


def test_closed_month_is_frozen_and_not_pulled_again(monkeypatch):
    db = _snap_db(*FROZEN_SEP)
    calls = _patch_pull(monkeypatch, [(Decimal("40.25"), True, Decimal("5.00"), Decimal("1498.30"))])
    first = pnl._all_extras_for_period(db, [ACCOUNT, "act_222"], *SEP)
    assert first == (Decimal("40.25"), True, Decimal("5.00"), Decimal("1498.30")) and len(calls) == 1
    second = pnl._all_extras_for_period(db, ["act_222", ACCOUNT], *SEP)   # scope order must not matter; results list empty -> a pull would raise
    assert second == first and len(calls) == 1


def test_refetch_overwrites_the_frozen_month(monkeypatch):
    db = _snap_db((ACCOUNT, SEP[0]))
    calls = _patch_pull(monkeypatch, [
        (Decimal("10.00"), True, Decimal("0"), Decimal("100.00")),
        (Decimal("12.00"), True, Decimal("0"), Decimal("150.00")),
    ])
    pnl._all_extras_for_period(db, [ACCOUNT], *SEP)
    refreshed = pnl._all_extras_for_period(db, [ACCOUNT], *SEP, refresh=True)
    assert refreshed[0] == Decimal("12.00") and len(calls) == 2
    assert pnl._all_extras_for_period(db, [ACCOUNT], *SEP)[3] == Decimal("150.00")


def test_current_month_is_never_frozen(monkeypatch):
    db = _snap_db((ACCOUNT, OCT[0]))
    calls = _patch_pull(monkeypatch, [(Decimal("1"), True, Decimal("0"), Decimal("2")), (Decimal("3"), True, Decimal("0"), Decimal("4"))])
    pnl._all_extras_for_period(db, [ACCOUNT], *OCT)
    pnl._all_extras_for_period(db, [ACCOUNT], *OCT)
    assert len(calls) == 2 and db.query(PnlMonthSnapshot).filter(PnlMonthSnapshot.ad_account_id.like("__all%")).count() == 0


def test_not_frozen_until_grace_period_and_account_snapshots_exist(monkeypatch):
    # Sept ended 2 days ago -> inside the 3-day grace window (late conversions / clawbacks still arriving)
    db = _snap_db(*FROZEN_SEP)
    calls = _patch_pull(monkeypatch, [(Decimal("1"), True, Decimal("0"), Decimal("1")), (Decimal("1"), True, Decimal("0"), Decimal("1"))], today=_date(2026, 10, 2))
    pnl._all_extras_for_period(db, [ACCOUNT, "act_222"], *SEP)
    pnl._all_extras_for_period(db, [ACCOUNT, "act_222"], *SEP)
    assert len(calls) == 2 and db.query(PnlMonthSnapshot).filter(PnlMonthSnapshot.ad_account_id.like("__all%")).count() == 0
    # grace over, but one account's own month is not frozen yet -> still live (could lock in a misclassification)
    db2 = _snap_db((ACCOUNT, SEP[0]))
    calls2 = _patch_pull(monkeypatch, [(Decimal("2"), True, Decimal("0"), Decimal("2"))])
    pnl._all_extras_for_period(db2, [ACCOUNT, "act_222"], *SEP)
    assert len(calls2) == 1 and db2.query(PnlMonthSnapshot).filter(PnlMonthSnapshot.ad_account_id.like("__all%")).count() == 0


def test_failed_pull_is_not_frozen_and_partial_ranges_never_are(monkeypatch):
    db = _snap_db((ACCOUNT, SEP[0]))
    calls = _patch_pull(monkeypatch, [
        (Decimal("0"), False, Decimal("0"), Decimal("0")),          # Everflow down
        (Decimal("7"), True, Decimal("0"), Decimal("8")),            # later pull succeeds -> frozen
    ])
    assert pnl._all_extras_for_period(db, [ACCOUNT], *SEP)[1] is False
    assert db.query(PnlMonthSnapshot).filter(PnlMonthSnapshot.ad_account_id.like("__all%")).count() == 0
    pnl._all_extras_for_period(db, [ACCOUNT], *SEP)
    assert db.query(PnlMonthSnapshot).filter(PnlMonthSnapshot.ad_account_id.like("__all%")).count() == 1 and len(calls) == 2
    calls2 = _patch_pull(monkeypatch, [(Decimal("1"), True, Decimal("0"), Decimal("1"))])
    pnl._all_extras_for_period(db, [ACCOUNT], _date(2026, 9, 1), _date(2026, 9, 15))   # not a whole month -> live
    assert len(calls2) == 1 and db.query(PnlMonthSnapshot).filter(PnlMonthSnapshot.ad_account_id.like("__all%")).count() == 1


def test_each_scope_gets_its_own_row_so_users_never_overwrite_each_other(monkeypatch):
    db = _snap_db(*FROZEN_SEP)
    calls = _patch_pull(monkeypatch, [
        (Decimal("1"), True, Decimal("0"), Decimal("2")),   # admin scope (2 accounts)
        (Decimal("5"), True, Decimal("0"), Decimal("6")),   # restricted scope (1 account)
    ])
    admin_first = pnl._all_extras_for_period(db, [ACCOUNT, "act_222"], *SEP)
    restricted = pnl._all_extras_for_period(db, [ACCOUNT], *SEP)
    assert restricted[0] == Decimal("5") and len(calls) == 2
    # both stay frozen independently — neither read triggers another pull, neither value changed
    assert pnl._all_extras_for_period(db, [ACCOUNT, "act_222"], *SEP) == admin_first
    assert pnl._all_extras_for_period(db, [ACCOUNT], *SEP) == restricted and len(calls) == 2


def test_rule_change_ignores_the_snapshot(monkeypatch):
    db = _snap_db((ACCOUNT, SEP[0]))
    calls = _patch_pull(monkeypatch, [(Decimal("1"), True, Decimal("0"), Decimal("2")), (Decimal("9"), True, Decimal("0"), Decimal("9"))])
    pnl._all_extras_for_period(db, [ACCOUNT], *SEP)
    snap = db.query(PnlMonthSnapshot).filter(PnlMonthSnapshot.ad_account_id.like("__all%")).one()
    snap.event_breakdown = {**snap.event_breakdown, "rule": "an-older-rule"}
    db.commit()
    assert pnl._all_extras_for_period(db, [ACCOUNT], *SEP)[0] == Decimal("9") and len(calls) == 2


def test_extras_row_never_matches_a_real_account_snapshot(monkeypatch):
    db = _snap_db((ACCOUNT, SEP[0]))
    _patch_pull(monkeypatch, [(Decimal("1"), True, Decimal("0"), Decimal("2"))])
    pnl._all_extras_for_period(db, [ACCOUNT], *SEP)
    stored = db.query(PnlMonthSnapshot).filter(PnlMonthSnapshot.ad_account_id == ACCOUNT, PnlMonthSnapshot.month == SEP[0]).one()
    assert stored.revenue_source is None   # the real account row is untouched by the extras write


# ---- ad-set recovery for unexpanded {{adset.id}} (via the RedTrack click's ad id) -------------------------------
from app.models import FacebookAd
from app.services.everflow_service import EverflowService


def _db_with_ad():
    db = _db()
    FacebookAd.__table__.create(db.get_bind())
    db.add(FacebookAd(id="ad1", adset_id="a1", name="Our ad", fb_ad_id="120000000000009001"))
    db.commit()
    return db


def _macro_row(click, revenue="30.00"):
    return {"offer": OFFER, "revenue": revenue, "sub3": "{{adset.id}}", "sub5": click, "conversion_unix_timestamp": 1792000000}


def test_macro_row_recovers_its_adset_from_the_redtrack_ad_id(monkeypatch):
    monkeypatch.setattr(pnl, "_redtrack_ad_ids_by_click", lambda s, e: {"click-ok": "120000000000009001", "click-unknown-ad": "120000000000009999"})
    rows = [_macro_row("click-ok"), _macro_row("click-unknown-ad", "7.00"), _macro_row("click-not-in-rt", "3.00"), {"offer": OFFER, "revenue": "5", "sub3": "", "sub5": "x"}]
    out = pnl._recover_macro_adsets(_db_with_ad(), rows)
    assert [r["sub3"] for r in out] == ["120000000000000001", "{{adset.id}}", "{{adset.id}}", ""]
    assert rows[0]["sub3"] == "{{adset.id}}"   # input rows are not mutated
    # the recovered conversion now lands in that ad set's per-account revenue ...
    report = EverflowService()._aggregate_rows(out, offer_names={OFFER})
    assert report["adsets"]["120000000000000001"]["revenue"] == Decimal("30.00")


def test_recovered_revenue_is_not_double_counted_in_the_all_accounts_extras(monkeypatch):
    monkeypatch.setattr(pnl, "EverflowService", _FakeEverflow)
    monkeypatch.setattr(pnl, "_everflow_account_ids", lambda: {ACCOUNT})
    monkeypatch.setattr(pnl, "_everflow_offer_names_for_account", lambda a: {OFFER, OUTSIDE_OFFER, "Fast Business Quote"})
    monkeypatch.setattr(pnl, "_redtrack_ad_ids_by_click", lambda s, e: {"click-ok": "120000000000009001"})
    _FakeEverflow.rows = [_macro_row("click-ok", "30.00"), _macro_row("click-lost", "7.00")]
    unknown, ok, foreign, network = pnl._everflow_unknown_revenue(_db_with_ad(), [ACCOUNT], date(2026, 10, 1), date(2026, 10, 31))
    assert unknown == Decimal("7.00")   # only the one that could not be placed; the other is in the per-account row


def test_redtrack_failure_leaves_rows_counted_as_before(monkeypatch):
    def boom(s, e):
        raise RuntimeError("RedTrack down")
    monkeypatch.setattr(pnl, "_redtrack_ad_ids_by_click", boom)
    rows = [_macro_row("click-ok")]
    assert pnl._recover_macro_adsets(_db_with_ad(), rows) == rows


def test_meta_fallback_resolves_ads_missing_locally_and_only_for_known_adsets(monkeypatch):
    monkeypatch.setattr(pnl, "_redtrack_ad_ids_by_click", lambda s, e: {"c1": "120000000000008001", "c2": "120000000000008002"})
    monkeypatch.setattr(pnl, "_meta_adsets_for_ads", lambda ids: {"120000000000008001": "120000000000000001", "120000000000008002": "120000000000000555"})
    out = pnl._recover_macro_adsets(_db_with_ad(), [_macro_row("c1"), _macro_row("c2")])
    # the first ad set exists locally -> recovered; the second is unknown locally -> left as-is (still counted, all-accounts only)
    assert [r["sub3"] for r in out] == ["120000000000000001", "{{adset.id}}"]
