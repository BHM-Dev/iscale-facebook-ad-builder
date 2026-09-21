"""Pure tests for Campaign Intelligence naming and date-window helpers."""

from datetime import date, datetime

import app.api.v1.intelligence as intelligence
from app.api.v1.intelligence import BEST_TIMES_DAYPARTS, _build_best_times, _extract_niche, _redtrack_adset_id, _redtrack_offer_matches, _resolve_preset


def test_best_times_dayparts_is_reusable_not_a_single_use_generator():
    # A bare `(expr for x in y)` is a generator expression, not a tuple — it
    # exhausts after one full iteration. build_timing_summary iterates this
    # twice per call (Mon-Fri and Sat-Sun) and is itself called once per
    # niche/campaign/adset in a single request, so a generator here silently
    # zeroes out every block after the very first iteration in production.
    assert isinstance(BEST_TIMES_DAYPARTS, tuple)
    assert len(list(BEST_TIMES_DAYPARTS)) == 12
    assert len(list(BEST_TIMES_DAYPARTS)) == 12  # second pass must not be empty


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


def test_redtrack_offer_match_accepts_canonical_name_inside_descriptive_label():
    assert _redtrack_offer_matches(
        {'offer': 'Commercial Insurance - Get Business Coverage - GBC - V2'},
        {'Get Business Coverage'},
    )
    assert not _redtrack_offer_matches(
        {'offer': 'Commercial Insurance - GBC - HVAC'},
        {'Get Business Coverage'},
    )


def test_best_times_excludes_unlabeled_and_explicitly_mismatched_redtrack_rows():
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
            {'sub2': '987654321', 'offer': 'Switchboard Offer', 'conv_time': '2026-09-15T09:00:00+00:00', 'payout': '30'},
            {'sub2': '987654321', 'offer': 'Other Offer', 'conv_time': '2026-09-15T10:00:00+00:00', 'payout': '10'},
        ],
    )

    assert result['attribution_allocated'] is True
    assert result['attribution_complete'] is True
    assert result['dropped_conversion_count'] == 0
    assert '1 RedTrack rows for other offers were excluded' in result['attribution_warning']
    assert '1 unlabeled RedTrack rows were excluded' in result['attribution_warning']


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


def test_best_times_excludes_no_delivery_everflow_rows_without_blocking_timing():
    result = _build_best_times(
        {
            'adsets': {'987654321': {'adset_name': 'HVAC', 'campaign_name': 'HVAC'}},
            'rows': [{'adset_id': '987654321', 'date': '2026-09-15', 'hour': 8, 'spend': 100, 'leads': 5}],
        },
        [
            {'offer': 'Get Business Coverage', 'sub3': '987654321', 'revenue': '100', 'conversion_date': '2026-09-15T08:00:00+00:00'},
            {'offer': 'Get Business Coverage', 'sub3': 'stale-adset', 'revenue': '25', 'conversion_date': '2026-09-15T08:00:00+00:00'},
        ],
        {'Get Business Coverage'},
        include_metadata=True,
        redtrack_rows=[
            {'sub2': '987654321', 'offer': 'Commercial Insurance - Get Business Coverage - GBC - V2', 'conv_time': '2026-09-15T08:00:00+00:00', 'payout': '20'},
        ],
    )

    assert result['attribution_complete'] is True
    assert result['attribution_allocated'] is True
    assert result['dropped_conversion_count'] == 0
    assert result['excluded_conversion_count'] == 1
    assert result['excluded_revenue'] == 25.0


def test_best_times_timing_blocks_are_fully_populated_across_multiple_entities():
    # Regression for the generator-exhaustion bug: with two niches sharing
    # BEST_TIMES_DAYPARTS across three build_timing_summary calls (niche,
    # campaign, adset), every one of them must still see all 12 blocks x 2
    # weekday groups — not just the first entity processed.
    result = _build_best_times(
        {
            'adsets': {
                '111111111': {'adset_name': 'HVAC', 'campaign_name': 'HVAC'},
                '222222222': {'adset_name': 'Plumbing', 'campaign_name': 'Plumbing'},
            },
            'rows': [
                # Monday (weekday) and Saturday (weekend) delivery for both niches.
                {'adset_id': '111111111', 'date': '2026-09-14', 'hour': 8, 'spend': 100, 'leads': 5},
                {'adset_id': '111111111', 'date': '2026-09-19', 'hour': 8, 'spend': 100, 'leads': 5},
                {'adset_id': '222222222', 'date': '2026-09-14', 'hour': 8, 'spend': 100, 'leads': 5},
                {'adset_id': '222222222', 'date': '2026-09-19', 'hour': 8, 'spend': 100, 'leads': 5},
            ],
        },
        [
            {'offer': 'Get Business Coverage', 'sub3': '111111111', 'revenue': '150', 'conversion_date': '2026-09-14T08:00:00+00:00'},
            {'offer': 'Get Business Coverage', 'sub3': '222222222', 'revenue': '150', 'conversion_date': '2026-09-14T08:00:00+00:00'},
        ],
        {'Get Business Coverage'},
        include_metadata=True,
        redtrack_rows=[],
    )

    assert len(result['niches']) == 2
    for niche in result['niches']:
        assert len(niche['timing_blocks']) == 24, f"{niche['niche']} got {len(niche['timing_blocks'])} blocks, expected 24"
        groups = {block['group'] for block in niche['timing_blocks']}
        assert groups == {'Mon–Fri', 'Sat–Sun'}, f"{niche['niche']} missing a group: {groups}"

    assert len(result['campaigns']) == 2
    for campaign in result['campaigns']:
        assert len(campaign['timing_blocks']) == 24
        for adset in campaign['adsets']:
            assert len(adset['timing_blocks']) == 24


def test_best_times_excludes_orphaned_billing_rows_without_blocking_verified_timing():
    result = _build_best_times(
        {
            'adsets': {'987654321': {'adset_name': 'HVAC', 'campaign_name': 'HVAC'}},
            'rows': [{'adset_id': '987654321', 'date': '2026-09-15', 'hour': 8, 'spend': 100, 'leads': 5}],
        },
        [
            {'offer': 'Get Business Coverage', 'sub3': '987654321', 'revenue': '100', 'conversion_date': '2026-09-15T08:00:00+00:00'},
            {'offer': 'Get Business Coverage', 'sub3': 'orphaned-adset', 'revenue': '25', 'conversion_date': '2026-09-15T08:00:00+00:00'},
        ],
        {'Get Business Coverage'},
        include_metadata=True,
        redtrack_rows=[
            {'sub2': '987654321', 'offer': 'Commercial Insurance - Get Business Coverage - GBC - V2', 'conv_time': '2026-09-15T08:00:00+00:00', 'payout': '20'},
        ],
    )

    assert result['attribution_complete'] is True
    assert result['excluded_conversion_count'] == 1
    assert result['excluded_revenue'] == 25.0
