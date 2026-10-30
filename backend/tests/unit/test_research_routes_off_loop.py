"""Research search routes are plain def and run the async scraper on a private loop (2026-10-30)."""
import asyncio
import inspect

from app.api.v1 import research


def test_routes_are_sync_so_fastapi_runs_them_in_the_threadpool():
    for fn in (research.search_ads, research.search_and_save, research.run_scheduled_searches,
               research.capture_advertiser_for_research, research.search_and_save_vertical):
        assert not inspect.iscoroutinefunction(fn), fn.__name__


def test_search_ads_runs_the_async_service(monkeypatch):
    monkeypatch.setattr(research, "_reserve_api_budget", lambda db, n: None)

    async def fake_search(self, request):
        await asyncio.sleep(0)
        return ["ad"]

    monkeypatch.setattr(research.ResearchService, "search_ads_async", fake_search)
    req = research.AdSearchRequest(query="x", limit=1)

    async def from_running_loop():
        # FastAPI calls a def route from a worker thread while the main loop keeps serving.
        return await asyncio.to_thread(research.search_ads, req, db=None, current_user=None)

    assert asyncio.run(from_running_loop()) == ["ad"]
