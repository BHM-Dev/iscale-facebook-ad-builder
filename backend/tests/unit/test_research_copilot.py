from types import SimpleNamespace

from app.api.v1.research import _copilot_query_suggestions, _dedupe_research_creatives, _has_retained_visual, _plan_research_copilot_question, _research_relevance_status, _sanitize_research_copilot_ai_summary


def test_copilot_plan_extracts_owner_operator_runtime_and_activity():
    plan = _plan_research_copilot_question(
        "Show active commercial auto ads for owner-operators running 30+ days",
        "commercial_insurance",
    )
    assert plan["segments"] == ["owner-operators"]
    assert plan["active_only"] is True
    assert plan["min_running_days"] == 30
    assert plan["captured_within_days"] is None


def test_copilot_plan_keeps_last_days_distinct_from_runtime():
    plan = _plan_research_copilot_question(
        "Find best performing trucker ads from the last 30 days",
        "commercial_insurance",
    )
    assert plan["segments"] == ["truckers"]
    assert plan["captured_within_days"] == 30
    assert plan["min_running_days"] is None


def test_copilot_suggestions_broaden_runtime_without_claiming_performance():
    question = "Show active commercial auto ads for owner-operators running 30+ days"
    plan = _plan_research_copilot_question(question, "commercial_insurance")
    suggestions = _copilot_query_suggestions(question, plan, "Commercial Insurance")
    assert suggestions
    assert any("runtime" in suggestion["reason"] for suggestion in suggestions)
    assert all("best performing" not in suggestion["question"].casefold() for suggestion in suggestions)


def test_copilot_plan_extracts_creative_pattern_cta_and_destination():
    plan = _plan_research_copilot_question(
        "Show UGC comparison ads with a learn more CTA that use an advertorial",
        "commercial_insurance",
    )
    assert plan["creative_tags"] == ["comparison", "ugc"]
    assert plan["cta_type"] == "learn_more"
    assert plan["page_type"] == "advertorial"


def test_commercial_relevance_status_flags_broad_non_offer_capture_for_review():
    ad = SimpleNamespace(platform="facebook", brand_name="Calan Services", headline="Build a patio", ad_copy="Book your free estimate", cta_text="Learn More")
    assert _research_relevance_status(ad, "commercial_insurance") == "needs_review"

    insurance_ad = SimpleNamespace(platform="facebook", brand_name="Example", headline="Commercial insurance", ad_copy="Compare a business insurance quote", cta_text="Get Quote")
    assert _research_relevance_status(insurance_ad, "commercial_insurance") == "high_confidence"
    assert _research_relevance_status({"platform": "facebook", "brand_name": "Example", "headline": "Commercial insurance", "ad_copy": "Compare a business insurance quote", "cta_text": "Get Quote"}, "commercial_insurance") == "high_confidence"


def test_retained_visual_requires_an_actual_asset_not_only_format_metadata():
    assert not _has_retained_visual(SimpleNamespace(media_type="video", thumbnail_url=None, media_url=None, media_preview_url=None, video_urls=[]))
    assert _has_retained_visual({"media_type": "video", "thumbnail_url": None, "media_url": None, "media_preview_url": "https://cdn.example.test/preview.mp4", "video_urls": []})


def test_catalog_dedupes_exact_visible_creative_but_keeps_copy_variants():
    base = dict(brand_name="RigCover", headline="Commercial coverage", ad_copy="Compare policies", cta_text="Get Quote", media_type="image")
    same = SimpleNamespace(**base)
    duplicate = SimpleNamespace(**base)
    variant = SimpleNamespace(**{**base, "ad_copy": "Compare commercial policies"})
    assert _dedupe_research_creatives([same, duplicate, variant]) == [same, variant]


def test_ai_summary_is_bounded_and_requires_a_grounded_answer():
    assert _sanitize_research_copilot_ai_summary({"patterns": ["Comparison"]}) is None
    summary = _sanitize_research_copilot_ai_summary({
        "answer": "A" * 700,
        "patterns": ["Fast quote", "Identity hook", "Comparison", "Ignore me"],
    })
    assert len(summary["answer"]) == 600
    assert summary["patterns"] == ["Fast quote", "Identity hook", "Comparison"]
