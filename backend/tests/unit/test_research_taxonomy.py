"""Pure regression tests for source-backed Research filters and sorting."""

from datetime import datetime
from types import SimpleNamespace

from app.api.v1.research import (
    _parse_research_date,
    _serialize_research_datetime,
    _sort_research_ads,
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
