from app.api.v1.usage import normalize_path


def test_normalize_path_strips_query_and_ids():
    assert normalize_path("/campaign-performance?tab=winners") == "/campaign-performance"
    assert normalize_path("/research/123456") == "/research/:id"
    assert normalize_path("/x/act_521142087204815") == "/x/:id"
    assert normalize_path("/feedback/8a280d8f-1234-4abc-9def-0123456789ab") == "/feedback/:id"
    assert normalize_path("/") == "/"


def test_normalize_path_rejects_non_app_paths():
    assert normalize_path("https://evil.example/") is None
    assert normalize_path("//evil.example") is None
    assert normalize_path("/a<script>") is None
    assert normalize_path(None) is None
