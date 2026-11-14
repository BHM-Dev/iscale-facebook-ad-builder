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


# Review S3 (2026-11-12): a failure building url_tags used to ship the ad with no sub1/2/3.
def test_apply_url_tags_falls_back_to_full_macro_set_and_alerts(monkeypatch):
    import app.core.redtrack_macros as rm
    import app.services.slack_service as slack
    from app.services.facebook_service import apply_redtrack_url_tags
    from facebook_business.adobjects.adcreative import AdCreative

    def boom(url):
        raise ValueError("parse bug")
    alerts = []
    monkeypatch.setattr(rm, "build_redtrack_url_tags", boom)
    monkeypatch.setattr(slack, "send_launch_alert", lambda *a, **k: alerts.append(a) or True)
    params, feed = {}, {"link_urls": [{"website_url": "https://x.test"}]}
    tags = apply_redtrack_url_tags(params, feed, "https://x.test/?a=1")
    assert tags == "sub1={{ad.id}}&sub2={{adset.id}}&sub3={{campaign.id}}"
    assert params[AdCreative.Field.url_tags] == tags
    assert feed["link_urls"][0]["url_tags"] == tags
    assert alerts and "url_tags" in alerts[0][0]


def test_apply_url_tags_normal_path_and_no_feed():
    from app.services.facebook_service import apply_redtrack_url_tags
    params = {}
    assert apply_redtrack_url_tags(params, None, "https://example.com/landing") == "sub1={{ad.id}}&sub2={{adset.id}}&sub3={{campaign.id}}"
    params = {}
    url = "https://example.com/?sub1={{ad.id}}&sub2={{adset.id}}&sub3={{campaign.id}}"
    assert apply_redtrack_url_tags(params, {"link_urls": []}, url) == "" and params == {}
