#!/usr/bin/env python3
"""
Prepare Chrome-captured Facebook Ad Library intel for Ad Builder import.

Input is the raw JSON capture saved from the browser-controlled Ad Library tab.
Output matches POST /api/v1/research/ad-library-import.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "ad_library_references" / "auto_insurance_cheap_latest_raw.json"
DEFAULT_OUTPUT = SCRIPT_DIR / "ad_library_references" / "auto_insurance_cheap_import_payload.json"


def normalize_date(value: str | None) -> str:
    if not value:
        return ""
    if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        return value[:10]
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def normalize_ad(raw_ad: dict[str, Any], index: int) -> dict[str, Any]:
    library_id = str(raw_ad.get("library_id") or raw_ad.get("external_id") or "").strip()
    body = raw_ad.get("ad_copy") or raw_ad.get("body_preview") or raw_ad.get("body") or ""
    media_type = raw_ad.get("media_type") or "image"
    video_urls = raw_ad.get("video_urls") or []
    if video_urls:
        media_type = "video"
    return {
        "library_id": library_id,
        "brand_name": raw_ad.get("brand_name") or raw_ad.get("page") or raw_ad.get("advertiser") or "",
        "headline": raw_ad.get("headline") or "",
        "ad_copy": body,
        "cta_text": raw_ad.get("cta_text") or raw_ad.get("cta") or "",
        "ad_link": raw_ad.get("ad_link") or f"https://www.facebook.com/ads/library/?id={library_id}",
        "platforms": raw_ad.get("platforms") or ["facebook"],
        "start_date": normalize_date(raw_ad.get("start_date") or raw_ad.get("started_running")),
        "media_type": media_type,
        "media_url": raw_ad.get("media_url") or raw_ad.get("thumbnail_url") or "",
        "destination_domain": raw_ad.get("destination_domain") or raw_ad.get("domain") or "",
        "rank_position": raw_ad.get("rank_position") or index + 1,
        "is_multiple_versions": bool(raw_ad.get("is_multiple_versions") or raw_ad.get("multiple_versions")),
        "video_urls": video_urls,
        "thumbnail_url": raw_ad.get("thumbnail_url") or raw_ad.get("media_url") or "",
        "creative_intel": {
            "visible_copy_preview": body[:1200],
            "imported_from_chrome": True,
        },
    }


def build_payload(raw: dict[str, Any], vertical: str) -> dict[str, Any]:
    source_ads = raw.get("ads") or raw.get("visible_ads") or []
    ads = [normalize_ad(ad, index) for index, ad in enumerate(source_ads)]
    ads = [ad for ad in ads if ad["library_id"]]
    unmapped_videos = len(raw.get("videos") or [])
    for ad in ads:
        ad["creative_intel"]["unmapped_video_inventory_count"] = unmapped_videos
    return {
        "query": raw.get("query") or "cheap auto insurance",
        "country": raw.get("country") or "US",
        "vertical": vertical,
        "sort_mode": raw.get("sort_mode") or raw.get("sort") or "total_impressions_desc",
        "source_url": raw.get("source_url") or raw.get("page_url") or "",
        "ads": ads,
        "capture_quality": {
            "ads": len(ads),
            "with_media": sum(1 for ad in ads if ad.get("media_url") or ad.get("thumbnail_url") or ad.get("video_urls")),
            "with_mapped_video": sum(1 for ad in ads if ad.get("video_urls")),
            "unmapped_video_inventory": unmapped_videos,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Chrome Ad Library capture JSON for Ad Builder import.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Raw Chrome capture JSON path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Import-ready JSON output path.")
    parser.add_argument("--vertical", default="Auto Insurance", help="Research vertical name.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    raw = json.loads(input_path.read_text())
    payload = build_payload(raw, args.vertical)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n")
    quality = payload["capture_quality"]
    print(
        f"Wrote {len(payload['ads'])} ads to {output_path} "
        f"({quality['with_media']} with media, {quality['with_mapped_video']} with mapped video, "
        f"{quality['unmapped_video_inventory']} unmapped videos observed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
