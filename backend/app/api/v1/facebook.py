import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, Optional
from app.services.facebook_service import FacebookService

logger = logging.getLogger(__name__)
from app.models import FacebookAd, FacebookAdSet, FacebookCampaign, User
from app.database import get_db
from app.core.deps import get_current_active_user, require_permission
from sqlalchemy.orm import Session

router = APIRouter()

def get_facebook_service():
    service = FacebookService()
    try:
        if not service.api:
            service.initialize()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return service

@router.get("/accounts")
def get_ad_accounts(
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(get_current_active_user)
):
    try:
        return service.get_ad_accounts()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/campaigns")
def read_campaigns(
    ad_account_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(get_current_active_user)
):
    try:
        campaigns = service.get_campaigns(ad_account_id)
        # Convert FB objects to dicts
        return [dict(c) for c in campaigns]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/campaigns")
def create_campaign(
    campaign: Dict[str, Any],
    ad_account_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(require_permission("campaigns:write"))
):
    try:
        result = service.create_campaign(campaign, ad_account_id)
        return dict(result)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Create campaign failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pixels")
def read_pixels(
    ad_account_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(get_current_active_user)
):
    try:
        pixels = service.get_pixels(ad_account_id)
        # Convert FB objects to dicts
        return [dict(p) for p in pixels]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pages")
def read_pages(
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(get_current_active_user)
):
    try:
        pages = service.get_pages()
        return pages
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
def sync_from_meta(
    ad_account_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Import all campaigns and ad sets from Meta into the local DB.

    Safe to run multiple times — uses fb_campaign_id / fb_adset_id to upsert,
    so existing records are updated rather than duplicated.
    Returns counts of created vs. updated records.
    """
    try:
        campaigns_raw = service.get_campaigns(ad_account_id=ad_account_id)
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch campaigns from Meta: {e}")

    created_campaigns = 0
    updated_campaigns = 0
    created_adsets = 0
    updated_adsets = 0

    for c in campaigns_raw:
        fb_id = str(c.get("id") or c.get(FacebookCampaign.__table__.c.get("fb_campaign_id", "id"), ""))
        if not fb_id:
            continue

        existing = db.query(FacebookCampaign).filter(FacebookCampaign.fb_campaign_id == fb_id).first()
        budget_type = "CBO" if c.get("daily_budget") or c.get("lifetime_budget") else "ABO"
        if existing:
            existing.name = c.get("name", existing.name)
            existing.status = c.get("status", existing.status)
            updated_campaigns += 1
            campaign_db = existing
        else:
            campaign_db = FacebookCampaign(
                id=str(uuid.uuid4()),
                name=c.get("name", "Imported Campaign"),
                objective=c.get("objective", "OUTCOME_LEADS"),
                budget_type=budget_type,
                status=c.get("status", "PAUSED"),
                fb_campaign_id=fb_id,
                special_ad_categories=c.get("special_ad_categories", []),
            )
            db.add(campaign_db)
            created_campaigns += 1

        db.flush()  # ensure campaign_db.id is available

        # Sync ad sets for this campaign
        try:
            adsets_raw = service.get_adsets(campaign_id=fb_id)
        except Exception:
            continue

        for a in adsets_raw:
            fb_adset_id = str(a.get("id") or "")
            if not fb_adset_id:
                continue

            existing_as = db.query(FacebookAdSet).filter(FacebookAdSet.fb_adset_id == fb_adset_id).first()
            if existing_as:
                existing_as.name = a.get("name", existing_as.name)
                existing_as.status = a.get("status", existing_as.status)
                existing_as.fb_adset_id = fb_adset_id
                updated_adsets += 1
            else:
                db.add(FacebookAdSet(
                    id=str(uuid.uuid4()),
                    campaign_id=campaign_db.id,
                    name=a.get("name", "Imported Ad Set"),
                    optimization_goal=a.get("optimization_goal", "LEAD_GENERATION"),
                    status=a.get("status", "PAUSED"),
                    fb_adset_id=fb_adset_id,
                    daily_budget=int(a["daily_budget"]) if a.get("daily_budget") else None,
                    budget_schedule_type="DAILY" if a.get("daily_budget") else "LIFETIME",
                ))
                created_adsets += 1

    db.commit()
    return {
        "message": "Sync complete",
        "campaigns": {"created": created_campaigns, "updated": updated_campaigns},
        "adsets": {"created": created_adsets, "updated": updated_adsets},
    }


@router.get("/adsets/saved")
def read_saved_adsets(
    campaign_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Return ad sets stored in our DB (includes fb_adset_id for live insights lookup).
    Deduplicates by fb_adset_id — if the same fb_adset_id appears more than once,
    only the most recently created entry is returned.
    """
    q = db.query(FacebookAdSet)
    if campaign_id:
        q = q.filter(FacebookAdSet.campaign_id == campaign_id)
    all_adsets = q.order_by(FacebookAdSet.created_at.desc()).all()

    # Deduplicate by fb_adset_id — keep the first (most recent) occurrence
    seen_fb_ids = set()
    adsets = []
    for a in all_adsets:
        key = a.fb_adset_id or a.id  # fallback to id for rows with no fb_adset_id
        if key not in seen_fb_ids:
            seen_fb_ids.add(key)
            adsets.append(a)

    return [
        {
            "id": a.id,
            "name": a.name,
            "fb_adset_id": a.fb_adset_id,
            "status": a.status,
            "campaign_id": a.campaign_id,
        }
        for a in adsets
    ]


@router.post("/sync/cleanup")
def cleanup_duplicate_adsets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Remove duplicate ad set rows that share the same fb_adset_id.
    Keeps the most recently created row for each fb_adset_id.
    Returns count of rows deleted.
    """
    from sqlalchemy import func

    # Find fb_adset_ids that appear more than once
    dupes = (
        db.query(FacebookAdSet.fb_adset_id)
        .filter(FacebookAdSet.fb_adset_id.isnot(None))
        .group_by(FacebookAdSet.fb_adset_id)
        .having(func.count(FacebookAdSet.id) > 1)
        .all()
    )

    deleted = 0
    for (fb_id,) in dupes:
        rows = (
            db.query(FacebookAdSet)
            .filter(FacebookAdSet.fb_adset_id == fb_id)
            .order_by(FacebookAdSet.created_at.desc())
            .all()
        )
        # Keep first (most recent), delete the rest
        for row in rows[1:]:
            db.delete(row)
            deleted += 1

    db.commit()
    return {"deleted": deleted, "message": f"Removed {deleted} duplicate ad set row(s)"}


@router.get("/adsets")
def read_adsets(
    ad_account_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(get_current_active_user)
):
    try:
        adsets = service.get_adsets(ad_account_id, campaign_id)
        return [dict(a) for a in adsets]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/adsets")
def create_adset(
    adset: Dict[str, Any],
    ad_account_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(require_permission("campaigns:write"))
):
    try:
        result = service.create_adset(adset, ad_account_id)
        return dict(result)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Create adset failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/creatives")
def create_creative(
    creative: Dict[str, Any],
    ad_account_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(require_permission("campaigns:write"))
):
    try:
        result = service.create_creative(creative, ad_account_id)
        return dict(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Create creative failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ads")
def create_ad(
    ad: Dict[str, Any],
    ad_account_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(require_permission("campaigns:write"))
):
    try:
        result = service.create_ad(ad, ad_account_id)
        return dict(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Create ad failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/ads")
def read_ads(
    adset_id: str,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(get_current_active_user)
):
    try:
        ads = service.get_ads(adset_id)
        return [dict(a) for a in ads]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/campaigns/save")
def save_campaign_locally(
    campaign_data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("campaigns:write"))
):
    try:
        # Check if exists
        existing = db.query(FacebookCampaign).filter(FacebookCampaign.id == campaign_data.get('id')).first()
        if existing:
            return {"message": "Campaign already exists", "id": existing.id}

        daily_budget = campaign_data.get('dailyBudget')
        if daily_budget is not None:
            daily_budget = int(float(daily_budget))

        lifetime_budget = campaign_data.get('lifetimeBudget')
        if lifetime_budget is not None:
            lifetime_budget = int(float(lifetime_budget))

        end_time = None
        end_time_raw = campaign_data.get('endTime')
        if end_time_raw:
            try:
                from datetime import datetime as _dt
                end_time = _dt.fromisoformat(str(end_time_raw).replace('Z', '+00:00'))
            except Exception:
                end_time = None

        special_ad_categories = campaign_data.get('specialAdCategories') or []
        if isinstance(special_ad_categories, str):
            special_ad_categories = [special_ad_categories] if special_ad_categories else []

        new_campaign = FacebookCampaign(
            id=campaign_data.get('id'),
            name=campaign_data.get('name'),
            objective=campaign_data.get('objective'),
            budget_type=campaign_data.get('budgetType', 'ABO'),
            budget_schedule_type=campaign_data.get('budgetScheduleType', 'DAILY'),
            daily_budget=daily_budget,
            lifetime_budget=lifetime_budget,
            end_time=end_time,
            bid_strategy=campaign_data.get('bidStrategy'),
            special_ad_categories=special_ad_categories,
            status=campaign_data.get('status'),
            fb_campaign_id=campaign_data.get('fbCampaignId')
        )
        db.add(new_campaign)
        db.commit()
        db.refresh(new_campaign)
        return {"message": "Campaign saved locally", "id": new_campaign.id}
    except Exception as e:
        db.rollback()
        print(f"Error saving campaign locally: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/adsets/save")
def save_adset_locally(
    adset_data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("campaigns:write"))
):
    try:
        # Check if exists
        existing = db.query(FacebookAdSet).filter(FacebookAdSet.id == adset_data.get('id')).first()
        if existing:
            return {"message": "AdSet already exists", "id": existing.id}
            
        # Ensure campaign exists (FK check)
        campaign_id = adset_data.get('campaignId')
        if not campaign_id:
             raise HTTPException(status_code=400, detail="campaignId is required")
             
        # We assume campaign is already saved by the frontend calling /campaigns/save first

        daily_budget = adset_data.get('dailyBudget')
        if daily_budget is not None:
            daily_budget = int(float(daily_budget))

        lifetime_budget = adset_data.get('lifetimeBudget')
        if lifetime_budget is not None:
            lifetime_budget = int(float(lifetime_budget))

        bid_amount = adset_data.get('bidAmount')
        if bid_amount is not None:
            bid_amount = int(float(bid_amount))

        end_time = None
        end_time_raw = adset_data.get('endTime')
        if end_time_raw:
            try:
                from datetime import datetime as _dt
                end_time = _dt.fromisoformat(str(end_time_raw).replace('Z', '+00:00'))
            except Exception:
                end_time = None

        new_adset = FacebookAdSet(
            id=adset_data.get('id'),
            campaign_id=campaign_id,
            name=adset_data.get('name'),
            optimization_goal=adset_data.get('optimizationGoal'),
            budget_schedule_type=adset_data.get('budgetScheduleType', 'DAILY'),
            daily_budget=daily_budget,
            lifetime_budget=lifetime_budget,
            end_time=end_time,
            bid_strategy=adset_data.get('bidStrategy'),
            bid_amount=bid_amount,
            targeting=adset_data.get('targeting'),
            pixel_id=adset_data.get('pixelId'),
            conversion_event=adset_data.get('conversionEvent'),
            status=adset_data.get('status'),
            fb_adset_id=adset_data.get('fbAdsetId')
        )
        db.add(new_adset)
        db.commit()
        db.refresh(new_adset)
        return {"message": "AdSet saved locally", "id": new_adset.id}
    except Exception as e:
        db.rollback()
        print(f"Error saving adset locally: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ads/save")
def save_ad_locally(
    ad_data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("campaigns:write"))
):
    try:
        # Check if adset exists locally, if not we might need to create it or handle error
        # For now, assuming adset exists or we just save the ID

        new_ad = FacebookAd(
            id=ad_data.get('id'),
            adset_id=ad_data.get('adsetId'),
            name=ad_data.get('name'),
            creative_name=ad_data.get('creativeName'),
            image_url=ad_data.get('imageUrl'),
            # Video support fields
            media_type=ad_data.get('mediaType', 'image'),
            video_url=ad_data.get('videoUrl'),
            video_id=ad_data.get('videoId'),
            thumbnail_url=ad_data.get('thumbnailUrl'),
            bodies=ad_data.get('bodies'),
            headlines=ad_data.get('headlines'),
            description=ad_data.get('description'),
            cta=ad_data.get('cta'),
            website_url=ad_data.get('websiteUrl'),
            status=ad_data.get('status'),
            fb_ad_id=ad_data.get('fbAdId'),
            fb_creative_id=ad_data.get('fbCreativeId')
        )
        db.add(new_ad)
        db.commit()
        db.refresh(new_ad)
        return {"message": "Ad saved locally", "id": new_ad.id}
    except Exception as e:
        db.rollback()
        print(f"Error saving ad locally: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload-image")
def upload_image(
    data: Dict[str, str],
    ad_account_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(require_permission("campaigns:write"))
):
    try:
        image_url = data.get("image_url")
        if not image_url:
            raise HTTPException(status_code=400, detail="image_url is required")
        image_hash = service.upload_image(image_url, ad_account_id)
        return {"image_hash": image_hash}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload-video")
def upload_video(
    data: Dict[str, Any],
    ad_account_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(require_permission("campaigns:write"))
):
    """Upload a video to Facebook Ad Library.

    Request body:
        video_url: URL of the video to upload
        wait_for_ready: Whether to wait for processing (default True)
        timeout: Max seconds to wait (default 600)

    Returns:
        video_id: Facebook video ID
        status: 'processing', 'ready', or 'error'
        thumbnails: List of auto-generated thumbnail URLs (if ready)
    """
    video_url = data.get("video_url")
    if not video_url:
        raise HTTPException(status_code=400, detail="video_url is required")

    try:
        wait_for_ready = data.get("wait_for_ready", True)
        timeout = data.get("timeout", 600)

        result = service.upload_video(
            video_url,
            ad_account_id,
            wait_for_ready=wait_for_ready,
            timeout=timeout
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/video-status/{video_id}")
def get_video_status(
    video_id: str,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(get_current_active_user)
):
    """Check the processing status of a video.

    Returns:
        status: 'processing', 'ready', or 'error'
        video_id: The video ID
        length: Video duration in seconds (if ready)
    """
    try:
        return service.get_video_status(video_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/video-thumbnails/{video_id}")
def get_video_thumbnails(
    video_id: str,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(get_current_active_user)
):
    """Get auto-generated thumbnails for a video.

    Returns:
        thumbnails: List of thumbnail URLs
    """
    try:
        thumbnails = service.get_video_thumbnails(video_id)
        return {"thumbnails": thumbnails}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/locations/search")
def search_locations(
    q: str,
    type: str = "city",
    limit: int = 10,
    ad_account_id: Optional[str] = None,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(get_current_active_user)
):
    try:
        locations = service.search_locations(q, type, limit, ad_account_id)
        return [dict(loc) for loc in locations]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

