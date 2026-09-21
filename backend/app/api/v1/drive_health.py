"""Read-only structural health report for synced Google Drive ad packages."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import User
from app.services.drive_sync_service import DriveSyncService

router = APIRouter()

_CACHE_TTL = timedelta(minutes=5)
_cache_lock = Lock()
_cache: Optional[Tuple[datetime, Dict[str, Any]]] = None


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
        "chain_ids": {folder.get("id") for folder in relative if folder.get("id")},
    }


def _copy_source_for_text(service: DriveSyncService, item: Dict[str, Any]) -> Optional[str]:
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
            media_by_basename[(package["brand_id"] or package["brand_name"], name.lower())].add(package["folder_id"])
        elif service._is_text_file(mime_type, name):
            text_items.append(item)

    source_rank = {"none": 0, "category_doc": 1, "strategy_doc": 2, "handoff_manifest": 3}
    for item in text_items:
        chain = service._parent_chain(item) or []
        package_id = next((folder.get("id") for folder in reversed(chain) if folder.get("id") in packages), None)
        if not package_id:
            continue
        source = _copy_source_for_text(service, item)
        if not source:
            continue
        record = packages[package_id]
        record["has_manifest"] = record["has_manifest"] or source == "handoff_manifest"
        if source_rank[source] > source_rank[record["copy_source"]]:
            record["copy_source"] = source

    collisions = []
    packages_with_cross_collision = set()
    for (_brand, basename), package_ids in sorted(media_by_basename.items()):
        if len(package_ids) < 2:
            continue
        paths = sorted(packages[package_id]["path"] for package_id in package_ids)
        collisions.append({"basename": basename, "packages": paths})
        packages_with_cross_collision.update(package_ids)

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
    global _cache
    now = datetime.now(timezone.utc)
    with _cache_lock:
        if _cache and now - _cache[0] < _CACHE_TTL:
            return _cache[1]
        try:
            report = build_package_health_report(DriveSyncService(db))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not inspect Drive package health: {exc}") from exc
        _cache = (now, report)
        return report
