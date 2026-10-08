import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import research as r
from app.core.redact import redact_secrets
from app.schemas.research import AdSearchRequest, BrandScrapeCreate


def test_search_limit_is_capped():
    assert AdSearchRequest(query="x", limit=300).limit == 300
    for bad in (0, 301, 100000):
        with pytest.raises(ValidationError):
            AdSearchRequest(query="x", limit=bad)
    with pytest.raises(ValidationError):
        AdSearchRequest(query="x", offset=10**6)
    with pytest.raises(ValidationError):
        AdSearchRequest(query="x" * 301)


def test_brand_scrape_input_bounds():
    with pytest.raises(ValidationError):
        BrandScrapeCreate(brand_name="", page_url="https://facebook.com/ads/library")
    with pytest.raises(ValidationError):
        BrandScrapeCreate(brand_name="a", page_url="u" * 2001)


def test_redact_secrets_strips_tokens():
    url = "Client error '400' for url 'https://graph.facebook.com/v24.0/ads_archive?search_terms=x&access_token=EAAB123abc&limit=300'"
    out = redact_secrets(url)
    assert "EAAB123abc" not in out and "access_token=***" in out and "limit=300" in out


def test_in_flight_claim_is_exclusive_and_releasable():
    key = "test:key"
    assert r._claim_in_flight(key) is True
    assert r._claim_in_flight(key) is False
    r._release_in_flight(key)
    assert r._claim_in_flight(key) is True
    r._release_in_flight(key)


def test_copilot_rate_limit_blocks_after_max():
    uid = "test-user-copilot"
    r._COPILOT_CALLS.pop(uid, None)
    for _ in range(r.COPILOT_MAX_CALLS):
        r._copilot_rate_limit(uid)
    with pytest.raises(HTTPException) as exc:
        r._copilot_rate_limit(uid)
    assert exc.value.status_code == 429
    r._COPILOT_CALLS.pop(uid, None)


class _U:
    def __init__(self, superuser=False, perms=()):
        self.is_superuser = superuser
        self._p = set(perms)

    def has_permission(self, name):
        return name in self._p


def test_delete_access_requires_superuser_or_ads_delete():
    r._require_delete_access(_U(superuser=True))
    r._require_delete_access(_U(perms=["ads:delete"]))
    with pytest.raises(HTTPException) as exc:
        r._require_delete_access(_U(perms=["ads:write"]))
    assert exc.value.status_code == 403


def test_redact_covers_json_and_bearer():
    assert "SECRET123" not in redact_secrets('{"access_token": "SECRET123", "x": 1}')
    assert "SECRET123" not in redact_secrets("Authorization: Bearer SECRET123")
    assert "SECRET123" not in redact_secrets("https://x/y?api_key=SECRET123&a=1")


def test_rate_limiter_counts_real_usage_rows():
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import ApiUsageLog
    from app.services.rate_limiter import RateLimiter

    engine = create_engine("sqlite://")
    ApiUsageLog.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    rl = RateLimiter(max_calls=10, window_minutes=59)
    now = datetime.now(timezone.utc)

    assert rl.check_limit(db) == (True, 10, 0)
    db.add(ApiUsageLog(endpoint="facebook_ads_library", api_calls=6, ads_returned=0, ads_saved=0, date="d", created_at=now - timedelta(minutes=5)))
    db.add(ApiUsageLog(endpoint="facebook_ads_library", api_calls=99, ads_returned=0, ads_saved=0, date="d", created_at=now - timedelta(minutes=120)))  # outside window
    db.commit()
    allowed, remaining, reset = rl.check_limit(db)
    assert (allowed, remaining) == (True, 4)

    db.add(ApiUsageLog(endpoint="facebook_ads_library", api_calls=4, ads_returned=0, ads_saved=0, date="d", created_at=now - timedelta(minutes=1)))
    db.commit()
    allowed, remaining, reset = rl.check_limit(db)
    assert allowed is False and remaining == 0 and 0 < reset <= 59 * 60
    assert rl.get_usage_stats(db)["used"] == 10


class _FakeSvc:
    def __init__(self, data=None, boom=False):
        self.calls = 0
        self.data = data
        self.boom = boom

    def get_ad_lifetime_insights(self, ad_id):
        self.calls += 1
        if self.boom:
            raise RuntimeError("Meta says no: access_token=SECRET123")
        return self.data


def test_outcome_insights_cached_and_errors_isolated():
    r._OUTCOME_CACHE.clear()
    ok = _FakeSvc({"spend": 60.0, "leads": 3, "cpl": 20.0, "date_start": "2026-10-01"})
    assert r._ad_lifetime_insights_cached(ok, "111") == (ok.data, None)
    assert r._ad_lifetime_insights_cached(ok, "111") == (ok.data, None)
    assert ok.calls == 1  # second read served from cache

    none = _FakeSvc(None)
    assert r._ad_lifetime_insights_cached(none, "222") == (None, None)  # no delivery yet is cached, not an error
    assert r._ad_lifetime_insights_cached(none, "222") == (None, None) and none.calls == 1

    bad = _FakeSvc(boom=True)
    assert r._ad_lifetime_insights_cached(bad, "333") == (None, "unavailable")
    assert r._ad_lifetime_insights_cached(bad, "333") == (None, "unavailable")
    assert bad.calls == 1  # failure backs off for 60 s instead of re-hitting Meta every page load
    r._OUTCOME_CACHE["333"] = (r._OUTCOME_CACHE["333"][0] - r._OUTCOME_FAILURE_TTL - 1, "__error__")
    ok2 = _FakeSvc({"spend": 1.0, "leads": 0, "cpl": None, "date_start": "2026-10-01"})
    assert r._ad_lifetime_insights_cached(ok2, "333")[1] is None and ok2.calls == 1  # retried after the backoff
    r._OUTCOME_CACHE.clear()


def test_learnings_aggregation_skips_unknowns_and_derates_single_tests():
    src_a = {"hook_type": "question", "promise": "save", "angle_tag": "rate_shock"}
    src_b = {"hook_type": "question"}
    pairs = [
        (src_a, {"spend": 100.0, "leads": 10, "revenue": 150.0, "profit": 50.0}),
        (src_b, {"spend": 50.0, "leads": 5, "profit": None}),   # unknown profit stays unknown, not $0
        (src_a, {"spend": None, "leads": None, "profit": 999.0}),  # no readable spend -> not counted
        ({"hook_type": "story"}, {"spend": 10.0, "leads": 1, "profit": 9999.0}),  # single test must not top the table
    ]
    rows = r._aggregate_learnings(pairs)
    question = next(x for x in rows if x["attribute"] == "hook type" and x["value"] == "question")
    assert question["tests"] == 2 and question["spend"] == 150.0 and question["leads"] == 15
    assert question["cpl"] == 10.0 and question["rpl"] is None and question["contribution"] is None
    assert question["profit"] == 50.0 and question["too_early"] is False
    story = next(x for x in rows if x["value"] == "story")
    assert story["too_early"] is True
    assert rows[0]["value"] == "question"  # 2-test row ranks above the 1-test row despite lower profit
    only_unknown = r._aggregate_learnings([(src_b, {"spend": 5.0, "leads": 0, "profit": None})])
    assert only_unknown[0]["profit"] is None and only_unknown[0]["cpl"] is None


def test_source_image_allowlist_blocks_private_and_unapproved_hosts(monkeypatch):
    from app.services import ad_remix_service as service

    monkeypatch.setattr(service.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    assert service.validate_source_image_url("https://scontent-lga3-1.xx.fbcdn.net/image.jpg")
    with pytest.raises(ValueError, match="approved"):
        service.validate_source_image_url("https://example.com/image.jpg")

    monkeypatch.setattr(service.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="private or reserved"):
        service.validate_source_image_url("https://scontent-lga3-1.xx.fbcdn.net/image.jpg")
