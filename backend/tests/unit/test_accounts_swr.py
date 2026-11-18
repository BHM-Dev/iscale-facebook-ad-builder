import threading
import time
from types import SimpleNamespace

from app.api.v1 import facebook as fb


class FakeService:
    def __init__(self):
        self.calls = 0
        self.done = threading.Event()

    def get_ad_accounts(self):
        self.calls += 1
        self.done.set()
        return [{"id": "act_2", "name": "New"}]


def test_expired_list_is_served_at_once_and_refreshed_in_background(monkeypatch):
    monkeypatch.setattr(fb, "_filter_accounts_for_user", lambda accounts, user: accounts)
    monkeypatch.setattr(fb, "HIDDEN_ACCOUNT_IDS", set())
    old = [{"id": "act_1", "name": "Old"}]
    with fb._accounts_cache_lock:
        fb._accounts_cache.update(data=old, ts=time.monotonic() - fb._ACCOUNTS_CACHE_TTL_SECONDS - 5, backoff_until=0.0)
    svc = FakeService()
    first = fb.get_ad_accounts(service=svc, current_user=SimpleNamespace())
    assert [a["id"] for a in first] == ["act_1"]          # no wait on Meta
    assert svc.done.wait(2)
    for _ in range(50):
        if not fb._accounts_refresh_lock.locked():
            break
        time.sleep(0.01)
    second = fb.get_ad_accounts(service=svc, current_user=SimpleNamespace())
    assert [a["id"] for a in second] == ["act_2"] and svc.calls == 1
