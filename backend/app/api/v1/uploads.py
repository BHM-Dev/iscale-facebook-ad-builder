from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
import os
import uuid
from typing import Dict, Optional
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from app.core.config import settings
from app.core.deps import get_current_active_user
from app.models import User
from app.services.image_crop_service import crop_to_aspect

router = APIRouter()

# Security: Define allowed file types and size limits
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.webm'}
ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB for images
MAX_VIDEO_SIZE = 500 * 1024 * 1024  # 500MB for videos

# Local upload dir for fallback
UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "uploads"
UPLOAD_DIR = UPLOAD_DIR.resolve()
os.makedirs(UPLOAD_DIR, mode=0o755, exist_ok=True)

# Initialize R2 client if configured
_s3_client = None

def get_s3_client():
    global _s3_client
    if _s3_client is None and settings.r2_enabled:
        import boto3
        _s3_client = boto3.client(
            's3',
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name='auto'
        )
    return _s3_client


async def upload_to_r2(file_content: bytes, filename: str, content_type: str) -> str:
    """Upload file to Cloudflare R2 and return public URL.

    boto3's put_object is blocking network I/O — this backend runs a single
    uvicorn worker with no --workers flag, so a naive `async def` here would
    hold the one event loop hostage for every upload (documented root cause
    of the 2026-08-28 login-slowdown incident). run_in_threadpool offloads it.
    """
    client = get_s3_client()
    if not client:
        raise HTTPException(status_code=500, detail="R2 storage not configured")

    try:
        await run_in_threadpool(
            client.put_object,
            Bucket=settings.R2_BUCKET_NAME,
            Key=filename,
            Body=file_content,
            ContentType=content_type,
        )
        return f"{settings.R2_PUBLIC_URL}/{filename}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload to R2: {str(e)}")


async def upload_to_local(file_content: bytes, filename: str) -> str:
    """Upload file to local filesystem and return relative URL"""
    file_path = UPLOAD_DIR / filename

    def _write():
        with open(file_path, "wb") as buffer:
            buffer.write(file_content)

    await run_in_threadpool(_write)
    return f"/uploads/{filename}"


@router.post("/", response_model=Dict[str, str])
async def upload_file(file: UploadFile = File(...), current_user: User = Depends(get_current_active_user)):
    try:
        # Security: Sanitize filename to prevent path traversal
        safe_filename = os.path.basename(file.filename)
        file_extension = os.path.splitext(safe_filename)[1].lower()

        # Security: Validate file extension
        if file_extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
            )

        # Determine if video or image
        is_video = file_extension in ALLOWED_VIDEO_EXTENSIONS
        max_size = MAX_VIDEO_SIZE if is_video else MAX_IMAGE_SIZE

        # Read file content
        file_content = await file.read()

        # Security: Validate file size
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {max_size / (1024 * 1024)}MB"
            )

        # Generate a unique filename
        filename = f"{uuid.uuid4()}{file_extension}"

        # Upload to R2 if configured, otherwise local
        if settings.r2_enabled:
            url = await upload_to_r2(file_content, filename, file.content_type or 'application/octet-stream')
        else:
            url = await upload_to_local(file_content, filename)

        # Return media type along with URL
        media_type = 'video' if is_video else 'image'
        return {"url": url, "media_type": media_type}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not upload file: {str(e)}")


# 1080px matches Meta's own recommended minimum for both formats — high enough
# quality, small enough to crop/resize/upload fast for an interactive control.
_CROP_TARGET_DIMENSIONS = {
    '1:1': (1080, 1080),
    '9:16': (1080, 1920),
}
_CROP_ANCHORS = {'start', 'center', 'end'}


@router.post("/crop-to-aspect", response_model=Dict[str, str])
async def crop_image_to_aspect(
    target_ratio: str = Form(...),
    anchor: str = Form('center'),
    file: Optional[UploadFile] = File(None),
    source_url: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
):
    """Crop (never stretch) an image to Feed (1:1) or Stories (9:16), from
    either a freshly uploaded file or an existing hosted image URL (e.g. a
    Drive-synced asset already on R2) — used to turn a single Feed/Stories
    duplicate into a real, correctly-cropped image instead of the raw source
    reused untouched at the wrong aspect ratio.

    Fetches source_url server-side (same pattern already used in
    facebook_service.py's upload_image) rather than in the browser, so this
    works regardless of whether the source host sets CORS headers permissive
    enough for a client-side canvas to read the pixels back out.
    """
    if target_ratio not in _CROP_TARGET_DIMENSIONS:
        raise HTTPException(status_code=400, detail="target_ratio must be '1:1' or '9:16'")
    if anchor not in _CROP_ANCHORS:
        raise HTTPException(status_code=400, detail=f"anchor must be one of {sorted(_CROP_ANCHORS)}")

    if file is not None:
        file_content = await file.read()
        if len(file_content) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {MAX_IMAGE_SIZE / (1024 * 1024)}MB"
            )
    elif source_url:
        import requests

        def _fetch():
            resp = requests.get(source_url, timeout=30, stream=True)
            resp.raise_for_status()
            content = resp.raw.read(MAX_IMAGE_SIZE + 1, decode_content=True)
            if len(content) > MAX_IMAGE_SIZE:
                raise ValueError(f"source_url image exceeds {MAX_IMAGE_SIZE / (1024 * 1024)}MB limit")
            return content

        try:
            # Blocking network call — run_in_threadpool keeps it off the single
            # event loop (see upload_to_r2 above for why that matters here).
            file_content = await run_in_threadpool(_fetch)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not fetch source_url: {e}")
    else:
        raise HTTPException(status_code=400, detail="Provide either 'file' or 'source_url'")

    target_w, target_h = _CROP_TARGET_DIMENSIONS[target_ratio]
    try:
        # Pillow crop/resize is CPU-bound — also threadpooled so a bulk-add of
        # many images can't stall every other request on this worker.
        cropped_bytes, crop_axis = await run_in_threadpool(
            crop_to_aspect, file_content, target_w, target_h, anchor
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not process image: {e}")

    filename = f"{uuid.uuid4()}.jpg"
    if settings.r2_enabled:
        url = await upload_to_r2(cropped_bytes, filename, 'image/jpeg')
    else:
        url = await upload_to_local(cropped_bytes, filename)

    return {"url": url, "media_type": "image", "crop_axis": crop_axis}
