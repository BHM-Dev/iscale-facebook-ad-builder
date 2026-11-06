from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1 import pnl
from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import User, normalize_account_id
from app.services import max_cpl_service

router = APIRouter()


@router.get("/max-cpl")
def max_cpl(ad_account_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    account_id = normalize_account_id(ad_account_id)
    if account_id not in pnl._permitted_active_account_ids(db, current_user):
        raise HTTPException(status_code=403, detail="You do not have access to this ad account")
    # compute_max_cpl never raises: failures come back as {available: False, reason} and are cached briefly.
    return max_cpl_service.compute_max_cpl(db, account_id)
