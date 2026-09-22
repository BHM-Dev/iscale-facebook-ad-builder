#!/usr/bin/env python3
"""Deterministically enrich existing Research rows; safe to run repeatedly."""
import argparse
from collections import Counter

from app.database import SessionLocal
from app.models import ScrapedAd
from app.api.v1.research import _infer_creative_taxonomy


BATCH_SIZE = 250


def taxonomy_update(ad):
    """Return the safe deterministic update for one legacy ad, or None."""
    if ad.taxonomy_source is not None:
        return None
    tags, cta_type = _infer_creative_taxonomy(ad.headline, ad.ad_copy, ad.cta_text)
    if not tags and cta_type in (None, "unknown"):
        return None
    return {"creative_tags": tags, "cta_type": cta_type, "taxonomy_source": "rules_v1", "taxonomy_confidence": "low"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="persist eligible labels")
    args = parser.parse_args()
    db = SessionLocal()
    changed = 0
    themes = Counter()
    ctas = Counter()
    try:
        # Keyset-paginated by id rather than a single yield_per generator held
        # open across commits (mixing a streamed cursor with mid-loop commits
        # risks invalidating it) and rather than re-running the
        # taxonomy_source IS NULL filter alone (in dry-run mode nothing ever
        # gets persisted, so that filter would return the same rows forever).
        # `id > last_id` always advances regardless of --apply.
        last_id = ""
        while True:
            batch = (
                db.query(ScrapedAd)
                .filter(ScrapedAd.taxonomy_source.is_(None), ScrapedAd.id > last_id)
                .order_by(ScrapedAd.id)
                .limit(BATCH_SIZE)
                .all()
            )
            if not batch:
                break
            last_id = batch[-1].id
            for ad in batch:
                update = taxonomy_update(ad)
                if not update:
                    continue
                changed += 1
                themes.update(update["creative_tags"] or [])
                if update["cta_type"]:
                    ctas.update([update["cta_type"]])
                if args.apply:
                    for field, value in update.items():
                        setattr(ad, field, value)
            if args.apply:
                db.commit()
            db.expunge_all()
        action = "Updated" if args.apply else "Would update"
        print(f"{action} {changed} research ads")
        if themes:
            print("Themes: " + ", ".join(f"{tag}={count}" for tag, count in themes.most_common()))
        if ctas:
            print("CTAs: " + ", ".join(f"{cta}={count}" for cta, count in ctas.most_common()))
    finally:
        db.close()


if __name__ == "__main__":
    main()
