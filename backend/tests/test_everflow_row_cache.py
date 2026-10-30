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


def test_parallel_windows_split_overflow_and_dedupe(monkeypatch):
    """A month is fetched as 7-day windows (several at once); a window at the 2000-row cap is split in half."""
    from datetime import date

    def fake_window(self, start, end, tz):
        days = (end - start).days + 1
        if days > 3:                       # pretend any window longer than 3 days overflows the cap
            return [{"conversion_id": f"partial-{start}"}], 9999
        return [{"conversion_id": f"{start}"}, {"conversion_id": "dup"}], 2

    monkeypatch.setattr(EverflowService, "_fetch_window", fake_window)
    rows = EverflowService()._fetch_conversion_rows_uncached("2026-10-01", "2026-10-31", 80)
    ids = {r["conversion_id"] for r in rows}
    assert not any(i.startswith("partial") for i in ids)          # overflowing windows were never kept
    covered = sorted(i for i in ids if i != "dup")
    # every day of the month is inside exactly one kept window, and the shared "dup" id is kept once
    assert "dup" in ids and len(rows) == len(ids)
    assert covered[0] == "2026-10-01"
    starts = [date.fromisoformat(c) for c in covered]
    assert all(b > a for a, b in zip(starts, starts[1:]))


def test_parallel_and_sequential_give_identical_rows(monkeypatch):
    def fake_window(self, start, end, tz):
        return [{"conversion_id": f"{start}:{i}", "revenue": 1} for i in range((end - start).days + 1)], None

    monkeypatch.setattr(EverflowService, "_fetch_window", fake_window)
    parallel = EverflowService()._fetch_conversion_rows_uncached("2026-09-01", "2026-10-31", 80)
    monkeypatch.setattr(EverflowService, "PARALLEL_WINDOWS", 1)
    sequential = EverflowService()._fetch_conversion_rows_uncached("2026-09-01", "2026-10-31", 80)
    assert sorted(r["conversion_id"] for r in parallel) == sorted(r["conversion_id"] for r in sequential)
    assert len(parallel) == 61


def test_refresh_bypasses_the_cache_and_restores_it(monkeypatch):
    calls = []
    monkeypatch.setattr(EverflowService, "_fetch_conversion_rows_uncached", lambda self, a, b, tz: calls.append(1) or [{"n": len(calls)}])
    EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80)
    assert EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80, refresh=True) == [{"n": 2}]
    assert EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80) == [{"n": 2}]   # reader gets the fresh rows
    assert len(calls) == 2


def test_fresh_reads_do_not_wait_for_a_background_refresh(monkeypatch):
    import threading
    started, release = threading.Event(), threading.Event()

    def slow(self, a, b, tz):
        started.set()
        release.wait(5)
        return [{"n": "new"}]

    monkeypatch.setattr(EverflowService, "_fetch_conversion_rows_uncached", lambda self, a, b, tz: [{"n": "old"}])
    EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80)
    monkeypatch.setattr(EverflowService, "_fetch_conversion_rows_uncached", slow)
    worker = threading.Thread(target=lambda: EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80, refresh=True))
    worker.start()
    started.wait(5)
    assert EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80) == [{"n": "old"}]   # served at once
    release.set()
    worker.join(5)
    assert EverflowService()._fetch_conversion_rows("2026-10-01", "2026-10-30", 80) == [{"n": "new"}]
