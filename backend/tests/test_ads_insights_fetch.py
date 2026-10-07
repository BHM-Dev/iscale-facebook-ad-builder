import pytest
from facebook_business.exceptions import FacebookRequestError

from app.services.facebook_service import FacebookService


class FakeAccount:
    def __init__(self, rows, fail_limits=()):
        self.rows, self.fail_limits, self.calls = rows, set(fail_limits), []

    def get_insights(self, fields, params):
        self.calls.append(params['limit'])
        if params['limit'] in self.fail_limits:
            raise FacebookRequestError(
                "Please reduce the amount of data you're asking for", {}, 400, {},
                '{"error":{"code":1,"message":"Please reduce the amount of data you\'re asking for"}}',
            )
        return iter(self.rows)


def make_service(account):
    svc = object.__new__(FacebookService)
    svc._get_account = lambda _id=None: account
    return svc


ROW = {'adset_id': '1', 'ad_id': '10', 'ad_name': 'a', 'spend': '5', 'impressions': '100', 'clicks': '2', 'ctr': '2'}


def test_fetches_all_rows_with_large_pages():
    acct = FakeAccount([ROW])
    out = make_service(acct).get_account_ads_insights_bulk(ad_account_id='act_1', date_preset='last_7d')
    assert acct.calls == [500]
    assert out['1'][0]['ad_id'] == '10'


def test_retries_smaller_pages_when_meta_says_too_much_data():
    acct = FakeAccount([ROW], fail_limits=(500,))
    out = make_service(acct).get_account_ads_insights_bulk(ad_account_id='act_1', date_preset='last_7d')
    assert acct.calls == [500, 100]
    assert '1' in out


def test_ad_statuses_are_read_unfiltered_so_derived_states_are_included():
    class StatusAccount:
        def __init__(self):
            self.params = None
        def get_ads(self, fields, params):
            self.params = params
            return [
                {'id': '1', 'status': 'ACTIVE', 'effective_status': 'ADSET_PAUSED'},
                {'id': '2', 'status': 'PAUSED', 'effective_status': 'PAUSED'},
            ]
    acct = StatusAccount()
    out = make_service(acct).get_account_ad_statuses(ad_account_id='act_1')
    assert 'effective_status' not in acct.params  # a filter silently drops ADSET_PAUSED/CAMPAIGN_PAUSED ads
    assert out['1'] == {'status': 'ACTIVE', 'effective_status': 'ADSET_PAUSED'}
