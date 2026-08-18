from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import User
from app.schemas.drive_assets import DriveAsset, DriveSyncResult
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
    brand_id: Optional[str] = None,
    product_id: Optional[str] = None,
    format: Optional[str] = Query(default=None, pattern="^(image|video)$"),
    archived: bool = False,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
):
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
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
):
    try:
        return DriveSyncService(db).sync_once()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
