from datetime import date

from app.services import max_cpl_service as service
from app.services import proposal_service
from app.services.proposal_service import RevenueUnavailable


def _rows(*rows):
    return lambda account_id, since, until: list(rows)


def _setup(monkeypatch, rows, revenue):
    import app.services.daily_close_service as dc
    monkeypatch.setattr(dc, "closed_day", lambda: date(2026, 11, 4))
    monkeypatch.setattr(service, "_pull_rows", rows)
    monkeypatch.setattr(service.proposal_service, "revenue_by_adset_day", revenue)
    service._CACHE.clear()


def test_count_leads_does_not_double_count_pixel_variant():
    # Real RHO shape (2026-11-04): Meta returns `lead` AND `offsite_conversion.fb_pixel_lead` with the same value.
    assert proposal_service.count_leads([{"action_type": "lead", "value": "7"},
                                         {"action_type": "offsite_conversion.fb_pixel_lead", "value": "7"},
                                         {"action_type": "link_click", "value": "90"}]) == 7
    assert proposal_service.count_leads([{"action_type": "offsite_conversion.fb_pixel_lead", "value": "3"}]) == 3
    assert proposal_service.count_leads(None) == 0


def test_max_cpl_math_window_and_small_sample(monkeypatch):
    seen = {}
    def rows(account_id, since, until):
        seen.update(since=since, until=until)
        return [{"adset_id": "big", "adset_name": "Big", "campaign_name": "Painting", "spend": "500",
                 "actions": [{"action_type": "lead", "value": "50"}, {"action_type": "offsite_conversion.fb_pixel_lead", "value": "50"}]},
                {"adset_id": "small", "adset_name": "Small", "campaign_name": "Florists", "spend": "100",
                 "actions": [{"action_type": "lead", "value": "10"}]}]
    _setup(monkeypatch, rows, lambda *a: {"big": {"2026-10-06": 1000}, "small": {"2026-10-06": 100}})
    result = service.compute_max_cpl(object(), "act_1")
    assert seen == {"since": date(2026, 10, 6), "until": date(2026, 11, 4)}   # 30 complete days, ending yesterday PT
    assert result["niches"]["Painting Contractors"]["rpl"] == 20               # 1000 / 50, not / 100
    assert result["adsets"]["big"]["max_cpl"] == 15.38
    assert result["adsets"]["small"]["source"] == "acct_avg"
    assert result["adsets"]["small"]["rpl"] == round(1100 / 60, 2)


def test_zero_revenue_niche_never_shows_zero_max_cpl(monkeypatch):
    rows = _rows({"adset_id": "a", "campaign_name": "Painting", "spend": "500", "actions": [{"action_type": "lead", "value": "50"}]},
                 {"adset_id": "b", "campaign_name": "Towing", "spend": "500", "actions": [{"action_type": "lead", "value": "50"}]})
    _setup(monkeypatch, rows, lambda *a: {"a": {"d": 1000}})
    result = service.compute_max_cpl(object(), "act_1")
    assert result["adsets"]["b"]["source"] == "acct_avg" and result["adsets"]["b"]["max_cpl"] > 0


def test_revenue_unavailable_is_not_zero_and_is_cached_briefly(monkeypatch):
    calls = []
    def unavailable(*args):
        calls.append(1)
        raise RevenueUnavailable("Everflow down")
    _setup(monkeypatch, _rows(), unavailable)
    first = service.compute_max_cpl(object(), "act_2")
    second = service.compute_max_cpl(object(), "act_2")
    assert first == {"available": False, "account_id": "act_2", "reason": "Everflow down"} and second == first
    assert len(calls) == 1


def test_unexpected_error_is_generic(monkeypatch):
    def boom(*a):
        raise RuntimeError("secret token in url")
    _setup(monkeypatch, boom, lambda *a: {})
    result = service.compute_max_cpl(object(), "act_3")
    assert result["available"] is False and "secret" not in result["reason"]
