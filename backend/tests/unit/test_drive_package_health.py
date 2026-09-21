import pytest

import json

from app.api.v1.drive_health import build_package_health_report
from app.services.drive_sync_service import DriveSyncService


ROOT = {"id": "root", "name": "Drive"}
BRAND = {"id": "brand", "name": "Commercial Insurance"}


def _file(file_id, name, parent_id, mime_type="image/png"):
    return {"id": file_id, "name": name, "mimeType": mime_type, "parents": [parent_id]}


def _service(files, chains, texts=None):
    service = DriveSyncService.__new__(DriveSyncService)
    service.root_folder_id = "root"
    service._client = lambda: object()
    service._initial_folder_walk = lambda _drive: files
    service._parent_chain = lambda item: chains[item["id"]]
    service._download_text_file = lambda file_id: (texts or {})[file_id]
    return service


def test_package_health_reports_each_structural_issue():
    package_a = {"id": "package-a", "name": "Fresh Creative"}
    package_b = {"id": "package-b", "name": "Legacy Creative"}
    package_c = {"id": "package-c", "name": "Duplicate Files"}
    feed = {"id": "feed", "name": "1x1 Images"}
    files = [
        _file("a-image", "ad1-identity-9x16.png", "package-a"),
        _file("b-image", "ad1-identity-9x16.png", "package-b"),
        _file("c-one", "same.png", "feed"),
        _file("c-two", "same.png", "feed"),
    ]
    chains = {
        "a-image": [ROOT, BRAND, package_a],
        "b-image": [ROOT, BRAND, package_b],
        "c-one": [ROOT, BRAND, package_c, feed],
        "c-two": [ROOT, BRAND, package_c, feed],
    }

    report = build_package_health_report(_service(files, chains))
    by_path = {package["path"]: package for package in report["packages"]}

    assert set(by_path["Commercial Insurance / Fresh Creative"]["issues"]) == {
        "no_copy_source", "flat_package", "duplicate_basename_across_packages"
    }
    assert set(by_path["Commercial Insurance / Legacy Creative"]["issues"]) == {
        "no_copy_source", "flat_package", "duplicate_basename_across_packages"
    }
    assert set(by_path["Commercial Insurance / Duplicate Files"]["issues"]) == {
        "no_copy_source", "duplicate_basename_within_package"
    }
    assert report["collisions"] == [{
        "basename": "ad1-identity-9x16.png",
        "packages": ["Commercial Insurance / Fresh Creative", "Commercial Insurance / Legacy Creative"],
        # folder_ids travel with each collision so the UI can deep-link the
        # package into Drive instead of making someone search for the path.
        "package_folders": [
            {"folder_id": "package-a", "path": "Commercial Insurance / Fresh Creative"},
            {"folder_id": "package-b", "path": "Commercial Insurance / Legacy Creative"},
        ],
    }]


def test_package_health_detects_manifest_and_recognized_copy_docs():
    manifest_package = {"id": "manifest-package", "name": "Manifest Package"}
    strategy_package = {"id": "strategy-package", "name": "Strategy Package"}
    copy_folder = {"id": "copy-folder", "name": "Ad Copy"}
    files = [
        _file("manifest-image", "manifest.png", "manifest-package"),
        _file("manifest", "HANDOFF_MANIFEST.txt", "manifest-package", "text/plain"),
        _file("strategy-image", "strategy.png", "strategy-package"),
        _file("strategy", "strategy.md", "copy-folder", "text/markdown"),
    ]
    chains = {
        "manifest-image": [ROOT, BRAND, manifest_package],
        "manifest": [ROOT, BRAND, manifest_package],
        "strategy-image": [ROOT, BRAND, strategy_package],
        "strategy": [ROOT, BRAND, strategy_package, copy_folder],
    }
    texts = {"strategy": "## AD-TEST-01\nMeta headline: Test\nPrimary text: Test"}

    report = build_package_health_report(_service(files, chains, texts))
    by_path = {package["path"]: package for package in report["packages"]}

    assert by_path["Commercial Insurance / Manifest Package"]["copy_source"] == "handoff_manifest"
    assert by_path["Commercial Insurance / Manifest Package"]["issues"] == []
    assert by_path["Commercial Insurance / Strategy Package"]["copy_source"] == "strategy_doc"
    assert by_path["Commercial Insurance / Strategy Package"]["issues"] == ["flat_package"]


def test_manifest_packages_skip_the_download_pass():
    """A handoff manifest is identified by filename alone.

    The first version downloaded every text file in the tree on every build --
    measured at over ten minutes against the live Drive. Packages resolved by
    name must not download anything, so assert nothing was fetched.
    """
    package = {"id": "package-a", "name": "Fresh Creative"}
    files = [
        _file("media-1", "ad1-1x1.png", "package-a"),
        _file("manifest", "FRESH_HANDOFF_MANIFEST.txt", "package-a", "text/plain"),
        _file("notes", "Random Notes.txt", "package-a", "text/plain"),
    ]
    chains = {
        "media-1": [ROOT, BRAND, package],
        "manifest": [ROOT, BRAND, package],
        "notes": [ROOT, BRAND, package],
    }
    service = _service(files, chains)
    downloaded = []

    def _explode(file_id):
        downloaded.append(file_id)
        raise AssertionError(f"downloaded {file_id} for a package already resolved by manifest name")

    service._download_text_file = _explode

    report = build_package_health_report(service)

    assert downloaded == []
    assert report["packages"][0]["copy_source"] == "handoff_manifest"
    assert report["packages"][0]["has_manifest"] is True


def test_text_files_outside_any_package_are_never_downloaded():
    package = {"id": "package-a", "name": "Fresh Creative"}
    stray = {"id": "stray", "name": "Loose Docs"}
    files = [
        _file("media-1", "ad1-1x1.png", "package-a"),
        _file("stray-doc", "Some Doc.txt", "stray", "text/plain"),
    ]
    chains = {
        "media-1": [ROOT, BRAND, package],
        "stray-doc": [ROOT, BRAND, stray],
    }
    service = _service(files, chains)

    def _explode(file_id):
        raise AssertionError(f"downloaded {file_id} from a folder with no media")

    service._download_text_file = _explode

    report = build_package_health_report(service)

    assert [item["path"] for item in report["packages"]] == ["Commercial Insurance / Fresh Creative"]


def test_report_is_json_serializable():
    """The report is persisted to drive_sync_state as JSON, so a stray set()
    leaking out of _package_for_media would break the scheduler, not just a view."""
    package = {"id": "package-a", "name": "Fresh Creative"}
    files = [_file("media-1", "ad1-1x1.png", "package-a")]
    chains = {"media-1": [ROOT, BRAND, package]}

    json.dumps(build_package_health_report(_service(files, chains)))


def test_same_basename_under_two_brands_is_not_a_collision():
    """Collisions are scoped per brand, and the UI keys rows on the basename --
    two brands sharing a name must not merge into one bogus collision."""
    brand_two = {"id": "brand-2", "name": "Home Services"}
    package_a = {"id": "package-a", "name": "Fresh Creative"}
    package_b = {"id": "package-b", "name": "Other Creative"}
    files = [
        _file("media-1", "ad1-1x1.png", "package-a"),
        _file("media-2", "ad1-1x1.png", "package-b"),
    ]
    chains = {
        "media-1": [ROOT, BRAND, package_a],
        "media-2": [ROOT, brand_two, package_b],
    }

    report = build_package_health_report(_service(files, chains))

    assert report["collisions"] == []
    for item in report["packages"]:
        assert "duplicate_basename_across_packages" not in item["issues"]


def test_collision_keeps_real_filename_casing():
    """The basename is what someone pastes into Drive search; a lowercased one
    will not match the folder."""
    package_a = {"id": "package-a", "name": "Fresh Creative"}
    package_b = {"id": "package-b", "name": "Legacy Creative"}
    files = [
        _file("media-1", "AD1-Identity-9x16.png", "package-a"),
        _file("media-2", "AD1-Identity-9x16.png", "package-b"),
    ]
    chains = {
        "media-1": [ROOT, BRAND, package_a],
        "media-2": [ROOT, BRAND, package_b],
    }

    report = build_package_health_report(_service(files, chains))

    assert report["collisions"][0]["basename"] == "AD1-Identity-9x16.png"
    assert {entry["folder_id"] for entry in report["collisions"][0]["package_folders"]} == {"package-a", "package-b"}


def test_failed_rebuild_stamps_the_error_and_keeps_the_previous_snapshot():
    """A rebuild that dies must not leave the old report looking current.

    Previously the exception was swallowed to the container log, nothing was
    written, and the page served the stale snapshot under a green summary with
    its old generated_at -- so an expired Drive credential would serve a
    months-old report as authoritative, forever.
    """
    from app.api.v1 import drive_health

    stored = {"value": json.dumps({
        "generated_at": "2026-09-01T00:00:00+00:00",
        "packages": [{"folder_id": "p", "path": "Old", "issues": []}],
        "collisions": [],
    })}
    written = {}

    class _FakeDb:
        def execute(self, statement, params=None):
            text_sql = str(statement)
            if "SELECT value" in text_sql:
                class _Row:
                    def first(_self):
                        return (stored["value"],) if stored["value"] else None
                return _Row()
            written.update(params or {})
            stored["value"] = (params or {}).get("value")
            class _Null:
                def first(_self):
                    return None
            return _Null()

        def commit(self):
            pass

    def _boom(_service):
        raise RuntimeError("drive credentials expired")

    original = drive_health.build_package_health_report
    drive_health.build_package_health_report = _boom
    try:
        with pytest.raises(RuntimeError):
            drive_health.refresh_package_health_snapshot(_FakeDb())
    finally:
        drive_health.build_package_health_report = original

    saved = json.loads(written["value"])
    assert saved["last_error"] == "drive credentials expired"
    assert saved["last_attempt_at"]
    # the previous result survives so the page can show it, clearly labelled stale
    assert saved["packages"] == [{"folder_id": "p", "path": "Old", "issues": []}]
    assert saved["generated_at"] == "2026-09-01T00:00:00+00:00"
    # and the in-flight flag is released even on the failure path
    assert drive_health._rebuilding is False
