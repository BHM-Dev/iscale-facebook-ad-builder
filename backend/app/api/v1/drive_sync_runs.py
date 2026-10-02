"""Read-only view of the Drive sync audit trail (`drive_sync_runs`)."""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import User

router = APIRouter()


@router.get("/sync-runs")
def list_drive_sync_runs(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
) -> Dict[str, List[Dict[str, Any]]]:
    """Newest-first Drive sync runs. An absent table reads as "no runs yet"."""
    try:
        rows = db.execute(
            text(
                """
                SELECT id, kind, started_at, finished_at, status, processed, created,
                       updated, archived, errors, error_summary, triggered_by
                FROM drive_sync_runs
                ORDER BY started_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
    except ProgrammingError:  # table not migrated yet; any other DB error should surface
        db.rollback()
        return {"runs": []}
    runs = []
    for row in rows:
        item = dict(row)
        for key in ("started_at", "finished_at"):
            item[key] = item[key].isoformat() if item.get(key) else None
        runs.append(item)
    return {"runs": runs}
