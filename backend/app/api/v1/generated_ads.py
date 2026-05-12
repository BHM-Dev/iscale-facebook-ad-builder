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
_PROMPT_MODEL = "claude-3-5-haiku-20241022"

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

        # Composition guidance differs by orientation
        is_portrait = aspect_ratio in ("9:16", "3:4")
        if is_portrait:
            composition_note = (
                "vertical story format — subject centered in the middle third of the frame, "
                "clear safe zones at both top and bottom for UI chrome, no key elements in top or bottom 20%"
            )
        else:
            composition_note = (
                "clean empty space at the bottom third for text overlay, "
                "subject prominent in upper two-thirds"
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

    # flux-kontext-pro is an image-editing model — it requires inputImage.
    # For pure text-to-image (no product shot), use flux-2/pro-text-to-image
    # which has a different nested-input schema.
    if input_image_url:
        model = "flux-kontext-pro"
        payload = {
            "model": model,
            "prompt": prompt,
            "aspectRatio": aspect_ratio,   # camelCase for kontext
            "outputFormat": "png",
            "inputImage": input_image_url,
        }
    else:
        model = "flux-2/pro-text-to-image"
        # NOTE: flux-2/pro-text-to-image does NOT support negative_prompt.
        # The only supported input fields are: prompt, aspect_ratio, resolution, nsfw_checker.
        # Sending unsupported fields causes immediate task failure (state: fail).
        input_block: Dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,  # snake_case inside input
            "resolution": "1K",
        }
        payload = {
            "model": model,
            "input": input_block,
        }

    async with httpx.AsyncClient(timeout=200.0) as client:
        # Create the task
        create_resp = await client.post(
            f"{KIE_AI_BASE_URL}/jobs/createTask",
            headers=headers,
            json=payload
        )
        create_resp.raise_for_status()
        task_data = create_resp.json()
        print(f"kie.ai createTask response: {task_data}")
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
                    input_image = (request.productShots[0] or None) if request.useProductImage and request.productShots else None
                    # negative_prompt is NOT supported by flux-2/pro-text-to-image (causes task failure).
                    # flux-kontext-pro ignores it too. Pass None for now; retained in signature
                    # in case a future kie.ai model supports it.
                    external_url = await _kie_generate_image(prompt, width, height, input_image, None)

                    print(f"Downloading image from kie.ai: {external_url[:50]}...")
                    image_url = await download_and_save_image(external_url, prefix="generated")
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
        "thumbnail_url": ad.thumbnail_url
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
            thumbnail_url=ad_data.thumbnailUrl
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
