import time

import app.services.token_monitor as tm


def _check(monkeypatch, data):
    monkeypatch.setenv("FACEBOOK_ACCESS_TOKEN", "t")
    monkeypatch.setenv("FACEBOOK_APP_ID", "a")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "s")

    class _Resp:
        def json(self):
            return {"data": data}

    monkeypatch.setattr(tm.httpx, "get", lambda *a, **k: _Resp())
    return tm.check_token_expiry()


def test_zero_expiry_with_a_data_access_date_is_not_never_expires(monkeypatch):
    soon = int(time.time()) + 5 * 86400
    r = _check(monkeypatch, {"is_valid": True, "expires_at": 0, "data_access_expires_at": soon})
    assert not r["never_expires"]
    assert r["expires_at"] == soon
    assert 4.9 < r["days_left"] < 5.1


def test_earlier_of_token_expiry_and_data_access_expiry_wins(monkeypatch):
    now = int(time.time())
    r = _check(monkeypatch, {"is_valid": True, "expires_at": now + 60 * 86400, "data_access_expires_at": now + 10 * 86400})
    assert 9.9 < r["days_left"] < 10.1


def test_genuinely_non_expiring_token_still_reads_as_never(monkeypatch):
    r = _check(monkeypatch, {"is_valid": True, "expires_at": 0, "data_access_expires_at": 0})
    assert r["never_expires"] and r["days_left"] is None


def test_a_revoked_token_with_no_expiry_is_invalid_not_never_expires_ok(monkeypatch):
    r = _check(monkeypatch, {"is_valid": False, "expires_at": 0})
    assert r["is_valid"] is False and r["never_expires"]

