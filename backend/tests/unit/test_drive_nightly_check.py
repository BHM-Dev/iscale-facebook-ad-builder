"""Nightly Drive check: per-package findings, safe repair, and the DM text."""
import json
from unittest.mock import MagicMock

from app.services import drive_nightly_check as n


class _Svc:
    def __init__(self, media, mapped=None, parse_error=None, manifest_errors=()):
        self.media, self.mapped, self.parse_error = media, mapped or set(), parse_error
        self.manifest_errors = list(manifest_errors)
        self.refreshed = None
        self._folder_metadata_cache = {}
        drive = MagicMock()
        drive.files.return_value.get.return_value.execute.return_value = {"name": "AUTO-20V | Kitchen"}
        self._client = lambda: drive

    def _list_folder_subtree(self, pkg):
        return [{"id": "man", "name": "AUTO-20V-HANDOFF-MANIFEST.txt", "mimeType": "text/plain"}, *self.media]

    def _is_supported_media(self, mime, name):
        return name.endswith(".mp4")

    def _is_handoff_manifest_file(self, name):
        return name.endswith("HANDOFF-MANIFEST.txt")

    def _download_text_file(self, fid):
        return "manifest"

    def _folder_copy_metadata(self, pkg, force=True):
        if self.parse_error:
            raise RuntimeError(self.parse_error)
        return {"assets_by_drive_id": {fid: {} for fid in self.mapped}}

    def refresh_copy_metadata_for_drive_files(self, ids):
        self.refreshed = list(ids)


def _db(rows_first, rows_after=None):
    db = MagicMock()
    calls = [rows_first, rows_after if rows_after is not None else rows_first]
    db.execute.side_effect = lambda *a, **k: MagicMock(mappings=lambda: MagicMock(all=lambda: calls.pop(0) if calls else []))
    return db


def _media(*ids):
    return [{"id": i, "name": f"{i}-VID-9x16.mp4", "mimeType": "video/mp4"} for i in ids]


COPY = json.dumps({"copy": {"headline": "H", "primary_text": "P"}})


def _patch_validator(monkeypatch, errors=()):
    import app.services.drive_manifest_validator as v
    monkeypatch.setattr(v, "validate_handoff_manifest", lambda *a, **k: {"errors": list(errors)})


def test_parse_failure_is_reported_with_the_parsers_reason(monkeypatch):
    _patch_validator(monkeypatch)
    svc = _Svc(_media("a", "b"), parse_error="inline AD 18 is missing its 4X5 video")
    r = n.check_package(svc, _db([{"drive_file_id": "a", "soft_tags": COPY}, {"drive_file_id": "b", "soft_tags": COPY}]), "pkg")
    assert any("4X5 video" in p for p in r["problems"]) and r["fixed"] is None


def test_missing_copy_is_repaired_when_the_parser_resolves_it(monkeypatch):
    _patch_validator(monkeypatch)
    svc = _Svc(_media("a", "b"), mapped={"a", "b"})
    before = [{"drive_file_id": "a", "soft_tags": "{}"}, {"drive_file_id": "b", "soft_tags": COPY}]
    after = [{"drive_file_id": "a", "soft_tags": COPY}]
    r = n.check_package(svc, _db(before, after), "pkg")
    assert svc.refreshed == ["a"] and r["fixed"] == "copy attached to 1 of 1 file(s)" and r["problems"] == []


def test_no_repair_mode_only_reports(monkeypatch):
    _patch_validator(monkeypatch)
    svc = _Svc(_media("a"), mapped={"a"})
    r = n.check_package(svc, _db([{"drive_file_id": "a", "soft_tags": "{}"}]), "pkg", repair=False)
    assert svc.refreshed is None and any("refresh would fix" in p for p in r["problems"])


def test_unimported_files_and_manifest_errors_are_listed(monkeypatch):
    _patch_validator(monkeypatch, errors=["Line 12 (AUTO-20V-HC-B1-C1): add a HEADLINE line"])
    svc = _Svc(_media("a", "b"), mapped={"a", "b"})
    r = n.check_package(svc, _db([{"drive_file_id": "a", "soft_tags": COPY}]), "pkg")
    assert any("not in the library yet" in p for p in r["problems"])
    assert any(p.startswith("manifest: Line 12") for p in r["problems"])


def test_report_text():
    clean = n.format_report({"since_hours": 26, "packages": [], "skipped_packages": 0})
    assert "no Drive packages changed" in clean[1]
    mixed = n.format_report({"since_hours": 26, "skipped_packages": 0, "packages": [
        {"package": "AUTO-18 | Life Events", "media": 16, "problems": ["copy can't be read"], "fixed": None},
        {"package": "AUTO-20V | Kitchen", "media": 88, "problems": [], "fixed": "copy attached to 88 of 88 file(s)"},
    ]})
    assert mixed[0].endswith("needs attention")
    assert "1 ready to launch, 1 need attention, 1 auto-fixed" in mixed[1]
    assert "AUTO-18 | Life Events (16 files): copy can't be read" in mixed[2] and "fixed AUTO-20V" in mixed[2]


def test_sync_lock_collision_is_reported_as_skipped_not_failed(monkeypatch):
    _patch_validator(monkeypatch)
    from fastapi import HTTPException
    svc = _Svc(_media("a"), mapped={"a"})
    def busy(ids):
        raise HTTPException(status_code=409, detail="sync running")
    svc.refresh_copy_metadata_for_drive_files = busy
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = n.check_package(svc, _db([{"drive_file_id": "a", "soft_tags": "{}"}]), "pkg")
    assert any("a Drive sync was running" in p for p in r["problems"])
    assert not any("refresh failed" in p for p in r["problems"])


def test_manifest_mistakes_go_to_joel_and_parser_gaps_do_not(monkeypatch):
    _patch_validator(monkeypatch, errors=["Line 12 (PKG-01): 'PKG-01-1x1.jpg' isn't in the package folder in Drive."])
    joel_case = n.check_package(_Svc(_media("a", "b"), mapped={"a"}), _db([{"drive_file_id": "a", "soft_tags": COPY}, {"drive_file_id": "b", "soft_tags": COPY}]), "pkg")
    assert joel_case["joel"] == ["Line 12 (PKG-01): 'PKG-01-1x1.jpg' isn't in the package folder in Drive."]

    _patch_validator(monkeypatch)   # manifest is fine, our parser fails -> ours, not Joel's
    ours = n.check_package(_Svc(_media("a"), parse_error="unsupported layout"), _db([{"drive_file_id": "a", "soft_tags": COPY}]), "pkg")
    assert ours["joel"] == [] and any("unsupported layout" in p for p in ours["problems"])


def test_unlisted_files_are_joels_to_list(monkeypatch):
    _patch_validator(monkeypatch)
    r = n.check_package(_Svc(_media("a", "b"), mapped={"a"}), _db([{"drive_file_id": "a", "soft_tags": COPY}, {"drive_file_id": "b", "soft_tags": COPY}]), "pkg")
    assert len(r["joel"]) == 1 and "b-VID-9x16.mp4" in r["joel"][0]


def test_joel_message_only_when_there_is_something_for_him():
    assert n.format_joel_message({"packages": [{"package": "X", "joel": []}]}) is None
    summary, detail = n.format_joel_message({"packages": [{"package": "AUTO-21 | New", "joel": ["fix A", "fix B"]}]})
    assert summary.startswith("1 Drive package(s) need a fix") and "*AUTO-21 | New*" in detail and "– fix B" in detail


def test_our_problems_are_classified_separately_from_joels(monkeypatch):
    _patch_validator(monkeypatch)   # clean manifest + parser failure -> ours
    r = n.check_package(_Svc(_media("a"), parse_error="unsupported layout"), _db([{"drive_file_id": "a", "soft_tags": COPY}]), "pkg")
    assert r["joel"] == [] and len(r["ours"]) == 1 and "unsupported layout" in r["ours"][0]
    _patch_validator(monkeypatch, errors=["Line 3: missing file"])   # manifest mistake -> Joel, not ours
    r = n.check_package(_Svc(_media("a"), parse_error="no complete matching entries"), _db([{"drive_file_id": "a", "soft_tags": COPY}]), "pkg")
    assert r["ours"] == [] and r["joel"]


def test_file_our_problems_dedupes_per_package():
    db = MagicMock()
    existing = MagicMock(soft_tags={"package_id": "p1"})
    db.query.return_value.filter.return_value.all.return_value = [existing]
    result = {"packages": [
        {"package": "Old", "package_id": "p1", "media": 2, "ours": ["x"]},
        {"package": "New", "package_id": "p2", "media": 4, "ours": ["parser gap"]},
        {"package": "Clean", "package_id": "p3", "media": 1, "ours": []},
    ]}
    assert n.file_our_problems(db, result) == 1
    row = db.add.call_args[0][0]
    assert row.user_email == "drive-nightly-check" and "'New'" in row.message and row.soft_tags["package_id"] == "p2"


class _Resolved:
    def __init__(self, brand_folder):
        self.brand_folder = brand_folder


def test_unimported_files_name_a_missing_brand(monkeypatch):
    """HELOC/Splitero, 2026-11-20: files sat outside the picker for days because their Drive folder matched no
    brand, and the report only said 'not in the library yet'."""
    _patch_validator(monkeypatch)
    svc = _Svc(_media("a", "b"), mapped={"a", "b"})
    svc._resolve_drive_path = lambda meta: _Resolved("HELOC")
    svc._match_brand_id = lambda name: None
    r = n.check_package(svc, _db([]), "pkg")
    assert 'no Ad Builder brand matches the Drive folder "HELOC"' in r["problems"][0]
    assert r["joel"] == [] and r["ours"] == []      # a brand is Steve's call: not Joel's, not the fix worker's


def test_matched_brand_adds_no_brand_problem(monkeypatch):
    _patch_validator(monkeypatch)
    svc = _Svc(_media("a"), mapped={"a"})
    svc._resolve_drive_path = lambda meta: _Resolved("Auto Insurance")
    svc._match_brand_id = lambda name: "brand-1"
    r = n.check_package(svc, _db([]), "pkg")
    assert not any("no Ad Builder brand" in p for p in r["problems"])
    assert any("not in the library yet" in p for p in r["problems"])


def test_packages_still_missing_are_checked_after_they_stop_changing(monkeypatch):
    import app.services.drive_sync_service as ds
    monkeypatch.setattr(ds, "DriveSyncService", lambda db: MagicMock())
    monkeypatch.setattr(n, "_changed_files", lambda svc, since: [])
    monkeypatch.setattr(n, "_still_missing_packages", lambda db: ["old-pkg"])
    seen = []
    monkeypatch.setattr(n, "check_package", lambda svc, db, pkg, repair=True: seen.append(pkg) or
                        {"package": "HEL-W2-G", "package_id": pkg, "media": 12, "problems": ["12 file(s) not in the library yet"],
                         "joel": [], "ours": [], "fixed": None})
    result = n.run_nightly_check(MagicMock())
    assert seen == ["old-pkg"] and result["packages"][0]["carried_over"] is True
    headline, summary, detail = n.format_report(result)
    assert headline.endswith("needs attention")
    assert "no Drive packages changed" in summary and "1 older package(s) still blocked" in summary
    assert detail.startswith("• still blocked: HEL-W2-G")


def test_changed_package_is_not_double_counted_as_carried_over(monkeypatch):
    import app.services.drive_sync_service as ds
    svc = MagicMock()
    svc._resolve_drive_path.return_value = True
    svc._find_package_folder.return_value = "pkg"
    monkeypatch.setattr(ds, "DriveSyncService", lambda db: svc)
    monkeypatch.setattr(n, "_changed_files", lambda svc, since: [{"id": "f1"}])
    monkeypatch.setattr(n, "_still_missing_packages", lambda db: ["pkg"])
    monkeypatch.setattr(n, "check_package", lambda svc, db, pkg, repair=True:
                        {"package": "P", "package_id": pkg, "media": 1, "problems": [], "joel": [], "ours": [], "fixed": None})
    result = n.run_nightly_check(MagicMock())
    assert len(result["packages"]) == 1 and result["packages"][0]["carried_over"] is False


def test_still_missing_reads_the_health_snapshot():
    db = MagicMock()
    db.execute.return_value.scalar.return_value = json.dumps({"all_missing_packages": [
        {"folder_id": "a", "missing_count": 3}, {"folder_id": "b", "missing_count": 0}]})
    assert n._still_missing_packages(db) == ["a"]
    db.execute.return_value.scalar.return_value = json.dumps({"last_error": "boom", "all_missing_packages": [{"folder_id": "a", "missing_count": 3}]})
    assert n._still_missing_packages(db) == []


def test_joel_is_not_re_messaged_about_carried_over_packages():
    pkg = {"package": "Home Equity Ads for Review", "media": 8, "problems": ["x"], "joel": ["8 file(s) aren't listed"], "fixed": None}
    assert n.format_joel_message({"packages": [{**pkg, "carried_over": True}]}) is None
    assert n.format_joel_message({"packages": [{**pkg, "carried_over": False}]}) is not None


def test_malformed_snapshot_never_breaks_the_check():
    db = MagicMock()
    for bad in ({"all_missing_packages": 5}, {"all_missing_packages": [{"folder_id": {"x": 1}, "missing_count": 2}]}, [1, 2]):
        db.execute.return_value.scalar.return_value = json.dumps(bad)
        assert n._still_missing_packages(db) == []
