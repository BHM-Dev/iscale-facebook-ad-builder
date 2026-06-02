"""Ad Copy Library — Joel's real winning ad copy, used as few-shot style examples.

Routes:
  POST /sync              Pull all ACTIVE/PAUSED ads from Meta, upsert to library
  GET  /                  List all entries (optional ?niche= filter)
  PATCH /{id}/pin         Toggle is_pinned on an entry
  DELETE /{id}            Remove an entry from the library
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AdCopyLibrary, FacebookAdSet, User
from app.services.facebook_service import FacebookService
from app.core.deps import get_current_active_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_niche(adset_name: str) -> str:
    """Extract niche from ad set name pattern '[Date] - [Niche] - [Batch info]'."""
    if not adset_name:
        return "Unknown"
    parts = adset_name.split(" - ")
    return parts[1].strip() if len(parts) >= 2 else adset_name


@router.post("/sync")
def sync_copy_library(
    ad_account_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Pull all ACTIVE/PAUSED ads from Meta and upsert into the library.

    Adset names (used for niche extraction) are looked up from the local
    FacebookAdSet table rather than fetched from Meta — the SDK silently drops
    nested field syntax like 'adset{name}'.

    Existing entries are updated (headline/body/niche).
    Entries already in the library are NOT deleted on sync — Joel may have
    intentionally removed them.

    Returns counts of created vs updated entries.
    """
    try:
        svc = FacebookService()
        ads = svc.get_account_ads_with_creative(ad_account_id=ad_account_id)
    except Exception as exc:
        logger.error("Meta API error during copy library sync: %s", exc)
        raise HTTPException(status_code=502, detail=f"Meta API error: {str(exc)}")

    # Build adset_id → adset_name map from local DB
    # (populated by the scheduled Meta sync that runs on login)
    adset_ids = {ad["fb_adset_id"] for ad in ads if ad.get("fb_adset_id")}
    adset_name_map: dict[str, str] = {}
    if adset_ids:
        rows = (
            db.query(FacebookAdSet.fb_adset_id, FacebookAdSet.name)
            .filter(FacebookAdSet.fb_adset_id.in_(adset_ids))
            .all()
        )
        adset_name_map = {row.fb_adset_id: row.name for row in rows}

    created = 0
    updated = 0

    for ad in ads:
        fb_ad_id = ad["fb_ad_id"]
        fb_adset_id = ad.get("fb_adset_id") or ""
        adset_name = adset_name_map.get(fb_adset_id, "")
        niche = _extract_niche(adset_name)

        existing = db.query(AdCopyLibrary).filter(
            AdCopyLibrary.fb_ad_id == fb_ad_id
        ).first()

        if existing:
            # Refresh copy text in case the ad was edited in Meta
            existing.headline = ad["headline"]
            existing.body = ad["body"]
            existing.fb_adset_id = fb_adset_id or existing.fb_adset_id
            existing.adset_name = adset_name or existing.adset_name
            existing.niche = niche
            updated += 1
        else:
            entry = AdCopyLibrary(
                fb_ad_id=fb_ad_id,
                fb_adset_id=fb_adset_id or None,
                adset_name=adset_name or None,
                niche=niche,
                headline=ad["headline"],
                body=ad["body"],
                is_pinned=False,
            )
            db.add(entry)
            created += 1

    db.commit()
    logger.info("Copy library sync: %d created, %d updated", created, updated)
    return {
        "created": created,
        "updated": updated,
        "total": created + updated,
        "message": (
            "Library synced. Copy injection is coming soon — once enabled, "
            "the AI will write in your voice based on these ads."
        ),
    }


@router.get("/")
def list_copy_library(
    niche: str | None = Query(None, description="Filter by niche (partial match)"),
    pinned_only: bool = Query(False),
    limit: int = Query(200, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return library entries, pinned first, then by import date descending.

    CPL and spend are always null until a future performance sync pipeline is built.
    """
    q = db.query(AdCopyLibrary)

    if niche:
        q = q.filter(AdCopyLibrary.niche.ilike(f"%{niche}%"))
    if pinned_only:
        q = q.filter(AdCopyLibrary.is_pinned == True)  # noqa: E712

    entries = (
        q.order_by(
            AdCopyLibrary.is_pinned.desc(),
            AdCopyLibrary.imported_at.desc(),
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "id": e.id,
            "fb_ad_id": e.fb_ad_id,
            "fb_adset_id": e.fb_adset_id,
            "adset_name": e.adset_name,
            "niche": e.niche,
            "headline": e.headline,
            "body": e.body,
            "cta_type": e.cta_type,
            "is_pinned": e.is_pinned,
            "imported_at": e.imported_at.isoformat() if e.imported_at else None,
        }
        for e in entries
    ]


@router.patch("/{entry_id}/pin")
def toggle_pin(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Toggle is_pinned on a library entry."""
    entry = db.query(AdCopyLibrary).filter(AdCopyLibrary.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    entry.is_pinned = not entry.is_pinned
    db.commit()
    return {"id": entry.id, "is_pinned": entry.is_pinned}


@router.delete("/{entry_id}")
def delete_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Remove an entry from the library."""
    entry = db.query(AdCopyLibrary).filter(AdCopyLibrary.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    return {"deleted": entry_id}
