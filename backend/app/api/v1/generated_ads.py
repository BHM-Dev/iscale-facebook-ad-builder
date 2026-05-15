from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from app.database import get_db
from app.models import GeneratedAd, User
from app.core.deps import get_current_active_user, require_permission
from fastapi.responses import StreamingResponse
import io
import csv
import anthropic as _anthropic_sdk

from pydantic import BaseModel, Field
from typing import Dict, Any

class ImageGenerationRequest(BaseModel):
    template: Optional[Dict[str, Any]] = None
    brand: Optional[Dict[str, Any]] = None
    product: Optional[Dict[str, Any]] = None
    ad_copy: Optional[Dict[str, Any]] = Field(None, alias="copy")
    count: int = 1
    imageSizes: List[Dict[str, Any]] = []
    resolution: str = "1K"
    productShots: List[str] = []
    model: str = "flux-kontext-pro"
    customPrompt: Optional[str] = None
    useProductImage: bool = False  # Use uploaded product image as base
    niche: Optional[str] = None   # e.g. "Religious organizations", "Flower shops" — passed to AI prompt builder
    # imageMode controls how a reference image (productShots[0]) is used:
    #   "iterate"   — Ad Remix path: preserve exact scene, change only lighting/mood (Flux image-to-image)
    #   "style_ref" — Batch Generate path: use reference for visual style only, Sonnet generates fresh scene
    imageMode: str = "iterate"
    # Text overlay fields — baked into image after kie.ai generation
    overlay_enabled: bool = False
    overlay_niche_line: Optional[str] = None   # e.g. "Winery Business Insurance" — rendered above headline
    overlay_offer_line: Optional[str] = None   # e.g. "From $24.95/Month"
    overlay_cta: Optional[str] = None          # Button text — uses ad_copy.cta if not set
    overlay_logo_url: Optional[str] = None     # Brand logo URL for top-right badge

def build_comprehensive_prompt(request: ImageGenerationRequest) -> str:
    """
    Build comprehensive prompt using old system's approach:
    - Product name + description
    - Brand name, voice, and primary color
    - Copy context (headline)
    - Template metadata (mood, lighting, composition, design_style)
    """

    # Custom prompt override
    if request.customPrompt:
        return request.customPrompt

    # Extract all context
    product_name = request.product.get('name', 'Product') if request.product else 'Product'
    product_desc = request.product.get('description', '') if request.product else ''
    brand_name = request.brand.get('name', '') if request.brand else ''
    brand_voice = request.brand.get('voice', 'Professional') if request.brand else 'Professional'
    brand_color = request.brand.get('colors', {}).get('primary', '') if request.brand else ''

    # Get template metadata
    template_type = request.template.get('type') if request.template else None

    if template_type == 'style':
        # Style archetype - has metadata fields
        mood = request.template.get('mood', 'Engaging')
        lighting = request.template.get('lighting', 'Professional lighting')
        composition = request.template.get('composition', 'Balanced')
        design_style = request.template.get('design_style', 'Modern')
    else:
        # Regular template - get from template data if available
        mood = request.template.get('mood', 'Engaging') if request.template else 'Engaging'
        lighting = request.template.get('lighting', 'Professional lighting') if request.template else 'Professional lighting'
        composition = request.template.get('composition', 'Balanced') if request.template else 'Balanced'
        design_style = request.template.get('design_style', 'Modern') if request.template else 'Modern'

    # Build comprehensive prompt (OLD SYSTEM STYLE)
    parts = [
        f"Product Photography of {product_name}",
        f"- {product_desc}" if product_desc else "",
        f"{brand_name} style: {brand_voice}" if brand_name else f"Style: {brand_voice}",
        f"Primary Color: {brand_color}" if brand_color else "",
    ]

    # NOTE: headline intentionally excluded — it causes kie.ai to render text visually.
    # The image should be a pure visual scene with no text baked in.

    # Add template art direction
    parts.append(f"Art Direction: {mood}, {lighting}, {composition}, {design_style}")

    # Quality standards
    parts.append("High quality, photorealistic, 4k, advertising standard")

    # Join non-empty parts
    prompt = ". ".join([p for p in parts if p])

    return prompt


class GeneratedAdCreate(BaseModel):
    id: str
    brandId: Optional[str] = None
    productId: Optional[str] = None
    templateId: Optional[str] = None
    imageUrl: Optional[str] = None  # Now optional for video ads
    headline: Optional[str] = None
    body: Optional[str] = None
    cta: Optional[str] = None
    sizeName: Optional[str] = None
    dimensions: Optional[str] = None
    prompt: Optional[str] = None
    adBundleId: Optional[str] = None
    # Video support fields
    mediaType: Optional[str] = 'image'  # 'image' or 'video'
    videoUrl: Optional[str] = None
    videoId: Optional[str] = None  # Facebook video ID
    thumbnailUrl: Optional[str] = None
    # Text overlay fields — saved so Iterate/Remix can reconstruct overlay settings
    niche: Optional[str] = None
    overlayEnabled: Optional[bool] = False
    overlayNicheLine: Optional[str] = None
    overlayOfferLine: Optional[str] = None
    overlayCta: Optional[str] = None
    overlayLogoUrl: Optional[str] = None

class BatchSaveRequest(BaseModel):
    ads: List[GeneratedAdCreate]

router = APIRouter()

import os
import asyncio
import uuid
import httpx
import json as _json
from pathlib import Path
from app.core.config import settings

# ---------------------------------------------------------------------------
# Anthropic client for AI-enhanced image prompt generation
# Uses AsyncAnthropic so the call fits naturally in async endpoints.
# Falls back gracefully if ANTHROPIC_API_KEY is not set.
# Uses Haiku — this is a fast, inexpensive transformation call (~$0.001 each).
# ---------------------------------------------------------------------------
_ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
_async_anthropic = _anthropic_sdk.AsyncAnthropic(api_key=_ANTHROPIC_KEY) if _ANTHROPIC_KEY else None
# Sonnet used for image prompt generation — Haiku was producing literal/costume imagery
# (e.g. biblical figures for "Religious Organizations" niche). Sonnet follows the
# contemporary-business-owner framing reliably. ~$0.003/call, acceptable for this task.
_PROMPT_MODEL = "claude-sonnet-4-5-20250929"

# NOTE: negativePrompt is NOT supported by flux-kontext-pro (confirmed via docs.kie.ai).
# It is a Stable Diffusion convention that Flux silently ignores. All content guidance
# must be expressed in the positive prompt. The _NEGATIVE_PROMPT block has been removed.

# Vertical hints used only in build_comprehensive_prompt() fallback (no Anthropic key).
# The Sonnet-based _build_ai_image_prompt() uses the niche field directly.
_VERTICAL_HINTS: Dict[str, str] = {
    "auto insurance":    "A car on an open road, golden light, clean landscape.",
    "commercial insurance": "A small business storefront or commercial building exterior, clean daylight.",
    "home insurance":    "A well-kept house exterior, warm afternoon light.",
    "personal loans":    "A young adult in a modern apartment or coffee shop, relaxed and focused.",
    "debt relief":       "A person stepping outside into sunlight, open space, sense of relief.",
    "reverse mortgage":  "An older adult enjoying outdoor time — gardening, walking, relaxing.",
    "mortgage":          "A house with a sold sign, warm afternoon light.",
    "health insurance":  "An active person outdoors in natural light.",
}

def _get_vertical_hint(product_name: str, product_desc: str) -> str:
    """Match product name/description to a vertical hint. Returns empty string if no match."""
    combined = f"{product_name} {product_desc}".lower()
    for keyword, hint in _VERTICAL_HINTS.items():
        if keyword in combined:
            return hint
    return ""


# Hardcoded Flux prompt lists for niches that fail with LLM-generated prompts.
# Each niche has multiple scene options — one is picked randomly per generation
# so Joel sees variety across runs. All scenes are written as specific Flux-ready
# descriptions with no ambiguous language that Flux could misinterpret.
# Rules per scene: contemporary only, specific setting, controlled people/no-people.
_NICHE_OVERRIDES: Dict[str, list] = {
    "religious": [
        # Exterior
        "Wide-angle exterior photograph of a white wooden church with a tall steeple, "
        "green lawn, oak trees, clear blue sky, warm morning sunlight. "
        "No people. No text, no logos. Photorealistic.",
        # Congregation in pews
        "Interior of a bright modern church sanctuary, diverse congregation of 20 people "
        "in contemporary clothing seated in wooden pews, large wooden cross at the front, "
        "sunlight streaming through clear windows, warm community atmosphere. "
        "No text, no logos. Photorealistic.",
        # Small prayer group
        "Four diverse adults in casual modern clothing seated around a round table in a "
        "church meeting room, small wooden cross on the wall behind them, coffee cups on "
        "the table, relaxed and engaged conversation, warm overhead lighting. "
        "No text, no logos. Photorealistic.",
        # Sunday service
        "Wide shot of a modern church interior during Sunday service, congregation in "
        "contemporary dress seated in pews, pastor in business casual at the front, "
        "bright natural light, welcoming community feel. "
        "No text, no logos. Photorealistic.",
    ],
    "church": [
        "Wide-angle exterior of a red brick church with arched windows and white steeple, "
        "tree-lined sidewalk, blue sky, bright daylight. No people. No text, no logos. Photorealistic.",
        "Diverse group of adults in modern casual clothing gathered outside a brick church "
        "entrance on a sunny day, smiling and talking, contemporary setting, natural light. "
        "No text, no logos. Photorealistic.",
        "Interior of a contemporary church hall, rows of chairs facing a simple wooden cross, "
        "warm lighting, clean modern space, empty before service. No text, no logos. Photorealistic.",
    ],
    "mosque": [
        "Exterior photograph of a modern mosque with a white dome and minaret, "
        "green courtyard, clear sky, warm afternoon light. No people. No text, no logos. Photorealistic.",
        "Interior of a modern mosque prayer hall, ornate geometric tile floor, high ceilings, "
        "soft natural light through arched windows, peaceful and empty. No text, no logos. Photorealistic.",
    ],
    "synagogue": [
        "Exterior of a stone synagogue, manicured grounds, blue sky, soft daylight. "
        "No people. No text, no logos. Photorealistic.",
        "Interior of a synagogue sanctuary with wooden pews, menorah at the front, "
        "warm lighting, stained glass casting soft color. Empty. No text, no logos. Photorealistic.",
    ],
    "winery": [
        "Rows of lush green grapevines on a hillside vineyard, golden afternoon light, "
        "rolling hills in background, clear sky. No people. No text, no logos. Photorealistic.",
        "Oak wine barrels stacked in a warm stone cellar, soft warm lighting, rustic brick walls. "
        "No people. No text, no logos. Photorealistic.",
        "Close-up of deep red wine being poured into a clean glass, dark background, "
        "warm studio lighting, rich color. No text, no logos. Photorealistic.",
        "Winery tasting room interior, wooden bar, wine bottles on shelves, warm lighting, "
        "rustic elegant decor. Empty. No text, no logos. Photorealistic.",
    ],
    "restaurant": [
        "Interior of a warm restaurant dining room, white tablecloths, pendant lighting, "
        "wood floors, set for service. Empty. No text, no logos. Photorealistic.",
        "Restaurant kitchen, chef in white coat plating food at a stainless steel counter, "
        "clean organized workspace, bright overhead lighting. No text, no logos. Photorealistic.",
        "Upscale restaurant bar area, backlit bottles, polished dark wood counter, "
        "warm amber lighting. Empty. No text, no logos. Photorealistic.",
    ],
    "bar": [
        "Interior of a clean upscale bar, backlit bottles, polished counter, warm lighting. "
        "Empty. No text, no logos. Photorealistic.",
        "Bartender in neat uniform pouring a cocktail behind a polished bar, warm lighting, "
        "bottles on shelves, professional setting. No text, no logos. Photorealistic.",
    ],
    "brewery": [
        "Interior of a craft brewery with large stainless steel fermentation tanks, "
        "warm industrial lighting, brick walls. No people. No text, no logos. Photorealistic.",
        "Brewer in casual work clothes checking gauges on a large fermentation tank, "
        "modern brewery interior, industrial lighting. No text, no logos. Photorealistic.",
    ],
    "daycare": [
        "Bright cheerful daycare classroom interior, colorful low tables and chairs, "
        "natural light through large windows, educational posters on walls. "
        "Empty. No text, no logos. Photorealistic.",
        "Daycare teacher in casual clothes reading a book to three small children seated "
        "in a circle on a colorful rug, bright classroom, warm natural light. "
        "No text, no logos. Photorealistic.",
    ],
    "gym": [
        "Modern gym interior with rows of treadmills and free weights, "
        "bright lighting, clean polished floors. Empty. No text, no logos. Photorealistic.",
        "Person in athletic wear working out on a cable machine in a clean modern gym, "
        "natural light, focused expression, contemporary fitness setting. No text, no logos. Photorealistic.",
    ],
    "trucking": [
        "Semi-truck cab with a professional driver in the seat, modern highway, "
        "open road, clear sky, natural light. No text, no logos. Photorealistic.",
        "Row of clean semi-trucks parked at a modern logistics depot, morning light, "
        "wide shot. No people. No text, no logos. Photorealistic.",
        "Close-up of a truck driver's hands on a large steering wheel, open highway "
        "visible through the windshield, warm natural light. No text, no logos. Photorealistic.",
    ],
    "welding": [
        "Close-up of a welder in full safety gear and dark visor, bright orange arc sparks "
        "flying, dark industrial workshop background. No text, no logos. Photorealistic.",
        "Welder in protective gear and gloves working on a steel beam in a well-lit "
        "industrial shop, sparks and heat visible, professional setting. No text, no logos. Photorealistic.",
    ],
}

def _get_niche_override(niche: str) -> str | None:
    """Return a randomly selected hardcoded Flux prompt for known failing niches."""
    import random
    niche_lower = niche.lower()
    for key, prompts in _NICHE_OVERRIDES.items():
        if key in niche_lower:
            chosen = random.choice(prompts)
            print(f"🏛️  Niche override for '{niche}': picked scene {prompts.index(chosen)+1}/{len(prompts)}")
            return chosen
    return None


# ── Pexels stock photo integration ─────────────────────────────────────────────
# For place/property niches where AI generation reliably fails, we pull curated
# stock photos from Pexels instead of kie.ai. Pexels is free (200 req/hr,
# 20k/month), commercially licensed, no attribution required.
# Multiple queries per niche → random selection → variety across runs.
_PEXELS_QUERIES: Dict[str, list] = {
    "religious":  ["church sunday service congregation", "church interior worship service", "church community gathering"],
    "church":     ["church building exterior steeple", "church congregation pews", "church community"],
    "mosque":     ["mosque exterior architecture", "mosque interior prayer hall"],
    "synagogue":  ["synagogue exterior", "synagogue interior"],
    "winery":     ["vineyard grapevines golden hour", "wine cellar barrels", "wine pouring glass red"],
    "restaurant": ["restaurant dining room interior", "restaurant kitchen chef cooking", "upscale restaurant tables"],
    "bar":        ["bar interior cocktails", "bartender pouring drinks"],
    "brewery":    ["craft brewery fermentation tanks", "brewery interior industrial"],
    "daycare":    ["daycare classroom teacher children", "preschool colorful classroom"],
    "gym":        ["gym fitness equipment workout", "gym interior treadmills weights"],
    "trucking":   ["semi truck highway open road", "truck driver cab steering wheel", "freight trucks depot"],
    "welding":    ["welder sparks metal industrial", "welding arc sparks workshop"],
    "plumbing":   ["plumber pipe work professional", "plumbing pipes tools"],
    "roofing":    ["roofer roof residential work", "roofing contractor shingles"],
    "landscaping":["landscaping crew lawn garden", "landscape gardening professional"],
    "auto repair":["auto mechanic car repair shop", "mechanic working on engine"],
    "dental":     ["dental office exam room", "dentist clinic modern"],
    "medical":    ["medical clinic exam room", "doctor office professional"],
}

def _get_pexels_query(niche: str) -> str | None:
    """Return a randomly selected Pexels search query for the given niche."""
    import random
    niche_lower = niche.lower()
    for key, queries in _PEXELS_QUERIES.items():
        if key in niche_lower:
            return random.choice(queries)
    return None


async def _pexels_fetch_image(query: str, aspect_ratio: str = "1:1") -> str | None:
    """
    Search Pexels for a stock photo matching the query and return a usable image URL.
    Returns None on any failure so caller can fall back to kie.ai.

    orientation mapping:
      9:16, 3:4  → portrait
      16:9, 4:3  → landscape
      1:1        → square (Pexels doesn't have square, use landscape and crop is fine)
    """
    api_key = settings.PEXELS_API_KEY
    if not api_key:
        print("PEXELS_API_KEY not configured — skipping Pexels")
        return None

    import random
    orientation = "portrait" if aspect_ratio in ("9:16", "3:4") else "landscape"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": api_key},
                params={
                    "query": query,
                    "per_page": 15,
                    "orientation": orientation,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        photos = data.get("photos", [])
        if not photos:
            print(f"Pexels returned 0 results for '{query}'")
            return None

        photo = random.choice(photos)
        # Use large2x (1880px wide) for quality; fall back to large (940px)
        url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
        print(f"📸 Pexels photo selected: id={photo.get('id')} url={url[:60] if url else 'None'}")
        return url

    except Exception as e:
        print(f"Pexels fetch failed ({e}) — falling back to kie.ai")
        return None


async def _build_ai_image_prompt(
    request: "ImageGenerationRequest",
    aspect_ratio: str = "1:1",
    has_input_image: bool = False,
) -> str:
    """
    Build a Flux prompt based on mode:

    has_input_image=False (text-to-image):
      - Pexels handles place/property niches; this path handles trades/professionals.
      - Niche overrides return hardcoded scene descriptions for known-failing niches.
      - Sonnet generates a fresh scene for everything else.

    has_input_image=True, imageMode="iterate" (Ad Remix):
      - Preservation-first prompt: keep exact scene, adjust lighting/mood only.
      - Skips niche overrides — the reference image IS the scene.

    has_input_image=True, imageMode="style_ref" (Batch Generate):
      - Reference image provides visual style influence to kie.ai via inputImage.
      - Sonnet generates a fresh scene prompt (same as text-to-image path).
      - Niche overrides still apply.
    """
    if not _async_anthropic:
        return build_comprehensive_prompt(request)

    try:
        product_name = request.product.get("name", "") if request.product else ""
        mood = request.template.get("mood", "engaging") if request.template else "engaging"
        lighting = request.template.get("lighting", "natural") if request.template else "natural"
        niche = (request.niche or "").strip()
        image_mode = (request.imageMode or "iterate").strip()

        is_portrait = aspect_ratio in ("9:16", "3:4")
        composition_note = (
            "vertical full-frame composition, subject fills frame top to bottom"
            if is_portrait else
            "full-bleed horizontal composition, subject fills the entire frame"
        )

        # ── iterate mode: preservation-first prompt ───────────────────────────────
        # Reference image is a winning ad. Keep scene intact, shift only mood/light.
        if has_input_image and image_mode == "iterate":
            niche_context = f" The ad is for {niche}." if niche else ""
            prompt = (
                f"Keep the exact same scene, composition, subject, and background."
                f"{niche_context}"
                f" Adjust the lighting to feel {lighting} and the mood to feel {mood}."
                f" {composition_note}."
                f" No written text, no typography, no logos in the image."
            )
            print(f"🔄 Iterate prompt ({aspect_ratio}): {prompt}")
            return prompt

        # ── style_ref or text-to-image: generate fresh scene ─────────────────────
        # Niche overrides bypass Sonnet for known Flux failure niches.
        # Skip overrides in style_ref only if you want fresh generation regardless —
        # currently we apply them to ensure quality for place/property niches.
        override = _get_niche_override(niche or product_name)
        if override:
            print(f"🏛️  Niche override for '{niche or product_name}': skipping Sonnet")
            return f"{override} {composition_note}"

        # Sonnet generates scene for trades, professionals, and everything else
        system_prompt = """You write short Flux image generation prompts for Facebook ads.

Rules:
- Buildings / places (hotel, gym, office, warehouse, marina, etc.): show the exterior or interior. No people.
- Trades (welding, plumbing, roofing, HVAC, construction, etc.): show the worker doing the job. Tools, action, craft.
- Professionals (lawyer, doctor, accountant, etc.): one person at a desk or in their workspace.
- Vehicles / transport: the vehicle itself or a driver in context.
- No illustrations. No stock-photo couples. No gray backdrops. Photorealistic only.
- End every prompt with: No written text, no typography, no logos in the image. Photorealistic.
- Max 45 words. Return ONLY the prompt."""

        user_msg = f"Niche: {niche or product_name}\nLighting: {lighting}\nMood: {mood}\n\nWrite the Flux prompt."

        response = await _async_anthropic.messages.create(
            model=_PROMPT_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": user_msg}],
            system=system_prompt,
        )

        ai_prompt = response.content[0].text.strip()
        print(f"🤖 AI scene prompt ({aspect_ratio}, mode={image_mode}): {ai_prompt}")
        return ai_prompt

    except Exception as e:
        print(f"AI prompt generation failed, falling back to static prompt: {e}")
        return build_comprehensive_prompt(request)

# ── kie.ai Flux Kontext API ─────────────────────────────────────────────────────
# Verified working from /test-kie endpoint (2026-05-14): both text-to-image and
# image-to-image return code 200 + taskId using the /flux/kontext/ endpoints.
# POST /api/v1/flux/kontext/generate          → { code: 200, data: { taskId } }
# GET  /api/v1/flux/kontext/record-info?taskId= → { code, data: { successFlag, response: { resultImageUrl } } }
# successFlag: 0=generating, 1=success, 2=create_failed, 3=generate_failed
# inputImage is OPTIONAL — omit for text-to-image, include URL for image-to-image
KIE_AI_BASE_URL = "https://api.kie.ai/api/v1/flux/kontext"


@router.get("/test-kie")
async def test_kie_connection():
    """Diagnostic: verifies kie.ai Flux Kontext API is reachable and accepts payloads.
    No auth required. Hits POST /generate only (no polling) so it returns fast.

    Test 1: text-to-image (no inputImage) — should return code 200 + taskId
    Test 2: image-to-image (R2 URL inputImage) — should return code 200 + taskId
    """
    api_key = settings.KIE_AI_API_KEY
    if not api_key:
        return {"error": "KIE_AI_API_KEY not configured on this server"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Upload a small placeholder for the image-to-image test
    placeholder_url = None
    placeholder_error = None
    try:
        from PIL import Image as _tPIL
        import io as _tio
        _tph = _tPIL.new("RGB", (512, 512), color=(255, 255, 255))
        _tbuf = _tio.BytesIO()
        _tph.save(_tbuf, format="JPEG")
        _tph_bytes = _tbuf.getvalue()
        _tph_name = f"test_placeholder_{str(uuid.uuid4())}.jpg"
        if settings.r2_enabled:
            from app.api.v1.uploads import upload_to_r2
            placeholder_url = await upload_to_r2(_tph_bytes, _tph_name, "image/jpeg")
        else:
            _tph_path = UPLOAD_DIR / _tph_name
            with open(_tph_path, "wb") as _tph_fh:
                _tph_fh.write(_tph_bytes)
            placeholder_url = f"{settings.PUBLIC_API_URL}/uploads/{_tph_name}"
    except Exception as _tph_err:
        placeholder_error = str(_tph_err)

    _prompt = "A confident small business owner standing in front of their shop, natural lighting"
    tests = [
        ("1. text-to-image (no inputImage)", {
            "model": "flux-kontext-pro",
            "prompt": _prompt,
            "aspectRatio": "1:1",
            "outputFormat": "png",
        }),
    ]
    if placeholder_url:
        tests.append(("2. image-to-image (R2 inputImage URL)", {
            "model": "flux-kontext-pro",
            "prompt": _prompt,
            "aspectRatio": "1:1",
            "outputFormat": "png",
            "inputImage": placeholder_url,
        }))
    else:
        tests.append((f"2. SKIPPED — placeholder upload failed: {placeholder_error}", None))

    results = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for label, payload in tests:
            if payload is None:
                results.append({"label": label, "skipped": True})
                continue
            try:
                r = await client.post(f"{KIE_AI_BASE_URL}/generate", headers=headers, json=payload)
                results.append({"label": label, "http": r.status_code, "body": r.json()})
            except Exception as exc:
                results.append({"label": label, "error": str(exc)})
    return {
        "key_prefix": api_key[:8] + "...",
        "placeholder_url": placeholder_url,
        "results": results,
        "interpretation": {
            "both_tests_should_be": "code 200 with data.taskId — confirms endpoint and schema are correct",
            "endpoint_used": f"{KIE_AI_BASE_URL}/jobs/createTask",
        }
    }


# Setup uploads directory (same as main.py StaticFiles mount)
UPLOAD_DIR = settings.upload_dir
os.makedirs(UPLOAD_DIR, mode=0o755, exist_ok=True)

async def download_and_save_image(image_url: str, prefix: str = "generated") -> str:
    """
    Download image from external URL; upload to R2 if configured, else save locally.
    Returns the public URL (R2 or relative /uploads/...) for use in production and dev.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url, timeout=30.0)
            response.raise_for_status()

            unique_id = str(uuid.uuid4())
            filename = f"{prefix}_{unique_id}.png"
            content = response.content

            if settings.r2_enabled:
                from app.api.v1.uploads import upload_to_r2
                return await upload_to_r2(content, filename, "image/png")
            else:
                file_path = UPLOAD_DIR / filename
                with open(file_path, "wb") as f:
                    f.write(content)
                return f"/uploads/{filename}"
    except Exception as e:
        print(f"Error downloading image: {e}")
        return image_url

async def _kie_generate_image(prompt: str, width: int, height: int,
                              input_image_url: str = None) -> str:
    """
    Submit a generation task to kie.ai and poll until complete.

    Verified working contract from kie.ai logs (2026-05-13):
      Model:    flux-2/pro-text-to-image
      Endpoint: POST /api/v1/jobs/createTask
      Schema:   flat snake_case (aspect_ratio, output_format — NOT camelCase)
      Poll:     GET  /api/v1/jobs/recordInfo?taskId=
      State:    data.state (string: "success" / "fail" / "failed" / "error")
      Image:    data.resultJson (JSON string) → resultUrls[0]
    """
    api_key = settings.KIE_AI_API_KEY
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Map pixel dimensions to kie.ai aspect ratio strings
    ratio = width / height
    if ratio >= 1.7:
        aspect_ratio = "16:9"
    elif ratio >= 1.2:
        aspect_ratio = "4:3"
    elif ratio >= 0.9:
        aspect_ratio = "1:1"
    elif ratio >= 0.7:
        aspect_ratio = "3:4"
    else:
        aspect_ratio = "9:16"

    # camelCase schema — verified working via /test-kie (2026-05-14)
    # promptUpsampling: True adds detail for text-to-image; False for image editing
    # (can cause unwanted drift when modifying a reference image).
    # negativePrompt is NOT supported by flux-kontext-pro — confirmed via docs.kie.ai.
    payload: Dict[str, Any] = {
        "model": "flux-kontext-pro",
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "outputFormat": "png",
        "promptUpsampling": not bool(input_image_url),  # True=text-to-image, False=editing
    }
    # inputImage is optional — include only when a valid re-hosted reference URL exists
    if input_image_url:
        payload["inputImage"] = input_image_url

    async with httpx.AsyncClient(timeout=200.0) as client:
        print(f"kie.ai generate payload: {payload}")
        create_resp = await client.post(
            f"{KIE_AI_BASE_URL}/generate",
            headers=headers,
            json=payload
        )
        task_data = create_resp.json()
        print(f"kie.ai generate HTTP {create_resp.status_code}: {task_data}")
        create_resp.raise_for_status()

        if not task_data.get("data") or not task_data["data"].get("taskId"):
            kie_msg = task_data.get("msg") or task_data.get("message") or str(task_data)
            raise ValueError(f"kie.ai error: {kie_msg}")

        task_id = task_data["data"]["taskId"]
        print(f"kie.ai task created: {task_id}")

        # Poll every 5s, max 36 attempts = 3 minutes
        # successFlag: 0=generating, 1=success, 2=create_failed, 3=generate_failed
        for attempt in range(36):
            await asyncio.sleep(5)
            status_resp = await client.get(
                f"{KIE_AI_BASE_URL}/record-info",
                headers=headers,
                params={"taskId": task_id}
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()
            data = status_data.get("data", {})
            flag = data.get("successFlag")
            print(f"kie.ai task {task_id} successFlag={flag!r} (attempt {attempt + 1}/36)")

            if flag == 1:  # success
                image_url = (data.get("response") or {}).get("resultImageUrl")
                if not image_url:
                    raise ValueError("kie.ai returned success but no resultImageUrl")
                return image_url
            elif flag in (2, 3):  # create_failed or generate_failed
                kie_msg = (
                    data.get("errorMessage") or data.get("msg")
                    or status_data.get("msg")
                    or f"successFlag={flag}"
                )
                raise ValueError(f"kie.ai task failed: {kie_msg}")
            # flag == 0: still generating — keep polling

    raise TimeoutError(
        f"kie.ai task {task_id} did not complete after 3 minutes. "
        "Check your kie.ai credit balance and try again."
    )


@router.post("/generate-image")
async def generate_image(
    request: ImageGenerationRequest,
    current_user: User = Depends(require_permission("ads:write"))
):
    """Generate ad images using kie.ai (with placeholder fallback)"""

    images = []
    use_kie = bool(settings.KIE_AI_API_KEY)

    if use_kie:
        print(f"Generating images with kie.ai...")
    else:
        print("KIE_AI_API_KEY not set — using placeholder images")

    def _get_aspect_ratio(w: int, h: int) -> str:
        ratio = w / h
        if ratio >= 1.7:   return "16:9"
        elif ratio >= 1.2: return "4:3"
        elif ratio >= 0.9: return "1:1"
        elif ratio >= 0.7: return "3:4"
        else:              return "9:16"

    # ── Resolve reference image ONCE before the generation loops ─────────────────
    # Must happen before prompt building so _build_ai_image_prompt knows whether
    # a reference image is present (affects prompt mode: iterate vs. fresh scene).
    # Re-hosting is done once regardless of how many sizes are generated.
    raw_input_image = (request.productShots[0] or None) if request.useProductImage and request.productShots else None
    input_image: Optional[str] = None
    rehost_failed = False  # track failure so we can fall back to standard prompt

    if raw_input_image and use_kie:
        try:
            async with httpx.AsyncClient(timeout=20.0) as _ref_client:
                _ref_resp = await _ref_client.get(raw_input_image)
                _ref_resp.raise_for_status()
                _ref_bytes = _ref_resp.content

            from PIL import Image as _PIL_Image
            import io as _io
            _ref_img = _PIL_Image.open(_io.BytesIO(_ref_bytes))
            _rw, _rh = _ref_img.size
            print(f"Reference image dimensions: {_rw}×{_rh}")

            if _rw < 200 or _rh < 200:
                print(f"WARNING: reference image too small ({_rw}×{_rh}) — skipping inputImage")
                rehost_failed = True
            else:
                _ref_id   = str(uuid.uuid4())
                _ref_name = f"ref_{_ref_id}.png"
                if settings.r2_enabled:
                    from app.api.v1.uploads import upload_to_r2
                    input_image = await upload_to_r2(_ref_bytes, _ref_name, "image/png")
                else:
                    _ref_path = UPLOAD_DIR / _ref_name
                    with open(_ref_path, "wb") as _rfh:
                        _rfh.write(_ref_bytes)
                    input_image = f"{settings.PUBLIC_API_URL}/uploads/{_ref_name}"
                print(f"Reference image re-hosted at {_rw}×{_rh}: {input_image}")
        except Exception as _ref_err:
            print(f"WARNING: could not re-host reference image ({_ref_err}) — proceeding text-to-image")
            rehost_failed = True

    # If re-hosting failed and we're in iterate mode, fall back to fresh-scene mode
    # so the preservation prompt doesn't run without a reference image.
    effective_image_mode = request.imageMode or "iterate"
    if rehost_failed and effective_image_mode == "iterate":
        print("⚠️  Reference image unavailable — switching from iterate to style_ref mode")
        effective_image_mode = "style_ref"
    # Propagate the resolved mode back onto the request so _build_ai_image_prompt
    # reads the correct value (it reads request.imageMode directly).
    request.imageMode = effective_image_mode

    # Build prompts per aspect-ratio bucket — one Sonnet call per unique AR.
    # Custom prompt bypasses AI entirely.
    _prompt_cache: Dict[str, str] = {}

    async def _get_prompt_for_size(w: int, h: int) -> str:
        if request.customPrompt:
            return request.customPrompt
        ar = _get_aspect_ratio(w, h)
        if ar not in _prompt_cache:
            _prompt_cache[ar] = await _build_ai_image_prompt(
                request,
                aspect_ratio=ar,
                has_input_image=bool(input_image),
            )
        return _prompt_cache[ar]

    _niche_label = (request.niche or "").strip()

    for i in range(request.count):
        for size in request.imageSizes:
            width = size.get('width', 1080)
            height = size.get('height', 1080)
            size_name = size.get('name', 'Square')

            prompt = await _get_prompt_for_size(width, height)

            print(f"\n{'='*80}")
            print(f"IMAGE GENERATION REQUEST")
            print(f"{'='*80}")
            print(f"📦 Brand: {request.brand.get('name') if request.brand else 'None'}")
            print(f"📦 Product: {request.product.get('name') if request.product else 'None'}")
            print(f"📦 Mode: {effective_image_mode} | has_input_image: {bool(input_image)}")
            print(f"📦 Copy Headline: {request.ad_copy.get('headline') if request.ad_copy else 'None'}")
            print(f"\n📝 FULL GENERATED PROMPT:")
            print(f"{prompt}")
            print(f"{'='*80}\n")
            if use_kie:
                try:
                    # ── Pexels: only for text-to-image (no reference image) ───────
                    # When a reference image is present (iterate/style_ref mode),
                    # skip Pexels entirely — kie.ai handles it with inputImage.
                    external_url = None

                    if not input_image:
                        _pexels_query = _get_pexels_query(_niche_label)
                        if _pexels_query:
                            _ar = _get_aspect_ratio(width, height)
                            external_url = await _pexels_fetch_image(_pexels_query, _ar)
                            if external_url:
                                print(f"✅ Pexels image for '{_niche_label}' (query: '{_pexels_query}')")
                            else:
                                print(f"⚠️  Pexels failed for '{_niche_label}' — falling back to kie.ai")

                    if not external_url:
                        external_url = await _kie_generate_image(prompt, width, height, input_image)

                    print(f"Downloading image from kie.ai: {external_url[:50]}...")

                    # Download image bytes so we can optionally apply text overlay before saving
                    async with httpx.AsyncClient() as _dl_client:
                        _dl_resp = await _dl_client.get(external_url, timeout=30.0)
                        _dl_resp.raise_for_status()
                        image_bytes = _dl_resp.content

                    # Apply Pillow text overlay if requested.
                    # Isolated in its own try/except so a font/render error never
                    # discards a perfectly good kie.ai image — falls back to un-overlaid.
                    if request.overlay_enabled:
                        from app.services.text_overlay_service import apply_text_overlay
                        _headline  = request.ad_copy.get('headline', '') if request.ad_copy else ''
                        _cta_text  = request.overlay_cta or (request.ad_copy.get('cta', 'LEARN MORE') if request.ad_copy else 'LEARN MORE')
                        print(f"Applying text overlay — headline={_headline!r}, offer={request.overlay_offer_line!r}, cta={_cta_text!r}")
                        try:
                            image_bytes = apply_text_overlay(
                                image_bytes=image_bytes,
                                headline=_headline,
                                offer_line=request.overlay_offer_line or '',
                                cta_text=_cta_text,
                                logo_url=request.overlay_logo_url,
                                niche_line=request.overlay_niche_line or '',
                            )
                        except Exception as _overlay_err:
                            # Log and continue — image saves without overlay rather than failing entirely
                            print(f"WARNING: text overlay failed, saving un-overlaid image: {_overlay_err}")

                    # Save bytes to R2 or local uploads
                    _unique_id = str(uuid.uuid4())
                    _filename  = f"generated_{_unique_id}.png"
                    if settings.r2_enabled:
                        from app.api.v1.uploads import upload_to_r2
                        image_url = await upload_to_r2(image_bytes, _filename, "image/png")
                    else:
                        _file_path = UPLOAD_DIR / _filename
                        with open(_file_path, "wb") as _fh:
                            _fh.write(image_bytes)
                        image_url = f"/uploads/{_filename}"

                    print(f"Saved as: {image_url}")

                except Exception as e:
                    err_msg = str(e)
                    print(f"kie.ai generation failed: {err_msg}")
                    raise HTTPException(status_code=500, detail=f"Image generation failed: {err_msg}")
            else:
                product_name = request.product.get('name', 'Product') if request.product else 'Product'
                image_url = f"https://placehold.co/{width}x{height}/png?text={product_name}+{i+1}"

            images.append({
                "url": image_url,
                "size": size_name,
                "dimensions": f"{width}x{height}",
                "prompt": prompt
            })

    return {"images": images}

@router.get("/")
def get_generated_ads(
    brand_id: Optional[str] = None,
    show_failures: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get all generated ads, optionally filtered by brand.
    By default hides placeholder/error images (placehold.co) and ads with no media URL.
    Pass show_failures=true to include them (e.g. for debugging)."""
    query = db.query(GeneratedAd)

    if brand_id:
        query = query.filter(GeneratedAd.brand_id == brand_id)

    if not show_failures:
        # Exclude placeholder/error images saved when kie.ai generation failed
        from sqlalchemy import and_, or_
        query = query.filter(
            and_(
                # Must have some media URL
                or_(
                    GeneratedAd.image_url.isnot(None),
                    GeneratedAd.video_url.isnot(None)
                ),
                # Exclude placehold.co placeholder/error URLs
                ~GeneratedAd.image_url.like('%placehold.co%')
            )
        )

    ads = query.order_by(GeneratedAd.created_at.desc()).all()

    return [{
        "id": ad.id,
        "brand_id": ad.brand_id,
        "product_id": ad.product_id,
        "template_id": ad.template_id,
        "image_url": ad.image_url,
        "headline": ad.headline,
        "body": ad.body,
        "cta": ad.cta,
        "size_name": ad.size_name,
        "dimensions": ad.dimensions,
        "prompt": ad.prompt,
        "ad_bundle_id": ad.ad_bundle_id,
        "created_at": ad.created_at.isoformat() if ad.created_at else None,
        # Video support fields
        "media_type": ad.media_type or 'image',
        "video_url": ad.video_url,
        "video_id": ad.video_id,
        "thumbnail_url": ad.thumbnail_url,
        # Text overlay fields — used by Iterate/Remix to pre-populate overlay settings
        "niche": ad.niche,
        "overlay_enabled": ad.overlay_enabled or False,
        "overlay_niche_line": ad.overlay_niche_line,
        "overlay_offer_line": ad.overlay_offer_line,
        "overlay_cta": ad.overlay_cta,
        "overlay_logo_url": ad.overlay_logo_url,
    } for ad in ads]

@router.delete("/{ad_id}")
def delete_generated_ad(
    ad_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("ads:delete"))
):
    """Delete a generated ad by ID"""
    ad = db.query(GeneratedAd).filter(GeneratedAd.id == ad_id).first()

    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")

    db.delete(ad)
    db.commit()

    return {"message": "Ad deleted successfully"}

@router.post("/export-csv")
def export_ads_csv(
    request: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Export selected ads to CSV"""
    ad_ids = request.get("ids", [])

    if not ad_ids:
        raise HTTPException(status_code=400, detail="No ad IDs provided")

    ads = db.query(GeneratedAd).filter(GeneratedAd.id.in_(ad_ids)).all()

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        "ID", "Brand ID", "Headline", "Body", "CTA",
        "Size", "Dimensions", "Media Type", "Image URL", "Video URL", "Video ID", "Thumbnail URL", "Created At"
    ])

    # Write data
    for ad in ads:
        writer.writerow([
            ad.id,
            ad.brand_id or "",
            ad.headline or "",
            ad.body or "",
            ad.cta or "",
            ad.size_name or "",
            ad.dimensions or "",
            ad.media_type or "image",
            ad.image_url or "",
            ad.video_url or "",
            ad.video_id or "",
            ad.thumbnail_url or "",
            ad.created_at.isoformat() if ad.created_at else ""
        ])

    # Prepare response
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=generated-ads.csv"}
    )

@router.post("/batch")
def batch_save_ads(
    request: BatchSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("ads:write"))
):
    """Batch save generated ads"""

    saved_ads = []
    for ad_data in request.ads:
        # Check if ad already exists
        existing = db.query(GeneratedAd).filter(GeneratedAd.id == ad_data.id).first()
        if existing:
            continue

        new_ad = GeneratedAd(
            id=ad_data.id,
            brand_id=ad_data.brandId,
            product_id=ad_data.productId,
            template_id=ad_data.templateId,
            image_url=ad_data.imageUrl,
            headline=ad_data.headline,
            body=ad_data.body,
            cta=ad_data.cta,
            size_name=ad_data.sizeName,
            dimensions=ad_data.dimensions,
            prompt=ad_data.prompt,
            ad_bundle_id=ad_data.adBundleId,
            # Video support fields
            media_type=ad_data.mediaType or 'image',
            video_url=ad_data.videoUrl,
            video_id=ad_data.videoId,
            thumbnail_url=ad_data.thumbnailUrl,
            # Text overlay fields
            niche=ad_data.niche,
            overlay_enabled=ad_data.overlayEnabled or False,
            overlay_niche_line=ad_data.overlayNicheLine,
            overlay_offer_line=ad_data.overlayOfferLine,
            overlay_cta=ad_data.overlayCta,
            overlay_logo_url=ad_data.overlayLogoUrl,
        )
        db.add(new_ad)
        saved_ads.append(new_ad)

    try:
        db.commit()
        return {"message": f"Saved {len(saved_ads)} ads", "count": len(saved_ads)}
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Invalid brand, product, or template ID. Use IDs from Brands/Products/Templates in this app (UUIDs), not Facebook page or ad IDs. " + str(e)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
