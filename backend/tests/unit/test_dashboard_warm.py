import time

from app.api.v1 import auto_pause as ap


def test_warmed_key_is_served_past_default_ttl():
    key = ("act_x", "2026-11-18", "2026-11-18", True, True)
    ap._insights_bulk_cache.clear()
    ap._insights_bulk_ttl.clear()
    ap._insights_bulk_cache[key] = (time.monotonic() - 120, time.monotonic() - 121, {"a": 1})
    assert ap._read_insights_bulk_cache(key, False) is None            # default 60s: expired
    ap._insights_bulk_cache[key] = (time.monotonic() - 120, time.monotonic() - 121, {"a": 1})
    ap._insights_bulk_ttl[key] = 360
    assert ap._read_insights_bulk_cache(key, False) == {"a": 1}       # warmed: still served
    assert ap._read_insights_bulk_cache(key, True) is None             # Refresh always bypasses


def test_warm_builds_both_permission_variants_and_never_raises(monkeypatch):
    calls = []

    def fake_build(db, account_id, preset, df, dt, refresh, include_niche, can_pnl, warm_ttl=None):
        calls.append((account_id, preset, can_pnl, warm_ttl))
        if can_pnl is False:
            raise RuntimeError("meta down")
        return {}

    monkeypatch.setattr(ap, "build_insights_bulk", fake_build)

    class DB:
        def rollback(self):
            pass

    out = ap.warm_dashboard_insights(DB(), ["act_1"], [("today", 360)])
    assert calls == [("act_1", "today", True, 360), ("act_1", "today", False, 360)]
    assert out["act_1:today:pnl"] == "ok" and out["act_1:today:nopnl"].startswith("failed")


def test_recent_dashboard_accounts_newest_first_and_capped():
    ap._recent_dashboard_accounts.clear()
    now = time.monotonic()
    for i in range(6):
        ap._recent_dashboard_accounts[f"act_{i}"] = now - 10 * (6 - i)
    assert ap.recent_dashboard_accounts(limit=4) == ["act_5", "act_4", "act_3", "act_2"]


def test_user_write_drops_warm_ttl_and_throttle_backs_off(monkeypatch):
    ap._insights_bulk_ttl.clear()
    ap._warm_backoff_until.clear()
    calls = []

    def throttled(db, account_id, preset, df, dt, refresh, include_niche, can_pnl, warm_ttl=None):
        calls.append(account_id)
        raise RuntimeError("Facebook API: (#17) User request limit reached")

    monkeypatch.setattr(ap, "build_insights_bulk", throttled)

    class DB:
        def rollback(self):
            pass

    ap.warm_dashboard_insights(DB(), ["act_9"], [("today", 360)])
    assert "act_9" in ap._warm_backoff_until
    before = len(calls)
    out = ap.warm_dashboard_insights(DB(), ["act_9"], [("today", 360)])
    assert len(calls) == before and out == {"act_9:*": "skipped: Meta throttled recently"}
