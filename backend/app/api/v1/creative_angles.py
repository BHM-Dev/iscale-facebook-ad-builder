from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models import CreativeAngle, Vertical

router = APIRouter()


@router.get("/")
def list_creative_angles(
    vertical_id: Optional[str] = Query(None, description="Filter by vertical ID"),
    vertical_name: Optional[str] = Query(None, description="Filter by vertical name (e.g. 'Auto Insurance')"),
    db: Session = Depends(get_db),
):
    query = db.query(CreativeAngle).filter(CreativeAngle.is_active == True)

    if vertical_id:
        query = query.filter(CreativeAngle.vertical_id == vertical_id)
    elif vertical_name:
        vertical = db.query(Vertical).filter(Vertical.name == vertical_name).first()
        if vertical:
            query = query.filter(CreativeAngle.vertical_id == vertical.id)
        else:
            return []

    angles = query.order_by(CreativeAngle.sort_order).all()
    return [
        {
            "id": a.id,
            "vertical_id": a.vertical_id,
            "vertical_name": a.vertical.name if a.vertical else None,
            "name": a.name,
            "hook": a.hook,
            "headline": a.headline,
            "body": a.body,
            "sort_order": a.sort_order,
        }
        for a in angles
    ]


@router.get("/verticals")
def list_verticals(db: Session = Depends(get_db)):
    verticals = db.query(Vertical).order_by(Vertical.name).all()
    return [{"id": v.id, "name": v.name, "description": v.description} for v in verticals]
