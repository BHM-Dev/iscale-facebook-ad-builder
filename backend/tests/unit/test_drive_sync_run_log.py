import pytest
from fastapi import HTTPException

import app.services.drive_sync_run_log as run_log


@pytest.fixture
def rows(monkeypatch):
    captured = []
    monkeypatch.setattr(
        run_log, "_write_row",
        lambda db, kind, started_at, status, result, error: captured.append((kind, status, result, error)),
    )
    return captured


def test_ok_run_is_recorded_with_counts(rows):
    result = run_log.logged_run(None, "incremental", lambda: {"processed": 3, "errors": 0})

    assert result == {"processed": 3, "errors": 0}
    assert rows == [("incremental", "ok", {"processed": 3, "errors": 0}, None)]


def test_run_with_file_errors_is_flagged(rows):
    run_log.logged_run(None, "backfill", lambda: {"processed": 5, "errors": 2})

    assert rows[0][1] == "ok_with_errors"


def test_409_is_contention_not_failure(rows):
    def locked():
        raise HTTPException(status_code=409, detail="A Drive sync is already running.")

    with pytest.raises(HTTPException):
        run_log.logged_run(None, "incremental", locked)

    assert rows[0][1] == "skipped_locked" and rows[0][3] is None


def test_reconcile_that_did_not_get_the_lock_is_skipped_locked(rows):
    run_log.logged_run(None, "reconcile", lambda: {"ran": False})

    assert rows[0][1] == "skipped_locked"


def test_failure_is_recorded_and_reraised(rows):
    def boom():
        raise RuntimeError("Drive unavailable")

    with pytest.raises(RuntimeError):
        run_log.logged_run(None, "scoped", boom)

    assert rows[0][1] == "error" and "Drive unavailable" in rows[0][3]


def test_write_failure_never_changes_the_outcome():
    # No real session: the write must fail quietly and the run's result stands.
    assert run_log.logged_run(object(), "incremental", lambda: {"processed": 1}) == {"processed": 1}


def test_decorator_resolves_kind_from_call_arguments(rows):
    class Service:
        db = None

        @run_log.logged_method(lambda self, folder_id=None: "scoped" if folder_id else "incremental")
        def sync(self, folder_id=None):
            return {"processed": 0}

    Service().sync(folder_id="f")
    Service().sync()

    assert [r[0] for r in rows] == ["scoped", "incremental"]


def test_active_run_is_written_before_work_and_finalized(monkeypatch):
    events = []

    monkeypatch.setattr(run_log, "_write_running_row", lambda db, kind, started_at: events.append(("start", kind)) or 42)
    monkeypatch.setattr(
        run_log,
        "_finish_running_row",
        lambda db, run_id, status, result, error: events.append(("finish", run_id, status, result, error)) or True,
    )
    monkeypatch.setattr(run_log, "_write_row", lambda *args: pytest.fail("fallback insert should not run"))

    def work():
        events.append(("work",))
        return {"processed": 2}

    assert run_log.logged_run(object(), "incremental", work) == {"processed": 2}
    assert events == [
        ("start", "incremental"),
        ("work",),
        ("finish", 42, "ok", {"processed": 2}, None),
    ]
