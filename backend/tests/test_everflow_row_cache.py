"""Switchboard Everflow rows are pulled once per range for a few minutes (one P&L load asked ~5x for the same month)."""
from app.services.everflow_service import EverflowService


def test_same_range_is_fetched_once(monkeypatch):
    calls = []
    monkeypatch.setattr(EverflowService, "_fetch_conversion_rows_uncached", lambda self, a, b, tz: calls.append((a, b)) or [{"conversion_id": "x"}])
    svc = EverflowService()
    assert svc._fetch_conversion_rows("2026-10-01", "2026-10-30", 80) == [{"conversion_id": "x"}]
    assert EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80) == [{"conversion_id": "x"}]
    EverflowService()._fetch_conversion_rows("2026-09-01", "2026-09-30", 80)
    assert calls == [("2026-10-01", "2026-10-30"), ("2026-09-01", "2026-09-30")]


def test_cache_expires(monkeypatch):
    calls = []
    monkeypatch.setattr(EverflowService, "_fetch_conversion_rows_uncached", lambda self, a, b, tz: calls.append(1) or [])
    monkeypatch.setattr(EverflowService, "ROWS_CACHE_TTL_SECONDS", 0)
    EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80)
    EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80)
    assert len(calls) == 2


def test_failures_are_not_cached(monkeypatch):
    calls = []

    def flaky(self, a, b, tz):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Everflow down")
        return [{"conversion_id": "ok"}]

    monkeypatch.setattr(EverflowService, "_fetch_conversion_rows_uncached", flaky)
    try:
        EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80)
    except RuntimeError:
        pass
    assert EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80) == [{"conversion_id": "ok"}]
