"""
AI Insights — natural language queries powered by Claude + live account data.

POST /api/v1/ai-insights/query
  Body: { "query": "...", "ad_account_id": "act_123", "date_preset": "last_7d" }
  Returns: { "answer": "..." }

Claude receives live ad set + ad-level insights, brand assignments, niche
performance, and Copy Library data pulled directly from our own DB and the
Meta Marketing API. No MCP dependency.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import anthropic
import os
import json
import logging
from sqlalchemy.orm import Session
from app.core.deps import get_current_active_user, get_db
from app.models import User, FacebookAdSet, Brand, AdCopyLibrary
from app.services.facebook_service import FacebookService

logger = logging.getLogger(__name__)

router = APIRouter()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

VALID_PRESETS = {"today", "yesterday", "last_3d", "last_7d", "last_14d", "last_30d", "this_month", "last_month"}

SYSTEM_PROMPT = """You are an expert Meta Ads analyst embedded inside a media buyer's ad management tool.

You have been given a structured JSON snapshot of the account's live performance data. Use it to answer the user's question directly and concisely.

Guidelines:
- Lead with the number, then the context. Never bury the answer.
- Flag anything urgent at the top (e.g. high CPL, zero leads on significant spend).
- For "what to scale": look for low CPL + consistent leads + headroom in budget.
- For "what needs help": look for high CPL vs account average, declining trend, or spend with no conversions.
- Use $ for spend, % for rates. Round CPL to nearest cent. Round ROAS to 1 decimal.
- When comparing ad sets, sort by CPL ascending (best first) or by spend descending depending on context.
- If the data window is too short to draw conclusions, say so.
- Be direct. Joel is a media buyer who reads fast. No padding, no hedging unless warranted.

The data snapshot includes:
- adset_insights: per-ad-set metrics (spend, leads, CPL, impressions, CTR, ROAS) for the requested date window
- ad_insights: per-ad metrics within each ad set
- brand_assignments: which brand is assigned to each ad set
- niche_summary: aggregated performance by niche (extracted from ad set name pattern)
- copy_library_pinned: Joel's pinned winning ads (headline + body + CPL) for reference

If the user asks about a different time window than what's provided, let them know and answer from the available data."""


class InsightQueryRequest(BaseModel):
    query: str
    ad_account_id: Optional[str] = None
    date_preset: Optional[str] = "last_7d"


class InsightQueryResponse(BaseModel):
    answer: str
    date_preset_used: str


def _extract_niche(adset_name: str) -> str:
    """Extract niche from pattern: [Date] - [Niche] - [Batch]"""
    import re
    NON_NICHE = re.compile(
        r'^(batch\s*\d+|v\d+|scale|retarget|broad|phase\s*\d+|test|duplicate|copy)$',
        re.IGNORECASE
    )
    parts = [p.strip() for p in adset_name.split(" - ")]
    for part in parts[1:]:
        if part and not NON_NICHE.match(part) and not re.match(r'^\d{1,2}/\d{1,2}', part):
            return part
    return "General"


def _build_data_snapshot(db: Session, ad_account_id: str, date_preset: str) -> dict:
    """Pull all account data and return a compact snapshot for Claude."""
    svc = FacebookService()

    # 1. Ad set insights from Meta
    try:
        adset_insights_raw = svc.get_account_insights_bulk(
            ad_account_id=ad_account_id,
            date_preset=date_preset,
        )
    except Exception as e:
        logger.warning("Could not fetch adset insights: %s", e)
        adset_insights_raw = {}

    # 2. Ad-level insights from Meta
    try:
        ad_insights_raw = svc.get_account_ads_insights_bulk(
            ad_account_id=ad_account_id,
            date_preset=date_preset,
        )
    except Exception as e:
        logger.warning("Could not fetch ad insights: %s", e)
        ad_insights_raw = {}

    # 3. Brand assignments from DB (fb_adset_id → brand name)
    brand_map = {}
    try:
        rows = (
            db.query(FacebookAdSet.fb_adset_id, Brand.brand_name)
            .join(Brand, FacebookAdSet.brand_id == Brand.id, isouter=True)
            .filter(FacebookAdSet.fb_adset_id.isnot(None))
            .all()
        )
        for fb_adset_id, brand_name in rows:
            if fb_adset_id:
                brand_map[fb_adset_id] = brand_name or "Unassigned"
    except Exception as e:
        logger.warning("Could not fetch brand assignments: %s", e)

    # 4. Build adset_insights list
    adset_insights = []
    for fb_adset_id, m in adset_insights_raw.items():
        spend = float(m.get("spend") or 0)
        if spend < 0.01:
            continue
        adset_insights.append({
            "adset_id": fb_adset_id,
            "adset_name": m.get("adset_name", ""),
            "brand": brand_map.get(fb_adset_id, "Unassigned"),
            "niche": _extract_niche(m.get("adset_name", "")),
            "spend": round(spend, 2),
            "leads": int(m.get("leads") or 0),
            "cpl": round(float(m.get("cpl") or 0), 2),
            "impressions": int(m.get("impressions") or 0),
            "ctr": round(float(m.get("ctr") or 0), 3),
            "roas": round(float(m.get("roas") or 0), 2),
        })
    adset_insights.sort(key=lambda x: x["spend"], reverse=True)

    # 5. Build ad_insights — top 3 ads per adset by spend, skip zero-spend
    ad_insights = {}
    for fb_adset_id, ads in ad_insights_raw.items():
        top_ads = []
        for ad in sorted(ads, key=lambda a: float(a.get("spend") or 0), reverse=True)[:3]:
            spend = float(ad.get("spend") or 0)
            if spend < 0.01:
                continue
            top_ads.append({
                "ad_name": ad.get("ad_name", ""),
                "spend": round(spend, 2),
                "leads": int(ad.get("leads") or 0),
                "cpl": round(float(ad.get("cpl") or 0), 2),
                "ctr": round(float(ad.get("ctr") or 0), 3),
            })
        if top_ads:
            ad_insights[fb_adset_id] = top_ads

    # 6. Niche summary
    niche_map = {}
    for row in adset_insights:
        n = row["niche"]
        if n not in niche_map:
            niche_map[n] = {"adsets": 0, "spend": 0, "leads": 0}
        niche_map[n]["adsets"] += 1
        niche_map[n]["spend"] += row["spend"]
        niche_map[n]["leads"] += row["leads"]
    niche_summary = []
    for niche, data in sorted(niche_map.items(), key=lambda x: x[1]["spend"], reverse=True):
        cpl = round(data["spend"] / data["leads"], 2) if data["leads"] else None
        niche_summary.append({
            "niche": niche,
            "adsets": data["adsets"],
            "spend": round(data["spend"], 2),
            "leads": data["leads"],
            "cpl": cpl,
        })

    # 7. Pinned copy library entries
    try:
        pinned = (
            db.query(AdCopyLibrary)
            .filter(AdCopyLibrary.is_pinned == True)
            .order_by(AdCopyLibrary.cpl.asc().nullslast())
            .limit(5)
            .all()
        )
        copy_library_pinned = [
            {
                "niche": r.niche,
                "headline": r.headline,
                "body": r.body[:200] if r.body else "",
                "cpl": float(r.cpl) if r.cpl else None,
                "status": r.status,
            }
            for r in pinned
        ]
    except Exception as e:
        logger.warning("Could not fetch copy library: %s", e)
        copy_library_pinned = []

    return {
        "date_preset": date_preset,
        "adset_count": len(adset_insights),
        "adset_insights": adset_insights,
        "ad_insights": ad_insights,
        "brand_assignments": brand_map,
        "niche_summary": niche_summary,
        "copy_library_pinned": copy_library_pinned,
    }


@router.post("/query", response_model=InsightQueryResponse)
def query_insights(
    body: InsightQueryRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if not _anthropic_client:
        raise HTTPException(503, "AI service not configured — ANTHROPIC_API_KEY missing")

    date_preset = body.date_preset if body.date_preset in VALID_PRESETS else "last_7d"

    try:
        snapshot = _build_data_snapshot(db, body.ad_account_id, date_preset)
    except Exception as e:
        logger.error("Failed to build data snapshot: %s", e)
        raise HTTPException(500, f"Failed to load account data: {str(e)}")

    context_json = json.dumps(snapshot, indent=None, separators=(",", ":"))

    user_message = f"""Account data snapshot ({date_preset}):

{context_json}

---

Question: {body.query}"""

    try:
        response = _anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        answer = "\n".join(
            block.text for block in response.content if hasattr(block, "text")
        ).strip() or "No response generated."
        return InsightQueryResponse(answer=answer, date_preset_used=date_preset)

    except anthropic.APIError as e:
        logger.error("Anthropic API error in ai_insights: %s", e)
        raise HTTPException(502, f"AI service error: {str(e)}")
