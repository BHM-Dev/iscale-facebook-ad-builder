"""Acceptance coverage for the vendor-neutral external Research importer."""
from uuid import uuid4

from app.models import FacebookPage, SavedSearch, ScrapedAd


def test_external_research_import_keeps_vendor_signal_as_context(client, auth_headers, db_session):
    external_id = f"external-import-{uuid4()}"
    query = f"external research test {uuid4()}"
    payload = {
        "source": "GetHookd",
        "vertical": "Commercial Insurance",
        "query": query,
        "source_url": "https://app.gethookd.ai/",
        "ads": [{
            "external_id": external_id,
            "brand_name": "Import Test Insurer",
            "headline": "Get a policy online in minutes",
            "primary_text": "Small business insurance with a quick quote.",
            "cta": "Get Quote",
            "landing_url": "example.test/quote",
            "format": "carousel",
            "first_seen": "2026-09-24",
            "segment": "Small business",
            "source_signal": "Winning — directional source signal",
            "creative_tags": ["comparison"],
        }],
    }

    try:
        response = client.post("/api/v1/research/external-import", json=payload, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["imported"] == 1

        ad = db_session.query(ScrapedAd).filter(ScrapedAd.external_id == external_id).one()
        assert ad.platform == "external"
        assert ad.destination_domain == "example.test"
        assert ad.ad_link == "https://example.test/quote"
        assert ad.creative_intel["research_source"] == "GetHookd"
        assert ad.creative_intel["source_signal"] == "Winning — directional source signal"
        assert ad.creative_intel["signal_disclaimer"] == "Directional source context; not verified BHM performance."
        assert ad.cta_type == "get_quote"

        repeat = client.post("/api/v1/research/external-import", json=payload, headers=auth_headers)
        assert repeat.status_code == 200
        assert repeat.json()["imported"] == 0
        assert repeat.json()["updated"] == 1
    finally:
        db_session.query(ScrapedAd).filter(ScrapedAd.external_id == external_id).delete()
        db_session.query(FacebookPage).filter(FacebookPage.page_name == "Import Test Insurer").delete()
        db_session.query(SavedSearch).filter(SavedSearch.query == query).delete()
        db_session.commit()


def test_external_research_import_rejects_unreachable_vertical_and_missing_source(client, auth_headers):
    invalid_vertical = client.post(
        "/api/v1/research/external-import",
        json={
            "source": "GetHookd",
            "vertical": "Commercial Lines",
            "ads": [{"brand_name": "Example", "landing_url": "https://example.test"}],
        },
        headers=auth_headers,
    )
    assert invalid_vertical.status_code == 422
    assert "configured Research vertical" in invalid_vertical.json()["detail"]

    missing_source = client.post(
        "/api/v1/research/external-import",
        json={
            "source": "GetHookd",
            "vertical": "Commercial Insurance",
            "ads": [{"brand_name": "Example"}],
        },
        headers=auth_headers,
    )
    assert missing_source.status_code == 422
    assert "landing_url" in missing_source.json()["detail"]
