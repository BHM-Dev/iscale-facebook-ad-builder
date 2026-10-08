"""
Ad Remix Service - Business logic for deconstructing and reconstructing ads
"""
import json
import base64
import requests
import anthropic
import ipaddress
import socket
from urllib.parse import urlparse
from typing import Any
from app.core.config import settings
from app.schemas.ad_blueprint import AdBlueprint, AdConcept, BrandData
from app.prompts.ad_remix_prompts import build_deconstruction_prompt, build_reconstruction_prompt
from app.utils.json_utils import extract_json_from_response
import os


# AsyncAnthropic client — non-blocking in FastAPI's async event loop.
# Guard against missing key: instantiate only if key is present so a missing
# ANTHROPIC_API_KEY fails gracefully at request time, not at server startup.
_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
_anthropic_client = anthropic.AsyncAnthropic(api_key=_ANTHROPIC_API_KEY) if _ANTHROPIC_API_KEY else None

# Anthropic's vision API only accepts these media types
_ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

_MODEL = "claude-sonnet-4-5-20250929"

_SOURCE_IMAGE_HOST_SUFFIXES = ("fbcdn.net", "facebook.com", "fbsbx.com")


def validate_source_image_url(raw_url: str) -> str:
    """Allow only HTTPS media hosts we intentionally fetch for remix analysis.

    The URL is client-supplied on the direct remix route, so host suffix checks
    alone are not enough: resolve every address and reject private, loopback,
    link-local, multicast, reserved, and unspecified targets before fetching.
    """
    parsed = urlparse((raw_url or "").strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        raise ValueError("Source image must be an HTTPS URL on an approved media host")
    if parsed.port not in (None, 443):
        raise ValueError("Source image host must use HTTPS on port 443")

    approved_hosts = set()
    for base_url in (settings.R2_PUBLIC_URL, settings.PUBLIC_API_URL):
        configured_host = urlparse(base_url or "").hostname
        if configured_host:
            approved_hosts.add(configured_host.lower().rstrip("."))
    allowed = host in approved_hosts or any(host == suffix or host.endswith("." + suffix) for suffix in _SOURCE_IMAGE_HOST_SUFFIXES)
    if not allowed:
        raise ValueError("Source image host is not approved")

    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError("Source image host could not be resolved") from exc
    if not addresses:
        raise ValueError("Source image host could not be resolved")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified)):
            raise ValueError("Source image host resolves to a private or reserved address")
    return parsed.geturl()


async def deconstruct_template(template_image_url: str) -> AdBlueprint:
    """
    Analyze a template image and extract its structural blueprint

    Args:
        template_image_url: URL or path to the template image

    Returns:
        AdBlueprint with extracted structure
    """
    if not _anthropic_client:
        raise Exception("Anthropic API key not configured")

    try:
        # Build the prompt
        prompt = build_deconstruction_prompt(template_image_url)

        # Fetch the image and base64-encode it for the vision API
        validate_source_image_url(template_image_url)
        image_response = requests.get(template_image_url, timeout=(5, 10), stream=True)
        image_response.raise_for_status()
        content_length = image_response.headers.get("Content-Length")
        if content_length and int(content_length) > 10 * 1024 * 1024:
            raise ValueError("Source image is larger than 10 MB")
        chunks = []
        total = 0
        for chunk in image_response.iter_content(chunk_size=1024 * 1024):
            total += len(chunk)
            if total > 10 * 1024 * 1024:
                raise ValueError("Source image is larger than 10 MB")
            chunks.append(chunk)
        image_bytes = base64.b64encode(b"".join(chunks)).decode('utf-8')
        content_type = image_response.headers.get('Content-Type', 'image/jpeg').split(';')[0].strip()

        # Normalize common non-standard media type aliases
        if content_type == 'image/jpg':
            content_type = 'image/jpeg'
        if content_type not in _ALLOWED_MEDIA_TYPES:
            # Default to jpeg for unknown types rather than hard-erroring on the Anthropic side
            content_type = 'image/jpeg'

        response = await _anthropic_client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": content_type,
                                "data": image_bytes,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )

        response_text = response.content[0].text

        # Parse the JSON response (model may wrap output in ```json blocks)
        blueprint_data = extract_json_from_response(response_text)

        # Validate and return as AdBlueprint
        return AdBlueprint(**blueprint_data)

    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse blueprint JSON: {e}")
    except Exception as e:
        raise Exception(f"Failed to deconstruct template: {e}")


async def reconstruct_ad(
    blueprint: AdBlueprint,
    brand_data: BrandData
) -> AdConcept:
    """
    Generate a new ad concept by applying brand data to a blueprint

    Args:
        blueprint: The structural blueprint to follow
        brand_data: The new brand/product information

    Returns:
        AdConcept with generated content
    """
    if not _anthropic_client:
        raise Exception("Anthropic API key not configured")

    try:
        # Convert blueprint to dict
        blueprint_dict = blueprint.model_dump()

        # Build the reconstruction prompt
        prompt = build_reconstruction_prompt(
            blueprint=blueprint_dict,
            brand_name=brand_data.brand_name,
            brand_voice=brand_data.brand_voice or "",
            product_name=brand_data.product_name,
            product_description=brand_data.product_description,
            audience_demographics=brand_data.audience_demographics,
            audience_pain_points=brand_data.audience_pain_points or "",
            audience_goals=brand_data.audience_goals or "",
            campaign_offer=brand_data.campaign_offer,
            campaign_urgency=brand_data.campaign_urgency or "",
            campaign_messaging=brand_data.campaign_messaging,
            niche=brand_data.niche or "",
            competitor_context=brand_data.competitor_context or "",
        )

        response = await _anthropic_client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        response_text = response.content[0].text

        if not response_text:
            raise ValueError("Model returned an empty response (possible content filter or rate limit)")

        # Parse the JSON response
        concept_data = extract_json_from_response(response_text)

        # Validate and return as AdConcept
        return AdConcept(**concept_data)

    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse ad concept JSON: {e}")
    except Exception as e:
        raise Exception(f"[{type(e).__name__}] Failed to reconstruct ad: {e}")


# extract_json_from_response imported from app.utils.json_utils
