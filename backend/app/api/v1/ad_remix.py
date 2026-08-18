"""
Ad Remix API Endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from typing import List
import json
import logging
import re

from app.database import get_db
from app.models import WinningAd, Brand, Product, CustomerProfile
from app.schemas.ad_blueprint import (
    AdBlueprint,
    AdBlueprintResponse,
    AdConcept,
    BrandData,
    DeconstructRequest,
    ReconstructRequest,
    ReconstructFromUrlRequest,
)
from app.services.ad_remix_service import deconstruct_template, reconstruct_ad

router = APIRouter()
logger = logging.getLogger(__name__)

_SIMILARITY_NGRAM_SIZE = 6
_SIMILARITY_RETRY_INSTRUCTION = """

SIMILARITY GUARD RETRY:
Your previous output was too similar to the third-party reference material.
Rewrite the headline, body copy, and CTA with completely different wording, sentence structure, and framing.
Keep the same strategic pattern, audience, offer, and CTA logic, but do not reuse any 6-word phrase or close wording from the reference.
"""
_SIMILARITY_WARNING = "Reference similarity warning: review copy before launch."


def _format_research_context(research_inspiration: dict | None) -> str:
    """Format competitor context for the prompt without telling the model to copy it."""
    if not research_inspiration:
        return ""

    advertiser = research_inspiration.get("advertiser") or "Unknown competitor"
    angle = research_inspiration.get("angle") or ""
    headline = research_inspiration.get("headline") or ""
    body = research_inspiration.get("body") or ""
    cta = research_inspiration.get("cta") or ""

    lines = [
        "",
        "COMPETITOR AD CONTEXT FROM RESEARCH:",
        f"- Advertiser: {advertiser}",
    ]
    if angle:
        lines.append(f"- Angle tag: {angle}")
    if headline:
        lines.append(f"- Competitor headline to study, not copy: {headline}")
    if body:
        lines.append(f"- Competitor body to study, not copy: {body[:700]}")
    if cta:
        lines.append(f"- Competitor CTA: {cta}")
    lines.append("- Instruction: create original copy for the selected brand using the same strategic angle, not the same words.")
    return "\n".join(lines)


def _truncate_for_prompt(text: str, limit: int = 1200) -> str:
    """Truncate on a word boundary and mark it explicitly, never mid-token.

    Slicing raw JSON at a fixed character offset can leave a dangling,
    unterminated quoted string right before the model starts generating —
    which reads exactly like a completion prompt an LLM has a documented
    tendency to "finish." That's the one failure mode this whole function
    exists to prevent, so truncation must never produce something that could
    be mistaken for intact, literal source text to continue.
    """
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    if cut <= 0:
        cut = limit
    return text[:cut] + " …[TRUNCATED — analysis only, not literal source text]"


def _format_reference_copy_context(reference_copy_context: dict | None) -> str:
    """Format saved copy intelligence as pattern guidance, not source copy."""
    if not reference_copy_context:
        return ""

    copy_analysis = reference_copy_context.get("copy_analysis")
    copy_patterns = reference_copy_context.get("copy_patterns")
    if not copy_analysis and not copy_patterns:
        return ""

    lines = [
        "",
        "THIRD-PARTY REFERENCE MATERIAL — ANALYSIS ONLY, NEVER QUOTE OR PARAPHRASE VERBATIM:",
        "- The text below is an AI analysis OF a third-party ad (often a competitor's), not your own copy.",
        "- Use it only as strategic pattern guidance: structure, tone, hook logic, objection handling, CTA logic, formatting.",
        "- Do NOT reproduce any phrase, sentence, claim, or brand-specific wording from it — not even a fragment.",
        "- If you find yourself about to write something that could have come from the reference, stop and rewrite it in different words. Never lift wording from below and present it as your output.",
        "- Write fully original copy for the selected brand, product, audience, and offer.",
    ]
    if copy_analysis:
        formatted = copy_analysis if isinstance(copy_analysis, str) else json.dumps(copy_analysis, ensure_ascii=False)
        lines.append(f"- Reference analysis (do not copy): {_truncate_for_prompt(formatted)}")
    if copy_patterns:
        formatted = copy_patterns if isinstance(copy_patterns, str) else json.dumps(copy_patterns, ensure_ascii=False)
        lines.append(f"- Reference patterns (do not copy): {_truncate_for_prompt(formatted)}")
    lines.append(
        "- Reminder: everything above this line is third-party reference material for pattern study only. "
        "Do not quote, paraphrase closely, or reuse any of its exact wording in your output."
    )
    return "\n".join(lines)


def _build_prompt_context(
    research_inspiration: dict | None = None,
    reference_copy_context: dict | None = None,
) -> str:
    """Combine optional context blocks while preserving an empty no-context path."""
    return "".join([
        _format_research_context(research_inspiration),
        _format_reference_copy_context(reference_copy_context),
    ])


def _normalize_similarity_words(text: str) -> list[str]:
    """Normalize copy to words for phrase-overlap checks."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _format_similarity_source(source_type: str, source_name: str = "") -> str:
    """Create a short source label for warnings and debug logs."""
    if source_type == "research":
        return f"research competitor {source_name}".strip()
    if source_type == "winning_ad":
        return f"winning-ad reference {source_name}".strip()
    return "reference material"


def _stringify_reference_value(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _build_similarity_sources(
    research_inspiration: dict | None = None,
    reference_copy_context: dict | None = None,
) -> list[dict]:
    """Build raw, untruncated corpora for similarity checks."""
    sources = []

    if research_inspiration:
        advertiser = research_inspiration.get("advertiser") or "Unknown competitor"
        reference_text = "\n".join([
            research_inspiration.get("headline") or "",
            research_inspiration.get("body") or "",
            research_inspiration.get("cta") or "",
        ]).strip()
        if reference_text:
            sources.append({
                "type": "research",
                "name": advertiser,
                "label": _format_similarity_source("research", advertiser),
                "text": reference_text,
                "cta": research_inspiration.get("cta") or "",
            })

    if reference_copy_context:
        reference_text = "\n".join([
            _stringify_reference_value(reference_copy_context.get("copy_analysis")),
            _stringify_reference_value(reference_copy_context.get("copy_patterns")),
        ]).strip()
        if reference_text:
            name = reference_copy_context.get("name") or reference_copy_context.get("template_name") or ""
            sources.append({
                "type": "winning_ad",
                "name": name,
                "label": _format_similarity_source("winning_ad", name),
                "text": reference_text,
                "cta": reference_copy_context.get("cta") or "",
            })

    return sources


def _shared_ngram_phrase(generated_text: str, reference_text: str, size: int = _SIMILARITY_NGRAM_SIZE) -> str | None:
    """Return a shared phrase when generated copy repeats a long reference phrase."""
    generated_words = _normalize_similarity_words(generated_text)
    reference_words = _normalize_similarity_words(reference_text)
    if len(generated_words) < size or len(reference_words) < size:
        return None

    reference_ngrams = {
        tuple(reference_words[i:i + size])
        for i in range(len(reference_words) - size + 1)
    }
    for i in range(len(generated_words) - size + 1):
        ngram = tuple(generated_words[i:i + size])
        if ngram in reference_ngrams:
            return " ".join(ngram)
    return None


# Deliberately NOT doing a standalone short-CTA similarity check (exact/near-match on
# cta_button alone). Verified live 2026-08-18: this app's own CTA vocabulary is a small,
# fixed set of generic direct-response phrases (see CTA_MAP in api/v1/facebook.py — "Get
# Quote", "Learn More", "Get Started", etc.), which every ad in this vertical draws from
# regardless of what any particular competitor did. A standalone CTA-only check would flag
# the expected common case (two unrelated ads both landing on "Get My Quote") as
# "similarity," which is noise, not signal — CTAs aren't distinctive creative expression the
# way a headline or body hook is. It was also non-functional for the winning-ad/template
# path in practice, since WinningAd records have no CTA field to compare against.
# cta_button still participates in the phrase check below (concatenated into
# generated_text), so a genuinely distinctive multi-word CTA phrase reused verbatim from a
# reference is still caught — just not a bare match on a generic short CTA.
def _find_reference_similarity(ad_concept: AdConcept, similarity_sources: list[dict]) -> dict | None:
    """Check generated headline/body/CTA against raw reference corpora."""
    if not similarity_sources:
        return None

    generated_text = "\n".join([
        ad_concept.headline_remix or "",
        ad_concept.body_copy or "",
        ad_concept.cta_button or "",
    ])
    for source in similarity_sources:
        matched_phrase = _shared_ngram_phrase(generated_text, source["text"])
        if matched_phrase:
            return {
                "kind": "phrase",
                "source": source["label"],
                "match": matched_phrase,
            }
    return None


def _build_similarity_warning(match: dict) -> str:
    return (
        f"{_SIMILARITY_WARNING} Similar to {match['source']}. "
        f"Matched text: \"{match['match']}\". "
        "Regenerate or manually edit the flagged wording before launching this ad."
    )


async def _reconstruct_with_similarity_guard(
    blueprint: AdBlueprint,
    brand_data: BrandData,
    similarity_sources: list[dict],
) -> AdConcept:
    """Generate an ad, retry once on reference overlap, then warn without blocking."""
    ad_concept = await reconstruct_ad(blueprint, brand_data)
    if not similarity_sources:
        logger.info("Ad Remix similarity guard: skipped (no reference material)")
        return ad_concept

    match = _find_reference_similarity(ad_concept, similarity_sources)
    if not match:
        logger.info("Ad Remix similarity guard: checked and clean")
        return ad_concept

    logger.info("Ad Remix similarity guard: flagged on first pass (%s), retrying once", match["source"])
    retry_brand_data = brand_data.model_copy(update={
        "competitor_context": (brand_data.competitor_context or "") + _SIMILARITY_RETRY_INSTRUCTION,
    })
    try:
        retry_concept = await reconstruct_ad(blueprint, retry_brand_data)
    except Exception:
        logger.info("Ad Remix similarity guard: retry call failed, returning first result with warning")
        ad_concept.similarity_warning = _build_similarity_warning(match)
        return ad_concept

    retry_match = _find_reference_similarity(retry_concept, similarity_sources)
    if retry_match:
        logger.info("Ad Remix similarity guard: still flagged after retry (%s)", retry_match["source"])
        retry_concept.similarity_warning = _build_similarity_warning(retry_match)
    else:
        logger.info("Ad Remix similarity guard: clean after retry")
    return retry_concept


@router.post("/deconstruct", response_model=AdBlueprint)
async def deconstruct_ad_template(
    request: DeconstructRequest,
    db: Session = Depends(get_db)
):
    """
    Deconstruct a template into a structural blueprint
    
    This analyzes the template image and extracts:
    - Layout framework
    - Narrative arc
    - Text hierarchy
    - Psychological triggers
    - Visual style guide
    """
    # Get the template
    template = db.query(WinningAd).filter(WinningAd.id == request.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Deconstruct the template
    try:
        blueprint = await deconstruct_template(template.image_url)
        
        # Save the blueprint to the template
        template.blueprint_json = blueprint.model_dump()
        template.blueprint_analyzed_at = func.now()
        db.commit()
        
        return blueprint
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deconstruction failed: {str(e)}")


@router.post("/reconstruct", response_model=AdConcept, response_model_exclude_none=True)
async def reconstruct_ad_from_blueprint(
    request: ReconstructRequest,
    db: Session = Depends(get_db)
):
    """
    Reconstruct an ad by applying brand data to a blueprint
    
    This takes a template's blueprint and generates a new ad concept
    with your brand/product information while maintaining the proven structure.
    """
    # Get the template with blueprint
    template = db.query(WinningAd).filter(WinningAd.id == request.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    if not template.blueprint_json:
        raise HTTPException(
            status_code=400,
            detail="Template has not been deconstructed yet. Run /deconstruct first."
        )
    
    # Get brand, product, and profile data
    brand = db.query(Brand).filter(Brand.id == request.brand_id).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    
    product = db.query(Product).filter(Product.id == request.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    profile = db.query(CustomerProfile).filter(CustomerProfile.id == request.profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Customer profile not found")
    
    # Build brand data
    brand_data = BrandData(
        brand_name=brand.name,
        brand_voice=brand.voice,
        product_name=product.name,
        product_description=product.description or "",
        audience_demographics=profile.demographics or "",
        audience_pain_points=profile.pain_points or "",
        audience_goals=profile.goals or "",
        campaign_offer=request.campaign_offer,
        campaign_urgency=request.campaign_urgency,
        campaign_messaging=request.campaign_messaging,
        niche=request.niche or "",
        competitor_context=_build_prompt_context(reference_copy_context=request.reference_copy_context),
    )

    # Reconstruct the blueprint
    blueprint = AdBlueprint(**template.blueprint_json)
    similarity_sources = _build_similarity_sources(reference_copy_context=request.reference_copy_context)
    
    try:
        ad_concept = await _reconstruct_with_similarity_guard(
            blueprint,
            brand_data,
            similarity_sources,
        )
        return ad_concept
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reconstruction failed: {str(e)}")


@router.post("/reconstruct-from-url", response_model=AdConcept, response_model_exclude_none=True)
async def reconstruct_from_url(
    request: ReconstructFromUrlRequest,
    db: Session = Depends(get_db)
):
    """Reconstruct an ad concept directly from a live ad image URL (no saved template needed).

    Used when Joel clicks 'Remix' on a winning creative in the performance page.
    If source_image_url is provided, we deconstruct it on the fly to extract a blueprint,
    then immediately reconstruct with the selected brand/product/profile data.
    If no image URL is available (video ads, expired CDN), we skip deconstruction
    and reconstruct using a generic direct-response blueprint.
    """
    # Get brand, product, profile
    brand = db.query(Brand).filter(Brand.id == request.brand_id).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    product = db.query(Product).filter(Product.id == request.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    profile = db.query(CustomerProfile).filter(CustomerProfile.id == request.profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Customer profile not found")

    brand_data = BrandData(
        brand_name=brand.name,
        brand_voice=brand.voice,
        product_name=product.name,
        product_description=product.description or "",
        audience_demographics=profile.demographics or "",
        audience_pain_points=profile.pain_points or "",
        audience_goals=profile.goals or "",
        campaign_offer=request.campaign_offer,
        campaign_urgency=request.campaign_urgency,
        campaign_messaging=request.campaign_messaging,
        niche=request.niche or "",
        competitor_context=_build_prompt_context(request.research_inspiration, request.reference_copy_context),
    )

    # Generic lead-gen blueprint used as fallback when no image is available
    # or when the Meta CDN URL has expired (typically within minutes to hours).
    _generic_blueprint = AdBlueprint(
        layout_framework="Single hero image with bold headline overlay and CTA button at bottom",
        narrative_arc="Problem → Relief → CTA",
        text_hierarchy="Large bold headline at top, 2-3 benefit bullets in middle, CTA button at bottom",
        psychological_triggers=["Pain relief", "Social proof", "Speed/simplicity", "No obligation"],
        visual_style_guide="Clean, professional, trust-building — confident direct response style",
    )

    try:
        if request.source_image_url:
            try:
                # Deconstruct the live image to extract its structural blueprint.
                # Meta CDN URLs expire — if the fetch fails, fall back gracefully.
                blueprint = await deconstruct_template(request.source_image_url)
            except Exception:
                blueprint = _generic_blueprint
        else:
            # No image available (video ad or no creative URL stored).
            blueprint = _generic_blueprint

        similarity_sources = _build_similarity_sources(request.research_inspiration, request.reference_copy_context)
        ad_concept = await _reconstruct_with_similarity_guard(
            blueprint,
            brand_data,
            similarity_sources,
        )
        return ad_concept

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Remix failed: {str(e)}")


@router.get("/blueprints/{template_id}", response_model=AdBlueprint)
async def get_template_blueprint(
    template_id: int,
    db: Session = Depends(get_db)
):
    """
    Get the blueprint for a specific template
    """
    template = db.query(WinningAd).filter(WinningAd.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    if not template.blueprint_json:
        raise HTTPException(
            status_code=404,
            detail="Template has not been deconstructed yet"
        )
    
    return AdBlueprint(**template.blueprint_json)


@router.get("/blueprints", response_model=List[dict])
async def list_templates_with_blueprints(
    db: Session = Depends(get_db)
):
    """
    List all templates that have been deconstructed
    """
    templates = db.query(WinningAd).filter(WinningAd.blueprint_json.isnot(None)).all()
    
    return [
        {
            "template_id": t.id,
            "template_name": t.name,
            "blueprint": t.blueprint_json,
            "analyzed_at": t.blueprint_analyzed_at
        }
        for t in templates
    ]
