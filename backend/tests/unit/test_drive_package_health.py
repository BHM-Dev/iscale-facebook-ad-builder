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
