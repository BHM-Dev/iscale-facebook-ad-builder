from datetime import datetime, timedelta, timezone

from googleapiclient.errors import HttpError

from app.services.drive_sync_service import (
    RETRY_FAST_ATTEMPTS,
    RETRY_MAX_ATTEMPTS,
    RETRY_SLOW_INTERVAL_SECONDS,
    DriveSyncService,
)


def _service(ledger=None):
    service = DriveSyncService.__new__(DriveSyncService)
    service.__dict__["_retry_state_store"] = {"ledger": ledger if ledger is not None else {}, "copy_failed": set(), "processed": set(), "load_ok": True, "loaded_json": None}
    return service


def _entry(attempts, last_attempt=None, code="old"):
    return {"name": "f.mp4", "kind": "file", "error": "boom", "attempts": attempts,
            "last_attempt": (last_attempt or datetime.now(timezone.utc)).isoformat(), "code": code}


def test_retry_is_due_every_cycle_for_first_attempts_then_backs_off_then_stops():
    now = datetime.now(timezone.utc)
    due = DriveSyncService._retry_is_due
    assert due(_entry(1), now, "old")
    assert due(_entry(RETRY_FAST_ATTEMPTS - 1), now, "old")
    assert not due(_entry(RETRY_FAST_ATTEMPTS, now - timedelta(minutes=30)), now, "old")
    assert due(_entry(RETRY_FAST_ATTEMPTS, now - timedelta(seconds=RETRY_SLOW_INTERVAL_SECONDS + 1)), now, "old")
    assert not due(_entry(RETRY_MAX_ATTEMPTS, now - timedelta(days=2)), now, "old")


def test_new_deploy_makes_even_an_exhausted_failure_due_again():
    now = datetime.now(timezone.utc)
    assert DriveSyncService._retry_is_due(_entry(RETRY_MAX_ATTEMPTS, now, code="abc"), now, "def")
    assert not DriveSyncService._retry_is_due(_entry(RETRY_MAX_ATTEMPTS, now, code="abc"), now, "abc")
    assert not DriveSyncService._retry_is_due(_entry(RETRY_MAX_ATTEMPTS, now, code="abc"), now, "unknown")


def test_note_failure_counts_attempts_and_resolve_removes_it():
    service = _service()
    service._ledger_note_failure("id1", "a.mp4", "first", kind="file")
    service._ledger_note_failure("id1", "a.mp4", "second", kind="file")
    assert service._ledger()["id1"]["attempts"] == 2
    assert service._ledger()["id1"]["error"] == "second"
    service._ledger_resolve("id1")
    assert "id1" not in service._ledger()
    service._ledger_resolve("never-failed")


def test_media_imports_flagged_unverified_when_copy_cannot_be_resolved():
    service = _service()
    marked = []

    def explode(file_meta, file_name):
        raise RuntimeError("manifest unreadable")

    service._metadata_for_media_file = explode
    service._mark_package_copy_unverified = lambda meta, reason: marked.append(reason)
    result = {"unverified": 0}

    tags = service._safe_metadata_for_media_file({"id": "vid1", "name": "v.mp4"}, "v.mp4", result)

    assert tags["copy_refresh_status"] == "unverified"
    assert tags["copy_import_unresolved"] is True
    assert "manifest unreadable" in tags["copy_refresh_error"]
    assert result["unverified"] == 1
    assert marked == ["manifest unreadable"]
    assert "vid1" in service._ledger() and service._ledger()["vid1"]["kind"] == "copy"
    assert "vid1" in service._retry_state()["copy_failed"]


def test_successful_copy_resolution_passes_straight_through():
    service = _service()
    service._metadata_for_media_file = lambda meta, name: {"copy_id": "X"}
    assert service._safe_metadata_for_media_file({"id": "a"}, "a.mp4", {}) == {"copy_id": "X"}
    assert service._ledger() == {}


class _FakeFiles:
    def __init__(self, metas):
        self.metas = metas

    def get(self, fileId, **kwargs):
        meta = self.metas[fileId]

        class _Req:
            def execute(_self):
                if isinstance(meta, Exception):
                    raise meta
                return meta
        return _Req()


class _FakeDrive:
    def __init__(self, metas):
        self._files = _FakeFiles(metas)

    def files(self):
        return self._files


class _Resp:
    status = 404
    reason = "not found"


def test_retry_pass_reprocesses_due_files_and_drops_deleted_ones():
    service = _service({
        "ok": _entry(1), "gone": _entry(1), "skip": _entry(RETRY_MAX_ATTEMPTS, code="same"),
    })
    service._ledger()["skip"]["code"] = "same"
    processed = []

    def fake_process(file_meta, result):
        processed.append(file_meta["id"])
        service._ledger_resolve(file_meta["id"])

    service._process_file_isolated = fake_process
    drive = _FakeDrive({
        "ok": {"id": "ok", "name": "ok.mp4"},
        "gone": HttpError(_Resp(), b"missing"),
        "skip": {"id": "skip", "name": "skip.mp4"},
    })
    result = {"archived": 0, "errors": 0}

    import os
    os.environ.pop("GIT_COMMIT", None)
    service._retry_failed_files(drive, result)

    assert processed == ["ok"]
    assert "gone" not in service._ledger()
    assert "skip" in service._ledger()
    assert (result["retried"], result["recovered"]) == (1, 1)


def test_retry_pass_skips_files_already_processed_in_this_sync():
    service = _service({"dup": _entry(1)})
    service._retry_state()["processed"].add("dup")
    service._process_file_isolated = lambda *a: (_ for _ in ()).throw(AssertionError("must not reprocess"))
    service._retry_failed_files(_FakeDrive({"dup": {"id": "dup", "name": "d.mp4"}}), {"archived": 0, "errors": 0})
    assert "dup" in service._ledger()


def test_flush_never_overwrites_saved_history_after_a_failed_load():
    service = _service({"new": _entry(1)})
    service._retry_state()["load_ok"] = False
    executed = []

    class _DB:
        def begin_nested(self):
            raise AssertionError("must not touch the DB")

        def execute(self, *a, **k):
            executed.append(a)

    service.db = _DB()
    service._ledger_flush()
    assert executed == []


def test_fetch_failures_count_as_attempts_so_they_cannot_loop_forever():
    service = _service({"x": _entry(1)})
    drive = _FakeDrive({"x": RuntimeError("503")})
    service._retry_failed_files(drive, {"archived": 0, "errors": 0})
    assert service._ledger()["x"]["attempts"] == 2
    assert "503" in service._ledger()["x"]["error"]


def test_a_404_retires_the_row_and_drops_the_entry():
    service = _service({"gone": _entry(1)})
    archived = []
    service._archive_by_drive_id_isolated = lambda drive_file_id, result: archived.append(drive_file_id) or 1
    result = {"archived": 0, "errors": 0}
    service._retry_failed_files(_FakeDrive({"gone": HttpError(_Resp(), b"x")}), result)
    assert archived == ["gone"] and result["archived"] == 1
    assert "gone" not in service._ledger()


def test_copy_entry_is_not_resolved_by_a_run_that_did_not_verify_copy():
    service = _service({"c": {**_entry(1), "kind": "copy"}})
    service._is_supported_media = lambda mime, name: True

    class _DB:
        class _SP:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def begin_nested(self):
            return self._SP()

    service.db = _DB()
    service._process_file = lambda meta, result: None  # e.g. early return: skipped / unmatched brand
    result = {"errors": 0}
    service._process_file_isolated({"id": "c", "name": "c.mp4", "mimeType": "video/mp4"}, result)
    assert "c" in service._ledger()


def test_recovered_copy_entry_re_verifies_the_package_siblings():
    service = _service({"c": {**_entry(1), "kind": "copy"}})
    refreshed = []

    def fake_process(meta, result):
        service._ledger_resolve(meta["id"])

    service._process_file_isolated = fake_process
    service._find_package_folder = lambda meta: "pkg"
    service._find_strategy_package_folder = lambda meta: None
    service._refresh_folder_copy_metadata = lambda meta, metadata_folder=None: refreshed.append(metadata_folder)

    class _DB:
        class _SP:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def begin_nested(self):
            return self._SP()

    service.db = _DB()
    service._retry_failed_files(_FakeDrive({"c": {"id": "c", "name": "c.mp4"}}), {"archived": 0, "errors": 0})
    assert refreshed == ["pkg"]


def test_old_exhausted_entries_are_pruned_on_load():
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    stale = {**_entry(RETRY_MAX_ATTEMPTS), "first_failed": old}
    fresh = {**_entry(RETRY_MAX_ATTEMPTS), "first_failed": datetime.now(timezone.utc).isoformat()}
    import json as _json

    class _Row(list):
        pass

    class _Res:
        def first(self):
            return [_json.dumps({"stale": stale, "fresh": fresh, "junk": "not-a-dict"})]

    class _DB:
        class _SP:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def begin_nested(self):
            return self._SP()

        def execute(self, *a, **k):
            return _Res()

    service = DriveSyncService.__new__(DriveSyncService)
    service.db = _DB()
    assert set(service._ledger()) == {"fresh"}


def test_only_files_still_failing_after_retries_are_alert_worthy_and_only_once():
    from app.services.drive_sync_service import RETRY_ALERT_AT_ATTEMPTS

    service = _service({
        "fresh": _entry(1),
        "exhausted": _entry(RETRY_ALERT_AT_ATTEMPTS),
        "told": {**_entry(RETRY_ALERT_AT_ATTEMPTS), "alerted": True},
    })
    flushed = []
    service._ledger_flush = lambda: flushed.append(True) or True

    class _DB:
        def commit(self):
            flushed.append("commit")

    service.db = _DB()

    pending = service.unalerted_exhausted_failures()
    assert [item["drive_file_id"] for item in pending] == ["exhausted"]

    service.acknowledge_failure_alerts(["exhausted"])
    assert service.unalerted_exhausted_failures() == []
    assert flushed == [True, "commit"]


def test_a_new_deploy_re_arms_the_alert_for_an_exhausted_failure():
    service = _service({"x": {**_entry(RETRY_MAX_ATTEMPTS, code="old"), "alerted": True}})
    service._process_file_isolated = lambda meta, result: None
    import os
    os.environ["GIT_COMMIT"] = "newsha"
    try:
        service._retry_failed_files(_FakeDrive({"x": {"id": "x", "name": "x.mp4"}}), {"archived": 0, "errors": 0})
    finally:
        os.environ.pop("GIT_COMMIT", None)
    assert "alerted" not in service._ledger()["x"]


def test_sync_failure_alert_is_throttled_to_once_per_window():
    from app.services.drive_sync_service import SYNC_FAILURE_ALERT_WINDOW_SECONDS

    now = datetime.now(timezone.utc)
    due = DriveSyncService._failure_alert_due
    assert due(None, now)
    assert due("not-a-date", now)
    assert not due((now - timedelta(minutes=15)).isoformat(), now)
    assert due((now - timedelta(seconds=SYNC_FAILURE_ALERT_WINDOW_SECONDS + 1)).isoformat(), now)


def test_alert_sync_failure_sends_once_then_suppresses_and_never_raises():
    from app.services import drive_sync_service as mod

    sent = []
    stored = {}

    class _Res:
        def __init__(self, value):
            self.value = value

        def first(self):
            return [self.value] if self.value else None

    class _DB:
        def execute(self, statement, params=None):
            if "SELECT" in str(statement):
                return _Res(stored.get("v"))
            stored["v"] = params["value"]
            return _Res(None)

        def commit(self):
            pass

        def rollback(self):
            pass

    service = DriveSyncService.__new__(DriveSyncService)
    service.db = _DB()
    original = mod.slack_service.send_drive_sync_alert
    mod.slack_service.send_drive_sync_alert = lambda summary, detail="", **k: sent.append(summary) or True
    try:
        service._alert_sync_failure(RuntimeError("auth revoked"))
        service._alert_sync_failure(RuntimeError("auth revoked"))
        service._alert_sync_failure(RuntimeError("auth revoked"))
    finally:
        mod.slack_service.send_drive_sync_alert = original
    assert sent == ["RuntimeError"]

    broken = DriveSyncService.__new__(DriveSyncService)
    broken.db = None
    broken._alert_sync_failure(RuntimeError("x"))
