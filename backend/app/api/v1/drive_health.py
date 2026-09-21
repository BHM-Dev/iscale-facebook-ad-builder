"""Read-only structural health report for synced Google Drive ad packages."""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user
from app.database import SessionLocal, get_db
from app.models import User
from app.services.drive_sync_service import DriveSyncService

logger = logging.getLogger(__name__)

router = APIRouter()

STATE_KEY = "package_health_report"

# Guards against two rebuilds running at once. Not a cache lock: the snapshot
# itself lives in Postgres, so it survives the container recreate that happens on
# every deploy -- an in-memory cache meant the first person to open the page after
# each deploy paid the full multi-minute walk.
_rebuild_lock = Lock()
_rebuilding = False


def _read_snapshot(db: Session) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text("SELECT value FROM drive_sync_state WHERE key = :key"),
        {"key": STATE_KEY},
    ).first()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        logger.warning("Stored Drive package health snapshot was not valid JSON")
        return None


def _write_snapshot(db: Session, report: Dict[str, Any]) -> None:
    db.execute(
        text(
            """
            INSERT INTO drive_sync_state (key, value, updated_at)
            VALUES (:key, :value, NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = NOW()
            """
        ),
        {"key": STATE_KEY, "value": json.dumps(report)},
    )
    db.commit()


def _record_failed_attempt(db: Session, message: str) -> None:
    """Stamp the failure onto the stored snapshot without discarding it.

    A rebuild that dies used to leave the previous snapshot in place with its old
    generated_at, so the page served a stale report as current and nothing said
    otherwise. If the Drive credentials expire, that means a months-old report
    presented under a green summary bar, indefinitely.
    """
    snapshot = _read_snapshot(db) or {"packages": [], "collisions": [], "generated_at": None}
    snapshot["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
    snapshot["last_error"] = message
    _write_snapshot(db, snapshot)


def refresh_package_health_snapshot(db: Session) -> Dict[str, Any]:
    """Build the report and persist it. Called by the scheduler and by a manual rebuild.

    Records the outcome either way: a silent failure that leaves yesterday's
    snapshot looking authoritative is the failure mode this page exists to avoid.
    """
    with _rebuild_lock:
        global _rebuilding
        _rebuilding = True
    try:
        report = build_package_health_report(DriveSyncService(db))
        report["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
        report["last_error"] = None
        _write_snapshot(db, report)
        return report
    except Exception as exc:
        try:
            _record_failed_attempt(db, str(exc)[:500] or exc.__class__.__name__)
        except Exception:
            logger.exception("Could not record Drive package health failure")
        raise
    finally:
        with _rebuild_lock:
            _rebuilding = False


def _rebuild_in_background() -> None:
    """Run a rebuild on its own session. Measured at ~285s against the live Drive,
    which is why it never runs inside a request."""
    global _rebuilding
    db = None
    try:
        # Inside the try: if SessionLocal() itself raises (pool exhausted, DB blip)
        # the thread would die before any finally and leave _rebuilding stuck True
        # with no thread behind it -- permanently refusing every later rebuild.
        db = SessionLocal()
        refresh_package_health_snapshot(db)
        logger.info("Drive package health snapshot rebuilt")
    except Exception:
        logger.exception("Drive package health rebuild failed")
    finally:
        if db is not None:
            db.close()
        with _rebuild_lock:
            _rebuilding = False


def _is_placement_folder(name: str) -> bool:
    normalized = " ".join((name or "").lower().replace("_", " ").split())
    return normalized.startswith(("1x1", "9x16", "4x5", "16x9"))


def _package_for_media(service: DriveSyncService, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve the containing package without writing or refreshing Drive data."""
    chain = service._parent_chain(item) or []
    root_index = next((i for i, folder in enumerate(chain) if folder.get("id") == service.root_folder_id), None)
    if root_index is None:
        return None
    relative = chain[root_index + 1:]
    # A package must live under a brand folder. Files directly under the sync
    # root are intentionally excluded from the report rather than guessed at.
    if len(relative) < 2:
        return None

    brand = relative[0]
    parent = relative[-1]
    package = relative[-2] if _is_placement_folder(parent.get("name", "")) else parent
    package_index = relative.index(package)
    return {
        "folder_id": package["id"],
        "path": " / ".join(folder.get("name") or "Unnamed folder" for folder in relative[:package_index + 1]),
        "depth": root_index + package_index + 2,
        "brand_id": brand.get("id"),
        "brand_name": brand.get("name") or "Unnamed brand",
        "is_direct_media": package["id"] == parent.get("id"),
        "is_placement_media": _is_placement_folder(parent.get("name", "")),
    }


def _copy_source_for_text(service: DriveSyncService, item: Dict[str, Any]) -> Optional[str]:
    """Classify a text document by content. Downloads -- callers should skip it
    for any package already resolved by the name-only manifest pass."""
    name = (item.get("name") or "").lower()
    if "handoff" in name and "manifest" in name:
        return "handoff_manifest"
    try:
        text = service._download_text_file(item["id"])
    except Exception:
        # An unreadable document is not treated as a source. The report's
        # no_copy_source flag deliberately makes that visible to its owner.
        return None
    if service._looks_like_strategy_copy_doc(text) or service._looks_like_ad_copy_doc(text):
        return "strategy_doc"
    if service._looks_like_category_copy_doc(text):
        return "category_doc"
    return None


def build_package_health_report(service: DriveSyncService) -> Dict[str, Any]:
    """Build a Drive-only report; this function has no DB or Drive write path."""
    drive = service._client()
    files = service._initial_folder_walk(drive)
    packages: Dict[str, Dict[str, Any]] = {}
    media_by_basename: Dict[Tuple[str, str], set[str]] = defaultdict(set)
    basename_display: Dict[Tuple[str, str], str] = {}
    text_items: List[Dict[str, Any]] = []

    for item in files:
        name = item.get("name") or ""
        mime_type = item.get("mimeType") or ""
        if service._is_supported_media(mime_type, name):
            package = _package_for_media(service, item)
            if not package:
                continue
            record = packages.setdefault(package["folder_id"], {
                **package,
                "media": [],
                "copy_source": "none",
                "has_manifest": False,
                "has_direct_media": False,
                "has_placement_media": False,
            })
            record["media"].append(item)
            record["has_direct_media"] = record["has_direct_media"] or package["is_direct_media"]
            record["has_placement_media"] = record["has_placement_media"] or package["is_placement_media"]
                # Key on the lowercased name (collision detection is case-insensitive)
            # but keep a real spelling for display -- this is the string someone
            # pastes into Drive search, and a lowercased one won't match the folder.
            key = (package["brand_id"] or package["brand_name"], name.lower())
            media_by_basename[key].add(package["folder_id"])
            basename_display.setdefault(key, name)
        elif service._is_text_file(mime_type, name):
            text_items.append(item)

    source_rank = {"none": 0, "category_doc": 1, "strategy_doc": 2, "handoff_manifest": 3}

    # Resolve each text file to its package once, and drop the ones that sit
    # outside any media-bearing package -- those can never contribute a source.
    owned_text: List[Tuple[str, Dict[str, Any]]] = []
    for item in text_items:
        chain = service._parent_chain(item) or []
        package_id = next((folder.get("id") for folder in reversed(chain) if folder.get("id") in packages), None)
        if package_id:
            owned_text.append((package_id, item))

    # Pass 1 is free: a handoff manifest is identified by FILENAME alone, no
    # download. It is also the highest-ranked source, so any package matched here
    # is finished and pass 2 can skip every other document it contains.
    for package_id, item in owned_text:
        name = (item.get("name") or "").lower()
        if "handoff" in name and "manifest" in name:
            record = packages[package_id]
            record["has_manifest"] = True
            record["copy_source"] = "handoff_manifest"

    # Pass 2 downloads, so it is the expensive one. Only packages with no source
    # yet are worth inspecting, and each stops at its first recognized document.
    # Without this the report downloaded every text file in the tree on every
    # build -- measured at over ten minutes against the live Drive, far past any
    # sane HTTP timeout.
    for package_id, item in owned_text:
        record = packages[package_id]
        if record["copy_source"] != "none":
            continue
        source = _copy_source_for_text(service, item)
        if not source:
            continue
        if source_rank[source] > source_rank[record["copy_source"]]:
            record["copy_source"] = source

    collisions = []
    packages_with_cross_collision = set()
    for key, package_ids in sorted(media_by_basename.items()):
        if len(package_ids) < 2:
            continue
        entries = sorted(
            ({"folder_id": pid, "path": packages[pid]["path"]} for pid in package_ids),
            key=lambda entry: entry["path"].lower(),
        )
        collisions.append({
            "basename": basename_display.get(key, key[1]),
            "packages": [entry["path"] for entry in entries],
            # folder_ids let the UI deep-link each package straight into Drive
            # instead of making someone hunt for the path by hand.
            "package_folders": entries,
        })
        packages_with_cross_collision.update(package_ids)

    collisions.sort(key=lambda entry: (-len(entry["packages"]), entry["basename"].lower()))

    result_packages = []
    for package_id, record in sorted(packages.items(), key=lambda pair: pair[1]["path"].lower()):
        names = [item.get("name", "").lower() for item in record["media"]]
        issues = []
        if record["copy_source"] == "none":
            issues.append("no_copy_source")
        if record["has_direct_media"] and not record["has_placement_media"] and not record["has_manifest"]:
            issues.append("flat_package")
        if package_id in packages_with_cross_collision:
            issues.append("duplicate_basename_across_packages")
        if len(names) != len(set(names)):
            issues.append("duplicate_basename_within_package")
        result_packages.append({
            "folder_id": package_id,
            "path": record["path"],
            "depth": record["depth"],
            "media_count": len(record["media"]),
            "has_manifest": record["has_manifest"],
            "copy_source": record["copy_source"],
            "issues": issues,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "packages": result_packages,
        "collisions": collisions,
    }


@router.get("/package-health")
def get_drive_package_health(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
):
    """Return the last persisted Drive package health snapshot.

    This is a single fast query on purpose. Building the report walks the whole
    Drive tree and was measured at ~285 seconds against production, far past any
    sane HTTP timeout -- so it is built by the scheduler (and by an explicit
    rebuild) and only ever read here.
    """
    snapshot = _read_snapshot(db)
    with _rebuild_lock:
        rebuilding = _rebuilding
    if snapshot and snapshot.get("generated_at"):
        # Hourly job, so anything older than two hours means rebuilds are failing
        # or the scheduler is not running. Either way the reader must be told.
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(snapshot["generated_at"])
            snapshot["stale"] = age > timedelta(hours=2)
            snapshot["age_seconds"] = int(age.total_seconds())
        except (TypeError, ValueError):
            snapshot["stale"] = True
            snapshot["age_seconds"] = None
    if not snapshot:
        # 200 with an explicit status, not an error: "not built yet" is a normal
        # state on a fresh database, and it must not render as a clean bill of health.
        return {
            "status": "pending",
            "rebuilding": rebuilding,
            "generated_at": None,
            "stale": False,
            "last_error": None,
            "packages": [],
            "collisions": [],
        }
    return {**snapshot, "status": "ready", "rebuilding": rebuilding}


@router.post("/package-health/refresh", status_code=202)
def refresh_drive_package_health(
    _current_user: User = Depends(get_current_active_user),
):
    """Kick off a rebuild and return immediately; the page polls the GET above.

    The rename-then-verify loop this page exists for needs a way to force a fresh
    read, but the build is minutes long, so it cannot happen inside the request.
    """
    global _rebuilding
    with _rebuild_lock:
        if _rebuilding:
            return {"status": "already_rebuilding"}
        _rebuilding = True
    try:
        threading.Thread(target=_rebuild_in_background, name="drive-health-rebuild", daemon=True).start()
    except Exception:
        # Clear the flag we just set, or the POST refuses every later attempt.
        with _rebuild_lock:
            _rebuilding = False
        logger.exception("Could not start Drive package health rebuild")
        raise HTTPException(status_code=503, detail="Could not start the Drive inspection. Try again shortly.")
    return {"status": "rebuilding"}
