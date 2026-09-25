from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Tuple
import re
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import urlparse
from app.database import get_db
from app.core.deps import get_current_active_user
from app.models import User
from app.schemas.research import (
    AdSearchRequest, ScrapedAdResponse, ScrapedAdCreate, ScrapedAdSearchResult, SavedSearchResponse,
    BrandScrapeCreate, BrandScrapeResponse, BrandScrapeListResponse, AdLibraryImportRequest,
    ExternalResearchImportRequest,
    ResearchBoardCreate, ResearchBoardItemCreate, ResearchBoardResponse, ResearchBoardItemResponse,
    ResearchMediaAttachment, ResearchBriefCuration, ResearchCopilotQuery,
)
from app.services.research_service import ResearchService
from app.services.rate_limiter import rate_limiter

router = APIRouter()

MAX_AD_LIBRARY_IMPORT_ADS = 100
MAX_AD_LIBRARY_VIDEO_URLS = 3
MAX_AD_LIBRARY_TEXT_CHARS = 5000
MAX_AD_LIBRARY_CREATIVE_INTEL_CHARS = 12000
RESEARCH_MEDIA_TYPES = {"image", "video", "carousel", "unknown"}
RESEARCH_SORT_OPTIONS = {"longest_running", "newest_seen", "most_sightings", "multiple_versions"}
RESEARCH_CREATIVE_TAGS = {"testimonial", "problem_agitation", "transformation", "comparison", "review", "listicle", "founder", "educational", "statistic", "ugc", "comment_response"}
RESEARCH_CTA_TYPES = {"learn_more", "get_quote", "sign_up", "apply_now", "contact_us", "shop_now", "unknown"}
RESEARCH_PAGE_TYPES = {"lead_form", "advertorial", "ecommerce", "homepage", "unknown"}
COPILOT_STOP_WORDS = {
    "active", "ad", "ads", "and", "are", "best", "cta", "day", "days", "find", "for", "from", "get", "in", "last", "me", "of", "performing", "please", "running", "show", "that", "the", "these", "this", "to", "use", "what", "with",
}
COPILOT_SEGMENTS = {
    "owner-operators": ("owner operator", "owner-operator", "owner operators", "owner-operators"),
    "truckers": ("trucker", "truckers", "trucking", "hauler", "haulers"),
    "religious organizations": ("church", "churches", "religious organization", "religious organizations", "ministry", "ministries"),
    "contractors": ("contractor", "contractors"),
    "tree services": ("tree service", "tree services", "arborist", "arborists"),
    "security firms": ("security firm", "security firms", "security company", "security companies"),
}
COPILOT_CREATIVE_TAGS = {
    "testimonial": ("testimonial", "testimonials", "customer story", "customer stories"),
    "review": ("review", "reviews", "rating", "ratings"),
    "problem_agitation": ("problem agitation", "pain point", "pain points", "cost shock"),
    "comparison": ("comparison", "compare", "versus", " vs "),
    "ugc": ("ugc", "user generated", "selfie ad", "creator ad"),
    "educational": ("educational", "explainer", "how it works"),
    "listicle": ("listicle", "top reasons", "top 5", "top five"),
}
COPILOT_CTA_PHRASES = {
    "get_quote": ("get quote", "quote ads", "quote ad"),
    "learn_more": ("learn more",),
    "apply_now": ("apply now",),
    "sign_up": ("sign up", "signup"),
    "contact_us": ("contact us", "contact them"),
}
COPILOT_PAGE_TYPE_PHRASES = {
    "lead_form": ("lead form", "lead-form"),
    "advertorial": ("advertorial", "presell", "pre sell"),
    "ecommerce": ("ecommerce", "e-commerce", "product page"),
    "homepage": ("homepage", "home page"),
}


def _normalize_external_url(value: str | None) -> str:
    """Return a browser-safe HTTP(S) URL, preserving invalid values as empty."""
    candidate = (value or "").strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        return candidate
    if candidate.startswith("//"):
        return f"https:{candidate}"
    if parsed.scheme or candidate.startswith(("/", "#", "?")):
        return ""
    return f"https://{candidate}"


def _external_destination_domain(value: str | None) -> str | None:
    """Extract a hostname from full or scheme-less external landing URLs."""
    normalized = _normalize_external_url(value)
    return urlparse(normalized).hostname or None


def _resolve_external_import_vertical(value: str) -> str | None:
    """Map an import vertical to a Browse-reachable configured label."""
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS

    labels = {config["label"] for config in VERTICAL_KEYWORD_SETS.values()}
    labels.update(
        sub_vertical["label"]
        for config in VERTICAL_KEYWORD_SETS.values()
        for sub_vertical in config.get("sub_verticals", {}).values()
    )
    normalized_labels = {label.casefold(): label for label in labels}
    return normalized_labels.get(value.strip().casefold())


def _infer_creative_taxonomy(headline, ad_copy, cta_text, supplied_tags=None):
    """Conservative, explainable enrichment for Chrome/API captures.

    We only add deterministic labels from visible text; all others remain
    unknown so the filter never pretends a classifier saw more than it did.
    """
    text = " ".join(filter(None, [headline, ad_copy])).lower()
    tags = [tag for tag in (supplied_tags or []) if tag in RESEARCH_CREATIVE_TAGS]
    rules = {
        "testimonial": ("testimonial", "customer story", "what our customers say"),
        "problem_agitation": ("tired of", "stop overpaying", "struggling with"),
        "comparison": ("vs.", "versus", "compare", "instead of"),
        "review": ("review", "rated", "stars"),
        "listicle": ("top 5", "top five", "ways to", "reasons why"),
        "founder": ("our founder", "i started", "we started"),
        "educational": ("how to", "what is", "guide to"),
        "statistic": ("%", "percent", "out of 10"),
        "ugc": ("i tried", "my experience", "honestly"),
    }
    for tag, phrases in rules.items():
        if tag not in tags and any(phrase in text for phrase in phrases):
            tags.append(tag)
    cta = (cta_text or "").strip().lower().replace(" ", "_")
    cta_map = {"learn_more": "learn_more", "get_quote": "get_quote", "sign_up": "sign_up", "apply_now": "apply_now", "contact_us": "contact_us", "shop_now": "shop_now"}
    return tags or None, cta_map.get(cta, "unknown" if cta else None)


def _matches_research_vertical(ad, config_id):
    """Last-line quality gate for legacy broad captures already in the catalog."""
    if config_id != "commercial_insurance":
        return True
    # External rows are explicitly attached to a validated configured vertical
    # at import time. Applying the legacy copy-keyword gate here hides useful
    # segment-led examples whenever their visible copy does not repeat
    # "commercial insurance". Keep this quality guard for broad legacy
    # captures, where it protects Browse from unrelated search noise.
    if getattr(ad, "platform", None) == "external":
        return True
    text = " ".join(filter(None, [ad.brand_name, ad.headline, ad.ad_copy, ad.cta_text])).lower()
    commercial = ("business insurance", "commercial insurance", "general liability", "workers comp", "workers compensation", "business owners policy", "commercial auto", "business coverage", "liability insurance")
    insurance_context = ("insurance", "coverage", "policy", "premium", "insured", "liability")
    obvious_noise = ("restaurant equipment", "now hiring", "lease type", "med spa", "hot-dog", "jewelry design", "tabletops")
    # A broad Ad Library search can return ordinary commercial/home-service
    # promotions. Require insurance language as well as a commercial offer
    # phrase before presenting a raw capture in this vertical.
    return (
        any(term in text for term in commercial)
        and any(term in text for term in insurance_context)
        and not any(term in text for term in obvious_noise)
    )


def _research_relevance_status(ad, config_id: str) -> str | None:
    """Expose a conservative review cue without hiding retained evidence.

    The legacy commercial catalog contains old broad-search captures. Keep
    them searchable, but label records that lack an explicit insurance-offer
    signal so an internal researcher does not mistake them for clean input.
    """
    if config_id != "commercial_insurance":
        return None
    value = (lambda field: ad.get(field) if isinstance(ad, dict) else getattr(ad, field, None))
    if value("platform") == "external":
        return "source_reviewed"
    text = " ".join(filter(None, [value("brand_name"), value("headline"), value("ad_copy"), value("cta_text")])).casefold()
    explicit_offer = (
        "commercial insurance", "business insurance", "small business insurance",
        "commercial auto", "general liability", "liability insurance",
        "business owners policy", "bop insurance", "insurance quote",
    )
    if any(phrase in text for phrase in explicit_offer):
        return "high_confidence"
    if "insurance" in text and any(phrase in text for phrase in ("quote", "coverage", "policy", "premium", "get insured")):
        return "high_confidence"
    return "needs_review"


def _has_retained_visual(ad) -> bool:
    """Return whether the catalog has a real, reviewable visual asset.

    `media_type` alone is only source metadata; a card marked "video" may
    still have no thumbnail or playable capture. Keep that distinction
    explicit so researchers can begin from actual creative when needed.
    """
    value = (lambda field: ad.get(field) if isinstance(ad, dict) else getattr(ad, field, None))
    return bool(value("thumbnail_url") or value("media_url") or value("media_preview_url") or value("video_urls"))


def _related_pattern_score(source, candidate):
    """Return an explainable metadata match score and reasons, or None."""
    shared_tags = sorted(set(source.creative_tags or []) & set(candidate.creative_tags or []))
    reasons = [f"theme: {tag.replace('_', ' ')}" for tag in shared_tags]
    same_cta = bool(source.cta_type and source.cta_type == candidate.cta_type)
    same_format = bool(source.media_type and source.media_type == candidate.media_type)
    same_destination = bool(source.destination_domain and source.destination_domain == candidate.destination_domain)
    if same_cta:
        reasons.append(f"CTA: {source.cta_type.replace('_', ' ')}")
    if same_format:
        reasons.append(f"format: {source.media_type}")
    if same_destination:
        reasons.append("same destination")
    # A shared CTA or media format alone is too generic to imply relevance —
    # "get_quote" + "video" matches across completely unrelated verticals
    # (e.g. a home-services ad "related" to a commercial-insurance ad) since
    # neither the ScrapedAd model nor this endpoint tracks vertical/config.
    # Require at least one specific, content-derived signal (a shared
    # creative tag or the same landing destination) before a generic signal
    # is allowed to count at all.
    if not shared_tags and not same_destination:
        return None
    return len(shared_tags) * 4 + (2 if same_cta else 0) + int(same_format) + int(same_destination), reasons


def _configured_vertical_label(config_id: str | None) -> str | None:
    """Resolve a Research UI config id to its persisted Vertical name."""
    if not config_id:
        return None
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS
    config = VERTICAL_KEYWORD_SETS.get(config_id)
    return config.get("label") if config else None


def _plan_research_copilot_question(question: str, vertical_id: str) -> dict:
    """Translate common media-buyer language into transparent, bounded filters.

    This is intentionally deterministic for v1. A model can later propose the
    same structured plan, but it must still pass these validation boundaries.
    """
    text = question.casefold().strip()
    # Meta's public Ad Library does not expose spend, ROAS, conversions, or
    # a trustworthy performance ranking. Preserve the operator's question,
    # but surface the limitation rather than quietly translating "best
    # performing" into our capture-order proxy.
    performance_intent = any(phrase in text for phrase in (
        "best performing", "top performing", "performance", "winning ad",
        "winning ads", "highest spend", "most spend", "roas", "roi",
        "conversions", "conversion", "impressions",
    ))
    segments = [label for label, phrases in COPILOT_SEGMENTS.items() if any(phrase in text for phrase in phrases)]
    creative_tags = [tag for tag, phrases in COPILOT_CREATIVE_TAGS.items() if any(phrase in text for phrase in phrases)]
    cta_type = next((cta for cta, phrases in COPILOT_CTA_PHRASES.items() if any(phrase in text for phrase in phrases)), None)
    page_type = next((page for page, phrases in COPILOT_PAGE_TYPE_PHRASES.items() if any(phrase in text for phrase in phrases)), None)
    active_only = any(term in text for term in ("active", "current", "running", "live now"))
    recent_match = re.search(r"(?:last|past)\s+(\d{1,3})\s+days", text)
    runtime_match = re.search(r"(?:running|run|active)[^\d]{0,20}(\d{1,3})\s*(?:\+|plus)?\s*days", text)
    media_type = "video" if "video" in text else "image" if any(term in text for term in ("image", "static")) else None
    raw_terms = re.findall(r"[a-z0-9]{3,}", text)
    terms = [term for term in raw_terms if term not in COPILOT_STOP_WORDS and not term.isdigit()]
    # Segment labels are query intent, not a reason to require every individual
    # phrase fragment (e.g. both "owner" and "operators") in a result.
    for phrase in sum((list(phrases) for label, phrases in COPILOT_SEGMENTS.items() if label in segments), []):
        for token in re.findall(r"[a-z0-9]{3,}", phrase):
            terms = [term for term in terms if term != token]
    for phrase in sum((list(phrases) for tag, phrases in COPILOT_CREATIVE_TAGS.items() if tag in creative_tags), []):
        for token in re.findall(r"[a-z0-9]{3,}", phrase):
            terms = [term for term in terms if term != token]
    for phrase_group, selected in ((COPILOT_CTA_PHRASES, cta_type), (COPILOT_PAGE_TYPE_PHRASES, page_type)):
        if not selected:
            continue
        for token in re.findall(r"[a-z0-9]{3,}", " ".join(phrase_group[selected])):
            terms = [term for term in terms if term != token]
    return {
        "vertical_id": vertical_id,
        "segments": segments,
        "creative_tags": creative_tags,
        "active_only": active_only,
        "captured_within_days": min(int(recent_match.group(1)), 365) if recent_match else None,
        "min_running_days": min(int(runtime_match.group(1)), 3650) if runtime_match else None,
        "media_type": media_type,
        "cta_type": cta_type,
        "page_type": page_type,
        "terms": terms[:8],
        "ranking": ["query relevance", "capture recency", "observed runtime", "creative versions"],
        "performance_intent": performance_intent,
    }


def _score_research_copilot_candidate(ad, plan: dict, now: datetime) -> tuple[int, list[str]] | None:
    text = " ".join(filter(None, [ad.brand_name, ad.headline, ad.ad_copy, ad.cta_text])).casefold()
    start = _parse_research_date(ad.start_date)
    last_seen = _parse_research_date(ad.last_seen)
    running_days = max(0, (now - start).days) if start and ad.platform != "external" else None
    reasons = []
    score = 0
    if plan["active_only"]:
        if not last_seen or (now - last_seen).days > 30:
            return None
        score += 18
        reasons.append("captured in the last 30 days")
    if plan["captured_within_days"]:
        if not last_seen or (now - last_seen).days > plan["captured_within_days"]:
            return None
        score += 14
        reasons.append(f"captured within {plan['captured_within_days']} days")
    if plan["min_running_days"]:
        if running_days is None or running_days < plan["min_running_days"]:
            return None
        score += min(30, running_days // 3)
        reasons.append(f"observed {running_days} days")
    if plan["media_type"]:
        if (ad.media_type or "").casefold() != plan["media_type"]:
            return None
        reasons.append(f"{plan['media_type']} format")
        score += 8
    if plan["cta_type"]:
        if ad.cta_type != plan["cta_type"]:
            return None
        reasons.append(f"{plan['cta_type'].replace('_', ' ')} CTA")
        score += 8
    if plan["page_type"]:
        if ad.page_type != plan["page_type"]:
            return None
        reasons.append(f"{plan['page_type'].replace('_', ' ')} destination")
        score += 8
    segment_matches = [segment for segment in plan["segments"] if any(phrase in text for phrase in COPILOT_SEGMENTS[segment])]
    if plan["segments"] and not segment_matches:
        return None
    if segment_matches:
        reasons.extend(f"{segment} language" for segment in segment_matches)
        score += 28 * len(segment_matches)
    tag_matches = [tag for tag in plan["creative_tags"] if tag in (ad.creative_tags or [])]
    if plan["creative_tags"] and not tag_matches:
        # Imports predating taxonomy may still carry the explicit phrase in
        # their visible copy. This fallback is transparent and avoids making
        # older, otherwise valid evidence disappear solely for missing tags.
        tag_matches = [tag for tag in plan["creative_tags"] if any(phrase in text for phrase in COPILOT_CREATIVE_TAGS[tag])]
    if plan["creative_tags"] and not tag_matches:
        return None
    if tag_matches:
        reasons.extend(f"{tag.replace('_', ' ')} pattern" for tag in tag_matches)
        score += 18 * len(tag_matches)
    term_matches = [term for term in plan["terms"] if term in text]
    if plan["terms"] and not term_matches and not segment_matches and not tag_matches:
        return None
    if term_matches:
        reasons.append("matched: " + ", ".join(term_matches[:3]))
        score += min(24, len(term_matches) * 8)
    if ad.is_multiple_versions:
        score += 7
        reasons.append("multiple captured versions")
    if ad.thumbnail_url or ad.media_url:
        score += 4
        reasons.append("retained visual")
    if last_seen:
        score += max(0, 10 - min(10, (now - last_seen).days // 3))
    return score, reasons or ["same selected research vertical"]


def _copilot_query_suggestions(question: str, plan: dict, vertical_label: str) -> list[dict]:
    """Offer transparent, deterministic recovery paths for a narrow query."""
    subject = f"{vertical_label} ads"
    if plan["segments"]:
        subject += f" for {plan['segments'][0]}"
    if plan["media_type"]:
        subject += f" with {plan['media_type']} creative"
    suggestions = []
    if plan["min_running_days"]:
        suggestions.append({"question": f"Show {subject}", "reason": f"Remove the {plan['min_running_days']}-day observed-runtime requirement"})
    if plan["active_only"]:
        suggestions.append({"question": f"Show {subject}", "reason": "Include older retained captures instead of only the last 30 days"})
    if plan["captured_within_days"]:
        suggestions.append({"question": f"Show {subject}", "reason": f"Remove the {plan['captured_within_days']}-day capture-recency requirement"})
    if plan["media_type"]:
        broad_subject = f"{vertical_label} ads" + (f" for {plan['segments'][0]}" if plan["segments"] else "")
        suggestions.append({"question": f"Show {broad_subject}", "reason": f"Include all retained formats instead of only {plan['media_type']} creative"})
    suggestions.append({"question": f"Show {subject}", "reason": "Review the broad retained catalog for this audience"})
    seen, unique = {question.casefold().strip()}, []
    for suggestion in suggestions:
        key = suggestion["question"].casefold()
        if key not in seen:
            unique.append(suggestion)
            seen.add(key)
    return unique[:3]


def _parse_research_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip()
    for parser in (
        lambda item: _normalize_research_datetime(datetime.fromisoformat(item.replace("Z", "+00:00"))),
        lambda item: datetime.strptime(item, "%B %d, %Y"),
        lambda item: datetime.strptime(item, "%b %d, %Y"),
    ):
        try:
            return parser(text)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_research_datetime(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _serialize_research_datetime(value):
    normalized = _parse_research_date(value)
    return f"{normalized.isoformat()}Z" if normalized else value


def _sort_research_ads(ads, sort_by):
    """Sort source-backed research signals with unknown dates last."""
    if sort_by == "longest_running":
        return sorted(ads, key=lambda ad: (
            ad.platform == "external" or _parse_research_date(ad.start_date) is None,
            _parse_research_date(ad.start_date) or datetime.max,
        ))
    if sort_by == "most_sightings":
        return sorted(ads, key=lambda ad: (ad.seen_count is None, -(ad.seen_count or 0)))
    if sort_by == "multiple_versions":
        return sorted(ads, key=lambda ad: (
            not bool(ad.is_multiple_versions),
            _parse_research_date(ad.last_seen) is None,
            -(_parse_research_date(ad.last_seen).timestamp() if _parse_research_date(ad.last_seen) else 0),
        ))
    return sorted(ads, key=lambda ad: (
        _parse_research_date(ad.last_seen) is None,
        -(_parse_research_date(ad.last_seen).timestamp() if _parse_research_date(ad.last_seen) else 0),
    ))


def _cap_ads_per_advertiser(ads, ads_per_advertiser):
    """Keep a sorted catalog varied without discarding unknown legacy pages."""
    if not ads_per_advertiser:
        return ads
    counts = {}
    limited = []
    for ad in ads:
        advertiser = (ad.brand_name or "").strip().casefold()
        if not advertiser:
            limited.append(ad)
            continue
        count = counts.get(advertiser, 0)
        if count >= ads_per_advertiser:
            continue
        counts[advertiser] = count + 1
        limited.append(ad)
    return limited


def _dedupe_research_creatives(ads):
    """Keep one representative for an identical retained creative.

    Ad Library imports can retain the same page/copy/CTA on more than one
    source row. It is useful as capture provenance, but it makes a working
    library feel like spam. This intentionally dedupes only exact visible
    creative identity after sorting, so a distinct headline or body remains
    available for comparison.
    """
    unique = []
    seen = set()
    for ad in ads:
        identity = tuple((value or "").strip().casefold() for value in (
            ad.brand_name, ad.headline, ad.ad_copy, ad.cta_text, ad.media_type,
        ))
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(ad)
    return unique


def _serialize_scraped_ad(ad, board_item_id=None):
    # _parse_research_date normalizes timezone-aware DB values to naive UTC
    # before arithmetic, matching datetime.utcnow() below.
    start_date = _parse_research_date(ad.start_date)
    last_seen = _parse_research_date(ad.last_seen)
    result = {
        "id": ad.id,
        "brand_name": ad.brand_name,
        "headline": ad.headline,
        "ad_copy": ad.ad_copy,
        "cta_text": ad.cta_text,
        "platform": ad.platform,
        "platforms": ad.platforms,
        "media_type": ad.media_type,
        "media_url": ad.media_url,
        "destination_domain": ad.destination_domain,
        "source_query": ad.source_query,
        "rank_position": ad.rank_position,
        "sort_mode": ad.sort_mode,
        "is_multiple_versions": ad.is_multiple_versions,
        "video_urls": ad.video_urls,
        "thumbnail_url": ad.thumbnail_url,
        "creative_intel": ad.creative_intel,
        "volume_score": ad.volume_score,
        "ad_link": ad.ad_link,
        "start_date": _serialize_research_datetime(ad.start_date),
        "seen_count": ad.seen_count or 1,
        "running_days": max(0, (datetime.utcnow() - start_date).days) if start_date and ad.platform != "external" else None,
        "is_active": bool(last_seen and (datetime.utcnow() - last_seen).days <= 30),
        "angle_tag": ad.angle_tag,
        "hook_type": ad.hook_type,
        "persona": ad.persona,
        "promise": ad.promise,
        "proof_type": ad.proof_type,
        "funnel_stage": ad.funnel_stage,
        "pacing": ad.pacing,
        "numbers_used": ad.numbers_used,
        "creative_tags": ad.creative_tags or [],
        "cta_type": ad.cta_type,
        "page_type": ad.page_type,
        "video_length_seconds": ad.video_length_seconds,
        "media_preview_url": ad.media_preview_url,
        "media_width": ad.media_width,
        "media_height": ad.media_height,
        "taxonomy_source": ad.taxonomy_source,
        "taxonomy_confidence": ad.taxonomy_confidence,
        "is_saved": ad.is_saved,
        "created_at": _serialize_research_datetime(ad.created_at),
        "first_seen": _serialize_research_datetime(ad.first_seen),
        "last_seen": _serialize_research_datetime(ad.last_seen),
    }
    if board_item_id is not None:
        result["board_item_id"] = board_item_id
    return result


def _truncate_text(value: str | None, max_chars: int = MAX_AD_LIBRARY_TEXT_CHARS) -> str | None:
    if value is None:
        return None
    return value[:max_chars]


def _bounded_json(value):
    if value is None:
        return None

    serialized = json.dumps(value)
    if len(serialized) <= MAX_AD_LIBRARY_CREATIVE_INTEL_CHARS:
        return value
    return {
        "truncated": True,
        "summary": "Creative intel exceeded import size limit and was truncated.",
        "original_keys": sorted(value.keys()) if isinstance(value, dict) else None,
    }


def _ad_library_content_hash(
    external_id: str,
    brand_name: str | None,
    headline: str | None,
    ad_copy: str | None,
    cta_text: str | None,
    destination_domain: str | None,
) -> str:
    payload = {
        "source": "ad_library",
        "external_id": external_id,
        "brand_name": (brand_name or "").strip().lower(),
        "headline": (headline or "").strip().lower(),
        "ad_copy": (ad_copy or "").strip().lower(),
        "cta_text": (cta_text or "").strip().lower(),
        "destination_domain": (destination_domain or "").strip().lower(),
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _directional_volume_score(rank_position: int | None, is_multiple_versions: bool | None, start_date: str | None, has_video: bool) -> int:
    score = 0
    if rank_position:
        if rank_position <= 3:
            score += 45
        elif rank_position <= 10:
            score += 35
        elif rank_position <= 25:
            score += 25
        else:
            score += 10
    if is_multiple_versions:
        score += 20
    if has_video:
        score += 10
    if start_date:
        try:
            started = datetime.fromisoformat(start_date.replace("Z", "+00:00").replace("+00:00", ""))
            running_days = max(0, (datetime.utcnow() - started).days)
            if running_days >= 90:
                score += 20
            elif running_days >= 30:
                score += 12
            elif running_days >= 14:
                score += 6
        except Exception:
            pass
    return min(score, 100)

@router.post("/search", response_model=List[ScrapedAdSearchResult])
async def search_ads(request: AdSearchRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Search ads without saving"""
    # Check rate limit (now uses database)
    allowed, remaining, reset_seconds = rate_limiter.check_limit(db)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {reset_seconds} seconds."
        )

    service = ResearchService(db)
    return await service.search_ads_async(request)

@router.post("/search-and-save")
async def search_and_save(request: AdSearchRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Execute search and save as SavedSearch with all ads"""
    # Check rate limit (now uses database)
    allowed, remaining, reset_seconds = rate_limiter.check_limit(db)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {reset_seconds} seconds."
        )

    service = ResearchService(db)
    saved_search, ads = await service.search_and_save(request)
    return {
        "search_id": saved_search.id,
        "query": saved_search.query,
        "country": saved_search.country,
        "ads_count": len(ads),
        # search-and-save is deliberately the query bar's persistence boundary:
        # every ad returned here is already a real ScrapedAd with a stable id.
        "ads": [_serialize_scraped_ad(ad) for ad in ads],
    }

@router.get("/saved-searches", response_model=List[SavedSearchResponse])
def get_saved_searches(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get all saved searches with their ads"""
    service = ResearchService(db)
    return service.get_saved_searches()

@router.get("/saved-searches/{search_id}", response_model=SavedSearchResponse)
def get_saved_search(search_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get single saved search with ads"""
    service = ResearchService(db)
    search = service.get_saved_search_with_ads(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    return search

@router.delete("/saved-searches/{search_id}")
def delete_saved_search(search_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Delete saved search and its ads"""
    service = ResearchService(db)
    if service.delete_saved_search(search_id):
        return {"message": "Search deleted"}
    raise HTTPException(status_code=404, detail="Search not found")

@router.get("/api-usage")
def get_api_usage(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get API usage stats grouped by date"""
    from app.models import ApiUsageLog
    from sqlalchemy import func

    # Get usage grouped by date
    usage = db.query(
        ApiUsageLog.date,
        func.sum(ApiUsageLog.api_calls).label('total_calls'),
        func.sum(ApiUsageLog.ads_returned).label('total_returned'),
        func.sum(ApiUsageLog.ads_saved).label('total_saved'),
        func.count(ApiUsageLog.id).label('search_count')
    ).group_by(ApiUsageLog.date).order_by(ApiUsageLog.date.desc()).all()

    return [
        {
            "date": row.date,
            "total_calls": row.total_calls,
            "total_returned": row.total_returned,
            "total_saved": row.total_saved,
            "search_count": row.search_count
        }
        for row in usage
    ]

@router.get("/blacklist")
def get_blacklist(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get all blacklisted pages"""
    from app.models import PageBlacklist
    pages = db.query(PageBlacklist).order_by(PageBlacklist.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "page_name": p.page_name,
            "reason": p.reason,
            "created_at": p.created_at.isoformat()
        }
        for p in pages
    ]

@router.post("/blacklist")
def add_to_blacklist(page_name: str, reason: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Add page to blacklist"""
    from app.models import PageBlacklist

    # Check if already blacklisted
    existing = db.query(PageBlacklist).filter(PageBlacklist.page_name == page_name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Page already blacklisted")

    blacklist_entry = PageBlacklist(page_name=page_name, reason=reason)
    db.add(blacklist_entry)
    db.commit()
    db.refresh(blacklist_entry)

    return {
        "id": blacklist_entry.id,
        "page_name": blacklist_entry.page_name,
        "reason": blacklist_entry.reason,
        "created_at": blacklist_entry.created_at.isoformat()
    }

@router.delete("/blacklist/{blacklist_id}")
def remove_from_blacklist(blacklist_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Remove page from blacklist"""
    from app.models import PageBlacklist

    entry = db.query(PageBlacklist).filter(PageBlacklist.id == blacklist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Blacklist entry not found")

    db.delete(entry)
    db.commit()
    return {"message": "Removed from blacklist"}

@router.get("/keyword-blacklist")
def get_keyword_blacklist(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get all blacklisted keywords"""
    from app.models import KeywordBlacklist
    keywords = db.query(KeywordBlacklist).order_by(KeywordBlacklist.created_at.desc()).all()
    return [
        {
            "id": k.id,
            "keyword": k.keyword,
            "reason": k.reason,
            "created_at": k.created_at.isoformat()
        }
        for k in keywords
    ]

@router.post("/keyword-blacklist")
def add_to_keyword_blacklist(keyword: str, reason: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Add keyword to blacklist"""
    from app.models import KeywordBlacklist

    # Check if already blacklisted
    existing = db.query(KeywordBlacklist).filter(KeywordBlacklist.keyword == keyword.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Keyword already blacklisted")

    blacklist_entry = KeywordBlacklist(keyword=keyword.lower(), reason=reason)
    db.add(blacklist_entry)
    db.commit()
    db.refresh(blacklist_entry)

    return {
        "id": blacklist_entry.id,
        "keyword": blacklist_entry.keyword,
        "reason": blacklist_entry.reason,
        "created_at": blacklist_entry.created_at.isoformat()
    }

@router.delete("/keyword-blacklist/{blacklist_id}")
def remove_from_keyword_blacklist(blacklist_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Remove keyword from blacklist"""
    from app.models import KeywordBlacklist

    entry = db.query(KeywordBlacklist).filter(KeywordBlacklist.id == blacklist_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Keyword blacklist entry not found")

    db.delete(entry)
    db.commit()
    return {"message": "Removed from keyword blacklist"}

@router.get("/rate-limit")
def get_rate_limit(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get current rate limit usage (trailing 59 minutes)"""
    return rate_limiter.get_usage_stats(db)

@router.get("/facebook-pages")
def get_facebook_pages(
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "total_ads",  # total_ads, page_name, last_seen
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get Facebook pages with ad counts (excludes blacklisted pages)"""
    from app.models import FacebookPage, PageBlacklist
    from sqlalchemy import desc

    # Get blacklisted page names
    blacklisted_pages = db.query(PageBlacklist.page_name).all()
    blacklisted_names = {p.page_name.lower() for p in blacklisted_pages}

    query = db.query(FacebookPage)

    # Sort
    if sort_by == "total_ads":
        query = query.order_by(desc(FacebookPage.total_ads))
    elif sort_by == "page_name":
        query = query.order_by(FacebookPage.page_name)
    elif sort_by == "last_seen":
        query = query.order_by(desc(FacebookPage.last_seen))

    pages = query.offset(offset).limit(limit).all()

    # Filter out blacklisted pages
    filtered_pages = [
        p for p in pages
        if p.page_name.lower() not in blacklisted_names
    ]

    # Get vertical names for display
    from app.models import Vertical
    vertical_map = {v.id: v.name for v in db.query(Vertical).all()}

    return [
        {
            "id": p.id,
            "page_name": p.page_name,
            "page_url": p.page_url,
            "total_ads": p.total_ads,
            "vertical_id": p.vertical_id,
            "vertical_name": vertical_map.get(p.vertical_id) if p.vertical_id else None,
            "first_seen": p.first_seen.isoformat() if p.first_seen else None,
            "last_seen": p.last_seen.isoformat() if p.last_seen else None,
        }
        for p in filtered_pages
    ]

@router.get("/verticals")
def get_verticals(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get all verticals"""
    from app.models import Vertical
    verticals = db.query(Vertical).order_by(Vertical.name).all()
    return [
        {
            "id": v.id,
            "name": v.name,
            "description": v.description,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in verticals
    ]

@router.post("/run-scheduled-searches")
async def run_scheduled_searches(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Manually trigger scheduled searches (called by cron job)"""
    from app.services.scheduler_service import SchedulerService

    scheduler = SchedulerService(db)
    await scheduler.run_scheduled_searches()

    return {"message": "Scheduled searches completed"}

@router.post("/verticals")
def create_vertical(name: str, description: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Create a new vertical"""
    from app.models import Vertical

    # Check if exists
    existing = db.query(Vertical).filter(Vertical.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Vertical already exists")

    vertical = Vertical(name=name, description=description)
    db.add(vertical)
    db.commit()
    db.refresh(vertical)

    return {
        "id": vertical.id,
        "name": vertical.name,
        "description": vertical.description,
        "created_at": vertical.created_at.isoformat() if vertical.created_at else None,
    }

@router.get("/verticals/{vertical_id}/aggregated-ads")
def get_vertical_aggregated_ads(vertical_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get all unique ads for a vertical, grouped by Facebook page with media type counts (excluding blacklisted pages)"""
    try:
        from app.models import ScrapedAd, SavedSearch, FacebookPage, PageBlacklist
        from sqlalchemy import func, distinct, case

        # Get all searches for this vertical
        searches = db.query(SavedSearch).filter(SavedSearch.vertical_id == vertical_id).all()
        search_ids = [s.id for s in searches]

        if not search_ids:
            return []

        # Get blacklisted page names
        blacklisted_pages = db.query(PageBlacklist.page_name).all()
        blacklisted_names = {p.page_name.lower() for p in blacklisted_pages}

        # Get all unique ads for these searches, grouped by page
        # Use COALESCE to fall back to ID when content_hash is NULL
        from sqlalchemy import func as sqlfunc
        unique_key = func.coalesce(ScrapedAd.content_hash, ScrapedAd.id)

        ads_by_page = db.query(
            FacebookPage.page_name,
            FacebookPage.id.label('page_id'),
            func.count(distinct(unique_key)).label('total_ads'),
            func.sum(case((ScrapedAd.media_type == 'image', 1), else_=0)).label('image_count'),
            func.sum(case((ScrapedAd.media_type == 'video', 1), else_=0)).label('video_count'),
            func.sum(case((ScrapedAd.media_type == 'carousel', 1), else_=0)).label('carousel_count')
        ).join(
            ScrapedAd, ScrapedAd.facebook_page_id == FacebookPage.id
        ).filter(
            ScrapedAd.search_id.in_(search_ids)
        ).group_by(
            FacebookPage.id, FacebookPage.page_name
        ).order_by(
            func.count(distinct(unique_key)).desc()
        ).all()

        # Filter out blacklisted pages
        return [
            {
                "page_name": row.page_name,
                "page_id": row.page_id,
                "total_ads": row.total_ads,
                "image_count": row.image_count or 0,
                "video_count": row.video_count or 0,
                "carousel_count": row.carousel_count or 0
            }
            for row in ads_by_page
            if row.page_name.lower() not in blacklisted_names
        ]
    except Exception as e:
        import traceback
        print(f"Error in get_vertical_aggregated_ads: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error fetching aggregated ads: {str(e)}")

@router.get("/verticals/{vertical_id}/pages/{page_id}/ads")
def get_vertical_page_ads(vertical_id: str, page_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get unique ads for a specific Facebook page within a vertical"""
    try:
        from app.models import ScrapedAd, SavedSearch, FacebookPage
        from sqlalchemy import func, distinct

        # Get all searches for this vertical
        searches = db.query(SavedSearch).filter(SavedSearch.vertical_id == vertical_id).all()
        search_ids = [s.id for s in searches]

        if not search_ids:
            return []

        # Get unique ads for this page (deduplicated by content_hash or ID)
        # Use a subquery to get one ad per unique key (content_hash if available, else ID)
        from sqlalchemy.orm import aliased
        from sqlalchemy import tuple_

        # For old ads without content_hash, each ad is unique
        # For new ads with content_hash, deduplicate by hash
        unique_key = func.coalesce(ScrapedAd.content_hash, ScrapedAd.id)

        subq = db.query(
            unique_key.label('unique_key'),
            func.min(ScrapedAd.id).label('min_id')
        ).filter(
            ScrapedAd.facebook_page_id == page_id,
            ScrapedAd.search_id.in_(search_ids)
        ).group_by(unique_key).subquery()

        ads = db.query(ScrapedAd).join(
            subq, ScrapedAd.id == subq.c.min_id
        ).order_by(ScrapedAd.created_at.desc()).all()

        return [
            {
                "id": ad.id,
                "brand_name": ad.brand_name,
                "headline": ad.headline,
                "ad_copy": ad.ad_copy,
                "cta_text": ad.cta_text,
                "media_type": ad.media_type,
                "ad_link": ad.ad_link,
                "start_date": ad.start_date,
                "platforms": ad.platforms,
                "seen_count": ad.seen_count or 1,
                "first_seen": ad.first_seen.isoformat() if ad.first_seen else None,
                "last_seen": ad.last_seen.isoformat() if ad.last_seen else None,
            }
            for ad in ads
        ]
    except Exception as e:
        import traceback
        print(f"Error in get_vertical_page_ads: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error fetching page ads: {str(e)}")


# ============= Brand Scrape Endpoints =============

@router.post("/brand-scrapes", response_model=BrandScrapeListResponse)
async def create_brand_scrape(
    request: BrandScrapeCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create a new brand scrape and start scraping in background."""
    from app.models import BrandScrape
    from app.services.brand_scraper import BrandScraperService, parse_page_id_from_url, parse_search_query_from_url

    # Parse page ID or search query from URL
    page_id = parse_page_id_from_url(request.page_url)
    search_query = parse_search_query_from_url(request.page_url)

    if not page_id and not search_query:
        raise HTTPException(
            status_code=400,
            detail="Invalid URL. Must be a Facebook Ads Library URL with view_all_page_id or q= parameter."
        )

    # Create brand scrape record
    brand_scrape = BrandScrape(
        brand_name=request.brand_name,
        page_id=page_id or search_query,  # Use search query as identifier if no page_id
        page_url=request.page_url,
        status="pending"
    )
    db.add(brand_scrape)
    db.commit()
    db.refresh(brand_scrape)

    # Start scraping in background
    async def run_scrape():
        from app.database import SessionLocal
        scrape_db = SessionLocal()
        try:
            scraper = BrandScraperService(scrape_db)
            scrape_record = scrape_db.query(BrandScrape).filter(BrandScrape.id == brand_scrape.id).first()
            if scrape_record:
                await scraper.scrape_brand(scrape_record)
        except Exception as e:
            print(f"Background scrape error: {e}")
            scrape_record = scrape_db.query(BrandScrape).filter(BrandScrape.id == brand_scrape.id).first()
            if scrape_record:
                scrape_record.status = "failed"
                scrape_record.error_message = str(e)[:500]
                scrape_db.commit()
        finally:
            scrape_db.close()

    background_tasks.add_task(run_scrape)

    return brand_scrape


@router.get("/brand-scrapes", response_model=List[BrandScrapeListResponse])
def get_brand_scrapes(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get all brand scrapes."""
    from app.models import BrandScrape

    scrapes = db.query(BrandScrape).order_by(BrandScrape.created_at.desc()).all()
    return scrapes


@router.get("/brand-scrapes/{scrape_id}", response_model=BrandScrapeResponse)
def get_brand_scrape(scrape_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Get a single brand scrape with all its ads."""
    from app.models import BrandScrape

    scrape = db.query(BrandScrape).filter(BrandScrape.id == scrape_id).first()
    if not scrape:
        raise HTTPException(status_code=404, detail="Brand scrape not found")

    return scrape


@router.post("/brand-scrapes/{scrape_id}/import-research")
def import_brand_scrape_into_research(
    scrape_id: str,
    vertical: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Promote our own R2-backed Brand Scrape media into Research.

    This is intentionally limited to media captured by our Meta scraper. It
    does not download or copy third-party research-platform assets.
    """
    from app.models import BrandScrape, FacebookPage, SavedSearch, ScrapedAd, Vertical

    scrape = db.query(BrandScrape).filter(BrandScrape.id == scrape_id).first()
    if not scrape:
        raise HTTPException(status_code=404, detail="Brand scrape not found")
    if scrape.status != "completed":
        raise HTTPException(status_code=400, detail="Wait for this Brand Scrape to complete before importing it")
    vertical_name = vertical.strip()
    if not vertical_name:
        raise HTTPException(status_code=400, detail="A Research vertical is required")
    target_vertical = db.query(Vertical).filter(Vertical.name == vertical_name).first()
    if not target_vertical:
        target_vertical = Vertical(name=vertical_name, description="R2-backed Meta Brand Scrape research")
        db.add(target_vertical)
        db.flush()
    saved_search = SavedSearch(
        query=scrape.brand_name,
        country="US",
        vertical_id=target_vertical.id,
        search_type="brand_scrape_import",
        schedule_config={"source": "brand_scrape", "brand_scrape_id": scrape.id, "page_url": scrape.page_url},
        is_active=False,
        last_run=datetime.utcnow(),
        ads_requested=len(scrape.ads),
        ads_returned=len(scrape.ads),
        ads_new=0,
        ads_duplicate=0,
    )
    db.add(saved_search)
    db.flush()
    imported = updated = with_visual = 0
    for captured in scrape.ads:
        external_id = captured.external_id.strip() if captured.external_id else f"brand-scrape:{scrape.id}:{captured.id}"
        ad = db.query(ScrapedAd).filter(ScrapedAd.external_id == external_id).first()
        if ad:
            updated += 1
            ad.last_seen = datetime.utcnow()
            ad.seen_count = (ad.seen_count or 0) + 1
        else:
            imported += 1
            ad = ScrapedAd(external_id=external_id, ad_link=captured.ad_link or scrape.page_url)
            db.add(ad)
        page_name = captured.page_name or scrape.page_name or scrape.brand_name
        page = db.query(FacebookPage).filter(FacebookPage.page_name == page_name).first()
        if not page:
            page = FacebookPage(page_name=page_name, page_url=captured.page_link or scrape.page_url, vertical_id=target_vertical.id)
            db.add(page)
            db.flush()
        media_urls = [url for url in (captured.media_urls or []) if _normalize_external_url(url)]
        primary_media = media_urls[0] if media_urls else None
        creative_tags, inferred_cta_type = _infer_creative_taxonomy(captured.headline, captured.ad_copy, captured.cta_text)
        ad.brand_name = page_name
        ad.headline = _truncate_text(captured.headline)
        ad.ad_copy = _truncate_text(captured.ad_copy)
        ad.cta_text = captured.cta_text
        ad.platform = "facebook"
        ad.ad_link = captured.ad_link or scrape.page_url
        ad.platforms = captured.platforms
        ad.start_date = captured.start_date
        ad.media_type = captured.media_type
        ad.media_url = primary_media
        ad.thumbnail_url = primary_media if captured.media_type != "video" else ad.thumbnail_url
        ad.media_preview_url = primary_media if captured.media_type == "video" else ad.media_preview_url
        ad.video_urls = media_urls if captured.media_type == "video" else ad.video_urls
        ad.source_query = f"brand-scrape:{scrape.id}"
        ad.search_id = saved_search.id
        ad.facebook_page_id = page.id
        ad.creative_tags = creative_tags
        ad.cta_type = inferred_cta_type
        ad.taxonomy_source = "brand_scrape" if creative_tags else None
        ad.creative_intel = _bounded_json({**dict(ad.creative_intel or {}), "capture_source": "brand_scrape", "brand_scrape_id": scrape.id, "media_provenance": "BHM R2 Meta capture"})
        if primary_media:
            with_visual += 1
    saved_search.ads_new = imported
    saved_search.ads_duplicate = updated
    db.commit()
    return {"scrape_id": scrape.id, "vertical": target_vertical.name, "imported": imported, "updated": updated, "with_visual": with_visual}


@router.delete("/brand-scrapes/{scrape_id}")
async def delete_brand_scrape(scrape_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Delete a brand scrape and its media from R2."""
    from app.models import BrandScrape
    from app.services.brand_scraper import BrandScraperService

    scrape = db.query(BrandScrape).filter(BrandScrape.id == scrape_id).first()
    if not scrape:
        raise HTTPException(status_code=404, detail="Brand scrape not found")

    scraper = BrandScraperService(db)
    success = await scraper.delete_brand_scrape(scrape)

    if success:
        return {"message": "Brand scrape deleted"}
    raise HTTPException(status_code=500, detail="Failed to delete brand scrape")


@router.delete("/scraped-ads/{ad_id}/save")
def unsave_scraped_ad(ad_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Remove a scraped ad from the user's curated research library."""
    from app.models import ScrapedAd
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    ad.is_saved = False
    db.commit()
    return {"id": ad_id, "is_saved": False}


@router.get("/scraped-ads/saved")
def get_saved_ads(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Return all scraped ads the user has saved to their research library."""
    from app.models import ScrapedAd
    ads = db.query(ScrapedAd).filter(ScrapedAd.is_saved == True).order_by(ScrapedAd.created_at.desc()).all()
    return [_serialize_scraped_ad(ad) for ad in ads]


# ============= Shared research boards =============

@router.get("/boards", response_model=List[ResearchBoardResponse])
def get_research_boards(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """List workspace-shared boards with their current item counts."""
    from app.models import ResearchBoard, ResearchBoardItem
    from sqlalchemy import func

    rows = (
        db.query(ResearchBoard, func.count(ResearchBoardItem.id).label("item_count"))
        .outerjoin(ResearchBoardItem, ResearchBoardItem.board_id == ResearchBoard.id)
        .group_by(ResearchBoard.id)
        .order_by(ResearchBoard.updated_at.desc(), ResearchBoard.created_at.desc())
        .all()
    )
    return [
        {
            "id": board.id,
            "name": board.name,
            "vertical_id": board.vertical_id,
            "created_by": board.created_by,
            "created_at": board.created_at,
            "updated_at": board.updated_at,
            "item_count": item_count,
        }
        for board, item_count in rows
    ]


@router.post("/boards", response_model=ResearchBoardResponse, status_code=201)
def create_research_board(
    request: ResearchBoardCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.models import ResearchBoard

    board = ResearchBoard(
        name=request.name.strip(),
        vertical_id=request.vertical_id,
        created_by=current_user.id,
    )
    db.add(board)
    db.commit()
    db.refresh(board)
    return {
        "id": board.id,
        "name": board.name,
        "vertical_id": board.vertical_id,
        "created_by": board.created_by,
        "created_at": board.created_at,
        "updated_at": board.updated_at,
        "item_count": 0,
    }


@router.delete("/boards/{board_id}")
def delete_research_board(board_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    from app.models import ResearchBoard

    board = db.query(ResearchBoard).filter(ResearchBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Research board not found")
    db.delete(board)
    db.commit()
    return {"message": "Research board deleted"}


@router.post("/boards/{board_id}/items", response_model=ResearchBoardItemResponse)
def add_research_board_item(
    board_id: str,
    request: ResearchBoardItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.models import ResearchBoard, ResearchBoardItem, ScrapedAd

    board = db.query(ResearchBoard).filter(ResearchBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Research board not found")
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == request.scraped_ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")

    existing = db.query(ResearchBoardItem).filter(
        ResearchBoardItem.board_id == board_id,
        ResearchBoardItem.scraped_ad_id == request.scraped_ad_id,
    ).first()
    if existing:
        return {**_serialize_scraped_ad(ad, existing.id)}

    item = ResearchBoardItem(board_id=board_id, scraped_ad_id=ad.id)
    db.add(item)
    try:
        db.commit()
        db.refresh(item)
    except IntegrityError:
        # The DB constraint is the concurrency guarantee; a second request
        # racing the pre-check is a successful no-op, not a 500.
        db.rollback()
        item = db.query(ResearchBoardItem).filter(
            ResearchBoardItem.board_id == board_id,
            ResearchBoardItem.scraped_ad_id == ad.id,
        ).first()
        if not item:
            raise
    return {**_serialize_scraped_ad(ad, item.id)}


@router.delete("/boards/{board_id}/items/{item_id}")
def delete_research_board_item(
    board_id: str,
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.models import ResearchBoardItem

    item = db.query(ResearchBoardItem).filter(
        ResearchBoardItem.id == item_id,
        ResearchBoardItem.board_id == board_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Board item not found")
    db.delete(item)
    db.commit()
    return {"message": "Ad removed from research board"}


@router.get("/boards/{board_id}/items", response_model=List[ResearchBoardItemResponse])
def get_research_board_items(
    board_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.models import ResearchBoard, ResearchBoardItem
    from sqlalchemy.orm import contains_eager

    if not db.query(ResearchBoard.id).filter(ResearchBoard.id == board_id).first():
        raise HTTPException(status_code=404, detail="Research board not found")
    # .join() alone only affects the SQL WHERE/JOIN — it does not populate the
    # ORM relationship, so `item.scraped_ad` below would otherwise issue one
    # extra SELECT per item (N+1), which scales badly for exactly the
    # many-ads-per-board case this feature exists for (code-auditor pre-push
    # review, MEDIUM). contains_eager tells the ORM to hydrate `scraped_ad`
    # from the same joined query instead of lazy-loading it per row.
    items = db.query(ResearchBoardItem).join(ResearchBoardItem.scraped_ad).options(
        contains_eager(ResearchBoardItem.scraped_ad)
    ).filter(
        ResearchBoardItem.board_id == board_id,
    ).order_by(
        ResearchBoardItem.sort_order.asc(), ResearchBoardItem.created_at.desc()
    ).all()
    return [_serialize_scraped_ad(item.scraped_ad, item.id) for item in items]


# ============= Pre-configured Vertical Endpoints =============

@router.get("/vertical-config")
def get_vertical_config(current_user: User = Depends(get_current_active_user)):
    """Return pre-configured keyword sets for each research vertical.

    Frontend reads this on mount so keyword sets are never hardcoded in JS.
    Includes angle tag definitions.
    """
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS, ANGLE_TAGS
    return {
        "verticals": VERTICAL_KEYWORD_SETS,
        "angle_tags": ANGLE_TAGS,
    }


@router.post("/ad-library-import")
def import_ad_library_capture(
    request: AdLibraryImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Import Chrome-captured Ad Library intel into the Research library.

    This is intentionally separate from the official Ad Library API path. It
    stores rendered-card observations from a US, active, most-impressions
    browser search so Joel/Saule can save competitor examples for creative
    inspiration and video-agent training.
    """
    from app.models import ScrapedAd, SavedSearch, Vertical, FacebookPage

    if not request.ads:
        raise HTTPException(status_code=400, detail="No ads provided")
    if len(request.ads) > MAX_AD_LIBRARY_IMPORT_ADS:
        raise HTTPException(
            status_code=400,
            detail=f"Import is capped at {MAX_AD_LIBRARY_IMPORT_ADS} ads. Paste a smaller capture batch.",
        )

    vertical = db.query(Vertical).filter(Vertical.name == request.vertical).first()
    if not vertical:
        vertical = Vertical(name=request.vertical, description="Imported from Chrome-rendered Facebook Ad Library captures")
        db.add(vertical)
        db.flush()

    saved_search = SavedSearch(
        query=request.query,
        country=request.country,
        vertical_id=vertical.id,
        search_type="chrome_ad_library_import",
        schedule_config={
            "source": "chrome",
            "sort_mode": request.sort_mode,
            "source_url": request.source_url,
        },
        is_active=False,
        last_run=datetime.utcnow(),
        ads_requested=len(request.ads),
        ads_returned=len(request.ads),
        ads_new=0,
        ads_duplicate=0,
    )
    db.add(saved_search)
    db.flush()

    imported = 0
    updated = 0
    skipped = 0
    page_counts: dict[str, int] = {}
    with_media = 0
    with_video = 0
    multiple_versions = 0

    for incoming in request.ads:
        external_id = incoming.library_id.strip()
        if not external_id:
            skipped += 1
            continue

        video_urls = (incoming.video_urls or [])[:MAX_AD_LIBRARY_VIDEO_URLS]
        # Preserve unknown media format instead of silently classifying every
        # non-video capture as an image. A missing source value is not evidence.
        media_type = incoming.media_type or ("video" if video_urls else None)
        has_media = bool(incoming.media_url or incoming.thumbnail_url or video_urls)
        if has_media:
            with_media += 1
        if media_type == "video" or video_urls:
            with_video += 1
        if incoming.is_multiple_versions:
            multiple_versions += 1
        volume_score = _directional_volume_score(
            incoming.rank_position,
            incoming.is_multiple_versions,
            incoming.start_date,
            media_type == "video" or bool(video_urls),
        )
        creative_intel = dict(incoming.creative_intel or {})
        creative_tags, inferred_cta_type = _infer_creative_taxonomy(
            incoming.headline, incoming.ad_copy, incoming.cta_text, incoming.creative_tags,
        )
        creative_intel.update(
            {
                "capture_source": "chrome_ad_library",
                "source_query": request.query,
                "country": request.country,
                "sort_mode": request.sort_mode,
                "source_url": request.source_url,
                "volume_score_method": "rank + multiple_versions + active_age + video_presence; directional only",
                "imported_by_user_id": current_user.id,
            }
        )
        creative_intel = _bounded_json(creative_intel)

        fb_page = None
        if incoming.brand_name:
            fb_page = db.query(FacebookPage).filter(FacebookPage.page_name == incoming.brand_name).first()
            if not fb_page:
                fb_page = FacebookPage(page_name=incoming.brand_name, total_ads=0, vertical_id=vertical.id)
                db.add(fb_page)
                db.flush()
            page_counts[incoming.brand_name] = page_counts.get(incoming.brand_name, 0) + 1

        ad = db.query(ScrapedAd).filter(ScrapedAd.external_id == external_id).first()
        if ad:
            updated += 1
            ad.last_seen = datetime.utcnow()
            ad.seen_count = (ad.seen_count or 0) + 1
        else:
            imported += 1
            ad = ScrapedAd(
                external_id=external_id,
                ad_link=incoming.ad_link or f"https://www.facebook.com/ads/library/?id={external_id}",
                content_hash=_ad_library_content_hash(
                    external_id,
                    incoming.brand_name,
                    _truncate_text(incoming.headline),
                    _truncate_text(incoming.ad_copy),
                    incoming.cta_text,
                    incoming.destination_domain,
                ),
                search_id=saved_search.id,
            )
            db.add(ad)

        ad.brand_name = incoming.brand_name
        ad.headline = _truncate_text(incoming.headline)
        ad.ad_copy = _truncate_text(incoming.ad_copy)
        ad.cta_text = incoming.cta_text
        ad.platform = "facebook"
        ad.platforms = incoming.platforms
        ad.start_date = incoming.start_date
        ad.media_type = media_type
        ad.media_url = incoming.media_url or incoming.thumbnail_url
        ad.destination_domain = incoming.destination_domain
        ad.source_query = request.query
        ad.rank_position = incoming.rank_position
        ad.sort_mode = request.sort_mode
        ad.is_multiple_versions = bool(incoming.is_multiple_versions)
        ad.video_urls = video_urls or None
        ad.thumbnail_url = incoming.thumbnail_url or incoming.media_url
        ad.creative_intel = creative_intel
        ad.volume_score = volume_score
        ad.creative_tags = creative_tags
        ad.cta_type = incoming.cta_type or inferred_cta_type
        ad.page_type = incoming.page_type
        ad.video_length_seconds = incoming.video_length_seconds
        ad.media_preview_url = incoming.media_preview_url or (video_urls[0] if video_urls else None)
        ad.media_width = incoming.media_width
        ad.media_height = incoming.media_height
        rules_matched = bool(creative_tags) or bool(inferred_cta_type and inferred_cta_type != "unknown")
        ad.taxonomy_source = "capture" if incoming.creative_tags or incoming.cta_type else ("rules_v1" if rules_matched else None)
        ad.taxonomy_confidence = "source" if incoming.creative_tags or incoming.cta_type else ("low" if rules_matched else None)
        ad.search_id = saved_search.id
        if fb_page:
            ad.facebook_page_id = fb_page.id

    saved_search.ads_new = imported
    saved_search.ads_duplicate = updated

    db.flush()
    for page_name in page_counts:
        page = db.query(FacebookPage).filter(FacebookPage.page_name == page_name).first()
        if page:
            page.total_ads = db.query(ScrapedAd).filter(ScrapedAd.facebook_page_id == page.id).count()
            page.last_seen = datetime.utcnow()

    db.commit()

    return {
        "search_id": saved_search.id,
        "query": request.query,
        "vertical": request.vertical,
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "total": imported + updated,
        "quality": {
            "with_media": with_media,
            "with_video": with_video,
            "multiple_versions": multiple_versions,
            "unmapped_video_inventory": max(
                [
                    (ad.creative_intel or {}).get("unmapped_video_inventory_count", 0)
                    for ad in request.ads
                ] or [0]
            ),
        },
        "message": f"Imported {imported} new ads, updated {updated} existing ads",
    }


@router.post("/external-import")
def import_external_research(
    request: ExternalResearchImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Import reviewed competitor rows from a transient external research source.

    Signals from a vendor are kept as source context only. They are never
    converted into BHM spend, impression, conversion, or profit claims.
    """
    from app.models import ScrapedAd, SavedSearch, Vertical, FacebookPage

    vertical_label = _resolve_external_import_vertical(request.vertical)
    if not vertical_label:
        raise HTTPException(
            status_code=422,
            detail="vertical must match a configured Research vertical or Home Services sub-vertical",
        )

    source_url = _normalize_external_url(request.source_url)
    missing_source_rows = [index + 1 for index, ad in enumerate(request.ads) if not (ad.landing_url or source_url)]
    if missing_source_rows:
        raise HTTPException(
            status_code=422,
            detail=f"Each row needs landing_url when source_url is omitted (rows: {missing_source_rows})",
        )

    vertical = db.query(Vertical).filter(Vertical.name == vertical_label).first()
    if not vertical:
        vertical = Vertical(name=vertical_label, description="Imported external competitor research")
        db.add(vertical)
        db.flush()

    saved_search = SavedSearch(
        query=request.query,
        country="US",
        vertical_id=vertical.id,
        search_type="external_research_import",
        schedule_config={"source": request.source, "source_url": source_url or None},
        is_active=False,
        last_run=datetime.utcnow(),
        ads_requested=len(request.ads),
        ads_returned=len(request.ads),
        ads_new=0,
        ads_duplicate=0,
    )
    db.add(saved_search)
    db.flush()

    imported = updated = 0
    page_counts: dict[str, int] = {}
    source_key = request.source.strip().casefold()

    for incoming in request.ads:
        landing_url = _normalize_external_url(incoming.landing_url)
        normalized = "|".join([
            source_key, incoming.external_id or "", incoming.brand_name.strip().casefold(),
            (incoming.headline or "").strip().casefold(), (incoming.primary_text or "").strip().casefold(), landing_url.casefold(),
        ])
        external_id = incoming.external_id or f"external:{hashlib.sha256(normalized.encode()).hexdigest()[:32]}"
        destination_domain = _external_destination_domain(landing_url)
        creative_tags, inferred_cta_type = _infer_creative_taxonomy(
            incoming.headline, incoming.primary_text, incoming.cta, incoming.creative_tags,
        )
        fb_page = db.query(FacebookPage).filter(FacebookPage.page_name == incoming.brand_name).first()
        if not fb_page:
            fb_page = FacebookPage(page_name=incoming.brand_name, total_ads=0, vertical_id=vertical.id)
            db.add(fb_page)
            db.flush()
        page_counts[incoming.brand_name] = page_counts.get(incoming.brand_name, 0) + 1

        ad = db.query(ScrapedAd).filter(ScrapedAd.external_id == external_id).first()
        if ad:
            updated += 1
            ad.last_seen = datetime.utcnow()
            ad.seen_count = (ad.seen_count or 0) + 1
        else:
            imported += 1
            ad = ScrapedAd(
                external_id=external_id,
                ad_link=landing_url or source_url,
                content_hash=hashlib.sha256(normalized.encode()).hexdigest(),
                search_id=saved_search.id,
            )
            db.add(ad)

        ad.brand_name = incoming.brand_name.strip()
        ad.headline = _truncate_text(incoming.headline)
        ad.ad_copy = _truncate_text(incoming.primary_text)
        ad.cta_text = incoming.cta
        ad.platform = "external"
        # A vendor's first-seen date is provenance, not an independently
        # verified Meta start date. Never use it for runtime or ranking.
        ad.start_date = None
        ad.media_type = incoming.format.lower().strip() if incoming.format else None
        ad.destination_domain = destination_domain
        ad.source_query = request.query
        ad.creative_intel = _bounded_json({
            "capture_source": "external_research_import",
            "research_source": request.source.strip(),
            "source_url": source_url or None,
            "source_signal": incoming.source_signal,
            "source_first_seen": incoming.first_seen,
            "segment": incoming.segment,
            "imported_by_user_id": current_user.id,
            "signal_disclaimer": "Directional source context; not verified BHM performance.",
        })
        ad.creative_tags = creative_tags
        ad.cta_type = inferred_cta_type
        ad.taxonomy_source = "external_import" if incoming.creative_tags else ("rules_v1" if creative_tags else None)
        ad.taxonomy_confidence = "source" if incoming.creative_tags else ("low" if creative_tags else None)
        ad.search_id = saved_search.id
        ad.facebook_page_id = fb_page.id

    saved_search.ads_new = imported
    saved_search.ads_duplicate = updated
    db.flush()
    for page_name in page_counts:
        page = db.query(FacebookPage).filter(FacebookPage.page_name == page_name).first()
        if page:
            page.total_ads = db.query(ScrapedAd).filter(ScrapedAd.facebook_page_id == page.id).count()
            page.last_seen = datetime.utcnow()
    db.commit()
    return {
        "search_id": saved_search.id,
        "source": request.source,
        "vertical": vertical_label,
        "imported": imported,
        "updated": updated,
        "total": imported + updated,
        "message": f"Imported {imported} new external research rows, updated {updated} existing rows",
    }


@router.post("/scraped-ads/{ad_id}/save")
def save_scraped_ad_with_angle(
    ad_id: str,
    angle_tag: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Mark a scraped ad as saved and optionally assign an angle tag."""
    from app.models import ScrapedAd
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    ad.is_saved = True
    if angle_tag is not None:
        ad.angle_tag = angle_tag
    db.commit()
    return {"id": ad_id, "is_saved": True, "angle_tag": ad.angle_tag}


@router.patch("/scraped-ads/{ad_id}/angle")
def update_angle_tag(
    ad_id: str,
    angle_tag: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update the angle tag on a scraped ad (can also clear it by passing null)."""
    from app.models import ScrapedAd
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    ad.angle_tag = angle_tag
    db.commit()
    return {"id": ad_id, "angle_tag": ad.angle_tag}


@router.patch("/scraped-ads/{ad_id}/strategy-notes")
def update_strategy_notes(
    ad_id: str,
    notes: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Partially update the free-text strategy notes for a scraped ad."""
    from app.models import ScrapedAd
    allowed = {'hook_type', 'persona', 'promise', 'proof_type', 'funnel_stage', 'pacing', 'numbers_used'}
    unknown = set(notes) - allowed
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown strategy note field(s): {sorted(unknown)}")
    # A non-string, non-null value (e.g. {"hook_type": 123}) would otherwise
    # silently coerce to None below instead of erroring — cheap hardening,
    # not currently reachable from the UI (code-auditor pre-push review, LOW).
    invalid = {k: v for k, v in notes.items() if v is not None and not isinstance(v, str)}
    if invalid:
        raise HTTPException(status_code=400, detail=f"Strategy note fields must be strings or null: {sorted(invalid)}")
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    for field in allowed & set(notes):
        value = notes[field]
        setattr(ad, field, value.strip() if isinstance(value, str) and value.strip() else None)
    db.commit()
    return {"id": ad_id, **{field: getattr(ad, field) for field in allowed}}


@router.patch("/scraped-ads/{ad_id}/media")
def attach_research_media(
    ad_id: str,
    attachment: ResearchMediaAttachment,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Attach operator-provided, durable visual research to a captured ad.

    The browser uploads the file through the authenticated R2 upload endpoint
    first; this route only links that resulting URL to the finding. It never
    downloads or copies third-party vendor media.
    """
    from app.models import ScrapedAd
    url = _normalize_external_url(attachment.url)
    if not url:
        raise HTTPException(status_code=400, detail="A valid image or video URL is required")
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    ad.media_type = attachment.media_type
    ad.media_url = url
    ad.thumbnail_url = url if attachment.media_type == "image" else ad.thumbnail_url
    ad.media_preview_url = url if attachment.media_type == "video" else ad.media_preview_url
    db.commit()
    return {
        "id": ad.id,
        "media_type": ad.media_type,
        "media_url": ad.media_url,
        "thumbnail_url": ad.thumbnail_url,
        "media_preview_url": ad.media_preview_url,
    }


@router.get("/scraped-ads/{ad_id}/visual-candidates")
def get_research_visual_candidates(
    ad_id: str,
    limit: int = 8,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return only this app's retained Meta captures that can be attached safely.

    External research rows deliberately do not carry vendor media.  This is the
    explicit bridge to a matching BHM-owned Brand Scrape capture; it never
    copies an image or video from a third-party research platform.
    """
    from app.models import ScrapedAd

    source = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Ad not found")
    normalized_brand = (source.brand_name or "").strip().lower()
    if not normalized_brand:
        return []
    candidates = (
        db.query(ScrapedAd)
        .filter(ScrapedAd.id != source.id)
        # Meta page labels occasionally arrive with invisible surrounding
        # whitespace; normalize both sides before enforcing the advertiser
        # boundary so those captures remain available for deliberate review.
        .filter(func.lower(func.trim(ScrapedAd.brand_name)) == normalized_brand)
        .filter(ScrapedAd.media_url.isnot(None))
        .order_by(ScrapedAd.last_seen.desc())
        .limit(100)
        .all()
    )
    safe_candidates = []
    for candidate in candidates:
        candidate_intel = candidate.creative_intel or {}
        if candidate_intel.get("capture_source") != "brand_scrape" and candidate.taxonomy_source != "brand_scrape":
            continue
        # This is an operator-selected association, not an automatic match.
        # An exact advertiser match plus BHM-owned capture provenance is the
        # durable safety boundary; saved-search vertical ids have historically
        # been duplicated during imports and are not reliable enough to hide
        # a legitimate same-brand visual from review.
        safe_candidates.append(_serialize_scraped_ad(candidate))
        if len(safe_candidates) >= max(1, min(limit, 12)):
            break
    return safe_candidates


@router.post("/scraped-ads/{ad_id}/adopt-visual")
def adopt_retained_research_visual(
    ad_id: str,
    source_ad_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Attach an explicitly selected, BHM-owned Brand Scrape visual to a finding."""
    from app.models import ScrapedAd

    target = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    source = db.query(ScrapedAd).filter(ScrapedAd.id == source_ad_id).first()
    if not target or not source:
        raise HTTPException(status_code=404, detail="Research capture not found")
    if not source.media_url or ((source.creative_intel or {}).get("capture_source") != "brand_scrape" and source.taxonomy_source != "brand_scrape"):
        raise HTTPException(status_code=400, detail="Select a retained Brand Scrape visual")
    if (target.brand_name or "").strip().lower() != (source.brand_name or "").strip().lower():
        raise HTTPException(status_code=400, detail="Visual must come from the same advertiser")
    target.media_type = source.media_type if source.media_type in {"image", "video"} else "image"
    target.media_url = source.media_url
    target.thumbnail_url = source.thumbnail_url or (source.media_url if target.media_type == "image" else None)
    target.media_preview_url = source.media_preview_url or (source.media_url if target.media_type == "video" else None)
    target.video_urls = source.video_urls if target.media_type == "video" else target.video_urls
    intel = dict(target.creative_intel or {})
    intel.update({
        "visual_source_ad_id": source.id,
        "media_provenance": "BHM R2 Meta capture",
        "visual_attachment": "operator-selected retained Brand Scrape capture",
    })
    target.creative_intel = _bounded_json(intel)
    db.commit()
    return _serialize_scraped_ad(target)


@router.patch("/scraped-ads/{ad_id}/reviewed")
def set_research_reviewed(ad_id: str, reviewed: bool, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Curate a raw capture into (or out of) the analyst-facing Brief."""
    from app.models import ScrapedAd
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    intel = dict(ad.creative_intel or {})
    intel["reviewed"] = reviewed
    ad.creative_intel = intel
    db.commit()
    return {"id": ad.id, "creative_intel": ad.creative_intel}


@router.patch("/scraped-ads/{ad_id}/brief")
def update_research_brief_curation(
    ad_id: str,
    curation: ResearchBriefCuration,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Persist BHM's own takeaway and priority without altering source data."""
    from app.models import ScrapedAd
    ad = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    updates = curation.model_dump(exclude_unset=True)
    intel = dict(ad.creative_intel or {})
    if "pinned" in updates:
        intel["pinned"] = bool(updates["pinned"])
    if "bhm_takeaway" in updates:
        takeaway = (updates["bhm_takeaway"] or "").strip()
        if takeaway:
            intel["bhm_takeaway"] = takeaway
        else:
            intel.pop("bhm_takeaway", None)
    ad.creative_intel = intel
    db.commit()
    return {"id": ad.id, "creative_intel": ad.creative_intel}


@router.get("/scraped-ads/{ad_id}/related")
def get_related_research_ads(
    ad_id: str,
    limit: int = 6,
    vertical_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return explainable related patterns, never a fabricated performance rank."""
    from app.models import PageBlacklist, SavedSearch, ScrapedAd, Vertical
    from app.core.vertical_config import ALWAYS_BLOCKED_PAGES, VERTICAL_KEYWORD_SETS
    from sqlalchemy.orm import joinedload
    source = db.query(ScrapedAd).filter(ScrapedAd.id == ad_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Ad not found")
    source_vertical_id = getattr(source.saved_search, "vertical_id", None)
    # Bounded to the most recently seen rows so this stays cheap regardless of
    # how large scraped_ads grows — a full-table scan here (as an earlier
    # version of this endpoint did) is the exact query pattern already
    # flagged as a scaling risk elsewhere in this file.
    configured_vertical_name = _configured_vertical_label(vertical_id)
    candidates = (
        db.query(ScrapedAd)
        .options(joinedload(ScrapedAd.saved_search).joinedload(SavedSearch.vertical))
        .filter(ScrapedAd.id != source.id)
        .order_by(ScrapedAd.last_seen.desc())
        .limit(500)
        .all()
    )
    scored = []
    for candidate in candidates:
        # A reviewed external-source capture and a raw Meta capture have
        # different provenance. Do not present them as related solely from
        # generic metadata; analysts can still compare them deliberately in
        # the library.
        if source.platform == "external" and candidate.platform != "external":
            continue
        candidate_vertical_id = getattr(candidate.saved_search, "vertical_id", None)
        # Prefer an exact saved-search vertical match when both records have
        # one. This is stronger than a shared human-readable label and keeps
        # legacy imports from crossing between verticals.
        if source_vertical_id and candidate_vertical_id and candidate_vertical_id != source_vertical_id:
            continue
        candidate_vertical_name = getattr(getattr(candidate.saved_search, "vertical", None), "name", None)
        # Imported/captured records carry a persisted Vertical through their
        # SavedSearch. That is stronger than keyword inference and keeps an
        # auto-insurance record out of a commercial review even if it shares
        # a generic creative tag such as comparison.
        if configured_vertical_name and candidate_vertical_name and candidate_vertical_name != configured_vertical_name:
            continue
        # Related metadata is useful only when it belongs to the analyst's
        # current vertical. Without this guard, a shared CTA/video format can
        # lead a commercial-insurance review toward an auto-insurance ad.
        if vertical_id and not _matches_research_vertical(candidate, vertical_id):
            continue
        match = _related_pattern_score(source, candidate)
        if not match:
            continue
        score, reasons = match
        scored.append((score, candidate, reasons))
    scored.sort(key=lambda item: (-item[0], _parse_research_date(item[1].last_seen) or datetime.min))
    return [{**_serialize_scraped_ad(ad), "match_reasons": reasons} for _, ad, reasons in scored[:max(1, min(limit, 12))]]


@router.post("/copilot/query")
def query_research_copilot(
    payload: ResearchCopilotQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Answer a natural-language research question from BHM's retained catalog.

    This is deliberately read-only and uses only observable catalog signals.
    It does not call a model, scrape Meta, or represent source proxies as
    performance data.
    """
    from app.models import PageBlacklist, ScrapedAd, SavedSearch, Vertical
    from app.core.vertical_config import ALWAYS_BLOCKED_PAGES, VERTICAL_KEYWORD_SETS
    from sqlalchemy.orm import joinedload

    vertical_label = _configured_vertical_label(payload.vertical_id)
    if not vertical_label:
        raise HTTPException(status_code=400, detail="Choose a supported Research vertical")
    plan = _plan_research_copilot_question(payload.question, payload.vertical_id)
    now = datetime.utcnow()
    # The Copilot must search exactly the same eligible corpus that its
    # visible Ad Library represents. A wider ScrapedAd query can include
    # duplicate/off-topic legacy captures and makes the coverage count lie.
    config = VERTICAL_KEYWORD_SETS[payload.vertical_id]
    vertical_labels = [config["label"]]
    if payload.vertical_id == "home_services":
        vertical_labels = [item["label"] for item in config.get("sub_verticals", {}).values()]
    vertical_ids = [row.id for row in db.query(Vertical.id).filter(Vertical.name.in_(vertical_labels)).all()]
    search_ids = [row.id for row in db.query(SavedSearch.id).filter(SavedSearch.vertical_id.in_(vertical_ids)).all()]
    performance_limitation = (
        "This question asks about performance, but the retained catalog has no verified spend, "
        "impressions, ROAS, conversion, or delivery data. Results below are matching research "
        "examples—not a performance ranking."
    )
    if not search_ids:
        return {
            "question": payload.question.strip(),
            "query_plan": {**plan, "vertical": vertical_label},
            "coverage": {"matched": 0, "returned": 0, "catalog_candidates": 0, "sufficient": False, "live_capture_recommended": True},
            "suggestions": _copilot_query_suggestions(payload.question, plan, vertical_label),
            "results": [],
            "limitations": [
                "No retained captures are available for this Research vertical yet.",
                performance_limitation if plan["performance_intent"] else "Results are ordered by research relevance and catalog evidence, not Meta spend, ROAS, conversions, or delivery performance.",
            ],
        }
    blacklisted_names = {row.page_name.casefold() for row in db.query(PageBlacklist.page_name).all()} | {item.casefold() for item in ALWAYS_BLOCKED_PAGES}
    candidates = (
        db.query(ScrapedAd)
        .options(joinedload(ScrapedAd.saved_search).joinedload(SavedSearch.vertical))
        .filter(ScrapedAd.search_id.in_(search_ids))
        .order_by(ScrapedAd.last_seen.desc())
        .limit(750)
        .all()
    )
    eligible_candidates = []
    seen_keys = set()
    for ad in candidates:
        unique_key = ad.content_hash or ad.id
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        if ad.brand_name and ad.brand_name.casefold() in blacklisted_names:
            continue
        candidate_vertical = getattr(getattr(ad.saved_search, "vertical", None), "name", None)
        if candidate_vertical and candidate_vertical != vertical_label:
            continue
        if not _matches_research_vertical(ad, payload.vertical_id):
            continue
        eligible_candidates.append(ad)

    # The plan's coverage denominator must match the visible Ad Library, which
    # removes repeated visible creatives in addition to row-level content-hash
    # duplicates. Otherwise a copilot answer can claim it searched more
    # evidence than an operator can actually inspect.
    eligible_candidates = _dedupe_research_creatives(eligible_candidates)
    vertical_candidates = len(eligible_candidates)
    scored = []
    for ad in eligible_candidates:
        match = _score_research_copilot_candidate(ad, plan, now)
        if not match:
            continue
        score, reasons = match
        scored.append((score, ad, reasons))
    scored.sort(key=lambda item: (-item[0], _parse_research_date(item[1].last_seen) or datetime.min))
    results = []
    for score, ad, reasons in scored[:40]:
        record = _serialize_scraped_ad(ad)
        record["copilot_score"] = score
        record["match_reasons"] = reasons
        record["relevance_status"] = _research_relevance_status(ad, payload.vertical_id)
        results.append(record)
    return {
        "question": payload.question.strip(),
        "query_plan": {**plan, "vertical": vertical_label},
        "coverage": {
            "matched": len(scored),
            "returned": len(results),
            "catalog_candidates": vertical_candidates,
            "sufficient": len(scored) >= 5,
            "live_capture_recommended": len(scored) < 5,
        },
        "suggestions": _copilot_query_suggestions(payload.question, plan, vertical_label),
        "results": results,
        "limitations": [
            performance_limitation if plan["performance_intent"] else "Results are ordered by research relevance and catalog evidence, not Meta spend, ROAS, conversions, or delivery performance.",
            "Observed runtime is calculated from source-provided dates when available; it does not confirm current delivery.",
        ],
    }


@router.get("/config-verticals/{config_id}/browse-ads")
def get_vertical_browse_ads(
    config_id: str,
    sub_vertical: str | None = None,
    angle_tag: str | None = None,
    media_type: str | None = None,
    active_only: bool = False,
    advertiser: str | None = None,
    sort_by: str = "newest_seen",
    creative_tags: str | None = None,
    cta_type: str | None = None,
    page_type: str | None = None,
    new_within_days: int | None = None,
    needs_tagging: bool = False,
    has_visual: bool = False,
    ads_per_advertiser: int | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return all unique scraped ads for a pre-configured vertical (flat list for card gallery).

    config_id must match a key in VERTICAL_KEYWORD_SETS (e.g. 'commercial_insurance').
    For Home Services, pass sub_vertical to scope to a sub-vertical label.
    Deduplicates by content_hash. Applies optional angle/active/advertiser filters.
    """
    from app.models import ScrapedAd, SavedSearch, Vertical, FacebookPage, PageBlacklist
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS, ALWAYS_BLOCKED_PAGES
    from sqlalchemy import func, distinct, or_
    from datetime import datetime, timedelta

    if config_id not in VERTICAL_KEYWORD_SETS:
        raise HTTPException(status_code=404, detail=f"Unknown vertical config: {config_id}")

    config = VERTICAL_KEYWORD_SETS[config_id]

    # Determine the vertical label(s) to look up in the DB.
    if config_id == "home_services" and sub_vertical:
        sub = config.get("sub_verticals", {}).get(sub_vertical)
        if not sub:
            raise HTTPException(status_code=404, detail=f"Unknown sub-vertical: {sub_vertical}")
        vertical_labels = [sub["label"]]
    elif config_id == "home_services":
        # All home services sub-verticals
        vertical_labels = [sv["label"] for sv in config.get("sub_verticals", {}).values()]
    else:
        vertical_labels = [config["label"]]

    # Find DB verticals matching these labels
    verticals = db.query(Vertical).filter(Vertical.name.in_(vertical_labels)).all()
    if not verticals:
        return []  # No searches run yet for this vertical

    vertical_ids = [v.id for v in verticals]

    # Get all searches for these verticals
    search_ids = [
        s.id
        for s in db.query(SavedSearch.id).filter(SavedSearch.vertical_id.in_(vertical_ids)).all()
    ]
    if not search_ids:
        return []

    # Get blacklisted page names — DB list plus always-blocked hardcoded set
    blacklisted_names = (
        {p.page_name.lower() for p in db.query(PageBlacklist.page_name).all()}
        | {p.lower() for p in ALWAYS_BLOCKED_PAGES}
    )

    # Build query — one row per unique content_hash (or ad ID for legacy ads)
    unique_key = func.coalesce(ScrapedAd.content_hash, ScrapedAd.id)
    subq = (
        db.query(
            unique_key.label("unique_key"),
            func.min(ScrapedAd.id).label("min_id"),
        )
        .filter(ScrapedAd.search_id.in_(search_ids))
        .group_by(unique_key)
        .subquery()
    )

    query = db.query(ScrapedAd).join(subq, ScrapedAd.id == subq.c.min_id)

    # Filters
    if angle_tag:
        query = query.filter(ScrapedAd.angle_tag == angle_tag)
    if advertiser:
        query = query.filter(ScrapedAd.brand_name.ilike(f"%{advertiser}%"))
    if media_type and media_type not in RESEARCH_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown media_type: {media_type}")
    if media_type:
        query = query.filter(
            or_(
                func.nullif(ScrapedAd.media_type, "").is_(None),
                ~func.lower(ScrapedAd.media_type).in_(["image", "video", "carousel"]),
            ) if media_type == "unknown" else ScrapedAd.media_type == media_type
        )
    if active_only:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        query = query.filter(ScrapedAd.last_seen >= cutoff)
    selected_tags = [tag for tag in (creative_tags or "").split(",") if tag]
    unknown_tags = set(selected_tags) - RESEARCH_CREATIVE_TAGS
    if unknown_tags:
        raise HTTPException(status_code=400, detail=f"Unknown creative tag(s): {', '.join(sorted(unknown_tags))}")
    if cta_type:
        if cta_type not in RESEARCH_CTA_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown cta_type: {cta_type}")
        query = query.filter(ScrapedAd.cta_type == cta_type)
    if page_type:
        if page_type not in RESEARCH_PAGE_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown page_type: {page_type}")
        query = query.filter(ScrapedAd.page_type == page_type)
    if new_within_days is not None:
        if not 1 <= new_within_days <= 90:
            raise HTTPException(status_code=400, detail="new_within_days must be between 1 and 90")
        query = query.filter(ScrapedAd.first_seen >= datetime.now(timezone.utc) - timedelta(days=new_within_days))
    if needs_tagging:
        query = query.filter(ScrapedAd.taxonomy_source.is_(None))
    if ads_per_advertiser is not None and not 1 <= ads_per_advertiser <= 20:
        raise HTTPException(status_code=400, detail="ads_per_advertiser must be between 1 and 20")

    if sort_by not in RESEARCH_SORT_OPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown sort_by: {sort_by}. Use one of: {', '.join(sorted(RESEARCH_SORT_OPTIONS))}",
        )
    current_ads = [
        ad for ad in query.all()
        if (not ad.brand_name or ad.brand_name.lower() not in blacklisted_names)
        and (not selected_tags or any(tag in (ad.creative_tags or []) for tag in selected_tags))
        and _matches_research_vertical(ad, config_id)
        and (not has_visual or _has_retained_visual(ad))
    ]
    sorted_ads = _sort_research_ads(current_ads, sort_by)
    ads = _cap_ads_per_advertiser(_dedupe_research_creatives(sorted_ads), ads_per_advertiser)[:limit]

    # Compute running duration; filter blacklisted advertisers and off-topic ads
    now = datetime.utcnow()
    result = []
    for ad in ads:
        # Page blacklist check (DB list + hardcoded always-blocked set)
        if ad.brand_name and ad.brand_name.lower() in blacklisted_names:
            continue

        start = _parse_research_date(ad.start_date)
        running_days = max(0, (now - start).days) if start and ad.platform != "external" else None

        # "Active" proxy: seen within last 30 days
        is_active = False
        last_seen = _parse_research_date(ad.last_seen)
        if last_seen:
            is_active = (now - last_seen).days <= 30

        result.append({
            "id": ad.id,
            "brand_name": ad.brand_name,
            "headline": ad.headline,
            "ad_copy": ad.ad_copy,
            "cta_text": ad.cta_text,
            "platform": ad.platform,
            "ad_link": ad.ad_link,
            "media_url": ad.media_url,
            "media_type": ad.media_type,
            "platforms": ad.platforms,
            "destination_domain": ad.destination_domain,
            "source_query": ad.source_query,
            "rank_position": ad.rank_position,
            "sort_mode": ad.sort_mode,
            "is_multiple_versions": ad.is_multiple_versions,
            "video_urls": ad.video_urls,
            "thumbnail_url": ad.thumbnail_url,
            "creative_intel": ad.creative_intel,
            "volume_score": ad.volume_score,
            "start_date": _serialize_research_datetime(ad.start_date),
            "running_days": running_days,
            "is_active": is_active,
            "seen_count": ad.seen_count or 1,
            "angle_tag": ad.angle_tag,
            "hook_type": ad.hook_type,
            "persona": ad.persona,
            "promise": ad.promise,
            "proof_type": ad.proof_type,
            "funnel_stage": ad.funnel_stage,
            "pacing": ad.pacing,
            "numbers_used": ad.numbers_used,
            "creative_tags": ad.creative_tags or [],
            "cta_type": ad.cta_type,
            "page_type": ad.page_type,
            "video_length_seconds": ad.video_length_seconds,
            "media_preview_url": ad.media_preview_url,
            "media_width": ad.media_width,
            "media_height": ad.media_height,
            "taxonomy_source": ad.taxonomy_source,
            "taxonomy_confidence": ad.taxonomy_confidence,
            "relevance_status": _research_relevance_status(ad, config_id),
            "is_saved": ad.is_saved,
            "last_seen": _serialize_research_datetime(ad.last_seen),
            "first_seen": _serialize_research_datetime(ad.first_seen),
        })

    return result


@router.get("/config-verticals/{config_id}/advertisers")
def get_vertical_advertisers(
    config_id: str,
    sub_vertical: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Summarize retained, browse-eligible captures by advertiser.

    This is deliberately a catalog directory, not a claim about advertiser
    scale, spend, or live Meta delivery. It gives researchers a fast way to
    decide which retained advertiser evidence is worth opening next.
    """
    ads = get_vertical_browse_ads(
        config_id=config_id,
        sub_vertical=sub_vertical,
        limit=500,
        db=db,
        current_user=current_user,
    )
    grouped = {}
    review_queue_count = 0
    for ad in ads:
        if _research_relevance_status(ad, config_id) == "needs_review":
            review_queue_count += 1
            continue
        name = (ad.get("brand_name") or "Unknown advertiser").strip()
        key = name.casefold()
        item = grouped.setdefault(key, {
            "advertiser": name,
            "capture_count": 0,
            "active_capture_count": 0,
            "media_capture_count": 0,
            "multiple_version_count": 0,
            "latest_seen": None,
            "formats": set(),
            "domains": set(),
            "sample_ad_id": ad.get("id"),
        })
        item["capture_count"] += 1
        item["active_capture_count"] += int(bool(ad.get("is_active")))
        item["media_capture_count"] += int(bool(ad.get("thumbnail_url") or ad.get("media_url") or ad.get("media_preview_url")))
        item["multiple_version_count"] += int(bool(ad.get("is_multiple_versions")))
        if ad.get("media_type"):
            item["formats"].add(ad["media_type"])
        if ad.get("destination_domain"):
            item["domains"].add(ad["destination_domain"])
        latest_seen = _parse_research_date(ad.get("last_seen"))
        if latest_seen and (not item["latest_seen"] or latest_seen > item["latest_seen"]):
            item["latest_seen"] = latest_seen

    directory = []
    for item in grouped.values():
        directory.append({
            **item,
            "formats": sorted(item["formats"]),
            "domains": sorted(item["domains"])[:3],
            "latest_seen": _serialize_research_datetime(item["latest_seen"]),
        })
    directory.sort(key=lambda item: (
        -item["active_capture_count"],
        -item["capture_count"],
        -item["media_capture_count"],
        item["advertiser"].casefold(),
    ))
    return {
        "vertical": config_id,
        "advertisers": directory[:100],
        "review_queue_count": review_queue_count,
        "limitations": "Catalog footprint reflects retained, deduplicated captures only—not advertiser spend, scale, or current delivery.",
    }


@router.delete("/config-verticals/{config_id}/ads")
def clear_vertical_ads(
    config_id: str,
    sub_vertical: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete all non-saved scraped ads for a pre-configured vertical.

    Finds the matching Vertical records by label, then deletes all ScrapedAd rows
    linked to those verticals' SavedSearches where is_saved=False.
    Saved ads (is_saved=True) are preserved.
    """
    from app.models import ScrapedAd, SavedSearch, Vertical
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS

    if config_id not in VERTICAL_KEYWORD_SETS:
        raise HTTPException(status_code=404, detail=f"Unknown vertical config: {config_id}")

    config = VERTICAL_KEYWORD_SETS[config_id]

    # Determine vertical labels (same logic as get_vertical_browse_ads)
    if config_id == "home_services":
        if sub_vertical:
            selected = config.get("sub_verticals", {}).get(sub_vertical)
            if not selected:
                raise HTTPException(status_code=404, detail=f"Unknown sub-vertical: {sub_vertical}")
            vertical_labels = [selected["label"]]
        else:
            vertical_labels = [sv["label"] for sv in config.get("sub_verticals", {}).values()]
    else:
        vertical_labels = [config["label"]]

    verticals = db.query(Vertical).filter(Vertical.name.in_(vertical_labels)).all()
    if not verticals:
        return {"deleted": 0}

    vertical_ids = [v.id for v in verticals]
    search_ids = [
        s.id
        for s in db.query(SavedSearch.id).filter(SavedSearch.vertical_id.in_(vertical_ids)).all()
    ]
    if not search_ids:
        return {"deleted": 0}

    deleted = (
        db.query(ScrapedAd)
        .filter(ScrapedAd.search_id.in_(search_ids), ScrapedAd.is_saved == False)  # noqa: E712
        .delete(synchronize_session="fetch")
    )
    db.commit()
    return {"deleted": deleted}


@router.post("/search-and-save-vertical")
async def search_and_save_vertical(
    vertical_id: str,
    sub_vertical: str | None = None,
    limit_per_keyword: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Run all keyword searches for a pre-configured vertical and save results.

    Looks up or creates the DB Vertical records matching the config labels,
    then runs each keyword through the existing search_and_save service.
    Returns aggregate stats: total_new, total_duplicate, keywords_run.

    For home_services, pass sub_vertical (e.g. 'floor_installation') to refresh
    only that sub-vertical. Omit sub_vertical to refresh all home services trades.
    """
    from app.core.vertical_config import VERTICAL_KEYWORD_SETS
    from app.models import Vertical
    from app.schemas.research import AdSearchRequest
    from app.services.research_service import ResearchService
    from app.services.rate_limiter import rate_limiter

    if vertical_id not in VERTICAL_KEYWORD_SETS:
        raise HTTPException(status_code=404, detail=f"Unknown vertical: {vertical_id}")

    print(
        f"[research] search-and-save-vertical called: vertical_id={vertical_id} "
        f"sub_vertical={sub_vertical} limit_per_keyword={limit_per_keyword}"
    )

    config = VERTICAL_KEYWORD_SETS[vertical_id]
    negative_keywords = config.get("negative_keywords", [])

    # Build list of (label, keywords) pairs to process
    pairs: list[tuple[str, list[str]]] = []

    if vertical_id == "home_services":
        sub_verticals = config.get("sub_verticals", {})
        if sub_vertical:
            if sub_vertical not in sub_verticals:
                raise HTTPException(status_code=404, detail=f"Unknown sub-vertical: {sub_vertical}")
            sv = sub_verticals[sub_vertical]
            pairs = [(sv["label"], sv["keywords"])]
        else:
            pairs = [(sv["label"], sv["keywords"]) for sv in sub_verticals.values()]
    else:
        pairs = [(config["label"], config["keywords"])]

    # Check rate limit up-front (rough check — actual enforcement per keyword)
    allowed, remaining, reset_seconds = rate_limiter.check_limit(db)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {reset_seconds} seconds.",
        )

    service = ResearchService(db)
    total_new = 0
    total_duplicate = 0
    keywords_run = 0
    first_error: str | None = None
    rate_limited = False

    for label, keywords in pairs:
        # Look up or create the DB Vertical for this label
        vertical = db.query(Vertical).filter(Vertical.name == label).first()
        if not vertical:
            vertical = Vertical(name=label, description=f"Auto-created for {label} research vertical")
            db.add(vertical)
            db.commit()
            db.refresh(vertical)

        for keyword in keywords:
            try:
                allowed, remaining, _ = rate_limiter.check_limit(db)
                if not allowed:
                    rate_limited = True
                    first_error = first_error or "Rate limit reached before all keywords were checked"
                    break  # Hit rate limit mid-run — stop gracefully

                request = AdSearchRequest(
                    query=keyword,
                    platform="facebook",
                    limit=limit_per_keyword,
                    country="US",
                    offset=0,
                    exclude_ids=[],
                    negative_keywords=negative_keywords,
                    vertical_id=vertical.id,
                    search_type="one_time",
                    schedule_config=None,
                )
                saved_search, ads = await service.search_and_save(request)
                print(
                    f"[research] scraper returned {len(ads)} ads for "
                    f"vertical='{label}' keyword='{keyword}'"
                )
                total_new += saved_search.ads_new or 0
                total_duplicate += saved_search.ads_duplicate or 0
                keywords_run += 1
            except Exception as exc:
                import logging, traceback
                logging.getLogger(__name__).warning(
                    "Keyword search failed for '%s': %s\n%s", keyword, exc, traceback.format_exc()
                )
                if first_error is None:
                    first_error = f"{type(exc).__name__}: {exc}"
                # Roll back any partial transaction so the next keyword gets a clean session
                try:
                    db.rollback()
                except Exception:
                    pass

        if rate_limited:
            break

    return {
        "total_new": total_new,
        "total_duplicate": total_duplicate,
        "keywords_run": keywords_run,
        "message": f"Refreshed {keywords_run} keywords — {total_new} new ads found",
        "first_error": first_error,  # None when all succeed; error class + message when any fail
        "rate_limited": rate_limited,
        "status": "failed" if first_error and keywords_run == 0 and not rate_limited else "partial" if first_error or rate_limited else "complete",
    }
