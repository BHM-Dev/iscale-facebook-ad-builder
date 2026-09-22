from types import SimpleNamespace
from pathlib import Path
import sys

from app.api.v1.research import _infer_creative_taxonomy, _matches_research_vertical, _related_pattern_score

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from backfill_research_taxonomy import taxonomy_update


def test_taxonomy_rules_are_conservative_and_preserve_source_tags():
    tags, cta = _infer_creative_taxonomy(
        "Stop overpaying", "Here are 5 ways to compare business coverage", "Get Quote", ["testimonial", "not-real"],
    )
    assert tags == ["testimonial", "problem_agitation", "comparison", "listicle"]
    assert cta == "get_quote"


def test_taxonomy_does_not_guess_without_visible_evidence():
    assert _infer_creative_taxonomy(None, None, None) == (None, None)


def test_taxonomy_keeps_unknown_cta_honest():
    assert _infer_creative_taxonomy("A", "B", "Call now") == (None, "unknown")


def test_commercial_catalog_does_not_show_obvious_broad_query_noise():
    relevant = SimpleNamespace(brand_name="Example", headline="", ad_copy="Get business insurance and commercial auto coverage", cta_text="")
    noise = SimpleNamespace(brand_name="Example", headline="", ad_copy="Restaurant equipment now hiring", cta_text="")
    assert _matches_research_vertical(relevant, "commercial_insurance") is True
    assert _matches_research_vertical(noise, "commercial_insurance") is False


def test_backfill_only_updates_untagged_rows_with_real_signal():
    legacy = SimpleNamespace(taxonomy_source=None, headline="Stop overpaying", ad_copy="", cta_text="Get Quote")
    existing = SimpleNamespace(taxonomy_source="capture", headline="Stop overpaying", ad_copy="", cta_text="Get Quote")
    unknown = SimpleNamespace(taxonomy_source=None, headline="", ad_copy="", cta_text="Call now")
    assert taxonomy_update(legacy)["taxonomy_source"] == "rules_v1"
    assert taxonomy_update(existing) is None
    assert taxonomy_update(unknown) is None


def test_related_pattern_score_is_explainable_and_not_a_performance_score():
    source = SimpleNamespace(creative_tags=["comparison"], cta_type="get_quote", media_type="video", destination_domain="example.com")
    matching = SimpleNamespace(creative_tags=["comparison"], cta_type="get_quote", media_type="video", destination_domain="other.com")
    unrelated = SimpleNamespace(creative_tags=[], cta_type=None, media_type="image", destination_domain=None)
    assert _related_pattern_score(source, matching) == (7, ["theme: comparison", "CTA: get quote", "format: video"])
    assert _related_pattern_score(source, unrelated) is None
