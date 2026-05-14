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

    # Add copy context (headline)
    if request.ad_copy and request.ad_copy.get('headline'):
        parts.append(f"Context: Visual representation of \"{request.ad_copy.get('headline')}\"")
    
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
_PROMPT_MODEL = "claude-haiku-4-5-20251001"

# Negative prompt applied to all flux-2/pro-text-to-image calls.
# Blocks the most common ad creative failure modes across financial/insurance verticals.
_NEGATIVE_PROMPT = (
    "text, words, letters, watermark, logo, brand name, signature, caption, speech bubble, "
    "blurry, out of focus, low quality, distorted, deformed, bad anatomy, extra fingers, "
    "six fingers, multiple hands, ugly, multiple people, crowd, busy cluttered background, "
    "oversaturated, harsh shadows, grainy, noise, low resolution, "
    "illustration, cartoon, 3D render, clipart, stock photo style, "
    "lens flare, heavy vignette, HDR effect, collage, multiple scenes, split image"
)

# Per-vertical emotional direction for the image prompt.
# Haiku performs significantly better with an explicit emotional target and scene vocabulary.
_VERTICAL_HINTS: Dict[str, str] = {
    "auto insurance":        "Place the subject near or in a vehicle. Emotional beat: peace of mind, feeling protected on the road.",
    "commercial insurance":  "Show a small business owner confidently in their environment (shop, office, restaurant). Emotional beat: security, running a tight operation.",
    "home insurance":        "Subject at or around their home, sense of ownership and pride. Emotional beat: protected, settled.",
    "personal loans":        "Young adult achieving something (moving into new place, buying furniture, paying off a bill). Emotional beat: access, momentum, relief.",
    "debt relief":           "Person exhaling, unclenching shoulders, stepping outside into daylight. Emotional beat: relief, breathing room, fresh start — NOT paperwork or stress.",
    "reverse mortgage":      "Active 60s–70s adult doing something enjoyable — gardening, traveling, time with family. Emotional beat: earned freedom, enjoying retirement on their own terms.",
    "mortgage":              "Family or individual in front of a home or receiving keys. Emotional beat: milestone, new beginning.",
    "health insurance":      "Active, healthy-looking person in natural surroundings. Emotional beat: vitality, peace of mind.",
}

def _get_vertical_hint(product_name: str, product_desc: str) -> str:
    """Match product name/description to a vertical hint. Returns empty string if no match."""
    combined = f"{product_name} {product_desc}".lower()
    for keyword, hint in _VERTICAL_HINTS.items():
        if keyword in combined:
            return hint
    return ""


async def _build_ai_image_prompt(
    request: "ImageGenerationRequest",
    aspect_ratio: str = "1:1",
) -> str:
    """
    Use Claude Haiku to convert brand/product/copy context into a
    Flux-optimized visual scene description for Facebook ad creatives.

    aspect_ratio is passed so the model can tailor composition guidance
    (portrait/story vs. square/landscape).

    Falls back to build_comprehensive_prompt() if the API call fails or
    if ANTHROPIC_API_KEY is not configured.
    """
    if not _async_anthropic:
        return build_comprehensive_prompt(request)

    try:
        product_name = request.product.get("name", "") if request.product else ""
        product_desc = request.product.get("description", "") if request.product else ""
        brand_voice = request.brand.get("voice", "professional") if request.brand else "professional"
        brand_color = request.brand.get("colors", {}).get("primary", "") if request.brand else ""
        headline = request.ad_copy.get("headline", "") if request.ad_copy else ""
        body = request.ad_copy.get("body", "") if request.ad_copy else ""
        mood = request.template.get("mood", "engaging") if request.template else "engaging"
        lighting = request.template.get("lighting", "natural") if request.template else "natural"

        niche = request.niche or ""
        vertical_hint = _get_vertical_hint(product_name, product_desc)

        # Composition guidance differs by orientation.
        # Text is composited onto the image via Pillow post-generation, so the
        # image must fill the FULL frame — no empty bands or dead space.
        is_portrait = aspect_ratio in ("9:16", "3:4")
        if is_portrait:
            composition_note = (
                "vertical story format — rich scene content filling the full frame top to bottom, "
                "subject positioned center-to-upper area, visually engaging background throughout"
            )
        else:
            composition_note = (
                "full-bleed scene filling every corner of the frame, subject prominent and engaging, "
                "visually rich background throughout — no empty bands, no plain floor or sky taking up the lower half"
            )

        system_prompt = f"""You are a professional art director who writes image generation prompts for Facebook ad creatives. Your prompts feed directly into Flux, a photorealistic image generation model.

Your job is to translate ad copy and brand context into a vivid, specific visual scene description that Flux can render as a high-quality Facebook ad background image.

Rules:
- Describe a REAL SCENE with a real person in a real moment that emotionally matches the ad copy. Never do product photography for abstract services (insurance, loans, mortgages, debt relief).
- Lead with the subject: "A [specific person description] [doing a specific action] in [specific setting]"
- Include: photographic lens style (e.g. 85mm portrait lens), lighting quality, color mood, depth of field
- Composition: {composition_note}
- End with: "Facebook ad creative format, no text, no logos, no watermarks"
- Max 80 words total
- Never mention the brand name, product name, company name, or any specific text that would appear in the image
- Avoid stock-photo clichés (handshakes, generic smiles at cameras, floating money). Be emotionally specific."""

        user_msg = f"""Create a Flux image generation prompt for this Facebook ad:

Vertical / service: {product_name}{(' — ' + product_desc) if product_desc else ''}
{('Niche / target business type: ' + niche) if niche else ''}
Brand voice: {brand_voice}
Brand color palette: {brand_color if brand_color else 'not specified'}
Ad headline: {headline}
Ad body copy: {body if body else 'not provided'}
Visual mood: {mood}
Lighting direction: {lighting}
{('Vertical guidance: ' + vertical_hint) if vertical_hint else ''}

Return ONLY the image prompt. No explanation, no preamble."""

        response = await _async_anthropic.messages.create(
            model=_PROMPT_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": user_msg}],
            system=system_prompt,
        )

        ai_prompt = response.content[0].text.strip()
        print(f"🤖 AI-enhanced image prompt ({aspect_ratio}): {ai_prompt}")
        return ai_prompt

    except Exception as e:
        print(f"AI prompt generation failed, falling back to static prompt: {e}")
        return build_comprehensive_prompt(request)

KIE_AI_BASE_URL = "https://api.kie.ai/api/v1"


@router.get("/test-kie")
async def test_kie_connection():
    """Diagnostic: calls kie.ai createTask with minimal payloads and returns raw responses.
    No auth required. Hit GET /api/v1/generated-ads/test-kie to debug kie.ai issues."""
    api_key = settings.KIE_AI_API_KEY
    if not api_key:
        return {"error": "KIE_AI_API_KEY not configured on this server"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    tests = [
        ("flux-2/pro-text-to-image flat", {"model": "flux-2/pro-text-to-image", "prompt": "test", "aspectRatio": "1:1", "outputFormat": "png"}),
        ("flux-kontext-pro no image",      {"model": "flux-kontext-pro",          "prompt": "test", "aspectRatio": "1:1", "outputFormat": "png"}),
    ]
    results = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for label, payload in tests:
            try:
                r = await client.post(f"{KIE_AI_BASE_URL}/jobs/createTask", headers=headers, json=payload)
                results.append({"label": label, "http": r.status_code, "body": r.json()})
            except Exception as exc:
                results.append({"label": label, "error": str(exc)})
    return {"key_prefix": api_key[:8] + "...", "results": results}


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
                              input_image_url: str = None,
                              negative_prompt: str = None) -> str:
    """
    Submit an image generation task to kie.ai and poll until complete.
    Uses Flux Kontext for text-to-image and image-to-image.
    Returns the generated image URL.
    """
    api_key = settings.KIE_AI_API_KEY
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Map pixel dimensions to the closest kie.ai aspect ratio
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

    # kie.ai unified both models to the same flat camelCase schema.
    # Old nested { "input": { "prompt": ..., "aspect_ratio": ... } } was deprecated.
    # flux-kontext-pro = image-to-image (requires inputImage)
    # flux-2/pro-text-to-image = pure text-to-image (no inputImage needed)
    # Both now use the same flat top-level field structure.
    if input_image_url:
        payload: Dict[str, Any] = {
            "model": "flux-kontext-pro",
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "outputFormat": "png",
            "inputImage": input_image_url,
        }
    else:
        payload = {
            "model": "flux-2/pro-text-to-image",
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "outputFormat": "png",
        }

    async with httpx.AsyncClient(timeout=200.0) as client:
        # Create the task
        print(f"kie.ai createTask payload: {payload}")
        create_resp = await client.post(
            f"{KIE_AI_BASE_URL}/jobs/createTask",
            headers=headers,
            json=payload
        )
        task_data = create_resp.json()
        print(f"kie.ai createTask HTTP {create_resp.status_code}: {task_data}")
        # Raise on non-2xx AFTER logging so we capture the body
        create_resp.raise_for_status()
        if not task_data.get("data"):
            # Surface kie.ai's own error message when available (e.g. "Insufficient credits")
            kie_msg = task_data.get("msg") or task_data.get("message") or str(task_data)
            raise ValueError(f"kie.ai error: {kie_msg}")
        task_id = task_data["data"]["taskId"]
        print(f"kie.ai task created: {task_id}")

        # Poll until done (max ~3 minutes — story/9:16 can take longer than square)
        # Use 5s sleep × 36 attempts = 180 seconds
        _FAIL_STATES = {"fail", "failed", "error", "cancelled", "canceled"}

        for attempt in range(36):
            await asyncio.sleep(5)
            status_resp = await client.get(
                f"{KIE_AI_BASE_URL}/jobs/recordInfo",
                headers=headers,
                params={"taskId": task_id}
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()
            if not status_data.get("data"):
                raise ValueError(f"kie.ai recordInfo returned no data: {status_data}")
            state = status_data["data"].get("state", "")
            # Normalise to lowercase so "FAIL" / "Failed" / "fail" all match
            state_lower = state.lower() if state else ""
            print(f"kie.ai task {task_id} state: {state!r} (attempt {attempt + 1}/36)")

            if state_lower == "success":
                result_json = status_data["data"].get("resultJson", "{}")
                result = _json.loads(result_json) if isinstance(result_json, str) else result_json
                image_url = result.get("resultUrls", [None])[0]
                if not image_url:
                    raise ValueError("kie.ai returned success but no image URL")
                return image_url
            elif state_lower in _FAIL_STATES:
                # Extract a useful message from the response if kie.ai provides one
                kie_msg = (
                    status_data["data"].get("msg")
                    or status_data["data"].get("message")
                    or status_data.get("msg")
                    or f"state={state!r}"
                )
                raise ValueError(f"kie.ai task failed: {kie_msg}")

    raise TimeoutError(
        f"kie.ai task {task_id} did not complete after 3 minutes. "
        "This can happen when kie.ai is under load or credits are low. "
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

    # Build prompts per aspect-ratio bucket so portrait (9:16, 3:4) gets different
    # composition guidance from square/landscape — but we don't call the AI more than
    # once per unique ratio, keeping cost minimal.
    # Custom prompt bypasses AI entirely — Joel has full manual control.
    _prompt_cache: Dict[str, str] = {}

    def _get_aspect_ratio(w: int, h: int) -> str:
        ratio = w / h
        if ratio >= 1.7:   return "16:9"
        elif ratio >= 1.2: return "4:3"
        elif ratio >= 0.9: return "1:1"
        elif ratio >= 0.7: return "3:4"
        else:              return "9:16"

    async def _get_prompt_for_size(w: int, h: int) -> str:
        if request.customPrompt:
            return request.customPrompt
        ar = _get_aspect_ratio(w, h)
        if ar not in _prompt_cache:
            _prompt_cache[ar] = await _build_ai_image_prompt(request, aspect_ratio=ar)
        return _prompt_cache[ar]

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
            print(f"📦 Product Desc: {request.product.get('description') if request.product else 'None'}")
            print(f"📦 Template Type: {request.template.get('type') if request.template else 'None'}")
            print(f"📦 Copy Headline: {request.ad_copy.get('headline') if request.ad_copy else 'None'}")
            print(f"\n📝 FULL GENERATED PROMPT:")
            print(f"{prompt}")
            print(f"{'='*80}\n")
            if use_kie:
                try:
                    # Use `or None` to coerce an empty string URL (failed upload) to None
                    raw_input_image = (request.productShots[0] or None) if request.useProductImage and request.productShots else None

                    # Re-host the input image on our own server before passing to kie.ai.
                    # External URLs (Facebook CDN, etc.) often:
                    #   1. Require auth tokens — kie.ai can't fetch them
                    #   2. Are thumbnails (64x64) that are too small for flux-kontext-pro
                    #   3. Expire within hours
                    # Downloading and re-uploading ensures kie.ai gets a stable public URL.
                    input_image = None
                    if raw_input_image:
                        try:
                            async with httpx.AsyncClient(timeout=20.0) as _ref_client:
                                _ref_resp = await _ref_client.get(raw_input_image)
                                _ref_resp.raise_for_status()
                                _ref_bytes = _ref_resp.content

                            # Dimension check — kie.ai rejects images smaller than ~200px.
                            # Facebook's creative.image_url is a 64×64 thumbnail; the full-size
                            # image comes from object_story_spec.link_data.picture (now fixed in
                            # facebook_service.py). If we still get a tiny image, skip it.
                            from PIL import Image as _PIL_Image
                            import io as _io
                            _ref_img = _PIL_Image.open(_io.BytesIO(_ref_bytes))
                            _rw, _rh = _ref_img.size
                            print(f"Reference image dimensions: {_rw}×{_rh}")
                            if _rw < 200 or _rh < 200:
                                print(f"WARNING: reference image too small ({_rw}×{_rh}) — skipping inputImage, using text-to-image")
                                input_image = None
                            else:
                                # Save to R2 or local uploads so kie.ai can fetch from our stable URL
                                _ref_id   = str(uuid.uuid4())
                                _ref_name = f"ref_{_ref_id}.png"
                                if settings.r2_enabled:
                                    from app.api.v1.uploads import upload_to_r2
                                    input_image = await upload_to_r2(_ref_bytes, _ref_name, "image/png")
                                else:
                                    _ref_path = UPLOAD_DIR / _ref_name
                                    with open(_ref_path, "wb") as _rfh:
                                        _rfh.write(_ref_bytes)
                                    # kie.ai needs a full https:// URL — relative paths don't work
                                    input_image = f"{settings.PUBLIC_API_URL}/uploads/{_ref_name}"
                                print(f"Reference image re-hosted at {_rw}×{_rh}: {input_image}")
                        except Exception as _ref_err:
                            print(f"WARNING: could not re-host reference image ({_ref_err}) — proceeding text-to-image")
                            input_image = None

                    external_url = await _kie_generate_image(prompt, width, height, input_image, None)

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
