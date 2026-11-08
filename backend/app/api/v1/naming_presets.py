"""Shared naming presets: one naming convention per ad account.

GET never writes: an account with no saved row gets the default template
strings back with `saved: false`. Nothing here talks to Meta; `observed-codes`
reads names already in the local DB.
"""
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import FacebookAdSet, FacebookCampaign, NamingPreset, User, normalize_account_id
from app.services.naming_presets import DEFAULT_TEMPLATES, default_preset, observe_codes

router = APIRouter()

_LEVELS = ("campaign", "adset", "ad")


class CodeRow(BaseModel):
    code: str = Field(..., max_length=16)
    niche: Optional[str] = Field(None, max_length=120)
    wave: Optional[str] = Field(None, max_length=120)
    seen: Optional[int] = None


class NamingPresetIn(BaseModel):
    brand_code: str = Field("", max_length=40)
    tracking_tag: str = Field("", max_length=40)
    uppercase: bool = True
    templates: Dict[str, str]
    waves: List[CodeRow] = Field(default_factory=list, max_length=100)
    niche_codes: List[CodeRow] = Field(default_factory=list, max_length=500)
    objective_tags: Dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("templates")
    @classmethod
    def _templates(cls, value: Dict[str, str]) -> Dict[str, str]:
        unknown = set(value) - set(_LEVELS)
        if unknown:
            raise ValueError(f"unknown template level(s): {', '.join(sorted(unknown))}")
        if any(len(v or "") > 300 for v in value.values()):
            raise ValueError("templates are limited to 300 characters")
        return {level: value.get(level) or DEFAULT_TEMPLATES[level] for level in _LEVELS}


def _account(user: User, ad_account_id: str) -> str:
    acct = normalize_account_id(ad_account_id)
    allowed = user.allowed_account_ids()
    if allowed is not None and acct not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this ad account")
    return acct


def _serialize(row: NamingPreset) -> dict:
    return {
        "ad_account_id": row.ad_account_id,
        "brand_code": row.brand_code or "",
        "tracking_tag": row.tracking_tag or "",
        "uppercase": bool(row.uppercase),
        "templates": {level: (row.templates or {}).get(level) or DEFAULT_TEMPLATES[level] for level in _LEVELS},
        "waves": row.waves or [],
        "niche_codes": row.niche_codes or [],
        "objective_tags": row.objective_tags or {},
        "variant": row.variant,
        "soft_tags": row.soft_tags,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at,
        "saved": True,
    }


@router.get("/{ad_account_id}")
def get_naming_preset(ad_account_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    acct = _account(current_user, ad_account_id)
    row = db.query(NamingPreset).filter(NamingPreset.ad_account_id == acct).first()
    return _serialize(row) if row else default_preset(acct)


@router.put("/{ad_account_id}")
def put_naming_preset(
    ad_account_id: str,
    body: NamingPresetIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    acct = _account(current_user, ad_account_id)
    row = db.query(NamingPreset).filter(NamingPreset.ad_account_id == acct).first()
    if row is None:
        row = NamingPreset(ad_account_id=acct)
        db.add(row)
    row.brand_code = body.brand_code.strip()
    row.tracking_tag = body.tracking_tag.strip()
    row.uppercase = body.uppercase
    row.templates = body.templates
    row.waves = [{**r.model_dump(exclude_none=True), 'code': r.code.strip().upper()} for r in body.waves if r.code.strip()]
    row.niche_codes = [{**r.model_dump(exclude_none=True), 'code': r.code.strip().upper()} for r in body.niche_codes if r.code.strip()]
    row.objective_tags = body.objective_tags
    row.updated_by = current_user.id
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.get("/{ad_account_id}/observed-codes")
def get_observed_codes(ad_account_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    acct = _account(current_user, ad_account_id)
    bare = acct[4:]
    rows = (
        db.query(FacebookAdSet.name, FacebookCampaign.name)
        .join(FacebookCampaign, FacebookAdSet.campaign_id == FacebookCampaign.id)
        .filter(FacebookCampaign.fb_account_id.in_([acct, bare]))
        .all()
    )
    return observe_codes(rows)
