"""Ad Copy Library — Joel's real winning ad copy, used as few-shot style examples.

Routes:
  POST /sync              Pull all ACTIVE/PAUSED ads from Meta, upsert to library
  GET  /                  List all entries (optional ?niche= filter)
  PATCH /{id}/pin         Toggle is_pinned on an entry
  DELETE /{id}            Remove an entry from the library
"""
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AdCopyLibrary, User
from app.services.facebook_service import FacebookService
from app.core.deps import get_current_active_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Patterns that indicate the extracted value is a batch/test tag, not a real niche.
# If the niche extraction produces one of these, fall back to None (displayed as "General").
_NON_NICHE_RE = re.compile(
    r'^(batch[\s\d]|set[\s\d]|v\d[\s_]|scale|open$|image$|calls$|test|broad|'
    r'retarget|phase[\s\d]|round[\s\d]|\d{4}-\d{2}-\d{2}|gbc\s*\|)',
    re.IGNORECASE,
)


def _extract_niche(adset_name: str) -> str | None:
    """Extract niche from ad set name pattern '[Date] - [Niche] - [Batch info]'.

    Returns None for empty names or when the extracted candidate looks like a
    batch/test label rather than a real niche. The caller stores None and the
    frontend displays it as 'General'.
    """
    if not adset_name:
        return None
    parts = adset_name.split(" - ")
    if len(parts) < 2:
        # No separator — can't extract niche reliably; store the full name if
        # it doesn't look like a batch tag, otherwise None.
        return None if _NON_NICHE_RE.match(adset_name.strip()) else adset_name.strip() or None

    candidate = parts[1].strip()
    if not candidate or _NON_NICHE_RE.match(candidate):
        return None
    return candidate


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
            # Use the best available adset name so a failed map call (adset_name="")
            # doesn't silently wipe an existing niche value.  If _extract_niche()
            # returns None (name doesn't parse cleanly), preserve whatever niche
            # was already stored rather than overwriting it with None.
            effective_adset_name = adset_name or existing.adset_name or ""
            new_niche = _extract_niche(effective_adset_name)
            if new_niche is not None:
                existing.niche = new_niche
            # else: keep existing.niche — don't overwrite a valid value with None
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
    logger.info("Copy library sync: %d created, %d updated", created, updated)
    return {
        "created": created,
        "updated": updated,
        "total": created + updated,
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
