from types import SimpleNamespace
from pathlib import Path
import sys

from app.api.v1.research import _cap_ads_per_advertiser, _infer_creative_taxonomy, _matches_research_vertical, _related_pattern_score
from app.schemas.research import ResearchBriefCuration

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


def test_commercial_catalog_keeps_validated_external_segment_rows():
    """External imports are scoped to a configured vertical at write time."""
    segment_led_external = SimpleNamespace(
        platform="external",
        brand_name="RigCover.com",
        headline="Security firms: coverage tied to the work you do",
        ad_copy="Compare options for your operation.",
        cta_text="Get Quote",
    )

    assert _matches_research_vertical(segment_led_external, "commercial_insurance") is True


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


def test_related_pattern_score_rejects_cross_vertical_matches_on_generic_signals_alone():
    """A shared CTA and media format alone must not imply relevance -- neither
    ScrapedAd nor this endpoint tracks vertical, so this is the only guard
    against e.g. a home-services ad surfacing as "related" to a commercial-
    insurance ad purely because both use "get_quote" + "video"."""
    commercial_insurance = SimpleNamespace(creative_tags=[], cta_type="get_quote", media_type="video", destination_domain="quote.example.com")
    home_services = SimpleNamespace(creative_tags=[], cta_type="get_quote", media_type="video", destination_domain="booking.example.com")
    assert _related_pattern_score(commercial_insurance, home_services) is None

    # Same generic signals, but a real content-level match (shared tag) still counts.
    tagged_candidate = SimpleNamespace(creative_tags=["problem_agitation"], cta_type="get_quote", media_type="video", destination_domain="booking.example.com")
    commercial_insurance.creative_tags = ["problem_agitation"]
    assert _related_pattern_score(commercial_insurance, tagged_candidate) is not None

    # Same generic signals, but a shared landing destination still counts too.
    commercial_insurance.creative_tags = []
    same_destination_candidate = SimpleNamespace(creative_tags=[], cta_type="get_quote", media_type="video", destination_domain="quote.example.com")
    assert _related_pattern_score(commercial_insurance, same_destination_candidate) is not None


def test_commercial_relevance_guard_excludes_auto_insurance_related_candidates():
    auto_candidate = SimpleNamespace(
        platform="facebook",
        brand_name="SmarterAuto",
        headline="Compare auto insurance quotes",
        ad_copy="Save on car coverage today.",
        cta_text="Get Quote",
    )
    assert _matches_research_vertical(auto_candidate, "commercial_insurance") is False


def test_advertiser_cap_preserves_sorted_first_result_and_unknown_legacy_rows():
    ads = [
        SimpleNamespace(brand_name="Acme"),
        SimpleNamespace(brand_name="acme"),
        SimpleNamespace(brand_name="Bravo"),
        SimpleNamespace(brand_name=None),
        SimpleNamespace(brand_name=""),
    ]
    limited = _cap_ads_per_advertiser(ads, 1)
    assert [ad.brand_name for ad in limited] == ["Acme", "Bravo", None, ""]
    assert _cap_ads_per_advertiser(ads, None) == ads


def test_brief_curation_accepts_operator_context_without_source_fields():
    curation = ResearchBriefCuration(pinned=True, bhm_takeaway="Test the segment-to-risk sequence with verified claims.")
    assert curation.model_dump(exclude_unset=True) == {
        "pinned": True,
        "bhm_takeaway": "Test the segment-to-risk sequence with verified claims.",
    }
