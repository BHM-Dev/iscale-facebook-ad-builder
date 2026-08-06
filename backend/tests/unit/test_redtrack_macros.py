from app.core.redtrack_macros import build_redtrack_url_tags


def test_build_redtrack_url_tags_adds_missing_subs():
    assert (
        build_redtrack_url_tags("https://example.com/landing?utm_source=meta")
        == "sub1={{ad.id}}&sub2={{adset.id}}&sub3={{campaign.id}}"
    )


def test_build_redtrack_url_tags_skips_correct_existing_subs():
    url = (
        "https://example.com/landing"
        "?sub1={{ad.id}}&sub2={{adset.id}}&sub3={{campaign.id}}"
    )

    assert build_redtrack_url_tags(url) == ""


def test_build_redtrack_url_tags_overrides_wrong_sub2_macro():
    url = "https://example.com/landing?sub1={{ad.id}}&sub2={{campaign.id}}"

    assert build_redtrack_url_tags(url) == "sub2={{adset.id}}&sub3={{campaign.id}}"


def test_build_redtrack_url_tags_overrides_hardcoded_numeric_sub():
    url = "https://example.com/landing?sub1=12345&sub2={{adset.id}}"

    assert build_redtrack_url_tags(url) == "sub1={{ad.id}}&sub3={{campaign.id}}"
