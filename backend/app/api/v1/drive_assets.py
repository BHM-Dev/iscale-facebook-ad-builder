from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import User
from app.schemas.drive_assets import DriveAsset, DriveCopyHealth, DriveCopyRefreshRequest, DriveSyncResult
from app.services.drive_sync_service import DriveSyncService

router = APIRouter()


def _table_exists(db: Session, table_name: str) -> bool:
    return bool(
        db.execute(
            text("SELECT to_regclass(:table_name) IS NOT NULL"),
            {"table_name": table_name},
        ).scalar()
    )


@router.get("", response_model=List[DriveAsset])
def list_drive_assets(
    response: Response,
    brand_id: Optional[str] = None,
    product_id: Optional[str] = None,
    format: Optional[str] = Query(default=None, pattern="^(image|video)$"),
    archived: bool = False,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
):
    # The picker reads this immediately after a copy refresh.  Without an
    # explicit response policy, browsers may reuse a heuristic-cached GET and
    # render stale copy metadata even though the refresh committed correctly.
    # This is operational launch state, so it must never be cached by a client
    # or intermediary.
    response.headers["Cache-Control"] = "no-store"
    if not _table_exists(db, "drive_assets"):
        raise HTTPException(
            status_code=503,
            detail="Drive asset table is not installed yet. Apply the migration before using Creative Library.",
        )

    clauses = ["COALESCE(da.archived, FALSE) = :archived"]
    params = {"archived": archived}
    if brand_id:
        clauses.append("da.brand_id = :brand_id")
        params["brand_id"] = brand_id
    if product_id:
        clauses.append("da.product_id = :product_id")
        params["product_id"] = product_id
    if format:
        clauses.append("da.format = :format")
        params["format"] = format

    rows = db.execute(
        text(
            f"""
            SELECT
                da.id,
                da.drive_file_id,
                da.brand_id,
                b.name AS brand_name,
                da.product_id,
                da.format,
                da.folder_path,
                da.file_name,
                da.r2_key,
                da.thumbnail_r2_key,
                da.drive_modified_time,
                da.synced_at,
                da.archived,
                da.soft_tags,
                da.variant,
                da.geo
            FROM drive_assets da
            LEFT JOIN brands b ON b.id = da.brand_id
            WHERE {" AND ".join(clauses)}
            ORDER BY b.name ASC, da.folder_path ASC NULLS FIRST, da.synced_at DESC
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.post("/sync-now", response_model=DriveSyncResult)
def sync_drive_assets_now(
    backfill: bool = Query(default=False),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
):
    try:
        return DriveSyncService(db).sync_once(backfill=backfill)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/copy-health", response_model=DriveCopyHealth)
def get_drive_copy_health(
    response: Response,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
):
    """Expose named copy exceptions after every sync or manual refresh."""
    response.headers["Cache-Control"] = "no-store"
    if not _table_exists(db, "drive_assets"):
        raise HTTPException(status_code=503, detail="Drive asset table is not installed yet.")
    return DriveSyncService(db).get_copy_health_summary()


@router.post("/refresh-copy-metadata", response_model=DriveSyncResult)
def refresh_drive_copy_metadata(
    payload: DriveCopyRefreshRequest = Body(default_factory=DriveCopyRefreshRequest),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
):
    """Re-match imported media to the current Drive copy sources.

    This is intentionally independent of the incremental changes checkpoint.
    A buyer pressing Refresh needs the current documents now; replaying a large
    historic changes backlog can otherwise leave the button spinning before it
    reaches the edit they just made.
    """
    try:
        service = DriveSyncService(db)
        if payload.skip_full_refresh:
            return DriveSyncResult(copy_health=service.get_copy_health_summary())
        if payload.source_file_ids and not payload.force_full_refresh:
            return service.refresh_copy_metadata_for_sources(payload.source_file_ids)
        return service.refresh_copy_metadata()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
