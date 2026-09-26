"""Regression tests for Brand Scrape advertiser identity checks."""

from app.services.brand_scraper import requested_brand_matches_page


def test_matching_requested_brand_and_resolved_page_is_allowed():
    assert requested_brand_matches_page(
        "Progressive Small Business Insurance",
        "Progressive Small Business Insurance",
    )


def test_unrelated_resolved_page_is_rejected():
    assert not requested_brand_matches_page("Insurance Direct", "Cholesterol Wellness Hub")


def test_short_but_distinct_brand_name_is_checked():
    assert requested_brand_matches_page("Jeep", "Jeep Insurance")
    assert not requested_brand_matches_page("Jeep", "RigCover.com")
