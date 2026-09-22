from types import SimpleNamespace

from app.api.v1.research import _infer_creative_taxonomy, _matches_research_vertical


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
