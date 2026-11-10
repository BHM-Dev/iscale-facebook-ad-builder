"""A single Switchboard hang must not fail the whole revenue pull (seen live 2026-11-10)."""
from datetime import date
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.everflow_service import EverflowService


def _ok(rows):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"conversions": rows, "paging": {"total_count": len(rows)}}
    resp.raise_for_status.return_value = None
    return resp


def _svc():
    svc = EverflowService.__new__(EverflowService)  # no API key / network needed
    return svc


def test_timeout_then_success_is_retried():
    svc = _svc()
    calls = []

    def post(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("The read operation timed out")
        return _ok([{"conversion_id": "c1"}])

    svc._post_window = post
    rows, total = svc._fetch_window(date(2026, 11, 3), date(2026, 11, 9), 80)
    assert rows == [{"conversion_id": "c1"}] and total == 1 and len(calls) == 2


def test_three_timeouts_still_raise_rather_than_report_zero_revenue():
    svc = _svc()

    def post(*_a, **_k):
        raise httpx.ReadTimeout("The read operation timed out")

    svc._post_window = post
    with pytest.raises(httpx.ReadTimeout):
        svc._fetch_window(date(2026, 11, 3), date(2026, 11, 9), 80)
