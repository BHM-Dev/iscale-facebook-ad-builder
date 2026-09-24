from typing import List, Optional

import os
import tempfile

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import User
from app.schemas.drive_assets import DriveAsset, DriveCopyHealth, DriveCopyRefreshRequest, DriveSyncResult
from app.services.drive_sync_service import DriveSyncService


MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_VIDEO_SIZE = 500 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm"}

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


@router.post("/upload", response_model=DriveAsset)
def upload_drive_asset(
    file: UploadFile = File(...),
    brand_id: str = Form(...),
    placement: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
):
    """Add a new file to the shared Drive-backed Creative Library.

    This intentionally does not use the generic uploads endpoint: a launch
    creative must remain a Drive asset so it gets the same R2 mirror, folder
    provenance, pairing checks, and picker behavior as every other selection.
    """
    filename = (file.filename or "").split("/")[-1].split("\\")[-1]
    mime_type = file.content_type or ""
    is_video = mime_type.startswith("video/")
    extension = os.path.splitext(filename)[1].lower()
    allowed_extensions = ALLOWED_VIDEO_EXTENSIONS if is_video else ALLOWED_IMAGE_EXTENSIONS
    if not (mime_type.startswith("image/") or is_video) or extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Only image and video files can be added to Creative Library")
    if placement not in (None, "1x1", "9x16"):
        raise HTTPException(status_code=400, detail="Placement must be 1x1 or 9x16")
    if is_video and placement is None:
        raise HTTPException(status_code=400, detail="Choose Feed (1:1) or Stories/Reels (9:16) for a video")
    max_size = MAX_VIDEO_SIZE if is_video else MAX_IMAGE_SIZE
    temp_path = None

    try:
        # UploadFile is already a spooled temporary file. Copy in bounded chunks
        # to a real file so Drive and R2 can stream a 500MB video without putting
        # multiple full copies in RAM.
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = temp_file.name
            total = 0
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > max_size:
                    raise HTTPException(
                        status_code=400,
                        detail=f"File is too large. Maximum is {max_size // (1024 * 1024)}MB for {'videos' if is_video else 'images'}.",
                    )
                temp_file.write(chunk)
        drive_file_id = DriveSyncService(db).import_uploaded_media(
            file_path=temp_path,
            file_name=filename,
            mime_type=mime_type,
            brand_id=brand_id,
            placement=placement,
        )
        row = db.execute(
            text(
                """
                SELECT da.id, da.drive_file_id, da.brand_id, b.name AS brand_name,
                       da.product_id, da.format, da.folder_path, da.file_name,
                       da.r2_key, da.thumbnail_r2_key, da.drive_modified_time,
                       da.synced_at, da.archived, da.soft_tags, da.variant, da.geo
                FROM drive_assets da
                LEFT JOIN brands b ON b.id = da.brand_id
                WHERE da.drive_file_id = :drive_file_id
                """
            ),
            {"drive_file_id": drive_file_id},
        ).mappings().first()
        if not row:
            raise RuntimeError("Uploaded creative was not found in the library")
        return dict(row)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Could not add creative to the library: {exc}") from exc
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


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
