"""Persistent audit trail for Drive sync runs.

Container stdout is wiped on every deploy (`up -d --build` recreates the
container), which is why the 2026-10-02 CA-PROVEN miss has no recoverable cause.
Each sync/reconcile/refresh run therefore writes one row to `drive_sync_runs`.

Hard rule: logging must never be able to change the outcome of a sync. Rows are
written through an independent session (the caller's transaction may have rolled
back), and every failure here is swallowed.
"""
import functools
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_COUNT_KEYS = ("processed", "created", "updated", "archived", "errors")


def _write_row(db, kind: str, started_at: datetime, status: str, result: Optional[dict], error: Optional[str]) -> None:
    try:
        counts = {key: int((result or {}).get(key) or 0) for key in _COUNT_KEYS}
        if not error:
            # Informational, not a failure: the run succeeded but skipped things a human should
            # know about. Prefixed "Note:" so an ok run's summary is never mistaken for an error.
            notes = []
            unmatched = int((result or {}).get("unmatched_brand") or 0)
            if unmatched:
                names = ", ".join((result or {}).get("unmatched_brand_names") or [])
                notes.append(f"{unmatched} file(s) skipped: folder matches no brand" + (f" ({names})" if names else ""))
            shortcuts = int((result or {}).get("shortcuts_skipped") or 0)
            if shortcuts:
                names = ", ".join((result or {}).get("shortcut_names") or [])
                notes.append(
                    f"{shortcuts} Drive shortcut(s) to a file or folder ignored; put the real file (not a shortcut) in the package folder"
                    + (f" ({names})" if names else "")
                )
            ghosts = int((result or {}).get("ghosts_archived") or 0)
            if ghosts:
                notes.append(f"{ghosts} library row(s) retired because their Drive file is gone")
            if (result or {}).get("ghost_mass_event"):
                notes.append(
                    f"{(result or {}).get('ghost_candidates')} library rows are missing from the Drive walk; "
                    "not archived (looks like a Drive sharing change, check the service account's access)"
                )
            if (result or {}).get("ledger_unsaved"):
                notes.append("the retry list could not be saved, so this run's failures may not be retried")
            if notes:
                error = "Note: " + "; ".join(notes)
        run_db = Session(bind=db.get_bind())
        try:
            run_db.execute(
                text(
                    """
                    INSERT INTO drive_sync_runs
                        (kind, started_at, finished_at, status, processed, created, updated, archived, errors, error_summary)
                    VALUES
                        (:kind, :started_at, :finished_at, :status, :processed, :created, :updated, :archived, :errors, :error_summary)
                    """
                ),
                {
                    "kind": kind,
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "status": status,
                    "error_summary": (error or "")[:500] or None,
                    **counts,
                },
            )
            run_db.commit()
        finally:
            run_db.close()
    except Exception:  # noqa: BLE001 - see module docstring
        logger.warning("Could not record Drive sync run (%s)", kind, exc_info=True)


def logged_run(db, kind: str, fn: Callable[[], Any]) -> Any:
    """Run `fn`, then record one `drive_sync_runs` row describing the outcome."""
    started_at = datetime.now(timezone.utc)
    status, result, error = "ok", None, None
    try:
        result = fn()
        if isinstance(result, dict) and result.get("ran") is False:
            status = "skipped_locked"
        elif isinstance(result, dict) and result.get("errors"):
            status = "ok_with_errors"
        return result
    except HTTPException as exc:
        # "Already running" is contention, not a failure.
        status = "skipped_locked" if exc.status_code == 409 else "error"
        error = None if exc.status_code == 409 else f"HTTP {exc.status_code}: {exc.detail}"
        raise
    except Exception as exc:  # noqa: BLE001 - re-raised below
        status, error = "error", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _write_row(db, kind, started_at, status, result if isinstance(result, dict) else None, error)


def logged_method(kind):
    """Decorator for DriveSyncService methods. `kind` is a string or a callable
    taking the call's (self, *args, **kwargs) and returning one."""
    def decorator(method):
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            resolved = kind(self, *args, **kwargs) if callable(kind) else kind
            return logged_run(getattr(self, "db", None), resolved, lambda: method(self, *args, **kwargs))
        return wrapper
    return decorator
