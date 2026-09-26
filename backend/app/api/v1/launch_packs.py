"""Workspace-shared, exact-target launch shortcuts.

Packs deliberately hold Meta IDs rather than a vague 'last used' hint. The UI
revalidates those IDs against the current user's accessible Meta data before it
lands on Creative, so a deleted or inaccessible target fails safely.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import LaunchPack, User, normalize_account_id
from app.schemas.launch_packs import LaunchPackCreate, LaunchPackResponse
from app.api.v1.facebook import get_facebook_service
from app.services.facebook_service import FacebookService

router = APIRouter()


def _ensure_account_access(user: User, ad_account_id: str) -> None:
    allowed = user.allowed_account_ids()
    if allowed is not None and normalize_account_id(ad_account_id) not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this ad account")


def _validate_live_target(service: FacebookService, ad_account_id: str, campaign_id: str, adset_id: str) -> None:
    """Confirm the saved hierarchy with Meta before making it visible to teammates."""
    try:
        campaigns = [dict(item) for item in service.get_campaigns(ad_account_id)]
        if not any(str(item.get("id")) == str(campaign_id) for item in campaigns):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That campaign is not available in the selected ad account")
        adsets = [dict(item) for item in service.get_adsets(ad_account_id, campaign_id)]
        if not any(str(item.get("id")) == str(adset_id) for item in adsets):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That ad set is not available in the selected campaign")
    except HTTPException:
        raise
    except Exception as exc:
        # Do not save an unverified team shortcut during a transient Meta failure.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not verify this Meta target: {exc}")


@router.get("", response_model=List[LaunchPackResponse])
def list_launch_packs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # Packs are intentionally workspace-shared. Account access is checked again
    # while loading because a colleague's pack may point at an account this user
    # cannot act on.
    packs = db.query(LaunchPack).order_by(LaunchPack.updated_at.desc(), LaunchPack.created_at.desc()).all()
    allowed = current_user.allowed_account_ids()
    if allowed is None:
        return packs
    return [pack for pack in packs if normalize_account_id(pack.ad_account_id) in allowed]


@router.post("", response_model=LaunchPackResponse, status_code=status.HTTP_201_CREATED)
def create_launch_pack(
    request: LaunchPackCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    service: FacebookService = Depends(get_facebook_service),
):
    normalized_account_id = normalize_account_id(request.ad_account_id)
    _ensure_account_access(current_user, normalized_account_id)
    _validate_live_target(service, normalized_account_id, request.campaign_id, request.adset_id)
    payload = request.model_dump()
    payload["ad_account_id"] = normalized_account_id
    # Exact targets are unique in practice. Upsert rather than append so a
    # repeated click cannot bury the canonical shared shortcut under copies.
    pack = db.query(LaunchPack).filter(
        LaunchPack.ad_account_id == normalized_account_id,
        LaunchPack.campaign_id == request.campaign_id,
        LaunchPack.adset_id == request.adset_id,
    ).first()
    if pack:
        for key, value in payload.items():
            setattr(pack, key, value)
    else:
        pack = LaunchPack(**payload, created_by=current_user.id)
        db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


@router.delete("/{pack_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_launch_pack(
    pack_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    pack = db.query(LaunchPack).filter(LaunchPack.id == pack_id).first()
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Launch pack not found")
    _ensure_account_access(current_user, pack.ad_account_id)
    if not (current_user.is_superuser or pack.created_by == current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the pack creator can delete it")
    db.delete(pack)
    db.commit()
