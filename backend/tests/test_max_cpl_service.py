from datetime import date

from app.services import max_cpl_service as service


def test_max_cpl_math_and_small_sample(monkeypatch):
    class Account:
        def get_insights(self, **kwargs):
            return [
                {"adset_id": "big", "adset_name": "Big", "campaign_name": "Painting", "spend": "500", "actions": [{"action_type": "lead", "value": "50"}]},
                {"adset_id": "small", "adset_name": "Small", "campaign_name": "Florists", "spend": "100", "actions": [{"action_type": "lead", "value": "10"}]},
            ]
    monkeypatch.setattr(service.FacebookService, "initialize", lambda self: None)
    monkeypatch.setattr(service.FacebookService, "_get_account", lambda self, account_id: Account())
    monkeypatch.setattr(service.proposal_service, "account_today", lambda account: date(2026, 11, 5))
    monkeypatch.setattr(service.proposal_service, "revenue_by_adset_day", lambda *args: {"big": {"2026-10-06": 1000}, "small": {"2026-10-06": 100}})
    service._CACHE.clear()
    result = service.compute_max_cpl(object(), "act_1")
    assert result["niches"]["Painting Contractors"]["rpl"] == 20
    assert result["adsets"]["big"]["source"] == "niche"
    assert result["adsets"]["small"]["source"] == "acct_avg"


def test_revenue_unavailable_is_not_zero(monkeypatch):
    class Account:
        def get_insights(self, **kwargs):
            return []
    monkeypatch.setattr(service.FacebookService, "initialize", lambda self: None)
    monkeypatch.setattr(service.FacebookService, "_get_account", lambda self, account_id: Account())
    monkeypatch.setattr(service.proposal_service, "account_today", lambda account: date(2026, 11, 5))
    def unavailable(*args):
        from app.services.proposal_service import RevenueUnavailable
        raise RevenueUnavailable("Everflow down")
    monkeypatch.setattr(service.proposal_service, "revenue_by_adset_day", unavailable)
    service._CACHE.clear()
    try:
        service.compute_max_cpl(object(), "act_2")
    except Exception as exc:
        assert str(exc) == "Everflow down"
    else:
        raise AssertionError("RevenueUnavailable should reach the API boundary")
