#!/usr/bin/env python3
"""Deterministically enrich existing Research rows; safe to run repeatedly."""
import argparse

from app.database import SessionLocal
from app.models import ScrapedAd
from app.api.v1.research import _infer_creative_taxonomy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="persist eligible labels")
    args = parser.parse_args()
    db = SessionLocal()
    changed = 0
    try:
        for ad in db.query(ScrapedAd).filter(ScrapedAd.taxonomy_source.is_(None)).yield_per(250):
            tags, cta_type = _infer_creative_taxonomy(ad.headline, ad.ad_copy, ad.cta_text)
            if not tags and cta_type in (None, "unknown"):
                continue
            changed += 1
            if args.apply:
                ad.creative_tags = tags
                ad.cta_type = cta_type
                ad.taxonomy_source = "rules_v1"
                ad.taxonomy_confidence = "low"
        if args.apply:
            db.commit()
        print(f"{'Updated' if args.apply else 'Would update'} {changed} research ads")
    finally:
        db.close()


if __name__ == "__main__":
    main()
