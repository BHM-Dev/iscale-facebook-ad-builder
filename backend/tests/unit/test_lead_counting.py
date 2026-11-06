"""Leads must be counted once. Meta returns `lead` (the aggregate) AND `offsite_conversion.fb_pixel_lead`
with the same value; RHO 2026-11-04: 51 of 71 ad sets, summed 334 vs real 167."""
from app.services import facebook_service as fs_mod
from app.services.facebook_service import FacebookService
from app.services.meta_actions import count_leads
from app.services import proposal_service

DOUBLE = [
    {'action_type': 'lead', 'value': '167'},
    {'action_type': 'offsite_conversion.fb_pixel_lead', 'value': '167'},
    {'action_type': 'link_click', 'value': '900'},
]
CPA = [
    {'action_type': 'lead', 'value': '12.00'},
    {'action_type': 'offsite_conversion.fb_pixel_lead', 'value': '12.00'},
]


class FakeAccount:
    def __init__(self, rows):
        self.rows = rows

    def get_insights(self, fields, params):
        return iter(self.rows)


def make_service(rows):
    svc = object.__new__(FacebookService)
    acct = FakeAccount(rows)
    svc._get_account = lambda _id=None: acct
    svc._get_state_insights_account = lambda _id=None: (acct, None)
    return svc


def test_count_leads_prefers_lead_aggregate():
    assert count_leads(DOUBLE) == 167
    assert count_leads([{'action_type': 'offsite_conversion.fb_pixel_lead', 'value': '4'},
                        {'action_type': 'onsite_conversion.lead_grouped', 'value': '3'}]) == 4
    assert count_leads(None) == 0 and count_leads([]) == 0
    # zero-ness must match the old sum: auto-pause's zero-lead kill keys on leads == 0
    assert count_leads([{'action_type': 'lead', 'value': '0'},
                        {'action_type': 'offsite_conversion.fb_pixel_lead', 'value': '5'}]) == 5


def test_proposal_service_reexport_is_the_same_helper():
    assert proposal_service.count_leads is count_leads


def test_account_daily_insights_counts_once():
    svc = make_service([{'date_start': '2026-11-04', 'spend': '2004', 'actions': DOUBLE}])
    [day] = svc.get_account_daily_insights('act_1', '2026-11-04', '2026-11-04')
    assert day['leads'] == 167
    assert day['cpl'] == 12.0


def test_bulk_adset_insights_counts_once_and_keeps_meta_cpl():
    row = {'adset_id': '1', 'adset_name': 'a', 'spend': '2004', 'actions': DOUBLE, 'cost_per_action_type': CPA}
    out = make_service([row])._fetch_account_insights_bulk('act_1', 'last_7d', None, None)
    assert out['1']['leads'] == 167
    assert out['1']['cpl'] == 12.0


def test_bulk_adset_cpl_fallback_unchanged_pending_signoff():
    # Auto-pause reads this cpl. With no cost_per_action_type, the fallback intentionally still divides
    # by the legacy summed count (334) until Steve/buyers sign off on the trigger change.
    row = {'adset_id': '1', 'adset_name': 'a', 'spend': '2004', 'actions': DOUBLE}
    out = make_service([row])._fetch_account_insights_bulk('act_1', 'last_7d', None, None)
    assert out['1']['leads'] == 167
    assert out['1']['cpl'] == 6.0


def test_ads_bulk_counts_once():
    row = {'adset_id': '1', 'ad_id': '10', 'ad_name': 'x', 'spend': '2004', 'impressions': '1',
           'clicks': '1', 'ctr': '1', 'actions': DOUBLE, 'cost_per_action_type': CPA}
    out = make_service([row]).get_account_ads_insights_bulk(ad_account_id='act_1', date_preset='last_7d')
    assert out['1'][0]['leads'] == 167


def test_adset_insights_counts_once(monkeypatch):
    class FakeAdSet:
        def __init__(self, fbid):
            pass

        def get_insights(self, fields=None, params=None):
            return [{'spend': '2004', 'actions': DOUBLE, 'cost_per_action_type': CPA}]

    monkeypatch.setattr(fs_mod, 'AdSet', FakeAdSet)
    svc = object.__new__(FacebookService)
    out = svc.get_adset_insights('1')
    assert out['leads'] == 167
    assert out['cpl'] == 12.0


def test_state_insights_counts_once():
    row = {'campaign_id': 'c', 'campaign_name': 'C', 'region': 'Texas', 'spend': '2004',
           'impressions': '1', 'reach': '1', 'clicks': '1', 'actions': DOUBLE}
    rows = make_service([row]).get_account_campaign_state_insights('act_1', date_from='2026-11-04',
                                                                    date_to='2026-11-04')
    flat = rows if isinstance(rows, list) else [rows]
    text = repr(flat)
    assert "'leads': 167" in text and "'leads': 334" not in text


def test_intelligence_meta_insights_counts_once(monkeypatch):
    from app.api.v1 import intelligence

    class FakeSvc:
        def initialize(self):
            pass

        def _get_account(self, _id=None):
            return FakeAccount([{'adset_id': '1', 'adset_name': 'a', 'campaign_name': 'c',
                                 'spend': '2004', 'impressions': '1', 'actions': DOUBLE}])

    monkeypatch.setattr(fs_mod, 'FacebookService', FakeSvc)
    out = intelligence._fetch_meta_insights('act_1', '2026-11-04', '2026-11-04', 'all')
    assert out['1']['leads'] == 167
    assert out['1']['cpl'] == 12.0
