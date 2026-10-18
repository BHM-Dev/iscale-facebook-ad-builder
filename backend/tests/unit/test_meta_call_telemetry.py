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


def _reset_alert_state():
    t._throttled_until = 0.0
    t._last_alert.update(throttle=0.0, usage=0.0)


def test_throttle_starts_backoff_and_alerts_once(monkeypatch):
    _reset_alert_state()
    sent = []
    monkeypatch.setattr(t, '_alert_async', lambda kind, cd, summary, detail: sent.append((kind, summary)))
    assert t.backoff_remaining() == 0
    t._record('GET', '/v24.0/act_1234567/insights', 'api/v1/x.py:f', 5, None, 4, True)
    assert 0 < t.backoff_remaining() <= t.THROTTLE_BACKOFF_SECONDS
    assert sent and sent[0][0] == 'throttle'
    _reset_alert_state()


def test_non_throttle_error_does_not_back_off(monkeypatch):
    _reset_alert_state()
    monkeypatch.setattr(t, '_alert_async', lambda *a: None)
    t._record('GET', '/v24.0/me', 'c', 5, None, 100, True)
    assert t.backoff_remaining() == 0


def test_high_usage_alerts_without_backoff(monkeypatch):
    _reset_alert_state()
    sent = []
    monkeypatch.setattr(t, '_alert_async', lambda kind, cd, summary, detail: sent.append(kind))
    headers = {'x-app-usage': json.dumps({'call_count': 85, 'total_cputime': 10, 'total_time': 10})}
    t._record('GET', '/v24.0/me', 'c', 5, headers, None, False)
    assert sent == ['usage'] and t.backoff_remaining() == 0
    t._record('GET', '/v24.0/me', 'c', 5, {'x-app-usage': json.dumps({'call_count': 20})}, None, False)
    assert sent == ['usage']  # below threshold: no second alert


def test_alert_cooldown_dedupes(monkeypatch):
    _reset_alert_state()
    calls = []
    import threading as _th

    class Immediate:
        def __init__(self, target, **kw): self.target = target
        def start(self): self.target()

    monkeypatch.setattr(t.threading, 'Thread', Immediate)
    monkeypatch.setattr('app.services.slack_service.send_meta_limit_alert', lambda s, d='': calls.append(s) or True)
    t._alert_async('throttle', 1800, 'one', 'd')
    t._alert_async('throttle', 1800, 'two', 'd')
    assert calls == ['one']
    _reset_alert_state()


def test_account_scoped_throttle_counts_but_does_not_gate_app(monkeypatch):
    _reset_alert_state()
    monkeypatch.setattr(t, '_alert_async', lambda *a: None)
    t._record('GET', '/v24.0/act_1234567/insights', 'c', 5, None, 80004, True)
    assert t.backoff_remaining() == 0
    assert sum(b['throttles'] for b in t._buckets.values()) == 1


def test_subcode_1504022_gates_app_and_window_is_not_extended(monkeypatch):
    _reset_alert_state()
    monkeypatch.setattr(t, '_alert_async', lambda *a: None)
    t._record('GET', '/v24.0/me', 'c', 5, None, 4, True, 1504022)
    first = t._throttled_until
    assert first > 0
    t._record('GET', '/v24.0/me', 'c', 5, None, 4, True, 1504022)
    assert t._throttled_until == first  # retries into a throttle must not extend the window
    _reset_alert_state()
