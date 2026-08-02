from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class AdSearchRequest(BaseModel):
    query: str
    platform: str = "facebook"
    limit: int = 10
    country: str = "US"
    offset: int = 0  # Pagination: controls scroll depth
    exclude_ids: List[str] = []  # IDs to skip (already fetched)
    negative_keywords: List[str] = []  # Keywords to exclude from results
    vertical_id: Optional[str] = None  # Vertical category ID
    search_type: str = "one_time"  # one_time, scheduled_daily, scheduled_weekly
    schedule_config: Optional[Dict[str, Any]] = None  # Cron schedule configuration

class ScrapedAdBase(BaseModel):
    brand_name: Optional[str] = None
    headline: Optional[str] = None
    ad_copy: Optional[str] = None
    cta_text: Optional[str] = None
    platform: str = "facebook"
    external_id: Optional[str] = None
    ad_link: str  # Link to original ad
    platforms: Optional[List[str]] = None  # ['facebook', 'instagram']
    start_date: Optional[str] = None  # When ad started running
    media_type: Optional[str] = None  # 'image', 'video', or 'carousel'
    media_url: Optional[str] = None  # Primary image or video thumbnail URL from Facebook Ad Library (may expire)
    destination_domain: Optional[str] = None
    source_query: Optional[str] = None
    rank_position: Optional[int] = None
    sort_mode: Optional[str] = None
    is_multiple_versions: Optional[bool] = None
    video_urls: Optional[List[str]] = None
    thumbnail_url: Optional[str] = None
    creative_intel: Optional[Dict[str, Any]] = None
    volume_score: Optional[int] = None

class ScrapedAdCreate(ScrapedAdBase):
    pass

# For search results (not saved to DB yet)
class ScrapedAdSearchResult(ScrapedAdBase):
    pass

class ScrapedAdResponse(ScrapedAdBase):
    id: str
    search_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class SavedSearchBase(BaseModel):
    query: str
    country: Optional[str] = None
    negative_keywords: Optional[List[str]] = None
    vertical_id: Optional[str] = None
    search_type: str = "one_time"
    schedule_config: Optional[Dict[str, Any]] = None
    is_active: bool = True
    last_run: Optional[datetime] = None

class SavedSearchResponse(SavedSearchBase):
    id: str
    created_at: datetime
    ads: List[ScrapedAdResponse] = []
    ads_requested: Optional[int] = None
    ads_returned: Optional[int] = None
    ads_new: Optional[int] = None
    ads_duplicate: Optional[int] = None

    class Config:
        from_attributes = True


# Brand Scrapes schemas
class BrandScrapeCreate(BaseModel):
    brand_name: str  # User-defined name, also R2 folder name
    page_url: str  # Facebook Ads Library URL with view_all_page_id


class BrandScrapedAdResponse(BaseModel):
    id: str
    external_id: str
    page_name: Optional[str] = None
    page_link: Optional[str] = None
    headline: Optional[str] = None
    ad_copy: Optional[str] = None
    cta_text: Optional[str] = None
    media_type: Optional[str] = None
    media_urls: Optional[List[str]] = None
    original_media_urls: Optional[List[str]] = None
    platforms: Optional[List[str]] = None
    start_date: Optional[str] = None
    ad_link: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BrandScrapeResponse(BaseModel):
    id: str
    brand_name: str
    page_id: str
    page_name: Optional[str] = None
    page_url: str
    total_ads: int = 0
    media_downloaded: int = 0
    status: str = "pending"
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    ads: List[BrandScrapedAdResponse] = []

    class Config:
        from_attributes = True


class BrandScrapeListResponse(BaseModel):
    """Response without ads for list view."""
    id: str
    brand_name: str
    page_id: str
    page_name: Optional[str] = None
    page_url: str
    total_ads: int = 0
    media_downloaded: int = 0
    status: str = "pending"
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AdLibraryImportAd(BaseModel):
    library_id: str = Field(max_length=200)
    brand_name: Optional[str] = Field(default=None, max_length=300)
    headline: Optional[str] = Field(default=None, max_length=5000)
    ad_copy: Optional[str] = Field(default=None, max_length=5000)
    cta_text: Optional[str] = Field(default=None, max_length=500)
    ad_link: Optional[str] = Field(default=None, max_length=2000)
    platforms: Optional[List[str]] = Field(default=None, max_length=10)
    start_date: Optional[str] = Field(default=None, max_length=100)
    media_type: Optional[str] = Field(default=None, max_length=50)
    media_url: Optional[str] = Field(default=None, max_length=2000)
    destination_domain: Optional[str] = Field(default=None, max_length=500)
    rank_position: Optional[int] = None
    is_multiple_versions: Optional[bool] = None
    video_urls: Optional[List[str]] = Field(default=None, max_length=10)
    thumbnail_url: Optional[str] = Field(default=None, max_length=2000)
    creative_intel: Optional[Dict[str, Any]] = None


class AdLibraryImportRequest(BaseModel):
    query: str = Field(default="cheap auto insurance", max_length=500)
    country: str = Field(default="US", max_length=10)
    vertical: str = Field(default="Auto Insurance", max_length=200)
    sort_mode: str = Field(default="total_impressions_desc", max_length=100)
    source_url: Optional[str] = Field(default=None, max_length=2000)
    ads: List[AdLibraryImportAd] = Field(max_length=200)
