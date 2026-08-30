"""Ad Copy Library — Joel's real winning ad copy, used as few-shot style examples.

Routes:
  POST /sync              Pull all ACTIVE/PAUSED ads from Meta, upsert to library
  GET  /                  List all entries (optional ?niche= filter)
  PATCH /{id}/pin         Toggle is_pinned on an entry
  DELETE /{id}            Remove an entry from the library
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AdCopyLibrary, User
from app.services.facebook_service import FacebookService
from app.services.niche_extraction import _extract_niche
from app.core.deps import get_current_active_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/sync")
def sync_copy_library(
    ad_account_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Pull all ACTIVE/PAUSED ads from Meta and upsert into the library.

    Adset names are fetched directly from Meta (via get_adset_name_map) rather
    than from the local DB, so niche extraction works even for adsets that
    haven't been pulled into the local FacebookAdSet table yet.

    Niche extraction applies a blocklist filter to reject batch/test tags
    (e.g., 'Batch 3', 'V2', 'SCALE') — those are stored as NULL and displayed
    as 'General' in the UI.

    Existing entries are updated (headline/body/niche/status).
    Entries already in the library are NOT deleted on sync — Joel may have
    intentionally removed them.

    Returns counts of created vs updated entries.
    """
    try:
        svc = FacebookService()
        ads = svc.get_account_ads_with_creative(ad_account_id=ad_account_id)
    except Exception as exc:
        logger.error("Meta API error during copy library sync (ads): %s", exc)
        raise HTTPException(status_code=502, detail=f"Meta API error: {str(exc)}")

    # Fetch adset names directly from Meta — more complete than the local DB
    # which only contains adsets synced since last login.
    adset_name_map = svc.get_adset_name_map(ad_account_id=ad_account_id)

    # One-time cleanup: null out legacy "Unknown" niche strings written by the
    # old sync code that couldn't resolve adset names. NULL displays as "General"
    # which is correct. Rows not touched by this sync (deleted/archived ads) also
    # benefit from this cleanup.
    db.execute(text("UPDATE ad_copy_library SET niche = NULL WHERE niche = 'Unknown'"))

    created = 0
    updated = 0

    for ad in ads:
        fb_ad_id = ad["fb_ad_id"]
        fb_adset_id = ad.get("fb_adset_id") or ""
        adset_name = adset_name_map.get(fb_adset_id, "")
        niche = _extract_niche(adset_name)
        status = ad.get("status") or None

        existing = db.query(AdCopyLibrary).filter(
            AdCopyLibrary.fb_ad_id == fb_ad_id
        ).first()

        if existing:
            existing.headline = ad["headline"]
            existing.body = ad["body"]
            existing.fb_adset_id = fb_adset_id or existing.fb_adset_id
            existing.adset_name = adset_name or existing.adset_name
            if adset_name:
                # Fresh name from Meta — always re-extract. This clears any stale
                # "Unknown" or mis-tagged values written by previous sync versions.
                existing.niche = _extract_niche(adset_name)
            else:
                # Map miss — fall back to stored name but only overwrite if we
                # get a valid niche (don't wipe a good value with None).
                fallback = existing.adset_name or ""
                if fallback:
                    new_niche = _extract_niche(fallback)
                    if new_niche is not None:
                        existing.niche = new_niche
            existing.status = status
            updated += 1
        else:
            entry = AdCopyLibrary(
                fb_ad_id=fb_ad_id,
                fb_adset_id=fb_adset_id or None,
                adset_name=adset_name or None,
                niche=niche,
                headline=ad["headline"],
                body=ad["body"],
                status=status,
                is_pinned=False,
            )
            db.add(entry)
            created += 1

    db.commit()

    # --- Performance data pass ------------------------------------------------
    # Pull lifetime spend + CPL for every synced ad and write it back. Runs after
    # the upsert commit so freshly-created rows are also populated. Non-fatal:
    # if Meta insights fail, the library is still synced (spend/cpl stay null).
    perf_updated = 0
    try:
        all_ad_ids = [ad["fb_ad_id"] for ad in ads if ad.get("fb_ad_id")]
        insights_map = svc.get_ad_insights_map(all_ad_ids, ad_account_id=ad_account_id)
        if all_ad_ids and not insights_map:
            # Distinguish "insights call failed" from "ads genuinely have no spend"
            # — otherwise a failed pass silently looks like a clean zero-spend sync.
            logger.warning(
                "Copy library sync: performance pass returned no data for %d ads "
                "(Meta insights may have failed/timed out) — spend/CPL left unchanged",
                len(all_ad_ids),
            )
        for fb_ad_id, metrics in insights_map.items():
            row = db.query(AdCopyLibrary).filter(
                AdCopyLibrary.fb_ad_id == fb_ad_id
            ).first()
            if row:
                row.spend = metrics.get("spend")
                row.cpl = metrics.get("cpl")
                perf_updated += 1
        db.commit()
    except Exception as exc:
        logger.warning("Copy library sync: performance pass failed (%s) — continuing", exc)
        db.rollback()

    logger.info(
        "Copy library sync: %d created, %d updated, %d with performance data",
        created, updated, perf_updated,
    )
    return {
        "created": created,
        "updated": updated,
        "total": created + updated,
        "with_performance": perf_updated,
        "message": (
            "Library synced. The AI will now use these examples to match "
            "your voice when generating copy."
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
    """Return library entries, pinned first, then by import date descending."""
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
            "status": e.status,
            "spend": float(e.spend) if e.spend is not None else None,
            "cpl": float(e.cpl) if e.cpl is not None else None,
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
