# Codex Brief: make `/pnl/months` faster

**Supersedes `CODEX_BRIEF_pnl_months_latency.md`.** That brief's Step 0 is done — your instrumentation is committed and on `develop` — and its premise was wrong. Read this one instead.

## What changed since that brief

**The endpoint was never failing.** Measured 2026-07-29 against `act_521142087204815` with a live token from the browser:

| Request | Wall time | Result |
|---|---|---|
| `/pnl/summary` (1 period) | 8.2s | 200 |
| `/pnl/months?limit=1` | 8.9s | 200 |
| `/pnl/months?limit=2` | 12.6s | 200 |
| `/pnl/months?limit=3` | 18.1s | 200 |
| `/pnl/months?limit=6` | **23.3s** | **200, all six months** |

So: **~6s fixed cost, then ~2.9s per additional month.** No proxy timeout, no error, no truncation.

The "Month history unavailable" report was an **auth refresh race**, unrelated to this endpoint — two concurrent requests after token expiry both sent the same rotating refresh token, and the loser's request was dropped. Fixed in `3132a10`. Don't chase it.

**This is now a pure performance task, and it is not urgent.** The page no longer blocks on it (`6a92ece` decoupled the fetches), so the numbers render while the table fills in behind. Do it well, not fast.

## The work

Each month still costs one Meta call plus one revenue call, run sequentially. That ~2.9s marginal is those two.

I could not split Meta vs RedTrack per phase — that needs the VPS logs, which requires Golden. Don't block on it. The marginal cost is clearly two sequential network round trips and both are worth removing.

### Yours: batch or parallelise the RedTrack calls

The account is on RedTrack today (Switchboard env vars aren't set yet), so this is the live path.

First check whether one call can cover the whole range. `_live_redtrack_report` requests `group=sub2`, which returns pre-aggregated per-ad-set totals with **no date dimension**, so its response can't be split by month. Find out whether RedTrack's `/report` accepts a compound group (`group=sub2,date`) or a date-breakdown parameter — `RedTrackService.get_report_by_sub` may hint at the shape.

- **If yes:** one call for the whole range, bucket by month client-side. Copy the shape of `_everflow_monthly_revenue_cache`, which already does exactly this for Everflow. Six calls become one.
- **If no:** run the six concurrently with a `ThreadPoolExecutor` (max ~6). `_live_redtrack_report` uses plain `httpx` with no shared client or global state, so it's safe to thread.

Keep the failure semantics: a failed revenue call must still yield `data_incomplete` for that month, never a silent $0. Don't let one batch failure turn six months into six confident zeros.

### Mine, not yours: the Meta side

One request with `time_increment='monthly'` over a six-month range returns a row per month — six calls become one. That's in `facebook_service.py`, a trigger file. **Don't touch it.**

And **don't parallelise the Meta calls** as a workaround: `FacebookService.__init__` calls `FacebookAdsApi.init(...)`, which mutates global SDK state. Concurrent construction races on it and can use the wrong token.

### Optional, last: cache closed months

A closed month never changes. If it's still slow after the above, cache by `(account_id, month, provider)`. In-process TTL is fine — no migration, and losing it on restart is acceptable. Don't add a table without asking.

## Constraints

- Don't reduce `limit` below 6. Steve wants the long view; showing less isn't a fix.
- Don't change what any number means. Revenue semantics are settled and reconcile to the Switchboard portal to the cent (`1e8d829`).
- No new tiles, columns or CPLs. Scope guard in `CODEX_BRIEF_pnl_everflow_revenue.md` still applies.
- Don't touch `models.py`, `main.py`, `backend/alembic/versions/`, or the four trigger files.
- No migration. If your answer needs one, stop and say so.
- **Don't push.** Hand back to Claude Code.

## Done means

Report the measured wall time for `limit=6` before and after, using the same method (browser fetch with a live token, or your own equivalent). If what's left is dominated by the single Meta call only Claude Code can fix, say so and hand over — a partial fix with real numbers is a good outcome.
