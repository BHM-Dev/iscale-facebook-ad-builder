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
