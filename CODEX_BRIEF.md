# Codex Brief — Cap Geography's Weekdays/Weekends MTD to 14 days

## Why

Live-verified against production today (RHO - Commercial Insurance, 81 campaigns): the Geography
tab's Weekdays MTD / Weekends MTD presets reliably fail with "Meta API timeout — try again in a
moment" on this account. The recent timeout-recovery fix (`09696f5`, `1620188`) is working
correctly — it now fails cleanly in ~15-18s instead of hanging ~32s, and the UI never shows a
false-empty "no signals" state — but the underlying query still can't complete in time on an
account this size.

Root cause is scale, not a bug: `weekdays_mtd`/`weekends_mtd` both request the account-wide
Insights call (no `campaign_id` filter) with `breakdowns: ['region']` **and** `time_increment: 1`
for month-to-date (today: 23 days). That's roughly 81 campaigns × ~50 US states × 23 days of
per-day rows Meta has to assemble and paginate back, all inside one synchronous request. A
mid-tier API review flagged this exact risk before it was confirmed live: "expect this to fail
with a clean timeout on the weekday/weekend toggle for wide date ranges on busy accounts... the
cheapest fix is to require a campaign_id whenever day_filter != 'all', or cap that combination to
14 days. Moving to async is the proper fix for later."

Cap first (cheap, immediate) — async report runs are the correct long-term fix but bigger scope,
not this pass.

## Scope

`backend/app/api/v1/intelligence.py` (`_resolve_preset`, `geography_watchlist` route) and
`frontend/src/pages/CampaignPerformance.jsx` (`CampaignIntelligencePanel`'s Geography preset
buttons/labels). Not trigger files, but this repo's Codex routing rules still apply — no push,
hand off to Claude Code per usual.

## The fix

### 1. Backend: cap the *effective* date range for weekday/weekend, independent of calendar MTD

`_resolve_preset` (`intelligence.py` ~line 109-142) currently returns, for both `weekdays_mtd` and
`weekends_mtd`: `(month_start, today, 'weekday'|'weekend', label)` — i.e. true month-to-date, which
grows to ~30 days by month-end and is exactly the size that times out.

Change: when `day_filter != 'all'`, clamp `resolved_from` to at most 14 days back from `today`,
**never** earlier than the true month start (so early-month behavior is unchanged — a "Weekdays
MTD" request on the 5th of the month should still just show the 5 days that exist, not stretch
backward). Something like:

```python
if preset == "weekdays_mtd":
    clamped_from = max(month_start, today - timedelta(days=13))
    return str(clamped_from), str(today), "weekday", "Weekdays (last 14d)"
if preset == "weekends_mtd":
    clamped_from = max(month_start, today - timedelta(days=13))
    return str(clamped_from), str(today), "weekend", "Weekends (last 14d)"
```

Rename the labels too ("Weekdays MTD" → "Weekends (last 14d)" or similar) so the UI is honest about
what it's actually showing — don't silently change the window while still calling it "MTD."

**Where this label string surfaces** — grep for it, don't assume one call site:
- The preset button labels in `CampaignPerformance.jsx` (`Weekdays MTD`/`Weekends MTD` button text,
  inside `CampaignIntelligencePanel`'s preset row — same component, separate from the geography
  preset row added in `2eeac96`/`e20a23b`. Both the drawer's shared preset row and any per-view
  label need the new copy.)
- `_resolve_preset`'s returned `preset_label` — flows into `panelData.preset_label` and is what's
  literally displayed above the results grid, e.g. `"{preset_label} · Sep 16–Sep 22"`.

Confirm both are updated consistently — a mismatch (button still says "MTD", results header says
"last 14d") is its own small trust problem, same shape as the Compass/Intelligence date-label bug
fixed earlier this session.

### 2. Do NOT apply this clamp to `niche_profitability`'s or `best_times`'s own weekdays_mtd/weekends_mtd

`_resolve_preset` is shared across at least three callers (`niche_profitability`, `best_times`,
`geography_watchlist` — grep call sites to confirm there are no others). The account-wide +
per-day-breakdown combination that times out is unique to `geography_watchlist`
(`get_account_campaign_state_insights` with `campaign_id=None`). `best_times`'s own
`_fetch_best_times_meta` already uses `time_increment: 1` at `level: 'adset'` with NO extra
breakdown and has been running in production without this problem — different, lighter query
shape. `niche_profitability` doesn't touch Meta's region breakdown at all.

So: **don't change `_resolve_preset` globally.** Instead, either (a) add an optional parameter to
`_resolve_preset` (e.g. `max_day_filter_days: int | None = None`) that only `geography_watchlist`
passes, or (b) do the clamping inline in the `geography_watchlist` route right after calling
`_resolve_preset`, before building the cache key / calling the service. Pick whichever keeps
`_resolve_preset` itself simple — your call, just don't regress Best Times or Niche by clamping a
shared function's general behavior for one caller's scale problem.

**Also update the cache key accordingly** — `geography_watchlist`'s `cache_key = (str(ad_account_id
or ''), resolved_from, resolved_to, day_filter)` already includes `resolved_from`/`resolved_to`, so
once those values reflect the clamped 14-day window instead of full MTD, the cache key changes
correctly and automatically — no separate cache fix needed, just confirm this falls out naturally
once the clamped dates flow through.

### 3. Frontend: no other changes needed

`CampaignIntelligencePanel`'s geography loader (`loadGeography`) just passes `preset` straight
through to the backend and displays whatever `preset_label`/`date_from`/`date_to` comes back — it
doesn't compute the window itself. Once the backend clamps and relabels, the frontend should just
work. Confirm by reading the component, don't assume — if you find frontend-side date math
duplicating `_resolve_preset`'s logic anywhere, flag it, that would need the same clamp.

## Acceptance checks

1. On a large account (act_521142087204815 / RHO - Commercial Insurance, ~81 campaigns), opening
   Geography → Weekdays MTD (or Weekends MTD) on 2026-09-23 requests a ~14-day window
   (`date_from` around 2026-09-10, not 2026-09-01), completes without timing out, and returns real
   state rows or the honest "No state delivery signals need review" empty state — not a 502.
2. Early in a month (e.g. clamp logic tested with a mocked "today" of the 5th) still returns just
   that month's 5 days, not padded backward past month start.
3. Preset button label and the results-panel header both say the same thing (e.g. "Weekdays (last
   14d)" in both places) — no mismatch between what was clicked and what's displayed.
4. `niche_profitability` and `best_times` endpoints' own weekdays_mtd/weekends_mtd behavior is
   unchanged — run their existing tests, confirm no regression.
5. `python3 scripts/check_alembic_heads.py` — no migration in this change, should be a no-op, just
   confirm nothing else drifted.
6. `npx vite build` clean.
7. Existing `test_intelligence.py`/`test_facebook.py` geography tests still pass; add one new test
   asserting the clamped date range for `weekdays_mtd`/`weekends_mtd` specifically (not just that
   `_resolve_preset`'s existing behavior didn't change for the other five presets).

## Process

Not a trigger file, no DB migration, no MCP need. Commit locally and hand off per this repo's
routing rules:

> "Edits done — ready for Claude Code review + push."

Flag in your handoff notes if you chose option (a) or (b) from section 2, and why.
