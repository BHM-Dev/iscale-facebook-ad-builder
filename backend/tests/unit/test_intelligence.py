"""Pure tests for Campaign Intelligence naming and date-window helpers."""

from datetime import date

from app.api.v1.intelligence import _extract_niche, _resolve_preset


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
