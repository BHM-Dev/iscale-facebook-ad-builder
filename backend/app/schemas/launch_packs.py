from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LaunchPackCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    ad_account_id: str = Field(min_length=1, max_length=200)
    ad_account_name: Optional[str] = Field(default=None, max_length=500)
    campaign_id: str = Field(min_length=1, max_length=200)
    campaign_name: Optional[str] = Field(default=None, max_length=500)
    adset_id: str = Field(min_length=1, max_length=200)
    adset_name: Optional[str] = Field(default=None, max_length=500)


class LaunchPackResponse(LaunchPackCreate):
    id: str
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
