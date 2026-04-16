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
from pathlib import Path
from app.core.config import settings

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
                              input_image_url: str = None) -> str:
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

    payload = {
        "model": "flux-kontext-pro",
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "outputFormat": "png",
    }
    if input_image_url:
        payload["inputImage"] = input_image_url

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Create the task
        create_resp = await client.post(
            f"{KIE_AI_BASE_URL}/jobs/createTask",
            headers=headers,
            json=payload
        )
        create_resp.raise_for_status()
        task_data = create_resp.json()
        task_id = task_data["data"]["taskId"]
        print(f"kie.ai task created: {task_id}")

        # Poll until done (max ~2 minutes)
        for attempt in range(24):
            await asyncio.sleep(5)
            status_resp = await client.get(
                f"{KIE_AI_BASE_URL}/jobs/recordInfo",
                headers=headers,
                params={"taskId": task_id}
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()
            state = status_data["data"].get("state")
            print(f"kie.ai task {task_id} state: {state} (attempt {attempt + 1})")

            if state == "success":
                import json as _json
                result_json = status_data["data"].get("resultJson", "{}")
                result = _json.loads(result_json) if isinstance(result_json, str) else result_json
                image_url = result.get("resultUrls", [None])[0]
                if not image_url:
                    raise ValueError("kie.ai returned success but no image URL")
                return image_url
            elif state == "fail":
                raise ValueError(f"kie.ai task failed: {status_data}")

    raise TimeoutError(f"kie.ai task {task_id} did not complete within timeout")


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

    for i in range(request.count):
        for size in request.imageSizes:
            width = size.get('width', 1080)
            height = size.get('height', 1080)
            size_name = size.get('name', 'Square')

            prompt = build_comprehensive_prompt(request)

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
                    input_image = request.productShots[0] if request.useProductImage and request.productShots else None
                    external_url = await _kie_generate_image(prompt, width, height, input_image)

                    print(f"Downloading image from kie.ai: {external_url[:50]}...")
                    image_url = await download_and_save_image(external_url, prefix="generated")
                    print(f"Saved as: {image_url}")

                except Exception as e:
                    print(f"kie.ai generation failed: {e}")
                    product_name = request.product.get('name', 'Product') if request.product else 'Product'
                    image_url = f"https://placehold.co/{width}x{height}/png?text={product_name}+Error"
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get all generated ads, optionally filtered by brand"""
    query = db.query(GeneratedAd)

    if brand_id:
        query = query.filter(GeneratedAd.brand_id == brand_id)

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
