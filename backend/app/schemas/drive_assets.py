from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DriveAsset(BaseModel):
    id: str
    drive_file_id: str
    brand_id: str
    brand_name: Optional[str] = None
    product_id: Optional[str] = None
    format: str
    folder_path: Optional[str] = None
    file_name: str
    r2_key: str  # full public R2 URL, not a bare object key — see models.DriveAsset
    thumbnail_r2_key: Optional[str] = None
    drive_modified_time: datetime
    synced_at: datetime
    archived: bool = False
    soft_tags: Optional[str] = None
    variant: Optional[str] = None
    geo: Optional[str] = None


class DriveSyncResult(BaseModel):
    processed: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    archived: int = 0
    unmatched_brand: int = 0
    errors: int = 0
    unverified: int = 0
    next_page_token_saved: bool = False
    copy_health: Optional[Dict[str, Any]] = None


class DriveCopyHealth(BaseModel):
    current_assets: int
    ready_assets: int
    exception_assets: int
    packages_with_exceptions: int
    exceptions: List[Dict[str, Any]] = Field(default_factory=list)
    manual_copy_assets: int = 0
    manual_copy_packages: List[Dict[str, Any]] = Field(default_factory=list)
    excluded_assets: int
    exclusions: List[Dict[str, Any]] = Field(default_factory=list)


class DriveCopyRefreshRequest(BaseModel):
    """Known source documents for a batch-scoped Creative-step refresh."""

    # A bulk launch can legitimately span more than 50 source documents. The
    # server processes them sequentially under its sync lock, so imposing an
    # arbitrary request cap would turn a valid batch into a false 422 failure.
    source_file_ids: List[str] = Field(default_factory=list)
    force_full_refresh: bool = False
    skip_full_refresh: bool = False
