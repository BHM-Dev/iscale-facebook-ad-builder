import json
from unittest.mock import patch

from app.services import meta_call_telemetry as t


def setup_function():
    t._buckets.clear()


def test_normalize_endpoint():
    assert t.normalize_endpoint('https://graph.facebook.com/v24.0/act_521142087204815/adsets') == 'act/adsets'
    assert t.normalize_endpoint(('act_521142087204815', 'insights')) == 'act/insights'
    assert t.normalize_endpoint('/v24.0/120252182064980048') == '{id}'
    assert t.normalize_endpoint('/v24.0/me/adaccounts?fields=id') == 'me/adaccounts'


def test_pct_max_reads_all_headers():
    headers = {
        'x-app-usage': json.dumps({'call_count': 12, 'total_cputime': 40, 'total_time': 7}),
        'x-business-use-case-usage': json.dumps({'521': [{'call_count': 3, 'total_cputime': 9, 'total_time': 2}]}),
    }
    assert t._pct_max(headers) == (40, 9)
    assert t._pct_max(None) == (None, None)
    assert t._pct_max({'x-app-usage': 'not json'}) == (None, None)


def test_record_counts_calls_errors_and_throttles():
    t._record('GET', '/v24.0/act_1234567/insights', 'api/v1/x.py:f', 100, None, None, False)
    t._record('GET', '/v24.0/act_1234567/insights', 'api/v1/x.py:f', 50, None, 4, True)
    t._record('GET', '/v24.0/act_1234567/insights', 'api/v1/x.py:f', 50, None, 100, True)
    (b,) = t._buckets.values()
    assert (b['calls'], b['errors'], b['throttles'], b['total_ms']) == (3, 2, 1, 200)


def test_wrapper_never_breaks_the_call_and_reraises():
    class Boom(Exception):
        pass

    class Api:
        def call(self, method, path, *a, **k):
            raise Boom('x')

    wrapped = t._wrap(Api.call)
    try:
        wrapped(Api(), 'GET', '/v24.0/me')
    except Boom:
        pass
    else:
        raise AssertionError('exception must propagate')
    assert sum(b['errors'] for b in t._buckets.values()) == 1

    class Ok:
        def call(self, method, path, *a, **k):
            return 'resp'

    assert t._wrap(Ok.call)(Ok(), 'GET', '/v24.0/me') == 'resp'


def test_record_failure_is_swallowed():
    with patch.object(t, 'normalize_endpoint', side_effect=RuntimeError('bad')):
        t._record('GET', '/x', 'c', 1, None, None, False)  # must not raise


def test_pct_max_flat_ad_account_usage():
    assert t._pct_max({'x-ad-account-usage': json.dumps({'acc_id_util_pct': 9})}) == (None, 9)
