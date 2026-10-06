import pytest

import json
from datetime import timedelta

from app.api.v1.drive_health import (
    PACKAGE_HEALTH_STALE_AFTER,
    _library_counts_by_package,
    build_package_health_report,
)
from app.services.drive_sync_service import DriveSyncService


ROOT = {"id": "root", "name": "Drive"}
BRAND = {"id": "brand", "name": "Commercial Insurance"}


def test_daily_package_health_has_a_full_day_plus_grace_before_stale():
    """The picker must not warn all day after a correctly scheduled daily run."""
    assert PACKAGE_HEALTH_STALE_AFTER == timedelta(hours=30)


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


class _LibraryDb:
    def __init__(self, folder_paths):
        self.folder_paths = folder_paths

    def execute(self, _statement):
        class _Result:
            def __init__(self, rows):
                self.rows = rows

            def all(self):
                return self.rows

        return _Result([(path,) for path in self.folder_paths])


def test_library_count_uses_production_path_shapes():
    # Snapshot paths lead with the brand folder; drive_assets.folder_path drops it.
    # Shapes copied from production (2026-10-02).
    packages = [
        {"folder_id": "proven", "path": "Commercial Insurance / Commercial Van Insurance / CA-PROVEN | Commercial Auto Video + Static"},
        {"folder_id": "vehicle", "path": "Commercial Insurance / Commercial Van Insurance / CA-VEHICLE | Vehicle Owner Statics"},
    ]
    db = _LibraryDb([
        "Commercial Van Insurance/CA-PROVEN | Commercial Auto Video + Static/1x1 Feed Images",
        "Commercial Van Insurance/CA-PROVEN | Commercial Auto Video + Static/4x5 Feed Videos",
        "Commercial Van Insurance/CA-PROVEN | Commercial Auto Video + Static/9x16 Stories and Reels Videos",
        "Commercial Van Insurance/CA-VEHICLE | Vehicle Owner Statics/1x1 Feed Images",
        "Commercial Insurance - LEGACY IMAGES/Winery/Final Creatives",
    ])

    assert _library_counts_by_package(db, packages) == {"proven": 3, "vehicle": 1}


def test_library_count_attributes_rows_to_the_deepest_package():
    packages = [
        {"folder_id": "parent", "path": "Brand / Category / Parent"},
        {"folder_id": "child", "path": "Brand / Category / Parent / Child"},
    ]
    db = _LibraryDb(["Category/Parent/Child/1x1", "Category/Parent/1x1"])

    assert _library_counts_by_package(db, packages) == {"parent": 1, "child": 1}


def test_thirty_six_drive_files_and_an_empty_library_read_as_thirty_six_missing():
    packages = [{"folder_id": "proven", "path": "Brand / Category / CA-PROVEN"}]

    assert _library_counts_by_package(_LibraryDb([]), packages) == {"proven": 0}


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


def test_manifest_packages_only_download_the_manifest_for_validation():
    """Manifest detection stays filename-only for unrelated text files.

    The manifest itself is downloaded once because the health snapshot now
    validates its structure; unrelated notes must still never be fetched.
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

    def _download(file_id):
        downloaded.append(file_id)
        if file_id == "manifest":
            return """PACKAGE: Commercial Insurance | Fresh Creative
Meta Button
Get Quote
## AD-01
PRIMARY TEXT
Primary
HEADLINE
Headline
1X1 IMAGE
ad1-1x1.png
"""
        raise AssertionError(f"downloaded unrelated file {file_id}")

    service._download_text_file = _download

    report = build_package_health_report(service)

    assert downloaded == ["manifest"]
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


def test_report_surfaces_drive_library_drift_totals_and_top_missing_package():
    package = {"id": "package-a", "name": "CA-PROVEN"}
    files = [_file(f"media-{index}", f"creative-{index}-1x1.png", "package-a") for index in range(36)]
    chains = {item["id"]: [ROOT, BRAND, package] for item in files}
    service = _service(files, chains)
    service.db = _LibraryDb([])

    report = build_package_health_report(service)

    assert report["drive_media_total"] == 36
    assert report["library_media_total"] == 0
    assert report["missing_total"] == 36
    assert report["missing_packages"][0] == {
        "folder_id": "package-a",
        "path": "Commercial Insurance / CA-PROVEN",
        "media_count": 36,
        "library_count": 0,
        "missing_count": 36,
    }


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


def test_same_named_packages_in_two_brands_do_not_raise_false_missing():
    packages = [
        {"folder_id": "a", "path": "Brand A / Category / CA-PROVEN"},
        {"folder_id": "b", "path": "Brand B / Category / CA-PROVEN"},
    ]
    db = _LibraryDb(["Category/CA-PROVEN/1x1 Feed Images"])

    assert _library_counts_by_package(db, packages) == {"a": 1, "b": 1}


def test_archive_folders_are_recognised_but_live_relaunch_packages_are_not():
    from app.api.v1.drive_health import _is_archived_package_path

    assert _is_archived_package_path("Commercial Insurance / Commercial Insurance - LEGACY IMAGES / Winery / Final Creatives")
    assert _is_archived_package_path("Brand / Old Stuff - Archive / Pkg")
    assert not _is_archived_package_path("Commercial Insurance / Barber Shops | Legacy Control Relaunch")
    assert not _is_archived_package_path("Commercial Insurance / Commercial Van Insurance / CA-PROVEN | Commercial Auto Video + Static")
