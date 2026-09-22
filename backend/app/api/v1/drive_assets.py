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


@router.post("/refresh-copy-metadata", response_model=DriveSyncResult)
def refresh_drive_copy_metadata(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_active_user),
):
    """Sync Drive changes, then re-match imported media to active copy sources."""
    try:
        service = DriveSyncService(db)
        # A copy refresh must reconcile the current Drive inventory before it
        # evaluates copy tags.  An incremental changes token can be older than
        # the asset rows (for example after a Drive re-export creates new file
        # IDs), which leaves the picker showing stale images as "No copy in
        # Drive" even though the canonical document is current.  Backfill is
        # cheap for unchanged rows because _process_file skips their binaries;
        # it ingests only newly discovered/replaced media and closes this gap.
        # defer_copy_resolution=True is safe ONLY here, where refresh_copy_metadata()
        # unconditionally runs next and re-derives copy tags for every matched
        # package — sync-now's standalone backfill (no guaranteed follow-up)
        # must not pass this, or unchanged rows silently stop picking up copy changes.
        sync_result = service.sync_once(backfill=True, defer_copy_resolution=True)
        refresh_result = service.refresh_copy_metadata()
        for key in ("processed", "created", "updated", "skipped", "archived", "unmatched_brand", "errors"):
            refresh_result[key] = (refresh_result.get(key) or 0) + (sync_result.get(key) or 0)
        refresh_result["next_page_token_saved"] = bool(
            refresh_result.get("next_page_token_saved") or sync_result.get("next_page_token_saved")
        )
        return refresh_result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
