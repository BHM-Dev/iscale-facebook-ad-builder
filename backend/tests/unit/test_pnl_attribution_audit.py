import pytest

from app.api.v1.pnl import _audit_revenue_attribution, _source_offer_breakdown


def test_attribution_audit_classifies_each_admitted_switchboard_row_once():
    result = _audit_revenue_attribution(
        rows=[
            {"offer": "Get Business Coverage", "revenue": "100.10", "sub3": "adset-1", "event": "lead"},
            {"offer": "Get Business Coverage", "revenue": "50.20", "sub1": "ad-1"},
            {"offer": "Get Business Coverage", "revenue": "25.30", "sub3": "campaign-1"},
            {"offer": "Get Business Coverage", "revenue": "10.40", "sub4": "adset-1"},
            {"offer": "Get Business Coverage", "revenue": "8.60", "sub2": "foreign-adset"},
            {"offer": "Get Business Coverage", "revenue": "5.50", "sub1": "not-a-meta-id"},
            {"offer": "Other Offer", "revenue": "999.99", "sub2": "adset-1"},
        ],
        offer_names={"Get Business Coverage"},
        scoped_adsets={"adset-1"},
        scoped_ads={"ad-1": "adset-1"},
        scoped_campaigns={"campaign-1"},
        foreign_meta_ids={"foreign-adset"},
    )

    assert result["total_events"] == 6
    assert result["total_revenue"] == 200.1
    assert result["classification_total"] == 200.1
    assert result["classification_difference"] == 0.0
    assert result["current_pnl_adset_revenue"] == 100.1
    assert result["current_pnl_adset_coverage"] == pytest.approx(100.1 / 200.1)
    assert result["buckets"]["current_pnl_exact_sub3_adset"]["events"] == 1
    assert result["buckets"]["current_pnl_exact_sub3_adset"]["event_types"] == {"lead": {"events": 1, "revenue": 100.1}}
    assert result["buckets"]["candidate_ad_other_field"]["events"] == 1
    assert result["buckets"]["current_pnl_campaign_only_sub3"]["events"] == 1
    assert result["buckets"]["candidate_adset_other_field"]["events"] == 1
    assert result["buckets"]["foreign_meta_id"]["events"] == 1
    assert result["buckets"]["missing_or_unknown"]["events"] == 1
    assert result["field_presence"]["sub4"] == {"events": 1, "revenue": 10.4}


def test_attribution_audit_prefers_adset_over_other_matching_meta_identifiers():
    result = _audit_revenue_attribution(
        rows=[{"offer": "Offer", "revenue": "10", "sub1": "ad-1", "sub2": "adset-1", "sub3": "adset-1"}],
        offer_names={"Offer"},
        scoped_adsets={"adset-1"},
        scoped_ads={"ad-1": "adset-1"},
        scoped_campaigns={"campaign-1"},
        foreign_meta_ids=set(),
    )

    assert result["buckets"]["current_pnl_exact_sub3_adset"]["events"] == 1
    assert result["buckets"]["candidate_ad_other_field"]["events"] == 0
    assert result["buckets"]["current_pnl_campaign_only_sub3"]["events"] == 0


def test_attribution_audit_rejects_missing_or_malformed_source_revenue():
    with pytest.raises(ValueError, match="missing or invalid revenue"):
        _audit_revenue_attribution(
            rows=[{"offer": "Offer", "revenue": "not-money"}],
            offer_names={"Offer"},
            scoped_adsets=set(),
            scoped_ads={},
            scoped_campaigns=set(),
            foreign_meta_ids=set(),
        )


def test_source_offer_breakdown_explicitly_flags_configured_offer_mismatch():
    result = _source_offer_breakdown(
        [
            {"offer": "Mapped Offer", "revenue": "10"},
            {"offer": "Other Offer", "revenue": "25"},
        ],
        {"Mapped Offer", "Configured But Missing"},
    )

    assert result["configured_offer_scope"] == {
        "admitted_events": 1,
        "admitted_revenue": 10.0,
        "excluded_events": 1,
        "excluded_revenue": 25.0,
        "excluded_offers": {"Other Offer": {"events": 1, "revenue": 25.0}},
        "configured_offers_without_source": ["Configured But Missing"],
        "status": "configured_offer_without_source",
    }
