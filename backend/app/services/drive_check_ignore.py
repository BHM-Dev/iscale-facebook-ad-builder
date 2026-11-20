"""Drive packages Steve has said are not launch packages (e.g. a review folder), so the Drive checks stop
flagging them. Stored as data in drive_sync_state, not in code, so a folder can be added without a deploy:

    [{"folder_id": "<Drive folder id>", "path": "<drive_assets.folder_path of the package>", "why": "..."}]

`folder_id` is what the nightly check compares; `path` is what copy health compares (it only sees stored rows).
Files in an ignored package still sync and stay pickable; only the warnings about them stop.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from sqlalchemy import text

logger = logging.getLogger(__name__)
STATE_KEY = "check_ignored_packages"


def load(db) -> List[Dict[str, Any]]:
    """Never raises: a broken ignore list must not stop a sync or the nightly check (it just ignores nothing).
    The read runs in a SAVEPOINT: copy health calls this inside a sync's open transaction, so a failed read
    must only undo itself, never the sync's uncommitted work (no full rollback here)."""
    try:
        with db.begin_nested():
            raw = db.execute(text("SELECT value FROM drive_sync_state WHERE key = :k"), {"k": STATE_KEY}).scalar()
    except Exception as exc:
        logger.warning("Drive check ignore list unreadable: %s", exc)
        return []
    try:
        items = json.loads(raw) if raw else []
    except (TypeError, ValueError) as exc:
        logger.warning("Drive check ignore list is not valid JSON: %s", exc)
        return []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def folder_ids(items: List[Dict[str, Any]]) -> set:
    return {i["folder_id"] for i in items if isinstance(i.get("folder_id"), str) and i["folder_id"]}


def paths(items: List[Dict[str, Any]]) -> List[str]:
    return [i["path"].strip("/") for i in items if isinstance(i.get("path"), str) and i["path"].strip("/")]


def path_is_ignored(folder_path: str, ignored_paths: List[str]) -> bool:
    p = (folder_path or "").strip("/")
    return any(p == ig or p.startswith(ig + "/") for ig in ignored_paths)
