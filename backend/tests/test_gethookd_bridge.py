"""GetHookd bridge: reference-only, never leaks the competitor's landing page, clear errors without a key."""
import asyncio

import pytest
from fastapi import HTTPException

from app.api.v1 import gethookd as gh

AD = {
    "id": 149175265,
    "title": "Commercial Property Owners — Stop Overpaying",
    "body": "Protect your property...",
    "link_description": "Compare Commercial Insurance Quotes Instantly",
    "cta_type": "GET_QUOTE",
    "asset_type": "video",
    "status": "active",
    "days_active": 93,
    "performance_score_title": "Winning",
    "landing_page": "https://trk.leadstracked.com/abc?sub1={{ad.id}}",
    "share_url": "https://app.gethookd.ai/share/ad/149175265?signature=x",
    "primary_image_url": "https://app.gethookd.ai/api/v1/media/149175265/1/download?variant=thumbnail",
    "brand": {"name": "Compare Commercial Insurance Quotes"},
    "media": [{"id": 1, "type": "video", "thumbnail_url": "https://app.gethookd.ai/thumb", "download_url": "https://app.gethookd.ai/video"}],
}


def test_summary_never_carries_the_landing_page():
    summary = gh._ad_summary(AD)
    assert "landing_page" not in summary
    assert "leadstracked" not in str(summary)
    assert summary["headline"].startswith("Commercial Property") and summary["cta_type"] == "GET_QUOTE"
    assert summary["performance"] == "Winning" and summary["media_count"] == 1


@pytest.mark.parametrize("ref,expected", [
    ("https://app.gethookd.ai/share/ad/149175265?signature=abc", 149175265),
    ("149175265", 149175265),
    ("  42 ", 42),
])
def test_parse_ad_ref(ref, expected):
    assert gh.parse_ad_ref(ref) == expected


def test_parse_ad_ref_rejects_other_links():
    with pytest.raises(HTTPException) as exc:
        gh.parse_ad_ref("https://www.facebook.com/ads/library/?id=1")
    assert exc.value.status_code == 400


def test_no_key_is_a_clear_503(monkeypatch):
    monkeypatch.delenv("GETHOOKD_API_KEY", raising=False)
    assert gh.status(current_user=None) == {"connected": False}
    with pytest.raises(HTTPException) as exc:
        gh._get("/swipefile")
    assert exc.value.status_code == 503 and "not connected" in exc.value.detail


class _Resp:
    def __init__(self, status=200, json_data=None, content=b"", ctype="image/jpeg"):
        self.status_code, self._json, self.content = status, json_data, content
        self.headers = {"content-type": ctype}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("bad")


def test_bad_key_says_so(monkeypatch):
    monkeypatch.setenv("GETHOOKD_API_KEY", "k")
    monkeypatch.setattr(gh.httpx, "get", lambda *a, **k: _Resp(401))
    with pytest.raises(HTTPException) as exc:
        gh._get("/swipefile")
    assert "rejected the API key" in exc.value.detail


def test_reference_copies_poster_and_drops_landing_page(monkeypatch):
    monkeypatch.setenv("GETHOOKD_API_KEY", "k")
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        return _Resp(json_data={"data": AD})

    monkeypatch.setattr(gh.httpx, "get", fake_get)

    class _Stream:
        def __init__(self, url):
            fetched.append(url)
            self.headers = {"content-type": "image/jpeg"}
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def raise_for_status(self):
            pass
        def iter_bytes(self):
            yield b"jpeg"; yield b"bytes"

    monkeypatch.setattr(gh.httpx, "stream", lambda method, url, **k: _Stream(url))
    monkeypatch.setattr(gh.settings.__class__, "r2_enabled", property(lambda self: True))
    stored = {}

    async def fake_upload(content, filename, content_type):
        stored.update(content=content, filename=filename)
        return f"https://r2.example/{filename}"

    import app.api.v1.uploads as uploads
    monkeypatch.setattr(uploads, "upload_to_r2", fake_upload)
    out = asyncio.run(gh.make_reference(gh.ReferenceBody(ad_id=149175265), current_user=None))
    assert fetched[1] == "https://app.gethookd.ai/thumb"          # a video's poster frame, never the video file
    assert out["reference_image_url"].startswith("https://r2.example/references/gethookd-149175265-")
    assert stored["content"] == b"jpegbytes"
    assert "leadstracked" not in str(out) and out["thumbnail_url"] is None


def test_reference_never_fetches_off_host(monkeypatch):
    """The media URL comes from GetHookd's response; the token must never go to another host."""
    monkeypatch.setenv("GETHOOKD_API_KEY", "k")
    evil = {**AD, "media": [{"id": 1, "type": "image", "download_url": "https://evil.example/x.jpg"}], "primary_image_url": "http://169.254.169.254/"}
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        return _Resp(json_data={"data": evil})

    monkeypatch.setattr(gh.httpx, "get", fake_get)
    out = asyncio.run(gh.make_reference(gh.ReferenceBody(ad_id=149175265), current_user=None))
    assert fetched == ["https://app.gethookd.ai/api/v1/ads/149175265"]
    assert out["reference_image_url"] is None


def test_unreadable_response_is_a_clean_502(monkeypatch):
    monkeypatch.setenv("GETHOOKD_API_KEY", "k")

    class Bad(_Resp):
        def json(self):
            raise ValueError("html")

    monkeypatch.setattr(gh.httpx, "get", lambda *a, **k: Bad())
    with pytest.raises(HTTPException) as exc:
        gh._get("/swipefile")
    assert exc.value.status_code == 502
