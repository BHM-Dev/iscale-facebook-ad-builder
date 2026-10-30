"""Pixels/Pages per-account cache in facebook.py (2026-10-30)."""
from app.api.v1 import facebook as fb


def test_pages_cached_per_account_and_refresh_bypasses(monkeypatch):
    fb._meta_list_cache.clear()
    calls = []

    class Svc:
        def get_pages(self, acct):
            calls.append(acct)
            return [{"id": "p1", "name": "Page", "access_token": "secret"}]

    monkeypatch.setattr(fb, "_assert_account_allowed", lambda u, a: None)
    monkeypatch.setattr(fb, "_resolve_scoped_default_account", lambda u, a: a)
    first = fb.read_pages(ad_account_id="act_1", refresh=False, service=Svc(), current_user=None)
    assert first == [{"id": "p1", "name": "Page"}]           # token stripped
    first[0]["name"] = "mutated"
    assert fb.read_pages(ad_account_id="act_1", refresh=False, service=Svc(), current_user=None)[0]["name"] == "Page"
    assert calls == ["act_1"]
    fb.read_pages(ad_account_id="act_2", refresh=False, service=Svc(), current_user=None)
    fb.read_pages(ad_account_id="act_1", refresh=True, service=Svc(), current_user=None)
    assert calls == ["act_1", "act_2", "act_1"]
    assert all("access_token" not in item for _, data in fb._meta_list_cache.values() for item in data)
