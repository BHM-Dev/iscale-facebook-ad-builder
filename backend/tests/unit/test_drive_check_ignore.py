"""Ignore list for Drive checks: review folders etc. stop being flagged, files still sync."""
import json
from unittest.mock import MagicMock

from app.services import drive_check_ignore as ig
from app.services.drive_sync_service import DriveSyncService


def test_load_is_safe_on_bad_data():
    db = MagicMock()
    for raw in (None, "not json", json.dumps({"a": 1}), json.dumps([1, {"folder_id": "x"}])):
        db.execute.return_value.scalar.return_value = raw
        out = ig.load(db)
        assert isinstance(out, list) and all(isinstance(i, dict) for i in out)


def test_path_matching_is_exact_or_subfolder():
    paths = ig.paths([{"path": "Home Equity Investment/Home Equity Ads for Review (Nov 18)/"}])
    assert ig.path_is_ignored("Home Equity Investment/Home Equity Ads for Review (Nov 18)", paths)
    assert ig.path_is_ignored("Home Equity Investment/Home Equity Ads for Review (Nov 18)/Videos", paths)
    assert not ig.path_is_ignored("Home Equity Investment/HEI-A Skip the HELOC", paths)
    assert not ig.path_is_ignored("Home Equity Investment/Home Equity Ads for Review (Nov 18) v2", paths)


def test_copy_health_excludes_ignored_package_without_hiding_others():
    rows = [
        {"drive_file_id": "r1", "file_name": "a.mp4", "folder_path": "HEI/Review", "soft_tags": "{}"},
        {"drive_file_id": "p1", "file_name": "b.jpg", "folder_path": "HEI/HEI-A", "soft_tags": "{}"},
    ]
    before = DriveSyncService._build_copy_health_summary(rows)
    after = DriveSyncService._build_copy_health_summary(rows, ignored_paths=["HEI/Review"])
    assert before["exception_assets"] == 2
    assert after["exception_assets"] == 1 and after["exceptions"][0]["package"] == "HEI/HEI-A"
    assert after["excluded_assets"] == 1 and "ignored by Steve" in after["exclusions"][0]["reason"]


def test_failed_read_never_rolls_back_the_callers_transaction():
    db = MagicMock()
    db.execute.side_effect = RuntimeError("relation does not exist")
    assert ig.load(db) == []
    db.rollback.assert_not_called()
    db.begin_nested.assert_called_once()
