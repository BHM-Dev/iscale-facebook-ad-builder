from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Tuple
from datetime import datetime, timezone
import hashlib
import json
from app.database import get_db
from app.core.deps import get_current_active_user
from app.models import User
from app.schemas.research import (
    AdSearchRequest, ScrapedAdResponse, ScrapedAdCreate, ScrapedAdSearchResult, SavedSearchResponse,
    BrandScrapeCreate, BrandScrapeResponse, BrandScrapeListResponse, AdLibraryImportRequest,
    ResearchBoardCreate, ResearchBoardItemCreate, ResearchBoardResponse, ResearchBoardItemResponse
)
from app.services.research_service import ResearchService
from app.services.rate_limiter import rate_limiter

router = APIRouter()

MAX_AD_LIBRARY_IMPORT_ADS = 100
MAX_AD_LIBRARY_VIDEO_URLS = 3
MAX_AD_LIBRARY_TEXT_CHARS = 5000
MAX_AD_LIBRARY_CREATIVE_INTEL_CHARS = 12000
RESEARCH_MEDIA_TYPES = {"image", "video", "carousel", "unknown"}
RESEARCH_SORT_OPTIONS = {"longest_running", "newest_seen", "most_sightings", "multiple_versions"}
RESEARCH_CREATIVE_TAGS = {"testimonial", "problem_agitation", "transformation", "comparison", "review", "listicle", "founder", "educational", "statistic", "ugc", "comment_response"}
RESEARCH_CTA_TYPES = {"learn_more", "get_quote", "sign_up", "apply_now", "contact_us", "shop_now", "unknown"}
RESEARCH_PAGE_TYPES = {"lead_form", "advertorial", "ecommerce", "homepage", "unknown"}


def _infer_creative_taxonomy(headline, ad_copy, cta_text, supplied_tags=None):
    """Conservative, explainable enrichment for Chrome/API captures.

    We only add deterministic labels from visible text; all others remain
    unknown so the filter never pretends a classifier saw more than it did.
    """
    text = " ".join(filter(None, [headline, ad_copy])).lower()
    tags = [tag for tag in (supplied_tags or []) if tag in RESEARCH_CREATIVE_TAGS]
    rules = {
        "testimonial": ("testimonial", "customer story", "what our customers say"),
        "problem_agitation": ("tired of", "stop overpaying", "struggling with"),
        "comparison": ("vs.", "versus", "compare", "instead of"),
        "review": ("review", "rated", "stars"),
        "listicle": ("top 5", "top five", "ways to", "reasons why"),
        "founder": ("our founder", "i started", "we started"),
        "educational": ("how to", "what is", "guide to"),
        "statistic": ("%", "percent", "out of 10"),
        "ugc": ("i tried", "my experience", "honestly"),
    }
    for tag, phrases in rules.items():
        if tag not in tags and any(phrase in text for phrase in phrases):
            tags.append(tag)
    cta = (cta_text or "").strip().lower().replace(" ", "_")
    cta_map = {"learn_more": "learn_more", "get_quote": "get_quote", "sign_up": "sign_up", "apply_now": "apply_now", "contact_us": "contact_us", "shop_now": "shop_now"}
    return tags or None, cta_map.get(cta, "unknown" if cta else None)


def _matches_research_vertical(ad, config_id):
    """Last-line quality gate for legacy broad captures already in the catalog."""
    if config_id != "commercial_insurance":
        return True
    text = " ".join(filter(None, [ad.brand_name, ad.headline, ad.ad_copy, ad.cta_text])).lower()
    commercial = ("business insurance", "commercial insurance", "general liability", "workers comp", "workers compensation", "business owners policy", "commercial auto", "business coverage", "liability insurance")
    obvious_noise = ("restaurant equipment", "now hiring", "lease type", "med spa", "hot-dog", "jewelry design", "tabletops")
    return any(term in text for term in commercial) and not any(term in text for term in obvious_noise)


def _related_pattern_score(source, candidate):
    """Return an explainable metadata match score and reasons, or None."""
    shared_tags = sorted(set(source.creative_tags or []) & set(candidate.creative_tags or []))
    reasons = [f"theme: {tag.replace('_', ' ')}" for tag in shared_tags]
    same_cta = bool(source.cta_type and source.cta_type == candidate.cta_type)
    same_format = bool(source.media_type and source.media_type == candidate.media_type)
    same_destination = bool(source.destination_domain and source.destination_domain == candidate.destination_domain)
    if same_cta:
        reasons.append(f"CTA: {source.cta_type.replace('_', ' ')}")
    if same_format:
        reasons.append(f"format: {source.media_type}")
    if same_destination:
        reasons.append("same destination")
    # A shared CTA or media format alone is too generic to imply relevance —
    # "get_quote" + "video" matches across completely unrelated verticals
    # (e.g. a home-services ad "related" to a commercial-insurance ad) since
    # neither the ScrapedAd model nor this endpoint tracks vertical/config.
    # Require at least one specific, content-derived signal (a shared
    # creative tag or the same landing destination) before a generic signal
    # is allowed to count at all.
    if not shared_tags and not same_destination:
        return None
    return len(shared_tags) * 4 + (2 if same_cta else 0) + int(same_format) + int(same_destination), reasons


def _parse_research_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip()
    for parser in (
        lambda item: _normalize_research_datetime(datetime.fromisoformat(item.replace("Z", "+00:00"))),
        lambda item: datetime.strptime(item, "%B %d, %Y"),
        lambda item: datetime.strptime(item, "%b %d, %Y"),
    ):
        try:
            return parser(text)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_research_datetime(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _serialize_research_datetime(value):
    normalized = _parse_research_date(value)
    return f"{normalized.isoformat()}Z" if normalized else value


def _sort_research_ads(ads, sort_by):
    """Sort source-backed research signals with unknown dates last."""
    if sort_by == "longest_running":
        return sorted(ads, key=lambda ad: (
            _parse_research_date(ad.start_date) is None,
            _parse_research_date(ad.start_date) or datetime.max,
        ))
    if sort_by == "most_sightings":
        return sorted(ads, key=lambda ad: (ad.seen_count is None, -(ad.seen_count or 0)))
    if sort_by == "multiple_versions":
        return sorted(ads, key=lambda ad: (
            not bool(ad.is_multiple_versions),
            _parse_research_date(ad.last_seen) is None,
            -(_parse_research_date(ad.last_seen).timestamp() if _parse_research_date(ad.last_seen) else 0),
        ))
    return sorted(ads, key=lambda ad: (
        _parse_research_date(ad.last_seen) is None,
        -(_parse_research_date(ad.last_seen).timestamp() if _parse_research_date(ad.last_seen) else 0),
    ))


def _cap_ads_per_advertiser(ads, ads_per_advertiser):
    """Keep a sorted catalog varied without discarding unknown legacy pages."""
    if not ads_per_advertiser:
        return ads
    counts = {}
    limited = []
    for ad in ads:
        advertiser = (ad.brand_name or "").strip().casefold()
        if not advertiser:
            limited.append(ad)
            continue
        count = counts.get(advertiser, 0)
        if count >= ads_per_advertiser:
            continue
        counts[advertiser] = count + 1
        limited.append(ad)
    return limited


def _serialize_scraped_ad(ad, board_item_id=None):
    # _parse_research_date normalizes timezone-aware DB values to naive UTC
    # before arithmetic, matching datetime.utcnow() below.
    start_date = _parse_research_date(ad.start_date)
    last_seen = _parse_research_date(ad.last_seen)
    result = {
        "id": ad.id,
        "brand_name": ad.brand_name,
        "headline": ad.headline,
        "ad_copy": ad.ad_copy,
        "cta_text": ad.cta_text,
        "platforms": ad.platforms,
        "media_type": ad.media_type,
        "media_url": ad.media_url,
        "destination_domain": ad.destination_domain,
        "source_query": ad.source_query,
        "rank_position": ad.rank_position,
        "sort_mode": ad.sort_mode,
        "is_multiple_versions": ad.is_multiple_versions,
        "video_urls": ad.video_urls,
        "thumbnail_url": ad.thumbnail_url,
        "creative_intel": ad.creative_intel,
        "volume_score": ad.volume_score,
        "ad_link": ad.ad_link,
        "start_date": _serialize_research_datetime(ad.start_date),
        "seen_count": ad.seen_count or 1,
        "running_days": max(0, (datetime.utcnow() - start_date).days) if start_date else None,
        "is_active": bool(last_seen and (datetime.utcnow() - last_seen).days <= 30),
        "angle_tag": ad.angle_tag,
        "hook_type": ad.hook_type,
        "persona": ad.persona,
        "promise": ad.promise,
        "proof_type": ad.proof_type,
        "funnel_stage": ad.funnel_stage,
        "pacing": ad.pacing,
        "numbers_used": ad.numbers_used,
        "creative_tags": ad.creative_tags or [],
        "cta_type": ad.cta_type,
        "page_type": ad.page_type,
        "video_length_seconds": ad.video_length_seconds,
        "media_preview_url": ad.media_preview_url,
        "media_width": ad.media_width,
        "media_height": ad.media_height,
        "taxonomy_source": ad.taxonomy_source,
        "taxonomy_confidence": ad.taxonomy_confidence,
        "is_saved": ad.is_saved,
        "created_at": _serialize_research_datetime(ad.created_at),
        "first_seen": _serialize_research_datetime(ad.first_seen),
        "last_seen": _serialize_research_datetime(ad.last_seen),
    }
    if board_item_id is not None:
        result["board_item_id"] = board_item_id
    return result


def _truncate_text(value: str | None, max_chars: int = MAX_AD_LIBRARY_TEXT_CHARS) -> str | None:
    if value is None:
        return None
    return value[:max_chars]


def _bounded_json(value):
    if value is None:
        return None

    serialized = json.dumps(value)
    if len(serialized) <= MAX_AD_LIBRARY_CREATIVE_INTEL_CHARS:
        return value
    return {
        "truncated": True,
        "summary": "Creative intel exceeded import size limit and was truncated.",
        "original_keys": sorted(value.keys()) if isinstance(value, dict) else None,
    }


def _ad_library_content_hash(
    external_id: str,
    brand_name: str | None,
    headline: str | None,
    ad_copy: str | None,
    cta_text: str | None,
    destination_domain: str | None,
) -> str:
    payload = {
        "source": "ad_library",
        "external_id": external_id,
        "brand_name": (brand_name or "").strip().lower(),
        "headline": (headline or "").strip().lower(),
        "ad_copy": (ad_copy or "").strip().lower(),
        "cta_text": (cta_text or "").strip().lower(),
        "destination_domain": (destination_domain or "").strip().lower(),
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _directional_volume_score(rank_position: int | None, is_multiple_versions: bool | None, start_date: str | None, has_video: bool) -> int:
    score = 0
    if rank_position:
        if rank_position <= 3:
            score += 45
        elif rank_position <= 10:
            score += 35
        elif rank_position <= 25:
            score += 25
        else:
            score += 10
    if is_multiple_versions:
        score += 20
    if has_video:
        score += 10
    if start_date:
        try:
            started = datetime.fromisoformat(start_date.replace("Z", "+00:00").replace("+00:00", ""))
            running_days = max(0, (datetime.utcnow() - started).days)
            if running_days >= 90:
                score += 20
            elif running_days >= 30:
                score += 12
            elif running_days >= 14:
                score += 6
        except Exception:
            pass
    return min(score, 100)

@router.post("/search", response_model=List[ScrapedAdSearchResult])
async def search_ads(request: AdSearchRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
async def search_and_save(request: AdSearchRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
        "ads_count": len(ads),
        # search-and-save is deliberately the query bar's persistence boundary:
        # every ad returned here is already a real ScrapedAd with a stable id.
        "ads": [_serialize_scraped_ad(ad) for ad in ads],
    }

@router.get("/saved-searches", response_model=List[SavedSearchResponse])
def get_saved_searches(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get all saved searches with their ads"""
    service = ResearchService(db)
    return service.get_saved_searches()

@router.get("/saved-searches/{search_id}", response_model=SavedSearchResponse)
def get_saved_search(search_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get single saved search with ads"""
    service = ResearchService(db)
    search = service.get_saved_search_with_ads(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    return search

@router.delete("/saved-searches/{search_id}")
def delete_saved_search(search_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Delete saved search and its ads"""
    service = ResearchService(db)
    if service.delete_saved_search(search_id):
        return {"message": "Search deleted"}
    raise HTTPException(status_code=404, detail="Search not found")

@router.get("/api-usage")
def get_api_usage(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
def get_blacklist(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
def add_to_blacklist(page_name: str, reason: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
def remove_from_blacklist(blacklist_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Remove page from blacklist"""
    from app.models import PageBlacklist

    entry = db.query(PageBlacklist).filter(PageBlacklist.id == blacklist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Blacklist entry not found")

    db.delete(entry)
    db.commit()
    return {"message": "Removed from blacklist"}

@router.get("/keyword-blacklist")
def get_keyword_blacklist(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
def add_to_keyword_blacklist(keyword: str, reason: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
def remove_from_keyword_blacklist(blacklist_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Remove keyword from blacklist"""
    from app.models import KeywordBlacklist

    entry = db.query(KeywordBlacklist).filter(KeywordBlacklist.id == blacklist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Keyword blacklist entry not found")

    db.delete(entry)
    db.commit()
    return {"message": "Removed from keyword blacklist"}

@router.get("/rate-limit")
def get_rate_limit(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get current rate limit usage (trailing 59 minutes)"""
    return rate_limiter.get_usage_stats(db)

@router.get("/facebook-pages")
def get_facebook_pages(
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "total_ads",  # total_ads, page_name, last_seen
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
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
def get_verticals(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
async def run_scheduled_searches(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Manually trigger scheduled searches (called by cron job)"""
    from app.services.scheduler_service import SchedulerService

    scheduler = SchedulerService(db)
    await scheduler.run_scheduled_searches()

    return {"message": "Scheduled searches completed"}

@router.post("/verticals")
def create_vertical(name: str, description: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
def get_vertical_aggregated_ads(vertical_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
def get_vertical_page_ads(vertical_id: str, page_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
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
def get_brand_scrapes(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get all brand scrapes."""
    from app.models import BrandScrape

    scrapes = db.query(BrandScrape).order_by(BrandScrape.created_at.desc()).all()
    return scrapes


@router.get("/brand-scrapes/{scrape_id}", response_model=BrandScrapeResponse)
def get_brand_scrape(scrape_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get a single brand scrape with all its ads."""
    from app.models import BrandScrape

    scrape = db.query(BrandScrape).filter(BrandScrape.id == scrape_id).first()
    if not scrape:
        raise HTTPException(status_code=404, detail="Brand scrape not found")

    return scrape


@router.delete("/brand-scrapes/{scrape_id}")
async def delete_brand_scrape(scrape_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
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
def unsave_scraped_ad(ad_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Remove a scraped ad from the user's curated research library."""
    from app.models import ScrapedAd
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    ad.is_saved = False
    db.commit()
    return {"id": ad_id, "is_saved": False}


@router.get("/scraped-ads/saved")
def get_saved_ads(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Return all scraped ads the user has saved to their research library."""
    from app.models import ScrapedAd
    ads = db.query(ScrapedAd).filter(ScrapedAd.is_saved == True).order_by(ScrapedAd.created_at.desc()).all()
    return [_serialize_scraped_ad(ad) for ad in ads]


# ============= Shared research boards =============

@router.get("/boards", response_model=List[ResearchBoardResponse])
def get_research_boards(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """List workspace-shared boards with their current item counts."""
    from app.models import ResearchBoard, ResearchBoardItem
    from sqlalchemy import func

    rows = (
        db.query(ResearchBoard, func.count(ResearchBoardItem.id).label("item_count"))
        .outerjoin(ResearchBoardItem, ResearchBoardItem.board_id == ResearchBoard.id)
        .group_by(ResearchBoard.id)
        .order_by(ResearchBoard.updated_at.desc(), ResearchBoard.created_at.desc())
        .all()
    )
    return [
        {
            "id": board.id,
            "name": board.name,
            "vertical_id": board.vertical_id,
            "created_by": board.created_by,
            "created_at": board.created_at,
            "updated_at": board.updated_at,
            "item_count": item_count,
        }
        for board, item_count in rows
    ]


@router.post("/boards", response_model=ResearchBoardResponse, status_code=201)
def create_research_board(
    request: ResearchBoardCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.models import ResearchBoard

    board = ResearchBoard(
        name=request.name.strip(),
        vertical_id=request.vertical_id,
        created_by=current_user.id,
    )
    db.add(board)
    db.commit()
    db.refresh(board)
    return {
        "id": board.id,
        "name": board.name,
        "vertical_id": board.vertical_id,
        "created_by": board.created_by,
        "created_at": board.created_at,
        "updated_at": board.updated_at,
        "item_count": 0,
    }


@router.delete("/boards/{board_id}")
def delete_research_board(board_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    from app.models import ResearchBoard

    board = db.query(ResearchBoard).filter(ResearchBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Research board not found")
    db.delete(board)
    db.commit()
    return {"message": "Research board deleted"}


@router.post("/boards/{board_id}/items", response_model=ResearchBoardItemResponse)
def add_research_board_item(
    board_id: str,
    request: ResearchBoardItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.models import ResearchBoard, ResearchBoardItem, ScrapedAd

    board = db.query(ResearchBoard).filter(ResearchBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Research board not found")
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == request.scraped_ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")

    existing = db.query(ResearchBoardItem).filter(
        ResearchBoardItem.board_id == board_id,
        ResearchBoardItem.scraped_ad_id == request.scraped_ad_id,
    ).first()
    if existing:
        return {**_serialize_scraped_ad(ad, existing.id)}

    item = ResearchBoardItem(board_id=board_id, scraped_ad_id=ad.id)
    db.add(item)
    try:
        db.commit()
        db.refresh(item)
    except IntegrityError:
        # The DB constraint is the concurrency guarantee; a second request
        # racing the pre-check is a successful no-op, not a 500.
        db.rollback()
        item = db.query(ResearchBoardItem).filter(
            ResearchBoardItem.board_id == board_id,
            ResearchBoardItem.scraped_ad_id == ad.id,
        ).first()
        if not item:
            raise
    return {**_serialize_scraped_ad(ad, item.id)}


@router.delete("/boards/{board_id}/items/{item_id}")
def delete_research_board_item(
    board_id: str,
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.models import ResearchBoardItem

    item = db.query(ResearchBoardItem).filter(
        ResearchBoardItem.id == item_id,
        ResearchBoardItem.board_id == board_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Board item not found")
    db.delete(item)
    db.commit()
    return {"message": "Ad removed from research board"}


@router.get("/boards/{board_id}/items", response_model=List[ResearchBoardItemResponse])
def get_research_board_items(
    board_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.models import ResearchBoard, ResearchBoardItem
    from sqlalchemy.orm import contains_eager

    if not db.query(ResearchBoard.id).filter(ResearchBoard.id == board_id).first():
        raise HTTPException(status_code=404, detail="Research board not found")
    # .join() alone only affects the SQL WHERE/JOIN — it does not populate the
    # ORM relationship, so `item.scraped_ad` below would otherwise issue one
    # extra SELECT per item (N+1), which scales badly for exactly the
    # many-ads-per-board case this feature exists for (code-auditor pre-push
    # review, MEDIUM). contains_eager tells the ORM to hydrate `scraped_ad`
    # from the same joined query instead of lazy-loading it per row.
    items = db.query(ResearchBoardItem).join(ResearchBoardItem.scraped_ad).options(
        contains_eager(ResearchBoardItem.scraped_ad)
    ).filter(
        ResearchBoardItem.board_id == board_id,
    ).order_by(
        ResearchBoardItem.sort_order.asc(), ResearchBoardItem.created_at.desc()
    ).all()
    return [_serialize_scraped_ad(item.scraped_ad, item.id) for item in items]


# ============= Pre-configured Vertical Endpoints =============

@router.get("/vertical-config")
def get_vertical_config(current_user: User = Depends(get_current_active_user)):
    """Return pre-configured keyword sets for each research vertical.

    Frontend reads this on mount so keyword sets are never hardcoded in JS.
    Includes angle tag definitions.
    """
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS, ANGLE_TAGS
    return {
        "verticals": VERTICAL_KEYWORD_SETS,
        "angle_tags": ANGLE_TAGS,
    }


@router.post("/ad-library-import")
def import_ad_library_capture(
    request: AdLibraryImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Import Chrome-captured Ad Library intel into the Research library.

    This is intentionally separate from the official Ad Library API path. It
    stores rendered-card observations from a US, active, most-impressions
    browser search so Joel/Saule can save competitor examples for creative
    inspiration and video-agent training.
    """
    from app.models import ScrapedAd, SavedSearch, Vertical, FacebookPage

    if not request.ads:
        raise HTTPException(status_code=400, detail="No ads provided")
    if len(request.ads) > MAX_AD_LIBRARY_IMPORT_ADS:
        raise HTTPException(
            status_code=400,
            detail=f"Import is capped at {MAX_AD_LIBRARY_IMPORT_ADS} ads. Paste a smaller capture batch.",
        )

    vertical = db.query(Vertical).filter(Vertical.name == request.vertical).first()
    if not vertical:
        vertical = Vertical(name=request.vertical, description="Imported from Chrome-rendered Facebook Ad Library captures")
        db.add(vertical)
        db.flush()

    saved_search = SavedSearch(
        query=request.query,
        country=request.country,
        vertical_id=vertical.id,
        search_type="chrome_ad_library_import",
        schedule_config={
            "source": "chrome",
            "sort_mode": request.sort_mode,
            "source_url": request.source_url,
        },
        is_active=False,
        last_run=datetime.utcnow(),
        ads_requested=len(request.ads),
        ads_returned=len(request.ads),
        ads_new=0,
        ads_duplicate=0,
    )
    db.add(saved_search)
    db.flush()

    imported = 0
    updated = 0
    skipped = 0
    page_counts: dict[str, int] = {}
    with_media = 0
    with_video = 0
    multiple_versions = 0

    for incoming in request.ads:
        external_id = incoming.library_id.strip()
        if not external_id:
            skipped += 1
            continue

        video_urls = (incoming.video_urls or [])[:MAX_AD_LIBRARY_VIDEO_URLS]
        # Preserve unknown media format instead of silently classifying every
        # non-video capture as an image. A missing source value is not evidence.
        media_type = incoming.media_type or ("video" if video_urls else None)
        has_media = bool(incoming.media_url or incoming.thumbnail_url or video_urls)
        if has_media:
            with_media += 1
        if media_type == "video" or video_urls:
            with_video += 1
        if incoming.is_multiple_versions:
            multiple_versions += 1
        volume_score = _directional_volume_score(
            incoming.rank_position,
            incoming.is_multiple_versions,
            incoming.start_date,
            media_type == "video" or bool(video_urls),
        )
        creative_intel = dict(incoming.creative_intel or {})
        creative_tags, inferred_cta_type = _infer_creative_taxonomy(
            incoming.headline, incoming.ad_copy, incoming.cta_text, incoming.creative_tags,
        )
        creative_intel.update(
            {
                "capture_source": "chrome_ad_library",
                "source_query": request.query,
                "country": request.country,
                "sort_mode": request.sort_mode,
                "source_url": request.source_url,
                "volume_score_method": "rank + multiple_versions + active_age + video_presence; directional only",
                "imported_by_user_id": current_user.id,
            }
        )
        creative_intel = _bounded_json(creative_intel)

        fb_page = None
        if incoming.brand_name:
            fb_page = db.query(FacebookPage).filter(FacebookPage.page_name == incoming.brand_name).first()
            if not fb_page:
                fb_page = FacebookPage(page_name=incoming.brand_name, total_ads=0, vertical_id=vertical.id)
                db.add(fb_page)
                db.flush()
            page_counts[incoming.brand_name] = page_counts.get(incoming.brand_name, 0) + 1

        ad = db.query(ScrapedAd).filter(ScrapedAd.external_id == external_id).first()
        if ad:
            updated += 1
            ad.last_seen = datetime.utcnow()
            ad.seen_count = (ad.seen_count or 0) + 1
        else:
            imported += 1
            ad = ScrapedAd(
                external_id=external_id,
                ad_link=incoming.ad_link or f"https://www.facebook.com/ads/library/?id={external_id}",
                content_hash=_ad_library_content_hash(
                    external_id,
                    incoming.brand_name,
                    _truncate_text(incoming.headline),
                    _truncate_text(incoming.ad_copy),
                    incoming.cta_text,
                    incoming.destination_domain,
                ),
                search_id=saved_search.id,
            )
            db.add(ad)

        ad.brand_name = incoming.brand_name
        ad.headline = _truncate_text(incoming.headline)
        ad.ad_copy = _truncate_text(incoming.ad_copy)
        ad.cta_text = incoming.cta_text
        ad.platform = "facebook"
        ad.platforms = incoming.platforms
        ad.start_date = incoming.start_date
        ad.media_type = media_type
        ad.media_url = incoming.media_url or incoming.thumbnail_url
        ad.destination_domain = incoming.destination_domain
        ad.source_query = request.query
        ad.rank_position = incoming.rank_position
        ad.sort_mode = request.sort_mode
        ad.is_multiple_versions = bool(incoming.is_multiple_versions)
        ad.video_urls = video_urls or None
        ad.thumbnail_url = incoming.thumbnail_url or incoming.media_url
        ad.creative_intel = creative_intel
        ad.volume_score = volume_score
        ad.creative_tags = creative_tags
        ad.cta_type = incoming.cta_type or inferred_cta_type
        ad.page_type = incoming.page_type
        ad.video_length_seconds = incoming.video_length_seconds
        ad.media_preview_url = incoming.media_preview_url or (video_urls[0] if video_urls else None)
        ad.media_width = incoming.media_width
        ad.media_height = incoming.media_height
        rules_matched = bool(creative_tags) or bool(inferred_cta_type and inferred_cta_type != "unknown")
        ad.taxonomy_source = "capture" if incoming.creative_tags or incoming.cta_type else ("rules_v1" if rules_matched else None)
        ad.taxonomy_confidence = "source" if incoming.creative_tags or incoming.cta_type else ("low" if rules_matched else None)
        ad.search_id = saved_search.id
        if fb_page:
            ad.facebook_page_id = fb_page.id

    saved_search.ads_new = imported
    saved_search.ads_duplicate = updated

    db.flush()
    for page_name in page_counts:
        page = db.query(FacebookPage).filter(FacebookPage.page_name == page_name).first()
        if page:
            page.total_ads = db.query(ScrapedAd).filter(ScrapedAd.facebook_page_id == page.id).count()
            page.last_seen = datetime.utcnow()

    db.commit()

    return {
        "search_id": saved_search.id,
        "query": request.query,
        "vertical": request.vertical,
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "total": imported + updated,
        "quality": {
            "with_media": with_media,
            "with_video": with_video,
            "multiple_versions": multiple_versions,
            "unmapped_video_inventory": max(
                [
                    (ad.creative_intel or {}).get("unmapped_video_inventory_count", 0)
                    for ad in request.ads
                ] or [0]
            ),
        },
        "message": f"Imported {imported} new ads, updated {updated} existing ads",
    }


@router.post("/scraped-ads/{ad_id}/save")
def save_scraped_ad_with_angle(
    ad_id: str,
    angle_tag: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
):
    """Update the angle tag on a scraped ad (can also clear it by passing null)."""
    from app.models import ScrapedAd
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    ad.angle_tag = angle_tag
    db.commit()
    return {"id": ad_id, "angle_tag": ad.angle_tag}


@router.patch("/scraped-ads/{ad_id}/strategy-notes")
def update_strategy_notes(
    ad_id: str,
    notes: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Partially update the free-text strategy notes for a scraped ad."""
    from app.models import ScrapedAd
    allowed = {'hook_type', 'persona', 'promise', 'proof_type', 'funnel_stage', 'pacing', 'numbers_used'}
    unknown = set(notes) - allowed
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown strategy note field(s): {sorted(unknown)}")
    # A non-string, non-null value (e.g. {"hook_type": 123}) would otherwise
    # silently coerce to None below instead of erroring — cheap hardening,
    # not currently reachable from the UI (code-auditor pre-push review, LOW).
    invalid = {k: v for k, v in notes.items() if v is not None and not isinstance(v, str)}
    if invalid:
        raise HTTPException(status_code=400, detail=f"Strategy note fields must be strings or null: {sorted(invalid)}")
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    for field in allowed & set(notes):
        value = notes[field]
        setattr(ad, field, value.strip() if isinstance(value, str) and value.strip() else None)
    db.commit()
    return {"id": ad_id, **{field: getattr(ad, field) for field in allowed}}


@router.get("/scraped-ads/{ad_id}/related")
def get_related_research_ads(
    ad_id: str,
    limit: int = 6,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return explainable related patterns, never a fabricated performance rank."""
    from app.models import ScrapedAd
    source = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Ad not found")
    # Bounded to the most recently seen rows so this stays cheap regardless of
    # how large scraped_ads grows — a full-table scan here (as an earlier
    # version of this endpoint did) is the exact query pattern already
    # flagged as a scaling risk elsewhere in this file.
    candidates = (
        db.query(ScrapedAd)
        .filter(ScrapedAd.id != source.id)
        .order_by(ScrapedAd.last_seen.desc())
        .limit(500)
        .all()
    )
    scored = []
    for candidate in candidates:
        match = _related_pattern_score(source, candidate)
        if not match:
            continue
        score, reasons = match
        scored.append((score, candidate, reasons))
    scored.sort(key=lambda item: (-item[0], _parse_research_date(item[1].last_seen) or datetime.min))
    return [{**_serialize_scraped_ad(ad), "match_reasons": reasons} for _, ad, reasons in scored[:max(1, min(limit, 12))]]


@router.get("/config-verticals/{config_id}/browse-ads")
def get_vertical_browse_ads(
    config_id: str,
    sub_vertical: str | None = None,
    angle_tag: str | None = None,
    media_type: str | None = None,
    active_only: bool = False,
    advertiser: str | None = None,
    sort_by: str = "newest_seen",
    creative_tags: str | None = None,
    cta_type: str | None = None,
    page_type: str | None = None,
    new_within_days: int | None = None,
    needs_tagging: bool = False,
    ads_per_advertiser: int | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return all unique scraped ads for a pre-configured vertical (flat list for card gallery).

    config_id must match a key in VERTICAL_KEYWORD_SETS (e.g. 'commercial_insurance').
    For Home Services, pass sub_vertical to scope to a sub-vertical label.
    Deduplicates by content_hash. Applies optional angle/active/advertiser filters.
    """
    from app.models import ScrapedAd, SavedSearch, Vertical, FacebookPage, PageBlacklist
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS, ALWAYS_BLOCKED_PAGES
    from sqlalchemy import func, distinct, or_
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

    # Get blacklisted page names — DB list plus always-blocked hardcoded set
    blacklisted_names = (
        {p.page_name.lower() for p in db.query(PageBlacklist.page_name).all()}
        | {p.lower() for p in ALWAYS_BLOCKED_PAGES}
    )

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
    if media_type and media_type not in RESEARCH_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown media_type: {media_type}")
    if media_type:
        query = query.filter(
            or_(
                func.nullif(ScrapedAd.media_type, "").is_(None),
                ~func.lower(ScrapedAd.media_type).in_(["image", "video", "carousel"]),
            ) if media_type == "unknown" else ScrapedAd.media_type == media_type
        )
    if active_only:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        query = query.filter(ScrapedAd.last_seen >= cutoff)
    selected_tags = [tag for tag in (creative_tags or "").split(",") if tag]
    unknown_tags = set(selected_tags) - RESEARCH_CREATIVE_TAGS
    if unknown_tags:
        raise HTTPException(status_code=400, detail=f"Unknown creative tag(s): {', '.join(sorted(unknown_tags))}")
    if cta_type:
        if cta_type not in RESEARCH_CTA_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown cta_type: {cta_type}")
        query = query.filter(ScrapedAd.cta_type == cta_type)
    if page_type:
        if page_type not in RESEARCH_PAGE_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown page_type: {page_type}")
        query = query.filter(ScrapedAd.page_type == page_type)
    if new_within_days is not None:
        if not 1 <= new_within_days <= 90:
            raise HTTPException(status_code=400, detail="new_within_days must be between 1 and 90")
        query = query.filter(ScrapedAd.first_seen >= datetime.now(timezone.utc) - timedelta(days=new_within_days))
    if needs_tagging:
        query = query.filter(ScrapedAd.taxonomy_source.is_(None))
    if ads_per_advertiser is not None and not 1 <= ads_per_advertiser <= 20:
        raise HTTPException(status_code=400, detail="ads_per_advertiser must be between 1 and 20")

    if sort_by not in RESEARCH_SORT_OPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown sort_by: {sort_by}. Use one of: {', '.join(sorted(RESEARCH_SORT_OPTIONS))}",
        )
    current_ads = [
        ad for ad in query.all()
        if (not ad.brand_name or ad.brand_name.lower() not in blacklisted_names)
        and (not selected_tags or any(tag in (ad.creative_tags or []) for tag in selected_tags))
        and _matches_research_vertical(ad, config_id)
    ]
    ads = _cap_ads_per_advertiser(_sort_research_ads(current_ads, sort_by), ads_per_advertiser)[:limit]

    # Compute running duration; filter blacklisted advertisers and off-topic ads
    now = datetime.utcnow()
    result = []
    for ad in ads:
        # Page blacklist check (DB list + hardcoded always-blocked set)
        if ad.brand_name and ad.brand_name.lower() in blacklisted_names:
            continue

        start = _parse_research_date(ad.start_date)
        running_days = max(0, (now - start).days) if start else None

        # "Active" proxy: seen within last 30 days
        is_active = False
        last_seen = _parse_research_date(ad.last_seen)
        if last_seen:
            is_active = (now - last_seen).days <= 30

        result.append({
            "id": ad.id,
            "brand_name": ad.brand_name,
            "headline": ad.headline,
            "ad_copy": ad.ad_copy,
            "cta_text": ad.cta_text,
            "ad_link": ad.ad_link,
            "media_url": ad.media_url,
            "media_type": ad.media_type,
            "platforms": ad.platforms,
            "destination_domain": ad.destination_domain,
            "source_query": ad.source_query,
            "rank_position": ad.rank_position,
            "sort_mode": ad.sort_mode,
            "is_multiple_versions": ad.is_multiple_versions,
            "video_urls": ad.video_urls,
            "thumbnail_url": ad.thumbnail_url,
            "creative_intel": ad.creative_intel,
            "volume_score": ad.volume_score,
            "start_date": _serialize_research_datetime(ad.start_date),
            "running_days": running_days,
            "is_active": is_active,
            "seen_count": ad.seen_count or 1,
            "angle_tag": ad.angle_tag,
            "hook_type": ad.hook_type,
            "persona": ad.persona,
            "promise": ad.promise,
            "proof_type": ad.proof_type,
            "funnel_stage": ad.funnel_stage,
            "pacing": ad.pacing,
            "numbers_used": ad.numbers_used,
            "creative_tags": ad.creative_tags or [],
            "cta_type": ad.cta_type,
            "page_type": ad.page_type,
            "video_length_seconds": ad.video_length_seconds,
            "media_preview_url": ad.media_preview_url,
            "media_width": ad.media_width,
            "media_height": ad.media_height,
            "taxonomy_source": ad.taxonomy_source,
            "taxonomy_confidence": ad.taxonomy_confidence,
            "is_saved": ad.is_saved,
            "last_seen": _serialize_research_datetime(ad.last_seen),
            "first_seen": _serialize_research_datetime(ad.first_seen),
        })

    return result


@router.delete("/config-verticals/{config_id}/ads")
def clear_vertical_ads(
    config_id: str,
    sub_vertical: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete all non-saved scraped ads for a pre-configured vertical.

    Finds the matching Vertical records by label, then deletes all ScrapedAd rows
    linked to those verticals' SavedSearches where is_saved=False.
    Saved ads (is_saved=True) are preserved.
    """
    from app.models import ScrapedAd, SavedSearch, Vertical
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS

    if config_id not in VERTICAL_KEYWORD_SETS:
        raise HTTPException(status_code=404, detail=f"Unknown vertical config: {config_id}")

    config = VERTICAL_KEYWORD_SETS[config_id]

    # Determine vertical labels (same logic as get_vertical_browse_ads)
    if config_id == "home_services":
        if sub_vertical:
            selected = config.get("sub_verticals", {}).get(sub_vertical)
            if not selected:
                raise HTTPException(status_code=404, detail=f"Unknown sub-vertical: {sub_vertical}")
            vertical_labels = [selected["label"]]
        else:
            vertical_labels = [sv["label"] for sv in config.get("sub_verticals", {}).values()]
    else:
        vertical_labels = [config["label"]]

    verticals = db.query(Vertical).filter(Vertical.name.in_(vertical_labels)).all()
    if not verticals:
        return {"deleted": 0}

    vertical_ids = [v.id for v in verticals]
    search_ids = [
        s.id
        for s in db.query(SavedSearch.id).filter(SavedSearch.vertical_id.in_(vertical_ids)).all()
    ]
    if not search_ids:
        return {"deleted": 0}

    deleted = (
        db.query(ScrapedAd)
        .filter(ScrapedAd.search_id.in_(search_ids), ScrapedAd.is_saved == False)  # noqa: E712
        .delete(synchronize_session="fetch")
    )
    db.commit()
    return {"deleted": deleted}


@router.post("/search-and-save-vertical")
async def search_and_save_vertical(
    vertical_id: str,
    sub_vertical: str | None = None,
    limit_per_keyword: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
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

    print(
        f"[research] search-and-save-vertical called: vertical_id={vertical_id} "
        f"sub_vertical={sub_vertical} limit_per_keyword={limit_per_keyword}"
    )

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
    rate_limited = False

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
                    rate_limited = True
                    first_error = first_error or "Rate limit reached before all keywords were checked"
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
                print(
                    f"[research] scraper returned {len(ads)} ads for "
                    f"vertical='{label}' keyword='{keyword}'"
                )
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

        if rate_limited:
            break

    return {
        "total_new": total_new,
        "total_duplicate": total_duplicate,
        "keywords_run": keywords_run,
        "message": f"Refreshed {keywords_run} keywords — {total_new} new ads found",
        "first_error": first_error,  # None when all succeed; error class + message when any fail
        "rate_limited": rate_limited,
        "status": "failed" if first_error and keywords_run == 0 and not rate_limited else "partial" if first_error or rate_limited else "complete",
    }
