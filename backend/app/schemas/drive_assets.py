from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DriveAsset(BaseModel):
    id: str
    drive_file_id: str
    brand_id: str
    brand_name: Optional[str] = None
    product_id: Optional[str] = None
    format: str
    folder_path: Optional[str] = None
    file_name: str
    r2_key: str
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
    next_page_token_saved: bool = False
