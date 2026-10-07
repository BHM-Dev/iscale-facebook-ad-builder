import pytest
from fastapi import HTTPException

from app.api.v1.auto_pause import _validate_rule_numbers


def test_sane_rules_pass():
    _validate_rule_numbers('cpl', 50, 20, 'pause')
    _validate_rule_numbers('roas', 1, 20, 'pause')
    _validate_rule_numbers('ctr', 1, 0, 'notify')


@pytest.mark.parametrize("metric,threshold,min_spend,action", [
    ('cpl', 0, 20, 'pause'),        # cleared threshold field -> 0 fires on any spend
    ('cpl', -5, 20, 'pause'),
    ('roas', 50, 20, 'pause'),      # stale default: ROAS < 50x pauses everything
    ('ctr', 500, 20, 'pause'),
    ('cpl', 50, 0, 'pause'),        # pause with no spend floor
    ('cpl', 50, -1, 'notify'),
    ('cpl', 20000, 20, 'pause'),
    ('cpl', 10, 0, 'increase_budget'),   # scale up on a single lead
    ('cpl', 10, 0, 'duplicate'),
    ('cpl', 10, 0, 'increase_bid'),
])
def test_dangerous_rules_rejected(metric, threshold, min_spend, action):
    with pytest.raises(HTTPException) as exc:
        _validate_rule_numbers(metric, threshold, min_spend, action)
    assert exc.value.status_code == 400


def test_object_missing_error_is_narrow_and_never_loose():
    from app.api.v1.auto_pause import _is_object_missing_error, _target_confirmed_gone
    from app.services.facebook_service import FacebookAPIError
    assert _is_object_missing_error(FacebookAPIError("gone", code=100, subcode=33))
    assert not _is_object_missing_error(RuntimeError("Ad set is archived"))
    assert not _is_object_missing_error(FacebookAPIError("slow down", code=17))
    assert not _is_object_missing_error(FacebookAPIError("bad param", code=100, subcode=1))

    class Svc:
        def __init__(self, live=None, boom=False):
            self.live, self.boom = live, boom
        def get_adset_status(self, _):
            if self.boom:
                raise FacebookAPIError("gone", code=100, subcode=33)
            return self.live

    # confirmed only by a successful read showing DELETED/ARCHIVED
    assert _target_confirmed_gone(Svc({"status": "ARCHIVED"}), 'adset', '1')
    assert _target_confirmed_gone(Svc({"effective_status": "DELETED"}), 'adset', '1')
    # lost-access token: the read fails too -> NOT confirmed, rule stays armed
    assert not _target_confirmed_gone(Svc(boom=True), 'adset', '1')
    assert not _target_confirmed_gone(Svc({"status": "ACTIVE"}), 'adset', '1')
    assert not _target_confirmed_gone(Svc({"status": "ARCHIVED"}), 'ad', '1')
