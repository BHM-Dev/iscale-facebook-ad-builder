"""Brand-scraper media fetches go through safe_fetch (2026-11-01 review).

Asserts the guard is actually called — a connection-refused on 127.0.0.1 would
make a weaker test pass against the old plain-httpx code too."""
import asyncio

from app.services import safe_fetch
from app.services.brand_scraper import BrandScraperService


def _recording_guard(monkeypatch):
    calls = []

    def fake_fetch_bytes(url, **kwargs):
        calls.append((url, kwargs))
        raise safe_fetch.UnsafeFetchError("blocked for test")

    monkeypatch.setattr(safe_fetch, "fetch_bytes", fake_fetch_bytes)
    return calls


def test_media_download_goes_through_safe_fetch(monkeypatch):
    calls = _recording_guard(monkeypatch)
    uploaded = []

    async def fake_upload(self, content, filename, media_type):
        uploaded.append(filename)
        return "r2://x"

    monkeypatch.setattr(BrandScraperService, "_upload_to_r2", fake_upload)
    s = BrandScraperService(db=None)
    r2, kind = asyncio.run(s._download_and_upload_media("http://169.254.169.254/x.mp4", "f", "1", 0))
    assert r2 is None and kind == "image"
    assert uploaded == []
    assert calls and calls[0][0] == "http://169.254.169.254/x.mp4"
    assert calls[0][1]["max_bytes"] == 100 * 1024 * 1024  # video cap


def test_snapshot_fetch_goes_through_safe_fetch(monkeypatch):
    calls = _recording_guard(monkeypatch)
    s = BrandScraperService(db=None)
    assert asyncio.run(s._extract_media_from_snapshot("http://127.0.0.1/snapshot")) == []
    assert calls and calls[0][1]["max_bytes"] == 20 * 1024 * 1024


def test_snapshot_success_path_extracts_media(monkeypatch):
    html = (b'<img src="https://scontent.xx.fbcdn.net/v/a.jpg?x=1">'
            b'<img src="https://other.example.com/b.jpg">'
            b'<video src="https://video.xx.fbcdn.net/v/c.mp4?y=2">')
    monkeypatch.setattr(safe_fetch, "fetch_bytes", lambda url, **kw: (html, "text/html"))
    urls = asyncio.run(BrandScraperService(db=None)._extract_media_from_snapshot("https://www.facebook.com/ads/archive/x"))
    assert urls == ["https://scontent.xx.fbcdn.net/v/a.jpg?x=1", "https://video.xx.fbcdn.net/v/c.mp4?y=2"]
