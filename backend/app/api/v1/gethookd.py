"""GetHookd bridge (Steve, 2026-11-18): Joel finds ads in GetHookd; this turns one into a "build like this" start.

Reference-only by decision: a competitor's ad informs our version, it is never launched as-is. So the only things
that leave this module are the ad's copy (as a starting point for a rewrite in our voice), a reference image we copy
into our own storage, and the GetHookd link. The competitor's landing page is never returned: our ads keep our own
destination and Everflow tracking.

Only free GetHookd endpoints are used (swipe file, single ad, media download); boards and search cost credits and
are not called. Auth: GETHOOKD_API_KEY (a token created in GetHookd -> API), sent as a bearer token.
"""
import logging
import os
import re
import time
import uuid
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.deps import get_current_active_user
from app.models import User

router = APIRouter()
logger = logging.getLogger(__name__)

GETHOOKD_HOST = "app.gethookd.ai"
API_BASE = f"https://{GETHOOKD_HOST}/api/v1"
SAVED_CACHE_SECONDS = 120
MAX_REFERENCE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}
_saved_cache: dict[int, tuple[float, dict]] = {}
_SHARE_ID = re.compile(r"/share/ad/(\d+)")


def _key() -> str | None:
    return (os.getenv("GETHOOKD_API_KEY") or "").strip() or None


def _get(path: str, params: dict | None = None) -> dict:
    key = _key()
    if not key:
        raise HTTPException(status_code=503, detail="GetHookd is not connected yet (GETHOOKD_API_KEY is not set).")
    try:
        resp = httpx.get(f"{API_BASE}{path}", params=params, timeout=20,
                         headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GetHookd did not answer: {exc.__class__.__name__}")
    if resp.status_code in (401, 403):
        raise HTTPException(status_code=502, detail="GetHookd rejected the API key (check its scopes: swipe-file:read, explore:read).")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="That ad was not found in GetHookd.")
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="GetHookd rate limit reached; try again in a minute.")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"GetHookd error {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="GetHookd sent an unreadable response.")
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="GetHookd sent an unexpected response.")
    return body


def _ad_summary(ad: dict) -> dict:
    """What the Ad Builder may use from a GetHookd ad. Deliberately excludes landing_page."""
    media = ad.get("media") or []
    first = media[0] if media else {}
    return {
        "id": ad.get("id"),
        "brand_name": (ad.get("brand") or {}).get("name"),
        "headline": ad.get("title") or "",
        "body": ad.get("body") or "",
        "description": ad.get("link_description") or "",
        "cta_type": ad.get("cta_type"),
        "format": ad.get("asset_type") or ad.get("display_format"),
        "status": ad.get("status"),
        "days_active": ad.get("days_active"),
        "performance": ad.get("performance_score_title"),
        "thumbnail_url": first.get("thumbnail_url") or ad.get("primary_image_url"),   # signed, ~24h: display only
        "share_url": ad.get("share_url"),
        "media_count": len(media),
    }


@router.get("/status")
def status(current_user: User = Depends(get_current_active_user)):
    return {"connected": bool(_key())}


@router.get("/saved")
def saved_ads(page: int = Query(1, ge=1, le=50), current_user: User = Depends(get_current_active_user)):
    """The workspace's GetHookd swipe file (free), newest first."""
    hit = _saved_cache.get(page)
    if hit and time.monotonic() - hit[0] < SAVED_CACHE_SECONDS:
        return hit[1]
    data = _get("/swipefile", {"per_page": 24, "page": page, "compact": "true"})
    rows = data.get("data") if isinstance(data.get("data"), list) else []
    result = {"ads": [_ad_summary(ad) for ad in rows if isinstance(ad, dict)], "total": (data.get("meta") or {}).get("total")}
    _saved_cache[page] = (time.monotonic(), result)
    return result


def parse_ad_ref(ref: str) -> int:
    """A GetHookd share link (…/share/ad/123?signature=…) or a bare ad id."""
    ref = (ref or "").strip()
    match = _SHARE_ID.search(ref)
    if match:
        return int(match.group(1))
    if ref.isdigit():
        return int(ref)
    raise HTTPException(status_code=400, detail="Paste a GetHookd ad link (Share → copy link) or an ad id.")


@router.get("/ad")
def lookup_ad(ref: str = Query(..., max_length=500), current_user: User = Depends(get_current_active_user)):
    """One ad by GetHookd link or id (free) — works for ads on boards too, not just the swipe file."""
    data = _get(f"/ads/{parse_ad_ref(ref)}")
    return _ad_summary(data.get("data") or data)


class ReferenceBody(BaseModel):
    ad_id: int = Field(..., ge=1)


@router.post("/reference")
async def make_reference(body: ReferenceBody, current_user: User = Depends(get_current_active_user)):
    """Copy the ad's first image (or a video's poster frame) into our storage and return the build-like-this
    handoff. GetHookd media links expire after 24h, so the remix must not depend on them."""
    from starlette.concurrency import run_in_threadpool
    from app.api.v1.uploads import upload_to_local, upload_to_r2

    data = await run_in_threadpool(_get, f"/ads/{body.ad_id}")
    ad = data.get("data") or data
    summary = _ad_summary(ad)
    media = ad.get("media") or []
    first = media[0] if media else {}
    source = (first.get("download_url") if first.get("type") == "image" else first.get("thumbnail_url")) or ad.get("primary_image_url")
    image_url = None
    # Only ever fetch from GetHookd itself, over https: the URL comes from their response, and our bearer token
    # must never be sent anywhere else (nor may a crafted URL make this server fetch an internal address).
    if source and urlparse(source).scheme == "https" and urlparse(source).hostname == GETHOOKD_HOST:
        def fetch():
            with httpx.stream("GET", source, timeout=30, follow_redirects=False,
                              headers={"Authorization": f"Bearer {_key()}"}) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if content_type not in IMAGE_TYPES:
                    raise ValueError(f"not a reference image: {content_type or 'no type'}")
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_REFERENCE_BYTES:
                        raise ValueError("reference image over 10MB")
                    chunks.append(chunk)
            return b"".join(chunks), content_type
        try:
            content, content_type = await run_in_threadpool(fetch)
            if content:
                ext = IMAGE_TYPES[content_type]
                filename = f"references/gethookd-{body.ad_id}-{uuid.uuid4().hex[:8]}.{ext}"
                image_url = await (upload_to_r2(content, filename, content_type) if settings.r2_enabled
                                   else upload_to_local(content, filename.replace("/", "-")))
        except Exception as exc:  # noqa: BLE001 — the copy still works without a reference image
            logger.warning("GetHookd reference image copy failed for ad %s: %s", body.ad_id, exc)
    return {**summary, "thumbnail_url": None, "reference_image_url": image_url}
