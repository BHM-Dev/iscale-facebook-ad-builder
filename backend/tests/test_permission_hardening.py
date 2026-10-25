"""2026-10-25 hardening: write permissions, account scoping, caps, and the media-URL (SSRF) fetch path.

Calls the REAL routes through FastAPI's TestClient with a fake logged-in user, so a missing or wrong dependency shows up
as a wrong status code. No database or Meta access: dependencies that would touch them are replaced.
"""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import deps
from app.main import app

client = TestClient(app, raise_server_exceptions=False)   # no context manager -> startup (DB connect) never runs


class FakeUser:
    def __init__(self, perms=(), superuser=False, allowed=None):
        self.id = "u-test"
        self.is_active = True
        self.is_superuser = superuser
        self._perms = set(perms)
        self._allowed = allowed

    def has_permission(self, name):
        return self.is_superuser or name in self._perms

    def allowed_account_ids(self):
        return self._allowed


@pytest.fixture
def as_user():
    def _set(user):
        app.dependency_overrides[deps.get_current_active_user] = lambda: user
        return user
    yield _set
    app.dependency_overrides.clear()


# (method, path, permission it must demand)
GATED = [
    ("post", "/api/v1/auto-pause/rules", "campaigns:write"),
    ("post", "/api/v1/auto-pause/rules/bulk", "campaigns:write"),
    ("patch", "/api/v1/auto-pause/rules/some-id", "campaigns:write"),
    ("delete", "/api/v1/auto-pause/rules/some-id", "campaigns:write"),
    ("post", "/api/v1/facebook/push-to-meta", "campaigns:write"),
    ("post", "/api/v1/capi-quality/sync", "campaigns:write"),
    ("post", "/api/v1/templates/bulk-delete", "templates:delete"),
    ("post", "/api/v1/prompts/", "templates:write"),
    ("put", "/api/v1/prompts/some-id", "templates:write"),
    ("delete", "/api/v1/prompts/some-id", "templates:delete"),
    ("post", "/api/v1/ad-styles/", "templates:write"),
    ("put", "/api/v1/ad-styles/some-id", "templates:write"),
    ("delete", "/api/v1/ad-styles/some-id", "templates:delete"),
    ("post", "/api/v1/ad-copy-library/sync", "ads:write"),
    ("patch", "/api/v1/ad-copy-library/some-id/pin", "ads:write"),
    ("delete", "/api/v1/ad-copy-library/some-id", "ads:delete"),
    ("post", "/api/v1/drive-assets/sync-now", "ads:write"),
    ("post", "/api/v1/drive-assets/refresh-copy-metadata", "ads:write"),
]


@pytest.mark.parametrize("method,path,perm", GATED)
def test_mutating_routes_demand_their_permission(as_user, method, path, perm):
    as_user(FakeUser(perms=["campaigns:read"]))   # a read-only user
    r = client.request(method.upper(), path, json={})
    assert r.status_code == 403, f"{method.upper()} {path} let a read-only user in ({r.status_code})"
    assert perm in r.text, f"{method.upper()} {path} demanded something other than {perm}: {r.text[:120]}"


@pytest.mark.parametrize("method,path,perm", GATED)
def test_holding_the_permission_gets_past_the_gate(as_user, method, path, perm):
    as_user(FakeUser(perms=[perm]))
    r = client.request(method.upper(), path, json={})
    assert r.status_code != 403 and r.status_code != 401   # may 404/422/500 afterwards (no DB) — the gate is what's tested


def test_test_kie_is_superuser_only(as_user):
    as_user(FakeUser(perms=["ads:write", "campaigns:write"]))
    assert client.get("/api/v1/generated-ads/test-kie").status_code == 403


def test_auto_pause_reads_need_only_an_active_user(as_user):
    as_user(FakeUser(perms=[]))
    r = client.get("/api/v1/auto-pause/rules")
    assert r.status_code not in (401, 403)


# ---- push-to-meta status validation ----------------------------------------------------------------------------
@pytest.fixture
def push_ready(as_user):
    from app.api.v1.facebook import get_facebook_service
    as_user(FakeUser(perms=["campaigns:write"]))
    app.dependency_overrides[get_facebook_service] = lambda: object()
    app.dependency_overrides[deps.get_db] = lambda: object()
    yield


@pytest.mark.parametrize("bad", ["DELETED", "ARCHIVED", "paused-ish", "WITH_ISSUES", "ACTIVE ", "pa used"])
def test_push_to_meta_rejects_statuses_that_are_not_active_or_paused(push_ready, bad):
    r = client.post("/api/v1/facebook/push-to-meta", json={"adset_id": "1", "request_id": "r1", "status": bad})
    if bad.strip().upper() in ("ACTIVE",):                       # 'ACTIVE ' is tidied to ACTIVE and accepted, then fails later on other fields
        assert "ACTIVE or PAUSED" not in r.text
    else:
        assert r.status_code == 400 and "ACTIVE or PAUSED" in r.text


def test_push_to_meta_blank_status_falls_back_to_the_safe_default(push_ready):
    r = client.post("/api/v1/facebook/push-to-meta", json={"request_id": "r1", "status": "   "})   # no adset_id -> stops at the next check
    assert r.status_code == 400 and "adset_id is required" in r.text and "ACTIVE or PAUSED" not in r.text


def test_push_to_meta_accepts_lowercase_active_and_null_falls_back_to_paused(push_ready):
    for ok in ("active", "Paused", None):
        r = client.post("/api/v1/facebook/push-to-meta", json={"request_id": "r1", "status": ok})   # no adset_id: stops at the NEXT check
        assert r.status_code == 400 and "adset_id is required" in r.text, (ok, r.text)


# ---- AI insights ------------------------------------------------------------------------------------------------
def test_ai_insights_blocks_an_account_outside_the_users_scope(as_user, monkeypatch):
    from app.api.v1 import ai_insights
    monkeypatch.setattr(ai_insights, "_anthropic_client", object())
    app.dependency_overrides[deps.get_db] = lambda: object()
    as_user(FakeUser(allowed={"act_111"}))
    r = client.post("/api/v1/ai-insights/query", json={"query": "how are we doing?", "ad_account_id": "act_222"})
    assert r.status_code == 403


def test_ai_insights_query_length_is_capped(as_user):
    as_user(FakeUser())
    assert client.post("/api/v1/ai-insights/query", json={"query": "x" * 1501}).status_code == 422
    assert client.post("/api/v1/ai-insights/query", json={"query": ""}).status_code == 422


def test_ai_insights_rate_limit_blocks_a_flood_but_not_a_person():
    from fastapi import HTTPException
    from app.api.v1 import ai_insights as ai
    uid = "flood-test"
    ai._AI_CALLS.pop(uid, None)
    for _ in range(ai.AI_QUERY_MAX_PER_WINDOW):
        ai._ai_rate_limit(uid)
    with pytest.raises(HTTPException) as exc:
        ai._ai_rate_limit(uid)
    assert exc.value.status_code == 429
    ai._AI_CALLS.pop(uid, None)


# ---- image-generation caps (the UI's own maxima: 10 variations, 3 sizes) ---------------------------------------------
def test_generation_caps_match_the_ui_and_stop_abuse():
    from app.api.v1.generated_ads import ImageGenerationRequest as R
    size = {"width": 1080, "height": 1080, "name": "Square"}
    assert R(count=10, imageSizes=[size] * 3).count == 10                  # the most the wizard can ask for
    assert R(count=1, imageSizes=[size]).count == 1                        # what Batch Generate / Remix send
    assert R().count == 1                                                  # defaults still valid
    for bad in (dict(count=11), dict(count=0), dict(count=-1), dict(count=100000),
                dict(imageSizes=[size] * 7), dict(count=10, imageSizes=[size] * 4),   # 40 images in one request
                dict(productShots=["u"] * 51)):
        with pytest.raises(ValidationError):
            R(**bad)


def test_generate_image_route_rejects_a_runaway_request_before_doing_any_work(as_user):
    as_user(FakeUser(perms=["ads:write"]))
    r = client.post("/api/v1/generated-ads/generate-image", json={"count": 100000, "imageSizes": [{"name": "s"}] * 50})
    assert r.status_code == 422


# ---- crop-to-aspect SSRF ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/", "https://127.0.0.1/a.png", "http://localhost:8000/api/v1/users",
    "https://10.0.0.5/a.png", "file:///etc/passwd", "https://evil.example.com/a.png", "gopher://x/",
])
def test_crop_to_aspect_never_fetches_internal_or_unapproved_urls(as_user, monkeypatch, url):
    import requests
    as_user(FakeUser())
    attempted = []

    def spy(*a, **k):
        attempted.append(a[0] if a else k.get("url"))
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(requests, "get", spy)
    r = client.post("/api/v1/uploads/crop-to-aspect", data={"target_ratio": "1:1", "source_url": url})
    assert r.status_code == 400
    # The point of the fix: the server must not even TRY to connect. (An old-style fetch would call requests.get here
    # and merely fail afterwards with the same 400, so the status code alone proves nothing.)
    assert attempted == [], f"the server attempted to fetch {attempted}"
