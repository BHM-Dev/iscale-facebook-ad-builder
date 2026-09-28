"""Pure regression tests for source-backed Research filters and sorting."""

from datetime import datetime
from types import SimpleNamespace

from app.api.v1.research import (
    _parse_research_date,
    _research_evidence_coverage,
    _serialize_research_datetime,
    _sort_research_ads,
    _watchlist_summary,
)


def ad(**overrides):
    values = {
        'start_date': None,
        'last_seen': None,
        'seen_count': 0,
        'is_multiple_versions': False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_research_dates_normalize_aware_values_to_utc():
    value = _parse_research_date('2026-09-20T12:00:00-04:00')
    assert value == datetime(2026, 9, 20, 16, 0, 0)
    assert _serialize_research_datetime('2026-09-20T12:00:00-04:00') == '2026-09-20T16:00:00Z'


def test_longest_running_puts_oldest_known_start_first_and_unknown_last():
    ads = [
        ad(id='new', start_date='2026-09-18'),
        ad(id='old', start_date='2026-08-18'),
        ad(id='unknown'),
    ]
    assert [item.id for item in _sort_research_ads(ads, 'longest_running')] == ['old', 'new', 'unknown']


def test_most_sightings_sorts_descending_and_keeps_unknown_as_zero():
    ads = [ad(id='low', seen_count=1), ad(id='high', seen_count=8), ad(id='none', seen_count=None)]
    assert [item.id for item in _sort_research_ads(ads, 'most_sightings')] == ['high', 'low', 'none']


def test_multiple_versions_prioritizes_versions_then_newest_seen():
    ads = [
        ad(id='single-new', is_multiple_versions=False, last_seen='2026-09-20'),
        ad(id='multi-old', is_multiple_versions=True, last_seen='2026-09-18'),
        ad(id='multi-new', is_multiple_versions=True, last_seen='2026-09-19'),
    ]
    assert [item.id for item in _sort_research_ads(ads, 'multiple_versions')] == ['multi-new', 'multi-old', 'single-new']


def test_watchlist_only_surfaces_new_catalog_changes_since_last_review():
    watchlist = SimpleNamespace(
        id='watch-1', advertiser='NerdInsure', advertiser_key='nerdinsure',
        vertical_id='commercial_insurance', created_at='2026-09-01T00:00:00Z',
        last_viewed_at='2026-09-10T00:00:00Z',
    )
    ads = [
        {
            'id': 'old', 'brand_name': 'NerdInsure', 'headline': 'Compare business coverage',
            'first_seen': '2026-09-05T00:00:00Z', 'last_seen': '2026-09-09T00:00:00Z',
            'cta_type': 'get_quote', 'media_type': 'image', 'creative_tags': ['comparison'],
            'destination_domain': 'nerdinsure.example', 'creative_intel': {'segment': 'contractors'},
        },
        {
            'id': 'new', 'brand_name': 'NerdInsure', 'headline': 'Security firms: compare coverage',
            'first_seen': '2026-09-12T00:00:00Z', 'last_seen': '2026-09-12T00:00:00Z',
            'cta_type': 'learn_more', 'media_type': 'video', 'creative_tags': ['educational'],
            'destination_domain': 'nerdinsure.example', 'creative_intel': {'segment': 'security firms'},
        },
    ]

    summary = _watchlist_summary(watchlist, ads)

    assert summary['new_capture_count'] == 1
    assert [ad['id'] for ad in summary['new_ads']] == ['new']
    labels = [change['label'] for change in summary['changes']]
    assert 'New hook: Security firms: compare coverage' in labels
    assert 'New CTA: learn more' in labels
    assert 'New format: video' in labels
    assert 'New audience segment: security firms' in labels
    assert summary['review_value'] > 0
    assert summary['review_priority'] == 'high'
    assert summary['refresh_status'] == 'stale'
    assert summary['days_since_latest_capture'] is not None
    assert 'more than 14 days old' in summary['refresh_reason']
    assert summary['evidence_coverage_count'] == 3
    assert summary['evidence_gaps'] == ['visual']


def test_evidence_coverage_names_only_missing_retained_fields():
    coverage = _research_evidence_coverage([{
        'headline': 'Compare commercial insurance',
        'ad_copy': None,
        'thumbnail_url': None,
        'media_url': None,
        'media_preview_url': None,
        'cta_type': None,
        'cta_text': None,
        'destination_domain': None,
    }])

    assert coverage['evidence_coverage_count'] == 1
    assert coverage['evidence_fields'] == ['copy']
    assert coverage['evidence_gaps'] == ['visual', 'CTA', 'destination']
