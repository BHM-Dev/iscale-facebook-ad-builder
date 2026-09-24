"""Pure regression tests for external competitor-research import guards."""

from app.api.v1.research import _external_destination_domain, _normalize_external_url, _resolve_external_import_vertical


def test_external_import_normalizes_scheme_less_destination_urls():
    assert _normalize_external_url("example.test/quote") == "https://example.test/quote"
    assert _external_destination_domain("example.test/quote") == "example.test"
    assert _external_destination_domain("https://sub.example.test/quote") == "sub.example.test"
    assert _external_destination_domain("/relative-path") is None
    assert _normalize_external_url("javascript:alert(1)") == ""


def test_external_import_only_accepts_browse_reachable_vertical_labels():
    assert _resolve_external_import_vertical("commercial insurance") == "Commercial Insurance"
    assert _resolve_external_import_vertical("Gutters") == "Gutters"
    assert _resolve_external_import_vertical("Commercial Lines") is None
