from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Brand, Product, GeneratedAd, WinningAd, FacebookCampaign
from app.services.facebook_service import FacebookService

router = APIRouter()


def extract_niche(adset_name: str) -> str:
    if not adset_name:
        return "Unknown"
    parts = adset_name.split(" - ")
    return parts[1].strip() if len(parts) >= 2 else adset_name

@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """
    Get aggregated statistics for the dashboard.
    """
    brands_count = db.query(Brand).count()
    products_count = db.query(Product).count()
    generated_ads_count = db.query(GeneratedAd).count()
    templates_count = db.query(WinningAd).count()
    campaigns_count = db.query(FacebookCampaign).count()

    return {
        "brands_count": brands_count,
        "products_count": products_count,
        "generated_ads_count": generated_ads_count,
        "templates_count": templates_count,
        "campaigns_count": campaigns_count
    }


@router.get("/niche-summary")
def get_niche_summary(
    ad_account_id: str | None = Query(None),
    date_preset: str = Query("last_7d"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """
    Aggregate Meta ad set performance by niche for the Dashboard.
    Returns [] on Meta API failures so the Dashboard remains usable.
    """
    try:
        svc = FacebookService()
        insights = svc.get_account_insights_bulk(
            ad_account_id=ad_account_id,
            date_preset=date_preset,
            date_from=date_from,
            date_to=date_to,
        )

        by_niche = {}
        for row in insights.values():
            adset_name = row.get("adset_name") or ""
            niche = extract_niche(adset_name)
            bucket = by_niche.setdefault(
                niche,
                {
                    "niche": niche,
                    "adset_count": 0,
                    "total_spend": 0.0,
                    "cpl_total": 0.0,
                    "cpl_count": 0,
                    "roas_total": 0.0,
                    "roas_count": 0,
                },
            )

            bucket["adset_count"] += 1
            bucket["total_spend"] += float(row.get("spend") or 0)

            if row.get("cpl") is not None:
                bucket["cpl_total"] += float(row["cpl"])
                bucket["cpl_count"] += 1

            if row.get("roas") is not None:
                bucket["roas_total"] += float(row["roas"])
                bucket["roas_count"] += 1

        summary = []
        for bucket in by_niche.values():
            summary.append({
                "niche": bucket["niche"],
                "adset_count": bucket["adset_count"],
                "total_spend": round(bucket["total_spend"], 2),
                "avg_cpl": round(bucket["cpl_total"] / bucket["cpl_count"], 2) if bucket["cpl_count"] else None,
                "avg_roas": round(bucket["roas_total"] / bucket["roas_count"], 2) if bucket["roas_count"] else None,
            })

        return sorted(summary, key=lambda item: item["total_spend"], reverse=True)
    except Exception:
        return []
