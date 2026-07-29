# Codex Brief: `/pnl/months` is failing in production

**Symptom:** the Month Over Month table on `/pnl` shows "Month history unavailable." Codex's own QA pass measured 12–24s loads before it tipped over into outright failure. Verified failing live 2026-07-29 against `act_521142087204815`.

**Why it matters:** this is the view Steve uses to judge whether the account is actually profitable over time. The summary tiles work; the history doesn't.

The page no longer *hangs* on it — commit `6a92ece` decoupled the two fetches, so the tiles render and the table fails independently. That stopped the bleeding. It did not fix the endpoint.

---

## Diagnosis

`get_months` builds 6 periods and calls `_summary` once per period. Each `_summary` makes **two sequential external HTTP calls**:

1. `_spend_for_account` → `FacebookService().get_account_insights_bulk()` — one Meta Graph call
2. `_revenue_for_account` → `_redtrack_revenue` → `_live_redtrack_report` — one RedTrack call

So a `limit=6` request is **12 sequential external calls**, plus more if any period has an all-account cost entry (`_spend_map` then walks every active account, and there are six accounts).

Everflow is already fixed — `_everflow_monthly_revenue_cache` pulls the whole range once and buckets by month. **Do the same thing for the other two.** Note the account is currently on RedTrack, not Everflow (env vars aren't set on the VPS yet), so the RedTrack path is the one actually hurting today.

---

## Step 0 — instrument first, do not optimise blind

Before changing anything, add timing so we know what actually dominates and whether it's latency or an error being swallowed.

Log per phase in `get_months`: total wall time, and for each month the Meta call duration, the revenue call duration, and the cost-resolution duration. `logger.info` is fine.

Then hit the endpoint and report the numbers. Two specific things to establish:

- **Is it slow, or is it erroring?** The frontend shows the same message for a non-2xx and a timeout. `_spend_for_account` raises on Meta failure by design, and `_summary` catches it per-month — but if something raises outside that guard, the whole request 500s.
- **Where does the request die?** uvicorn runs with `--timeout-keep-alive 300` (`backend/Dockerfile:51`) so it isn't uvicorn cutting it off at 60s. Suspect a reverse proxy in front of it on the VPS with a default 60s read timeout. If the timings add up to less than the point of failure, that's the answer and it's an infrastructure fix, not a code one — say so rather than optimising around it.

**Report the timings before writing the fix.** If Meta is 300ms and RedTrack is 11s, the work is entirely on the RedTrack side and half this brief is irrelevant.

---

## Fix A — batch the RedTrack calls (yours, safe)

Mirror the Everflow approach: one pull for the whole range, bucketed by month.

The blocker to check first: `_live_redtrack_report` requests `group=sub2`, which returns pre-aggregated totals per ad set with **no date dimension** — so its response cannot be bucketed by month. You need a date breakdown in the same response. Check whether RedTrack's `/report` accepts a compound group (`group=sub2,date` or similar) or a `date_breakdown`-style parameter. `RedTrackService.get_report_by_sub` may already hint at the shape.

- **If a date dimension is available:** one call for the whole range, bucket client-side, exactly like `_everflow_monthly_revenue_cache`. Best outcome — 6 calls become 1.
- **If it is not:** fall back to running the 6 calls concurrently with a `ThreadPoolExecutor` (max ~6 workers). `_live_redtrack_report` uses plain `httpx` with no shared client and no global state, so it is safe to thread. 6 sequential becomes roughly 1 call's latency.

Either way, keep the existing semantics: a failed revenue call must still produce `data_incomplete` for that month rather than a silent $0. Do not let a batch failure turn six months into six confident zeros.

## Fix B — one Meta call instead of six (NOT yours)

Meta Insights supports `time_increment` (`1`, `7`, `28`, `monthly`, `all_days`). A single request with a 6-month `time_range` and `time_increment='monthly'` returns one row per month — six calls collapse to one.

**This touches `backend/app/services/facebook_service.py`, which is a trigger file. Do not edit it.** Hand it to Claude Code with your timing numbers.

**Do NOT parallelise the Meta calls as a workaround.** `FacebookService.__init__` calls `FacebookAdsApi.init(...)`, which mutates global SDK state in `facebook-business`. Constructing several instances across threads races on that global and can misroute requests or use the wrong token. Threading the RedTrack calls is fine; threading Meta is not.

## Fix C — cache closed months (yours, optional, do last)

A closed month's spend and revenue never change. Once A and B land, measure again — if it's fast enough, stop. If not, cache closed-month results keyed by `(account_id, month, provider)`. In-process TTL is fine and needs no migration; losing it on container restart is acceptable. Do not add a table for this without asking.

---

## Constraints

- **Do not reduce `limit` below 6.** Steve explicitly wants the long view; making the endpoint fast by showing less is not a fix.
- **Do not change what the numbers mean.** Revenue semantics were settled 2026-07-29 and reconcile to the Switchboard portal to the cent (`1e8d829`). This is purely about how fast and how reliably they arrive.
- **Do not add tiles, columns, or CPLs.** Scope guard in `CODEX_BRIEF_pnl_everflow_revenue.md` still applies.
- Do not touch `models.py`, `main.py`, `backend/alembic/versions/`, or the four trigger files.
- No migration. If your answer needs one, stop and say so.
- **Do not push.** Hand back to Claude Code.

## Definition of done

`/pnl/months` returns 6 months reliably, and you can state its measured wall time before and after. If the remaining time is dominated by the single Meta call that only Claude Code can fix, say that explicitly and hand over — a partial fix with clear numbers is a good outcome here.
