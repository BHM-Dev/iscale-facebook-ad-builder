"""P&L revenue from BHM's own Everflow (network realm) for Splitero / LoanDepot.

Steve, 2026-10-29: internal Meta traffic = affiliates 232 and 125; LoanDepot = offer 4566, Splitero = offer 4626.
LoanDepot already carries outside affiliates' conversions, so revenue must be filtered by affiliate, never offer-wide.
"""
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import pnl
from app.models import FacebookAd, FacebookAdSet, FacebookCampaign
from app.services import bhm_everflow_service as svc_mod
from app.services.bhm_everflow_service import BhmEverflowService

SPLITERO = "act_994325837966073"
LOANDEPOT = "act_375215180951288"


def _row(cid, affiliate, revenue, sub3="", offer="LoanDepot Form O&O (RefiGuide)", ts=1793000000):
    # Shape of a real /networks/reporting/conversions row (verified 2026-10-29).
    return {
        "conversion_id": cid, "revenue": revenue, "payout": 0, "sub3": sub3, "event": "Lead Accept",
        "conversion_unix_timestamp": ts,
        "relationship": {"offer": {"name": offer}, "affiliate": {"network_affiliate_id": affiliate}},
    }


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cache():
    svc_mod._cache.clear()
    yield
    svc_mod._cache.clear()


def test_network_service_pages_and_keeps_only_internal_affiliates(monkeypatch):
    monkeypatch.setenv("BHM_EVERFLOW_API_KEY", "test")
    monkeypatch.setattr(svc_mod, "PAGE_SIZE", 2)
    pages = {
        1: [_row("a", 232, 10), _row("b", 985, 99)],        # 985 = outside affiliate -> dropped
        2: [_row("c", 125, 5), _row("d", 814, 77)],
        3: [_row("e", 232, 1)],
    }
    calls = []

    def fake_post(url, params, headers, json, timeout):
        calls.append((params["page"], json["query"]["filters"]))
        return _Resp({"conversions": pages[params["page"]], "paging": {"total_count": 5}})

    monkeypatch.setattr(httpx, "post", fake_post)
    rows = BhmEverflowService().get_internal_conversions(date(2026, 10, 1), date(2026, 10, 31), {"4566"}, {"232", "125"})
    assert sorted(r["conversion_id"] for r in rows) == ["a", "c", "e"]
    assert [p for p, _ in calls] == [1, 2, 3]                      # walked every page
    assert calls[0][1] == [{"resource_type": "offer", "filter_id_value": "4566"}]


def test_network_service_raises_on_short_page_set(monkeypatch):
    monkeypatch.setenv("BHM_EVERFLOW_API_KEY", "test")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp({"conversions": [], "paging": {"total_count": 3}}))
    try:
        BhmEverflowService().get_internal_conversions(date(2026, 10, 1), date(2026, 10, 2), {"4566"}, {"232"})
    except RuntimeError as exc:
        assert "0 of 3" in str(exc)
    else:
        raise AssertionError("a short page set must raise, never report a low number")


def _db():
    engine = create_engine("sqlite://")
    for model in (FacebookAdSet, FacebookCampaign, FacebookAd):
        model.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    db.add(FacebookAdSet(id="ld1", name="LD set", optimization_goal="LEAD_GENERATION", fb_adset_id="120000000000004566", fb_account_id=LOANDEPOT, campaign_id="c"))
    db.commit()
    return db


def test_provider_and_per_account_revenue_use_ad_set_attribution(monkeypatch):
    monkeypatch.delenv("BHM_EVERFLOW_ACCOUNT_OFFERS", raising=False)
    monkeypatch.setattr(pnl, "_everflow_account_ids", lambda: set())
    assert pnl._revenue_provider_for_account(LOANDEPOT) == "bhm_everflow"
    assert pnl._revenue_provider_for_account(SPLITERO) == "bhm_everflow"
    assert pnl._revenue_provider_for_account("act_521142087204815") == "none"   # not in the BHM map

    seen = {}

    def fake_rows(self, start, end, offers, affiliates):
        seen["offers"], seen["affiliates"] = offers, affiliates
        return [_row("x", 232, "40.00", sub3="120000000000004566"), _row("y", 125, "7.00", sub3="")]

    monkeypatch.setattr(BhmEverflowService, "get_internal_conversions", fake_rows)
    revenue, events, _, source, incomplete, _, _ = pnl._revenue_for_account(_db(), LOANDEPOT, date(2026, 11, 1), date(2026, 11, 30))
    assert seen == {"offers": {"4566"}, "affiliates": {"232", "125"}}
    assert (revenue, events, source, incomplete) == (Decimal("40.00"), 1, "bhm_everflow_live", False)
    # the blank-sub3 $7 is not on an ad set, so it is all-accounts only:
    unplaced, ok = pnl._bhm_everflow_unplaced_revenue(_db(), [LOANDEPOT], date(2026, 11, 1), date(2026, 11, 30))
    assert (unplaced, ok) == (Decimal("7.00"), True)


def test_failure_marks_the_period_incomplete_not_zero(monkeypatch):
    monkeypatch.setattr(pnl, "_everflow_account_ids", lambda: set())

    def boom(*a, **k):
        raise RuntimeError("Everflow down")

    monkeypatch.setattr(BhmEverflowService, "get_internal_conversions", boom)
    result = pnl._revenue_for_account(_db(), SPLITERO, date(2026, 11, 1), date(2026, 11, 30))
    assert result[3] == "bhm_everflow_unavailable" and result[4] is True
    assert pnl._bhm_everflow_unplaced_revenue(_db(), [SPLITERO], date(2026, 11, 1), date(2026, 11, 30)) == (Decimal("0"), False)
    assert pnl._snapshot_provider("bhm_everflow_live") == "bhm_everflow"


def test_rate_limit_is_retried_and_rows_are_cached(monkeypatch):
    monkeypatch.setenv("BHM_EVERFLOW_API_KEY", "test")
    monkeypatch.setattr(svc_mod.time, "sleep", lambda s: None)
    replies = [_Resp({}, 429), _Resp({"conversions": [_row("a", 232, 3)], "paging": {"total_count": 1}})]
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or replies.pop(0))
    service = BhmEverflowService()
    assert len(service.get_internal_conversions(date(2026, 11, 1), date(2026, 11, 2), {"4626"}, {"232"})) == 1
    assert len(service.get_internal_conversions(date(2026, 11, 1), date(2026, 11, 2), {"4626"}, {"232"})) == 1
    assert len(calls) == 2          # one 429, one success, then served from the cache


def test_rows_without_affiliate_ids_raise_instead_of_reading_zero(monkeypatch):
    monkeypatch.setenv("BHM_EVERFLOW_API_KEY", "test")
    bare = {"conversion_id": "a", "revenue": 5, "sub3": ""}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp({"conversions": [bare], "paging": {"total_count": 1}}))
    with pytest.raises(RuntimeError, match="no affiliate id"):
        BhmEverflowService().get_internal_conversions(date(2026, 11, 1), date(2026, 11, 2), {"4626"}, {"232"})


def test_unplaced_revenue_skips_meta_ids_outside_scope(monkeypatch):
    monkeypatch.setattr(pnl, "_everflow_account_ids", lambda: set())
    monkeypatch.setattr(BhmEverflowService, "get_internal_conversions", lambda self, *a: [
        _row("1", 232, "9.00", sub3="120000000000009999"),   # someone else's Meta ad set -> not added
        _row("2", 232, "4.00", sub3="{{adset.id}}"),          # ours, unrecoverable -> added
    ])
    monkeypatch.setattr(pnl, "_recover_macro_adsets", lambda db, rows: rows)
    assert pnl._bhm_everflow_unplaced_revenue(_db(), [LOANDEPOT], date(2026, 11, 1), date(2026, 11, 30)) == (Decimal("4.00"), True)


def test_bad_offer_map_env_disables_quietly(monkeypatch):
    monkeypatch.setenv("BHM_EVERFLOW_ACCOUNT_OFFERS", "[]")
    assert pnl._bhm_everflow_offer_map() == {}
    monkeypatch.setattr(pnl, "_everflow_account_ids", lambda: set())
    assert pnl._revenue_provider_for_account(LOANDEPOT) == "none"
