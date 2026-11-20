"""Nightly Drive check (11 p.m. ET): every package touched in the last day, checked before anyone launches.

For each package with a file added or changed in the last `since_hours`:
  1. Dry-run the copy parser (the same one the sync uses) and count media it can't attach copy to, with
     the parser's own reason.
  2. Run the handoff-manifest validator on the package's manifest, so a layout the sync can't read is
     named in plain words.
  3. Compare Drive media against the library: files not imported yet.
  4. Fix what is safe to fix: when the parser now resolves copy but imported files are still missing it
     (e.g. after a parser fix, or a manifest edited after import), run the same refresh the picker's
     Refresh button runs: it re-attaches copy and imports any of the package's media not yet in the
     library (Drive -> R2). Never writes to Drive or Meta.

Then one Slack DM to Steve (Drive alerts go to his DM only), also when everything is clean, so a silent
night means the job didn't run.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"


def _changed_files(svc, since: datetime, max_files: int = 2000) -> List[Dict[str, Any]]:
    drive = svc._client()
    out: List[Dict[str, Any]] = []
    page_token = None
    stamp = since.strftime("%Y-%m-%dT%H:%M:%S")
    while len(out) < max_files:
        resp = drive.files().list(
            q=f"modifiedTime > '{stamp}' and trashed = false and mimeType != '{FOLDER_MIME}'",
            corpora="allDrives",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageToken=page_token,
            pageSize=200,
            orderBy="modifiedTime desc",   # newest first, so a capped run checks the latest uploads
            fields="nextPageToken,files(id,name,mimeType,parents,modifiedTime)",
        ).execute()
        out.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    if page_token:
        logger.warning("Nightly Drive check: changed-file list truncated at %s", len(out))
        out.append({"_truncated": True})
    return out


def _has_copy(soft_tags: Any) -> bool:
    try:
        tags = json.loads(soft_tags) if isinstance(soft_tags, str) else (soft_tags or {})
    except (TypeError, ValueError):
        return False
    copy = (tags or {}).get("copy") if isinstance(tags, dict) else None
    return bool(isinstance(copy, dict) and str(copy.get("headline") or "").strip() and str(copy.get("primary_text") or "").strip())


class _SyncBusy(Exception):
    pass


def _rollback(db) -> None:
    try:
        db.rollback()
    except Exception:
        pass


def _refresh_waiting_for_sync_lock(svc, db, drive_file_ids, attempts: int = 3, wait_seconds: int = 90) -> None:
    """The refresh takes the same advisory lock as the 15-min sync and answers 409 while it is held. Wait for
    that run to finish instead of reporting a false failure."""
    import time
    for attempt in range(attempts):
        try:
            svc.refresh_copy_metadata_for_drive_files(drive_file_ids)
            return
        except Exception as exc:
            if getattr(exc, "status_code", None) != 409:
                raise
            _rollback(db)
            if attempt + 1 < attempts:
                time.sleep(wait_seconds)
    raise _SyncBusy()


def check_package(svc, db, package_id: str, repair: bool = True) -> Dict[str, Any]:
    from app.services.drive_manifest_validator import validate_handoff_manifest

    drive = svc._client()
    folder = drive.files().get(fileId=package_id, fields="name,parents", supportsAllDrives=True).execute() or {}
    name = folder.get("name") or package_id
    items = svc._list_folder_subtree(package_id)
    media = [i for i in items if svc._is_supported_media(i.get("mimeType") or "", i.get("name") or "")]
    # "joel": things only a change in Drive fixes (the manifest's wording, names, sizes). Everything else in
    # "problems" is ours to fix (parser gaps, imports, refresh) and goes to Steve only.
    # "ours": problems the Ad Builder itself has to fix (parser gaps, refresh failures, uncheckable manifests).
    # They are filed into the feedback inbox, where the Mac Mini's nightly Claude Code worker picks them up.
    report: Dict[str, Any] = {"package": name, "package_id": package_id, "media": len(media), "problems": [],
                              "joel": [], "ours": [], "fixed": None}

    # 1. parser dry run
    svc._folder_metadata_cache = {}
    mapped: set = set()
    try:
        meta = svc._folder_copy_metadata(package_id, force=True)
        mapped = set((meta.get("assets_by_drive_id") or {}).keys())
        parse_error = None
    except Exception as exc:
        parse_error = str(exc)[:200]
    unmapped = [m for m in media if m["id"] not in mapped]

    # 2. manifest validator (plain-language reasons, written for the person who edits the manifest)
    manifest_errors: List[str] = []
    for item in items:
        if svc._is_handoff_manifest_file(item.get("name") or ""):
            try:
                result = validate_handoff_manifest(
                    svc._download_text_file(item["id"]),
                    folder_media_names=[m["name"] for m in media],
                    file_name=item.get("name"),
                )
                manifest_errors.extend(result.get("errors", []))
            except Exception as exc:
                report["problems"].append(f"manifest {item.get('name')} couldn't be checked: {str(exc)[:120]}")
                report["ours"].append(f"manifest {item.get('name')} couldn't be checked: {str(exc)[:200]}")
    for error in manifest_errors[:3]:
        report["problems"].append(f"manifest: {error}")
    report["joel"].extend(manifest_errors[:5])
    if parse_error:
        report["problems"].append(f"copy can't be read for {len(media)} file(s): {parse_error}")
        if not manifest_errors:
            report["ours"].append(f"copy can't be read for {len(media)} file(s) although the manifest checks out: {parse_error}")
        # The validator shares the parser's binder: if it finds nothing to fix, the gap is ours, not Joel's.
    elif unmapped:
        sample = ", ".join(m["name"] for m in unmapped[:3])
        report["problems"].append(f"{len(unmapped)} file(s) aren't in the copy manifest (e.g. {sample})")
        if not manifest_errors:
            report["joel"].append(
                f"{len(unmapped)} file(s) aren't listed in the manifest, so they have no copy: "
                + ", ".join(m["name"] for m in unmapped[:5]) + (" …" if len(unmapped) > 5 else "")
            )

    # 3. library comparison
    ids = [m["id"] for m in media]
    rows = {}
    if ids:
        rows = {
            r["drive_file_id"]: r for r in db.execute(
                text("SELECT drive_file_id, soft_tags FROM drive_assets WHERE drive_file_id = ANY(:ids) AND COALESCE(archived, FALSE) = FALSE"),
                {"ids": ids},
            ).mappings().all()
        }
    not_imported = [m for m in media if m["id"] not in rows]
    if not_imported:
        report["problems"].append(
            f"{len(not_imported)} file(s) not in the library yet (e.g. {', '.join(m['name'] for m in not_imported[:3])})"
        )
        # Name the one cause no re-sync can fix: the package's top-level Drive folder matches no brand.
        brand_folder = _unmatched_brand_folder(svc, package_id, folder)
        if brand_folder:
            report["problems"].insert(0, (
                f'no Ad Builder brand matches the Drive folder "{brand_folder}", so these files can\'t be imported. '
                f"Create a brand with that name (or one ending in ' - {brand_folder}') and the next sync picks them up"
            ))

    # 4. safe repair: parser resolves copy, library rows lack it
    missing_copy = [fid for fid, r in rows.items() if fid in mapped and not _has_copy(r["soft_tags"])]
    if missing_copy and repair:
        try:
            _refresh_waiting_for_sync_lock(svc, db, missing_copy)
            db.expire_all()
            still = db.execute(
                text("SELECT drive_file_id, soft_tags FROM drive_assets WHERE drive_file_id = ANY(:ids)"),
                {"ids": missing_copy},
            ).mappings().all()
            fixed = sum(1 for r in still if _has_copy(r["soft_tags"]))
            report["fixed"] = f"copy attached to {fixed} of {len(missing_copy)} file(s)"
            if fixed < len(missing_copy):
                report["problems"].append(f"{len(missing_copy) - fixed} imported file(s) still have no copy after a refresh")
                report["ours"].append(f"{len(missing_copy) - fixed} imported file(s) still have no copy after a refresh")
        except _SyncBusy:
            report["problems"].append(f"{len(missing_copy)} imported file(s) have no copy; refresh skipped because a Drive sync was running (will retry tomorrow, or press Refresh)")
        except Exception as exc:
            _rollback(db)
            report["problems"].append(f"copy refresh failed for {len(missing_copy)} file(s): {str(exc)[:150]}")
            report["ours"].append(f"copy refresh failed for {len(missing_copy)} file(s): {str(exc)[:200]}")
    elif missing_copy:
        report["problems"].append(f"{len(missing_copy)} imported file(s) have no copy (refresh would fix)")
    return report


def _unmatched_brand_folder(svc, package_id: str, folder: Dict[str, Any]) -> Optional[str]:
    """The package's top-level Drive (brand) folder name when no brands row matches it, else None.
    Best effort: a lookup failure must not hide the rest of the package's report."""
    try:
        resolved = svc._resolve_drive_path({"id": package_id, "parents": folder.get("parents") or []})
        if resolved and resolved.brand_folder and not svc._match_brand_id(resolved.brand_folder):
            return resolved.brand_folder
    except Exception as exc:
        logger.warning("Nightly Drive check: couldn't resolve the brand folder for %s: %s", package_id, exc)
    return None


def _still_missing_packages(db) -> List[str]:
    """Package folders the hourly Package Health snapshot still shows with files missing from the picker.
    Checked every night until they clear, not only on the night they changed (a package blocked by a missing
    brand otherwise drops out of the report after 26h while still unusable)."""
    try:
        from app.api.v1.drive_health import STATE_KEY
        raw = db.execute(text("SELECT value FROM drive_sync_state WHERE key = :k"), {"k": STATE_KEY}).scalar()
        snapshot = json.loads(raw) if raw else {}
        if not isinstance(snapshot, dict) or snapshot.get("last_error"):
            return []
        return [p["folder_id"] for p in (snapshot.get("all_missing_packages") or [])
                if isinstance(p, dict) and isinstance(p.get("folder_id"), str) and p["folder_id"] and p.get("missing_count")]
    except Exception as exc:    # a malformed snapshot must never stop the nightly check itself
        _rollback(db)
        logger.warning("Nightly Drive check: couldn't read the package health snapshot: %s", exc)
        return []


def run_nightly_check(db, since_hours: int = 26, max_packages: int = 40, repair: bool = True,
                      now: Optional[datetime] = None) -> Dict[str, Any]:
    from app.services.drive_sync_service import DriveSyncService

    svc = DriveSyncService(db)
    since = (now or datetime.now(timezone.utc)) - timedelta(hours=since_hours)
    packages: Dict[str, None] = {}
    truncated = False
    for f in _changed_files(svc, since):
        if f.get("_truncated"):
            truncated = True
            continue
        try:
            if not svc._resolve_drive_path(f):        # outside the Ad Builder's Drive root
                continue
            pkg = svc._find_package_folder(f)
        except Exception as exc:
            logger.warning("Nightly Drive check: couldn't place %s: %s", f.get("name"), exc)
            continue
        if pkg:
            packages.setdefault(pkg, None)
    changed = set(packages)
    for pkg in _still_missing_packages(db):      # after the changed ones, so they keep priority under the cap
        packages.setdefault(pkg, None)
    reports = []
    for pkg in list(packages)[:max_packages]:
        try:
            report = check_package(svc, db, pkg, repair=repair)
        except Exception as exc:
            _rollback(db)   # one shared session: an aborted transaction must not fail every later package
            report = {"package": pkg, "package_id": pkg, "media": 0, "problems": [f"check failed: {str(exc)[:150]}"],
                      "joel": [], "ours": [f"check failed: {str(exc)[:200]}"], "fixed": None}
        report["carried_over"] = pkg not in changed
        reports.append(report)
    return {"since_hours": since_hours, "packages": reports, "skipped_packages": max(0, len(packages) - max_packages),
            "truncated": truncated}


def format_report(result: Dict[str, Any]) -> tuple[str, str, str]:
    reports = result["packages"]
    bad = [r for r in reports if r["problems"]]
    fixed = [r for r in reports if r.get("fixed")]
    if not reports:
        return "Drive nightly check", f"no Drive packages changed in the last {result['since_hours']}h.", ""
    changed = [r for r in reports if not r.get("carried_over")]
    carried = [r for r in reports if r.get("carried_over")]
    carried_bad = [r for r in carried if r["problems"]]
    if changed:
        changed_bad = [r for r in changed if r["problems"]]
        summary = (f"{len(changed)} package(s) changed in the last {result['since_hours']}h — "
                   f"{len(changed) - len(changed_bad)} ready to launch, {len(changed_bad)} need attention")
    else:
        summary = f"no Drive packages changed in the last {result['since_hours']}h"
    if carried_bad:
        summary += f"; {len(carried_bad)} older package(s) still blocked"
    cleared = len(carried) - len(carried_bad)
    if cleared:
        summary += f"; {cleared} older package(s) now clear"
    summary += (f", {len(fixed)} auto-fixed" if fixed else "") + "."
    lines = []
    for r in bad:
        tag = "still blocked: " if r.get("carried_over") else ""
        lines.append(f"• {tag}{r['package']} ({r['media']} files): " + "; ".join(r["problems"][:3]))
    for r in fixed:
        lines.append(f"• fixed {r['package']}: {r['fixed']}")
    if result.get("truncated"):
        lines.append("• more than 2,000 files changed; only the newest were checked.")
    if result.get("skipped_packages"):
        lines.append(f"• {result['skipped_packages']} more changed package(s) not checked tonight (cap).")
    headline = "Drive nightly check" if not bad else "Drive nightly check — needs attention"
    return headline, summary, "\n".join(lines)


JOEL_SLACK_ID = "U08HPNNGHBJ"


def format_joel_message(result: Dict[str, Any]) -> Optional[tuple[str, str]]:
    """Only the fixes Joel can make in Drive; None when there are none (nothing is sent). Packages carried over
    from earlier nights are left out: Joel hears about a package the night it changes, never nightly after."""
    packages = [r for r in result["packages"] if r.get("joel") and not r.get("carried_over")]
    if not packages:
        return None
    summary = (f"{len(packages)} Drive package(s) need a fix before those ads can launch. "
               "Once it's fixed in Drive, the Ad Builder picks it up on its own.")
    lines = []
    for r in packages:
        lines.append(f"• *{r['package']}*")
        lines.extend(f"    – {issue}" for issue in r["joel"][:5])
    return summary, "\n".join(lines)


def file_our_problems(db, result: Dict[str, Any]) -> int:
    """Put tonight's "ours" problems in the feedback inbox (one row per package, skipped while an open row for
    that package already exists) so the Mac Mini's nightly Claude Code worker works them with everything else."""
    from app.models import AppFeedback
    filed = 0
    for r in result["packages"]:
        if not r.get("ours"):
            continue
        open_rows = db.query(AppFeedback).filter(
            AppFeedback.user_email == "drive-nightly-check",
            AppFeedback.status.in_(("new", "in_progress")),
        ).all()
        if any((row.soft_tags or {}).get("package_id") == r.get("package_id") for row in open_rows):
            continue
        db.add(AppFeedback(
            user_email="drive-nightly-check",
            page_path="/libraries",
            message=(f"Drive nightly check: package '{r['package']}' ({r['media']} files) has a problem the Ad Builder "
                     "must fix (not a manifest mistake):\n- " + "\n- ".join(r["ours"][:5])),
            context={"source": "drive_nightly_check", "package": r["package"]},
            soft_tags={"source": "drive_nightly_check", "package_id": r.get("package_id")},
        ))
        filed += 1
    if filed:
        db.commit()
    return filed
