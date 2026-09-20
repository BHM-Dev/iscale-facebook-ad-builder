"""Pure tests for Campaign Intelligence naming and date-window helpers."""

from datetime import date, datetime

import app.api.v1.intelligence as intelligence
from app.api.v1.intelligence import _build_best_times, _extract_niche, _redtrack_adset_id, _resolve_preset


def test_extract_niche_skips_date_prefixed_ad_set_segments():
    assert _extract_niche('04/28/2026 - HORSE & STABLE - CAPI') == 'HORSE & STABLE'
    assert _extract_niche('2026-04-28 - HORSE & STABLE - CAPI') == 'HORSE & STABLE'
    assert _extract_niche('04-28-2026 - HORSE & STABLE - CAPI') == 'HORSE & STABLE'
    assert _extract_niche('2026/04/28 - HORSE & STABLE - CAPI') == 'HORSE & STABLE'


def test_extract_niche_skips_date_prefixed_campaign_segments_with_slashes():
    assert _extract_niche('BATCH 2 - CAPI', '04.28.2026 - COMMERCIAL ROOFING') == 'COMMERCIAL ROOFING'


def test_extract_niche_keeps_general_when_only_date_and_control_labels_exist():
    assert _extract_niche('2026-04-28 - BATCH 2 - CAPI') == 'General'


def test_extract_niche_preserves_numeric_niche_names():
    assert _extract_niche('24/7 Emergency Plumbing - Batch 1') == '24/7 Emergency Plumbing'
    assert _extract_niche('3/4 Ton Trucking - Batch 1') == '3/4 Ton Trucking'
    assert _extract_niche('1.2 Acre Homes - CAPI') == '1.2 Acre Homes'


def test_resolve_preset_defaults_to_last_seven_days():
    start, end, day_filter, label = _resolve_preset('unsupported', None, None)
    assert day_filter == 'all'
    assert label == 'Last 7 days'
    assert date.fromisoformat(end) - date.fromisoformat(start)
    assert (date.fromisoformat(end) - date.fromisoformat(start)).days == 6


def test_resolve_preset_uses_redtrack_calendar(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 19, tzinfo=tz)

    monkeypatch.setattr(intelligence, 'datetime', FixedDateTime)

    assert _resolve_preset('today', None, None)[:2] == ('2026-09-19', '2026-09-19')
    assert _resolve_preset('yesterday', None, None)[:2] == ('2026-09-18', '2026-09-18')
    assert _resolve_preset('this_month', None, None)[:2] == ('2026-09-01', '2026-09-19')


def test_redtrack_adset_join_prefers_matching_sub2_over_nonmatching_p_sub2():
    assert _redtrack_adset_id(
        {'p_sub2': 'campaign-123', 'sub2': '987654321'},
        {'987654321'},
    ) == '987654321'


def test_best_times_keeps_unlabeled_redtrack_rows_and_drops_explicit_mismatch():
    result = _build_best_times(
        {
            'adsets': {'987654321': {'adset_name': 'HVAC', 'campaign_name': 'HVAC'}},
            'rows': [{'adset_id': '987654321', 'date': '2026-09-15', 'hour': 8, 'spend': 100, 'leads': 5}],
        },
        [{'offer': 'Switchboard Offer', 'sub3': '987654321', 'revenue': '100', 'conversion_date': '2026-09-15T08:00:00+00:00'}],
        {'Switchboard Offer'},
        include_metadata=True,
        redtrack_rows=[
            {'p_sub2': 'campaign-123', 'sub2': '987654321', 'conv_time': '2026-09-15T08:00:00+00:00', 'payout': '20'},
            {'sub2': '987654321', 'conv_time': '2026-09-15T09:00:00+00:00', 'payout': '30'},
            {'sub2': '987654321', 'offer': 'Other Offer', 'conv_time': '2026-09-15T10:00:00+00:00', 'payout': '10'},
        ],
    )

    assert result['attribution_allocated'] is True
    assert result['dropped_conversion_count'] == 1
    assert result['dropped_revenue'] == 10.0
    assert 'unlabeled rows were retained' in result['attribution_warning']


def test_best_times_does_not_call_everflow_fallback_timing_complete():
    result = _build_best_times(
        {
            'adsets': {'987654321': {'adset_name': 'HVAC', 'campaign_name': 'HVAC'}},
            'rows': [{'adset_id': '987654321', 'date': '2026-09-15', 'hour': 8, 'spend': 100, 'leads': 5}],
        },
        [{'offer': 'Switchboard Offer', 'sub3': '987654321', 'revenue': '100', 'conversion_date': '2026-09-15T08:00:00+00:00'}],
        {'Switchboard Offer'},
        include_metadata=True,
        redtrack_rows=[],
    )

    assert result['attribution_method'] == 'everflow_adset_id_redtrack_unavailable'
    assert result['attribution_complete'] is False
