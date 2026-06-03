from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Tuple
from app.database import get_db
from app.schemas.research import (
    AdSearchRequest, ScrapedAdResponse, ScrapedAdCreate, ScrapedAdSearchResult, SavedSearchResponse,
    BrandScrapeCreate, BrandScrapeResponse, BrandScrapeListResponse
)
from app.services.research_service import ResearchService
from app.services.rate_limiter import rate_limiter

router = APIRouter()

@router.post("/search", response_model=List[ScrapedAdSearchResult])
async def search_ads(request: AdSearchRequest, db: Session = Depends(get_db)):
    """Search ads without saving"""
    # Check rate limit (now uses database)
    allowed, remaining, reset_seconds = rate_limiter.check_limit(db)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {reset_seconds} seconds."
        )

    service = ResearchService(db)
    return await service.search_ads_async(request)

@router.post("/search-and-save")
async def search_and_save(request: AdSearchRequest, db: Session = Depends(get_db)):
    """Execute search and save as SavedSearch with all ads"""
    # Check rate limit (now uses database)
    allowed, remaining, reset_seconds = rate_limiter.check_limit(db)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {reset_seconds} seconds."
        )

    service = ResearchService(db)
    saved_search, ads = await service.search_and_save(request)
    return {
        "search_id": saved_search.id,
        "query": saved_search.query,
        "country": saved_search.country,
        "ads_count": len(ads)
    }

@router.get("/saved-searches", response_model=List[SavedSearchResponse])
def get_saved_searches(db: Session = Depends(get_db)):
    """Get all saved searches with their ads"""
    service = ResearchService(db)
    return service.get_saved_searches()

@router.get("/saved-searches/{search_id}", response_model=SavedSearchResponse)
def get_saved_search(search_id: str, db: Session = Depends(get_db)):
    """Get single saved search with ads"""
    service = ResearchService(db)
    search = service.get_saved_search_with_ads(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    return search

@router.delete("/saved-searches/{search_id}")
def delete_saved_search(search_id: str, db: Session = Depends(get_db)):
    """Delete saved search and its ads"""
    service = ResearchService(db)
    if service.delete_saved_search(search_id):
        return {"message": "Search deleted"}
    raise HTTPException(status_code=404, detail="Search not found")

@router.get("/api-usage")
def get_api_usage(db: Session = Depends(get_db)):
    """Get API usage stats grouped by date"""
    from app.models import ApiUsageLog
    from sqlalchemy import func

    # Get usage grouped by date
    usage = db.query(
        ApiUsageLog.date,
        func.sum(ApiUsageLog.api_calls).label('total_calls'),
        func.sum(ApiUsageLog.ads_returned).label('total_returned'),
        func.sum(ApiUsageLog.ads_saved).label('total_saved'),
        func.count(ApiUsageLog.id).label('search_count')
    ).group_by(ApiUsageLog.date).order_by(ApiUsageLog.date.desc()).all()

    return [
        {
            "date": row.date,
            "total_calls": row.total_calls,
            "total_returned": row.total_returned,
            "total_saved": row.total_saved,
            "search_count": row.search_count
        }
        for row in usage
    ]

@router.get("/blacklist")
def get_blacklist(db: Session = Depends(get_db)):
    """Get all blacklisted pages"""
    from app.models import PageBlacklist
    pages = db.query(PageBlacklist).order_by(PageBlacklist.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "page_name": p.page_name,
            "reason": p.reason,
            "created_at": p.created_at.isoformat()
        }
        for p in pages
    ]

@router.post("/blacklist")
def add_to_blacklist(page_name: str, reason: str = None, db: Session = Depends(get_db)):
    """Add page to blacklist"""
    from app.models import PageBlacklist

    # Check if already blacklisted
    existing = db.query(PageBlacklist).filter(PageBlacklist.page_name == page_name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Page already blacklisted")

    blacklist_entry = PageBlacklist(page_name=page_name, reason=reason)
    db.add(blacklist_entry)
    db.commit()
    db.refresh(blacklist_entry)

    return {
        "id": blacklist_entry.id,
        "page_name": blacklist_entry.page_name,
        "reason": blacklist_entry.reason,
        "created_at": blacklist_entry.created_at.isoformat()
    }

@router.delete("/blacklist/{blacklist_id}")
def remove_from_blacklist(blacklist_id: str, db: Session = Depends(get_db)):
    """Remove page from blacklist"""
    from app.models import PageBlacklist

    entry = db.query(PageBlacklist).filter(PageBlacklist.id == blacklist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Blacklist entry not found")

    db.delete(entry)
    db.commit()
    return {"message": "Removed from blacklist"}

@router.get("/keyword-blacklist")
def get_keyword_blacklist(db: Session = Depends(get_db)):
    """Get all blacklisted keywords"""
    from app.models import KeywordBlacklist
    keywords = db.query(KeywordBlacklist).order_by(KeywordBlacklist.created_at.desc()).all()
    return [
        {
            "id": k.id,
            "keyword": k.keyword,
            "reason": k.reason,
            "created_at": k.created_at.isoformat()
        }
        for k in keywords
    ]

@router.post("/keyword-blacklist")
def add_to_keyword_blacklist(keyword: str, reason: str = None, db: Session = Depends(get_db)):
    """Add keyword to blacklist"""
    from app.models import KeywordBlacklist

    # Check if already blacklisted
    existing = db.query(KeywordBlacklist).filter(KeywordBlacklist.keyword == keyword.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Keyword already blacklisted")

    blacklist_entry = KeywordBlacklist(keyword=keyword.lower(), reason=reason)
    db.add(blacklist_entry)
    db.commit()
    db.refresh(blacklist_entry)

    return {
        "id": blacklist_entry.id,
        "keyword": blacklist_entry.keyword,
        "reason": blacklist_entry.reason,
        "created_at": blacklist_entry.created_at.isoformat()
    }

@router.delete("/keyword-blacklist/{blacklist_id}")
def remove_from_keyword_blacklist(blacklist_id: str, db: Session = Depends(get_db)):
    """Remove keyword from blacklist"""
    from app.models import KeywordBlacklist

    entry = db.query(KeywordBlacklist).filter(KeywordBlacklist.id == blacklist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Keyword blacklist entry not found")

    db.delete(entry)
    db.commit()
    return {"message": "Removed from keyword blacklist"}

@router.get("/rate-limit")
def get_rate_limit(db: Session = Depends(get_db)):
    """Get current rate limit usage (trailing 59 minutes)"""
    return rate_limiter.get_usage_stats(db)

@router.get("/facebook-pages")
def get_facebook_pages(
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "total_ads",  # total_ads, page_name, last_seen
    db: Session = Depends(get_db)
):
    """Get Facebook pages with ad counts (excludes blacklisted pages)"""
    from app.models import FacebookPage, PageBlacklist
    from sqlalchemy import desc

    # Get blacklisted page names
    blacklisted_pages = db.query(PageBlacklist.page_name).all()
    blacklisted_names = {p.page_name.lower() for p in blacklisted_pages}

    query = db.query(FacebookPage)

    # Sort
    if sort_by == "total_ads":
        query = query.order_by(desc(FacebookPage.total_ads))
    elif sort_by == "page_name":
        query = query.order_by(FacebookPage.page_name)
    elif sort_by == "last_seen":
        query = query.order_by(desc(FacebookPage.last_seen))

    pages = query.offset(offset).limit(limit).all()

    # Filter out blacklisted pages
    filtered_pages = [
        p for p in pages
        if p.page_name.lower() not in blacklisted_names
    ]

    # Get vertical names for display
    from app.models import Vertical
    vertical_map = {v.id: v.name for v in db.query(Vertical).all()}

    return [
        {
            "id": p.id,
            "page_name": p.page_name,
            "page_url": p.page_url,
            "total_ads": p.total_ads,
            "vertical_id": p.vertical_id,
            "vertical_name": vertical_map.get(p.vertical_id) if p.vertical_id else None,
            "first_seen": p.first_seen.isoformat() if p.first_seen else None,
            "last_seen": p.last_seen.isoformat() if p.last_seen else None,
        }
        for p in filtered_pages
    ]

@router.get("/verticals")
def get_verticals(db: Session = Depends(get_db)):
    """Get all verticals"""
    from app.models import Vertical
    verticals = db.query(Vertical).order_by(Vertical.name).all()
    return [
        {
            "id": v.id,
            "name": v.name,
            "description": v.description,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in verticals
    ]

@router.post("/run-scheduled-searches")
async def run_scheduled_searches(db: Session = Depends(get_db)):
    """Manually trigger scheduled searches (called by cron job)"""
    from app.services.scheduler_service import SchedulerService

    scheduler = SchedulerService(db)
    await scheduler.run_scheduled_searches()

    return {"message": "Scheduled searches completed"}

@router.post("/verticals")
def create_vertical(name: str, description: str = None, db: Session = Depends(get_db)):
    """Create a new vertical"""
    from app.models import Vertical

    # Check if exists
    existing = db.query(Vertical).filter(Vertical.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Vertical already exists")

    vertical = Vertical(name=name, description=description)
    db.add(vertical)
    db.commit()
    db.refresh(vertical)

    return {
        "id": vertical.id,
        "name": vertical.name,
        "description": vertical.description,
        "created_at": vertical.created_at.isoformat() if vertical.created_at else None,
    }

@router.get("/verticals/{vertical_id}/aggregated-ads")
def get_vertical_aggregated_ads(vertical_id: str, db: Session = Depends(get_db)):
    """Get all unique ads for a vertical, grouped by Facebook page with media type counts (excluding blacklisted pages)"""
    try:
        from app.models import ScrapedAd, SavedSearch, FacebookPage, PageBlacklist
        from sqlalchemy import func, distinct, case

        # Get all searches for this vertical
        searches = db.query(SavedSearch).filter(SavedSearch.vertical_id == vertical_id).all()
        search_ids = [s.id for s in searches]

        if not search_ids:
            return []

        # Get blacklisted page names
        blacklisted_pages = db.query(PageBlacklist.page_name).all()
        blacklisted_names = {p.page_name.lower() for p in blacklisted_pages}

        # Get all unique ads for these searches, grouped by page
        # Use COALESCE to fall back to ID when content_hash is NULL
        from sqlalchemy import func as sqlfunc
        unique_key = func.coalesce(ScrapedAd.content_hash, ScrapedAd.id)

        ads_by_page = db.query(
            FacebookPage.page_name,
            FacebookPage.id.label('page_id'),
            func.count(distinct(unique_key)).label('total_ads'),
            func.sum(case((ScrapedAd.media_type == 'image', 1), else_=0)).label('image_count'),
            func.sum(case((ScrapedAd.media_type == 'video', 1), else_=0)).label('video_count'),
            func.sum(case((ScrapedAd.media_type == 'carousel', 1), else_=0)).label('carousel_count')
        ).join(
            ScrapedAd, ScrapedAd.facebook_page_id == FacebookPage.id
        ).filter(
            ScrapedAd.search_id.in_(search_ids)
        ).group_by(
            FacebookPage.id, FacebookPage.page_name
        ).order_by(
            func.count(distinct(unique_key)).desc()
        ).all()

        # Filter out blacklisted pages
        return [
            {
                "page_name": row.page_name,
                "page_id": row.page_id,
                "total_ads": row.total_ads,
                "image_count": row.image_count or 0,
                "video_count": row.video_count or 0,
                "carousel_count": row.carousel_count or 0
            }
            for row in ads_by_page
            if row.page_name.lower() not in blacklisted_names
        ]
    except Exception as e:
        import traceback
        print(f"Error in get_vertical_aggregated_ads: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error fetching aggregated ads: {str(e)}")

@router.get("/verticals/{vertical_id}/pages/{page_id}/ads")
def get_vertical_page_ads(vertical_id: str, page_id: str, db: Session = Depends(get_db)):
    """Get unique ads for a specific Facebook page within a vertical"""
    try:
        from app.models import ScrapedAd, SavedSearch, FacebookPage
        from sqlalchemy import func, distinct

        # Get all searches for this vertical
        searches = db.query(SavedSearch).filter(SavedSearch.vertical_id == vertical_id).all()
        search_ids = [s.id for s in searches]

        if not search_ids:
            return []

        # Get unique ads for this page (deduplicated by content_hash or ID)
        # Use a subquery to get one ad per unique key (content_hash if available, else ID)
        from sqlalchemy.orm import aliased
        from sqlalchemy import tuple_

        # For old ads without content_hash, each ad is unique
        # For new ads with content_hash, deduplicate by hash
        unique_key = func.coalesce(ScrapedAd.content_hash, ScrapedAd.id)

        subq = db.query(
            unique_key.label('unique_key'),
            func.min(ScrapedAd.id).label('min_id')
        ).filter(
            ScrapedAd.facebook_page_id == page_id,
            ScrapedAd.search_id.in_(search_ids)
        ).group_by(unique_key).subquery()

        ads = db.query(ScrapedAd).join(
            subq, ScrapedAd.id == subq.c.min_id
        ).order_by(ScrapedAd.created_at.desc()).all()

        return [
            {
                "id": ad.id,
                "brand_name": ad.brand_name,
                "headline": ad.headline,
                "ad_copy": ad.ad_copy,
                "cta_text": ad.cta_text,
                "media_type": ad.media_type,
                "ad_link": ad.ad_link,
                "start_date": ad.start_date,
                "platforms": ad.platforms,
                "seen_count": ad.seen_count or 1,
                "first_seen": ad.first_seen.isoformat() if ad.first_seen else None,
                "last_seen": ad.last_seen.isoformat() if ad.last_seen else None,
            }
            for ad in ads
        ]
    except Exception as e:
        import traceback
        print(f"Error in get_vertical_page_ads: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error fetching page ads: {str(e)}")


# ============= Brand Scrape Endpoints =============

@router.post("/brand-scrapes", response_model=BrandScrapeListResponse)
async def create_brand_scrape(
    request: BrandScrapeCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Create a new brand scrape and start scraping in background."""
    from app.models import BrandScrape
    from app.services.brand_scraper import BrandScraperService, parse_page_id_from_url, parse_search_query_from_url

    # Parse page ID or search query from URL
    page_id = parse_page_id_from_url(request.page_url)
    search_query = parse_search_query_from_url(request.page_url)

    if not page_id and not search_query:
        raise HTTPException(
            status_code=400,
            detail="Invalid URL. Must be a Facebook Ads Library URL with view_all_page_id or q= parameter."
        )

    # Create brand scrape record
    brand_scrape = BrandScrape(
        brand_name=request.brand_name,
        page_id=page_id or search_query,  # Use search query as identifier if no page_id
        page_url=request.page_url,
        status="pending"
    )
    db.add(brand_scrape)
    db.commit()
    db.refresh(brand_scrape)

    # Start scraping in background
    async def run_scrape():
        from app.database import SessionLocal
        scrape_db = SessionLocal()
        try:
            scraper = BrandScraperService(scrape_db)
            scrape_record = scrape_db.query(BrandScrape).filter(BrandScrape.id == brand_scrape.id).first()
            if scrape_record:
                await scraper.scrape_brand(scrape_record)
        except Exception as e:
            print(f"Background scrape error: {e}")
            scrape_record = scrape_db.query(BrandScrape).filter(BrandScrape.id == brand_scrape.id).first()
            if scrape_record:
                scrape_record.status = "failed"
                scrape_record.error_message = str(e)[:500]
                scrape_db.commit()
        finally:
            scrape_db.close()

    background_tasks.add_task(run_scrape)

    return brand_scrape


@router.get("/brand-scrapes", response_model=List[BrandScrapeListResponse])
def get_brand_scrapes(db: Session = Depends(get_db)):
    """Get all brand scrapes."""
    from app.models import BrandScrape

    scrapes = db.query(BrandScrape).order_by(BrandScrape.created_at.desc()).all()
    return scrapes


@router.get("/brand-scrapes/{scrape_id}", response_model=BrandScrapeResponse)
def get_brand_scrape(scrape_id: str, db: Session = Depends(get_db)):
    """Get a single brand scrape with all its ads."""
    from app.models import BrandScrape

    scrape = db.query(BrandScrape).filter(BrandScrape.id == scrape_id).first()
    if not scrape:
        raise HTTPException(status_code=404, detail="Brand scrape not found")

    return scrape


@router.delete("/brand-scrapes/{scrape_id}")
async def delete_brand_scrape(scrape_id: str, db: Session = Depends(get_db)):
    """Delete a brand scrape and its media from R2."""
    from app.models import BrandScrape
    from app.services.brand_scraper import BrandScraperService

    scrape = db.query(BrandScrape).filter(BrandScrape.id == scrape_id).first()
    if not scrape:
        raise HTTPException(status_code=404, detail="Brand scrape not found")

    scraper = BrandScraperService(db)
    success = await scraper.delete_brand_scrape(scrape)

    if success:
        return {"message": "Brand scrape deleted"}
    raise HTTPException(status_code=500, detail="Failed to delete brand scrape")


@router.delete("/scraped-ads/{ad_id}/save")
def unsave_scraped_ad(ad_id: str, db: Session = Depends(get_db)):
    """Remove a scraped ad from the user's curated research library."""
    from app.models import ScrapedAd
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    ad.is_saved = False
    db.commit()
    return {"id": ad_id, "is_saved": False}


@router.get("/scraped-ads/saved")
def get_saved_ads(db: Session = Depends(get_db)):
    """Return all scraped ads the user has saved to their research library."""
    from app.models import ScrapedAd
    ads = db.query(ScrapedAd).filter(ScrapedAd.is_saved == True).order_by(ScrapedAd.created_at.desc()).all()
    return [
        {
            "id": ad.id,
            "brand_name": ad.brand_name,
            "headline": ad.headline,
            "ad_copy": ad.ad_copy,
            "cta_text": ad.cta_text,
            "media_type": ad.media_type,
            "ad_link": ad.ad_link,
            "start_date": ad.start_date,
            "seen_count": ad.seen_count or 1,
            "angle_tag": ad.angle_tag,
            "is_saved": ad.is_saved,
            "created_at": ad.created_at.isoformat() if ad.created_at else None,
            "last_seen": ad.last_seen.isoformat() if ad.last_seen else None,
        }
        for ad in ads
    ]


# ============= Pre-configured Vertical Endpoints =============

@router.get("/vertical-config")
def get_vertical_config():
    """Return pre-configured keyword sets for each research vertical.

    Frontend reads this on mount so keyword sets are never hardcoded in JS.
    Includes angle tag definitions.
    """
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS, ANGLE_TAGS
    return {
        "verticals": VERTICAL_KEYWORD_SETS,
        "angle_tags": ANGLE_TAGS,
    }


@router.post("/scraped-ads/{ad_id}/save")
def save_scraped_ad_with_angle(
    ad_id: str,
    angle_tag: str | None = None,
    db: Session = Depends(get_db),
):
    """Mark a scraped ad as saved and optionally assign an angle tag."""
    from app.models import ScrapedAd
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    ad.is_saved = True
    if angle_tag is not None:
        ad.angle_tag = angle_tag
    db.commit()
    return {"id": ad_id, "is_saved": True, "angle_tag": ad.angle_tag}


@router.patch("/scraped-ads/{ad_id}/angle")
def update_angle_tag(
    ad_id: str,
    angle_tag: str | None = None,
    db: Session = Depends(get_db),
):
    """Update the angle tag on a scraped ad (can also clear it by passing null)."""
    from app.models import ScrapedAd
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    ad.angle_tag = angle_tag
    db.commit()
    return {"id": ad_id, "angle_tag": ad.angle_tag}


@router.get("/config-verticals/{config_id}/browse-ads")
def get_vertical_browse_ads(
    config_id: str,
    sub_vertical: str | None = None,
    angle_tag: str | None = None,
    active_only: bool = False,
    advertiser: str | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
):
    """Return all unique scraped ads for a pre-configured vertical (flat list for card gallery).

    config_id must match a key in VERTICAL_KEYWORD_SETS (e.g. 'commercial_insurance').
    For Home Services, pass sub_vertical to scope to a sub-vertical label.
    Deduplicates by content_hash. Applies optional angle/active/advertiser filters.
    """
    from app.models import ScrapedAd, SavedSearch, Vertical, FacebookPage, PageBlacklist
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS
    from sqlalchemy import func, distinct
    from datetime import datetime, timedelta

    if config_id not in VERTICAL_KEYWORD_SETS:
        raise HTTPException(status_code=404, detail=f"Unknown vertical config: {config_id}")

    config = VERTICAL_KEYWORD_SETS[config_id]

    # Determine the vertical label(s) to look up in the DB.
    if config_id == "home_services" and sub_vertical:
        sub = config.get("sub_verticals", {}).get(sub_vertical)
        if not sub:
            raise HTTPException(status_code=404, detail=f"Unknown sub-vertical: {sub_vertical}")
        vertical_labels = [sub["label"]]
    elif config_id == "home_services":
        # All home services sub-verticals
        vertical_labels = [sv["label"] for sv in config.get("sub_verticals", {}).values()]
    else:
        vertical_labels = [config["label"]]

    # Find DB verticals matching these labels
    verticals = db.query(Vertical).filter(Vertical.name.in_(vertical_labels)).all()
    if not verticals:
        return []  # No searches run yet for this vertical

    vertical_ids = [v.id for v in verticals]

    # Get all searches for these verticals
    search_ids = [
        s.id
        for s in db.query(SavedSearch.id).filter(SavedSearch.vertical_id.in_(vertical_ids)).all()
    ]
    if not search_ids:
        return []

    # Get blacklisted page names
    blacklisted_names = {
        p.page_name.lower()
        for p in db.query(PageBlacklist.page_name).all()
    }

    # Build query — one row per unique content_hash (or ad ID for legacy ads)
    unique_key = func.coalesce(ScrapedAd.content_hash, ScrapedAd.id)
    subq = (
        db.query(
            unique_key.label("unique_key"),
            func.min(ScrapedAd.id).label("min_id"),
        )
        .filter(ScrapedAd.search_id.in_(search_ids))
        .group_by(unique_key)
        .subquery()
    )

    query = db.query(ScrapedAd).join(subq, ScrapedAd.id == subq.c.min_id)

    # Filters
    if angle_tag:
        query = query.filter(ScrapedAd.angle_tag == angle_tag)
    if advertiser:
        query = query.filter(ScrapedAd.brand_name.ilike(f"%{advertiser}%"))
    if active_only:
        cutoff = datetime.utcnow() - timedelta(days=30)
        query = query.filter(ScrapedAd.last_seen >= cutoff)

    ads = query.order_by(ScrapedAd.last_seen.desc().nullslast()).limit(limit).all()

    # Compute running duration and filter blacklisted advertisers
    now = datetime.utcnow()
    result = []
    for ad in ads:
        if ad.brand_name and ad.brand_name.lower() in blacklisted_names:
            continue

        running_days = None
        if ad.start_date:
            try:
                start = datetime.fromisoformat(ad.start_date.replace("Z", "+00:00").replace("+00:00", ""))
                running_days = (now - start).days
            except Exception:
                pass

        # "Active" proxy: seen within last 30 days
        is_active = False
        if ad.last_seen:
            is_active = (now - ad.last_seen.replace(tzinfo=None)).days <= 30

        result.append({
            "id": ad.id,
            "brand_name": ad.brand_name,
            "headline": ad.headline,
            "ad_copy": ad.ad_copy,
            "cta_text": ad.cta_text,
            "ad_link": ad.ad_link,
            "start_date": ad.start_date,
            "running_days": running_days,
            "is_active": is_active,
            "seen_count": ad.seen_count or 1,
            "angle_tag": ad.angle_tag,
            "is_saved": ad.is_saved,
            "last_seen": ad.last_seen.isoformat() if ad.last_seen else None,
        })

    return result


@router.post("/search-and-save-vertical")
async def search_and_save_vertical(
    vertical_id: str,
    sub_vertical: str | None = None,
    limit_per_keyword: int = 200,
    db: Session = Depends(get_db),
):
    """Run all keyword searches for a pre-configured vertical and save results.

    Looks up or creates the DB Vertical records matching the config labels,
    then runs each keyword through the existing search_and_save service.
    Returns aggregate stats: total_new, total_duplicate, keywords_run.

    For home_services, pass sub_vertical (e.g. 'floor_installation') to refresh
    only that sub-vertical. Omit sub_vertical to refresh all home services trades.
    """
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS
    from app.models import Vertical
    from app.schemas.research import AdSearchRequest
    from app.services.research_service import ResearchService
    from app.services.rate_limiter import rate_limiter

    if vertical_id not in VERTICAL_KEYWORD_SETS:
        raise HTTPException(status_code=404, detail=f"Unknown vertical: {vertical_id}")

    config = VERTICAL_KEYWORD_SETS[vertical_id]
    negative_keywords = config.get("negative_keywords", [])

    # Build list of (label, keywords) pairs to process
    pairs: list[tuple[str, list[str]]] = []

    if vertical_id == "home_services":
        sub_verticals = config.get("sub_verticals", {})
        if sub_vertical:
            if sub_vertical not in sub_verticals:
                raise HTTPException(status_code=404, detail=f"Unknown sub-vertical: {sub_vertical}")
            sv = sub_verticals[sub_vertical]
            pairs = [(sv["label"], sv["keywords"])]
        else:
            pairs = [(sv["label"], sv["keywords"]) for sv in sub_verticals.values()]
    else:
        pairs = [(config["label"], config["keywords"])]

    # Check rate limit up-front (rough check — actual enforcement per keyword)
    allowed, remaining, reset_seconds = rate_limiter.check_limit(db)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {reset_seconds} seconds.",
        )

    service = ResearchService(db)
    total_new = 0
    total_duplicate = 0
    keywords_run = 0
    first_error: str | None = None

    for label, keywords in pairs:
        # Look up or create the DB Vertical for this label
        vertical = db.query(Vertical).filter(Vertical.name == label).first()
        if not vertical:
            vertical = Vertical(name=label, description=f"Auto-created for {label} research vertical")
            db.add(vertical)
            db.commit()
            db.refresh(vertical)

        for keyword in keywords:
            try:
                allowed, remaining, _ = rate_limiter.check_limit(db)
                if not allowed:
                    break  # Hit rate limit mid-run — stop gracefully

                request = AdSearchRequest(
                    query=keyword,
                    platform="facebook",
                    limit=limit_per_keyword,
                    country="US",
                    offset=0,
                    exclude_ids=[],
                    negative_keywords=negative_keywords,
                    vertical_id=vertical.id,
                    search_type="one_time",
                    schedule_config=None,
                )
                saved_search, ads = await service.search_and_save(request)
                total_new += saved_search.ads_new or 0
                total_duplicate += saved_search.ads_duplicate or 0
                keywords_run += 1
            except Exception as exc:
                import logging, traceback
                logging.getLogger(__name__).warning(
                    "Keyword search failed for '%s': %s\n%s", keyword, exc, traceback.format_exc()
                )
                if first_error is None:
                    first_error = f"{type(exc).__name__}: {exc}"
                # Roll back any partial transaction so the next keyword gets a clean session
                try:
                    db.rollback()
                except Exception:
                    pass

    return {
        "total_new": total_new,
        "total_duplicate": total_duplicate,
        "keywords_run": keywords_run,
        "message": f"Refreshed {keywords_run} keywords — {total_new} new ads found",
        "first_error": first_error,  # None when all succeed; error class + message when any fail
    }
