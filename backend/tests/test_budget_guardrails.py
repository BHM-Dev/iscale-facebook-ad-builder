import pytest
from fastapi import HTTPException

from app.api.v1.facebook import (
    MAX_DAILY_BUDGET_CENTS,
    _enforce_budget_sanity,
    _positive_cents,
    _read_live_budget_or_raise,
)
from app.services.facebook_service import FacebookAPIError


def test_positive_cents():
    assert _positive_cents("2500") == 2500
    assert _positive_cents(None) is None
    assert _positive_cents("") is None
    assert _positive_cents("0") is None


def test_small_change_passes():
    _enforce_budget_sanity(5000, 5500, False, "Ad set")


def test_hundredfold_typo_needs_confirmation():
    with pytest.raises(HTTPException) as exc:
        _enforce_budget_sanity(5000, 500000, False, "Ad set")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "LARGE_BUDGET_CHANGE"
    assert exc.value.detail["current_cents"] == 5000


def test_large_cut_needs_confirmation():
    with pytest.raises(HTTPException) as exc:
        _enforce_budget_sanity(40000, 10000, False, "Ad set")
    assert exc.value.status_code == 409


def test_confirmed_large_change_passes():
    _enforce_budget_sanity(5000, 20000, True, "Ad set")


def test_hard_ceiling_applies_even_when_confirmed():
    with pytest.raises(HTTPException) as exc:
        _enforce_budget_sanity(5000, MAX_DAILY_BUDGET_CENTS + 1, True, "Ad set")
    assert exc.value.status_code == 400


def test_preread_fails_closed_on_throttle():
    def reader(_):
        raise FacebookAPIError("too many calls", code=17)
    with pytest.raises(HTTPException) as exc:
        _read_live_budget_or_raise(reader, "123", "Ad set")
    assert exc.value.status_code == 429


def test_preread_fails_closed_on_unexpected_error():
    def reader(_):
        raise RuntimeError("boom")
    with pytest.raises(HTTPException) as exc:
        _read_live_budget_or_raise(reader, "123", "Ad set")
    assert exc.value.status_code == 502


def test_http_error_mapping_throttle_vs_rejection():
    from app.api.v1.facebook import _http_error_from_meta
    assert _http_error_from_meta(FacebookAPIError("slow down", code=80004)).status_code == 429
    assert _http_error_from_meta(FacebookAPIError("slow down", code=17)).status_code == 429
    assert _http_error_from_meta(FacebookAPIError("bad param", code=100)).status_code == 400


def test_http_error_mapping_other_classes():
    from app.api.v1.facebook import _http_error_from_meta
    assert _http_error_from_meta(FacebookAPIError("app limit", code=341)).status_code == 429
    assert _http_error_from_meta(FacebookAPIError("temp", code=2)).status_code == 502
    assert _http_error_from_meta(FacebookAPIError("no code")).status_code == 502
    assert _http_error_from_meta(FacebookAPIError("token", code=190)).status_code == 502
    assert _http_error_from_meta(FacebookAPIError("perm", code=200)).status_code == 403
