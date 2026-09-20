# Codex Brief — "Best Times" by Niche (Campaign Intelligence, Phase 1)

**Origin:** Abel's manual day/hour ROI breakdown for commercial-auto niches, Slack `C0BG015BAJU`, 2026-09-19. Steve wants this built into the app so it's generated on demand instead of a manual pull every few weeks. Confirmed by Steve: Phase 1 must use **true revenue-based ROI**, not just Meta spend/CPL — otherwise we don't know which hours are actually profitable.

**Read `CLAUDE.md` in full before starting.** This follows the existing "Campaign Intelligence" engine in `backend/app/api/v1/intelligence.py` — extend it, don't fork a parallel system.

**This brief was updated 2026-09-20 after a live data audit against the VPS.** The audit confirmed real account scope, a real timezone bug, and a real niche-extraction gap — all folded in below. Don't rebuild the audit; use its findings as given.

---

## What exists today (don't rebuild this)

`GET /api/v1/intelligence/niche-profitability` in `intelligence.py`:
- `_extract_niche(adset_name)` — pulls niche from `[Date] - [Niche] - [Batch]` adset naming pattern
- `_resolve_preset()` — date range + weekday/weekend/all day_filter from a preset string
- `_fetch_meta_insights()` — pulls Meta ad set insights, already supports `time_increment=1` + day-of-week filtering (weekday vs weekend only — coarse)
- `_assign_verdict()` / `_assign_confidence()` / `_assign_suggested_action()` — ROI → verdict → action logic, with a `directional_` prefix convention for anything not backed by full-range revenue
- Revenue comes from RedTrack only right now (`_fetch_redtrack()` → `RedTrackService.get_report_by_adset()`), NOT Everflow-aware

Frontend: this powers a panel already live on `/campaign-performance` (`CampaignPerformance.jsx`, search `loadIntelligence`).

## What's new in this brief

Add a **"Best Times" view** to the same Campaign Intelligence surface: per-niche grid of day-of-week × hour-of-day, with real revenue-based ROI, not just CPL.

---

## Data sources — read these files before writing any fetch code

### Meta (spend, leads, hour-of-day)
`backend/app/services/facebook_service.py` has the SDK wrapper. For hour-of-day, add `breakdowns=['hourly_stats_aggregated_by_advertiser_time_zone']` to the insights call alongside `time_increment=1` (needed for day-of-week bucketing — see `_fetch_meta_insights` in `intelligence.py` for the existing pattern). Do **not** edit `facebook_service.py` itself unless there's truly no other way — it's a trigger file requiring Claude Code handoff regardless of anything else in this brief. Prefer building the insights call directly in `intelligence.py` (it already imports `FacebookService` and calls `account.get_insights()` directly, bypassing the service layer — follow that precedent).

### Confirmed account scope (live-audited 2026-09-20 — CLAUDE.md is stale, trust this table)

| Brand | Account ID | Meta account tz | In `SWITCHBOARD_EVERFLOW_AD_ACCOUNT_IDS`? | Offer in `SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS`? |
|---|---|---|---|---|
| RHO - Commercial Insurance | `act_521142087204815` | America/Los_Angeles | Yes | `"Get Business Coverage"` |
| RHO 4 - Commercial (CAPI) | `act_737291135429748` | America/Los_Angeles | Yes | `"Get Business Coverage"` |
| RHO 3 - Auto Insurance | `act_1675586233224658` | America/Los_Angeles | Yes | `"Fast Auto Quote.org"` |
| DIN Auto Insurance | `act_949433761196746` | America/Los_Angeles | Yes | `"Fast Auto Quote.org"` |
| Trusted Home Service | `act_287925406489877` | America/Los_Angeles | **No** | **No — resolves to $0 / not_tracked today** |

All five are Everflow-tracked per Steve; the app is already ahead of CLAUDE.md's documentation (RHO3-Auto and DIN Auto are live) except **THS, which has no Everflow offer mapping yet and silently reports $0 revenue rather than an error.** Getting THS a real offer-name mapping in `SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS` is an env var change over SSH — that's Claude Code's job, not this brief's, and needs Steve to confirm THS's exact Switchboard offer name first. **Until that's done, THS must show as "not tracked" in Best Times, never as a $0/zero-ROI niche** — those mean different things and must not be visually conflated.

RedTrack: only RHO is currently live in it; THS is coming soon per Steve. RedTrack coverage is independent of Everflow scope — see below.

### Revenue (the part that makes this "true ROI")

Two separate raw, timestamped conversion sources exist. Use whichever actually covers the account — **do not blend both for one account** (that's the exact double-counting bug `pnl.py`'s `_revenue_provider_for_account()` comment warns about; Everflow is the app's confirmed point of truth for billable revenue, so if an account is Everflow-scoped, use Everflow only, never RedTrack, even where both exist):

- **Everflow-tracked accounts (the 5 above):** `EverflowService.get_raw_conversions(date_from, date_to, timezone_id=90)` in `backend/app/services/everflow_service.py`. Real conversion rows, real timestamps. Per row:
  - `row['conversion_unix_timestamp']` → bucket into `(date, hour, day_of_week)` using `datetime.fromtimestamp(int(ts), tz=EVERFLOW_TZ_BY_ID[90])`.
  - **`timezone_id=90` (Pacific), not the module's `DEFAULT_TIMEZONE_ID` (80 / Eastern) — this is a real, audit-confirmed correctness bug, not a style choice.** All five accounts above run on `America/Los_Angeles`. Everflow's default in this codebase is Eastern. If you pull with the default, every hour bucket shifts 3 hours off Meta's own hourly breakdown and day-of-week mis-buckets near midnight. Pass `timezone_id=90` explicitly for this feature, or better, resolve it dynamically per-account from Meta's own `timezone_name` field (query it once, don't hardcode 90 if this ever needs to generalize past Pacific-timezone accounts).
  - `row['sub3']` = fb_adset_id (confirm against `META_ID_RE` regex already in the file)
  - `row['sub8']` = adset_name — **do not rely on this alone for niche matching.** The audit found real cases (Painting, Auto Dealer CAPI) where ad sets are named generically ("BATCH 2", CAPI-suffixed) and the real niche only shows up in the **campaign name**, not the ad set name. `_extract_niche()` as it exists today under-counts these. Extend niche resolution to fall back to campaign name when the ad-set-name pattern doesn't yield a real niche (reuse the campaign name already available from Meta's adset/campaign fetch — don't add a second API call if it's already in the payload). Validate this against real RHO data before shipping — the audit's exact comparison numbers are below and should roughly reproduce.
  - `row['revenue']` — accumulate as `Decimal`, only quantize once at output (see `_raw()` / `_money()` helpers already in the file)
  - Filter by offer name via `SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS`, same as `_aggregate_rows(offer_names=...)` already does

- **RedTrack-tracked accounts (RHO today, THS soon) that are NOT Everflow-scoped for that specific offer:** confirmed live 2026-09-20 — RedTrack **does** have a raw, timestamped conversion export, not just aggregate totals. Not used anywhere in this codebase today:
  ```
  GET https://api.redtrack.io/conversions?api_key=...&date_from=...&date_to=...&per=...
  ```
  Returns individual rows with `conv_time`/`track_time` (ISO8601, tz-aware, e.g. `2026-09-18T13:16:09-07:00` — already timezone-correct, no manual tz math needed) and `sub1`..`sub8`. **Field mapping differs from Everflow — do not copy-paste the sub-field assumptions across services:** RedTrack's `sub2` = fb_adset_id (matches existing `get_report_by_adset` usage), but RedTrack's `sub3` = **campaign_id**, not adset — Everflow's `sub3` is the adset id. Mixing these up silently misattributes revenue. Given all 5 in-scope accounts are already Everflow-covered (once THS gets its mapping), wiring RedTrack raw conversions is **not required for this brief's 5 accounts** — build it only if a future niche/account needs RedTrack as primary revenue with no Everflow mapping at all. Don't build it speculatively now; note the endpoint here so it's not re-discovered from scratch later.

Given the above, for the 5 accounts in scope for Phase 1, every niche should be able to show **true revenue-based ROI** — there's no confirmed case today that needs the Meta-only/"directional" fallback described in earlier drafts of this brief. Keep the `revenue_source` field in the response shape below anyway (values `"everflow"` / `"not_tracked"`) so THS shows honestly as untracked rather than silently omitted or shown as $0.

---

## Endpoint

New route (extend `intelligence.py`, don't create a new file):

```
GET /api/v1/intelligence/best-times
  ?preset=last_30d              (reuse _resolve_preset — but note: for this endpoint,
                                  "day_filter" doesn't apply the same way; the whole
                                  point is breaking IN to per-day/per-hour, not
                                  filtering weekday vs weekend)
  ?ad_account_id=act_...
  ?niche=Painting                (optional — omit for all niches)
```

Response shape (adjust as needed, but keep the shape self-describing):
```json
{
  "niches": [
    {
      "niche": "Painting",
      "revenue_source": "everflow" | "not_tracked",
      "cells": [
        {
          "day_of_week": 5,
          "hour": 14,
          "spend": 210.40,
          "leads": 12,
          "revenue": 340.00,
          "roi": 0.62,
          "confidence": "high" | "medium" | "low"
        }
      ]
    }
  ]
}
```

Reuse `_assign_confidence()` for the confidence field — same $300/10-lead thresholds already validated elsewhere in this file. Don't invent new thresholds.

---

## Frontend

Add a "Best Times" tab/toggle next to the existing niche table in the Campaign Intelligence panel (`CampaignPerformance.jsx`).

- **Grid, not 24 raw hourly columns.** Default view: 7 days × 4 dayparts, color-scaled by ROI (green=scale, red=cut, gray=insufficient data — reuse the verdict color logic already used in the niche table if it exists). Add a "view hourly" drill-down only if there's an obvious place for it — don't force raw hourly into the default view.
- **Daypart boundaries — audit-confirmed, not evenly split:** `12a–6a` / `6a–2p` / `2p–6p` / `6p–12a`. Real 30-day data across the 5 RHO niches shows morning (6a–2p) as the strongest window for Car Rental, both Auto Dealer cuts, and Limo; 2p–6p is the weakest window for 3 of 5 niches; but **Painting is a genuine outlier — its ROI peaks in the 6p–12a window**, opposite every auto/rental niche. Do not hardcode "mornings win" anywhere in the code or copy — the whole point of this feature is that it's real per-niche data, not a general assumption. The 4-part scheme is a display convenience; the underlying data model must always be the full day × hour matrix (see endpoint response shape), never pre-collapsed to just 4 buckets server-side.
- Niche selector (dropdown or tabs) — this is per-niche data, showing all niches' grids stacked at once will be unreadable.
- Any cell below the `_assign_confidence` "low" threshold: gray out, don't hide. Hiding data silently reads as "no data" when it's really "not enough data yet" — different things, and Joel/Abel need to tell them apart.
- `revenue_source: "not_tracked"` niches (THS today): visually distinct — different border/badge, not just a tooltip. Must be impossible to miss at a glance, and must not look like a $0-ROI niche.

---

## Non-goals for Phase 1 (do not build these)

- **No write-back to Meta.** This is read-only analysis. The "apply this dayparting to `adset_schedule`" action is Phase 2 — do not build it now, don't stub it half-built either.
- **No new DB table / caching.** Compute on demand for the requested range. If it turns out to be too slow or trips Meta's per-account rate limit (this account has hit "User request limit reached" / code 17 before under repeated insights calls in a short window — see CLAUDE.md), that's a signal to come back and design caching deliberately, not to add it speculatively now.
- **No scheduled job.** On-demand only, triggered by loading the tab.

---

## Validate against this before calling it done

Live-audited 30-day totals for RHO (`act_521142087204815` + `act_737291135429748`, "Get Business Coverage", 2026-08-21→09-20, `timezone_id=90`). Your build should reproduce these within a few percent — if it's off by more, suspect the niche-extraction fallback or the timezone param first:

| Niche | Spend | Revenue | Profit | ROI | Best day | Best window |
|---|---|---|---|---|---|---|
| Car Rental | $4,568 | $7,061 | $2,494 | 54.6% | Monday | 7a–2p (~82% ROI) |
| Auto Dealer — CAPI | $5,450 | $7,326 | $1,876 | 34.4% | Fri/Wed | 5a–12p (~77% ROI) |
| Painting | $2,892 | $4,327 | $1,434 | 49.6% | Sat (114.6%) / Sun (66.5%) | evening-weighted (6p–12a) |
| Auto Dealer — Non-CAPI | $6,901 | $7,548 | $646 | 9.4% | Mon, then Wed | 8a–12p (~38% ROI) |
| Limo | $1,805 | $2,779 | $974 | 53.9% | Mon, then Tue (52.4%) | 9a–3p |

These directionally match Abel's original Slack numbers (same best-day rankings, same weekend pause/live pattern) but his ROI figures ran ~9–11pp high on 3 of 5 niches — likely a slightly different window boundary or rounding on his manual pull, not a wrong direction. Painting and Limo matched almost exactly (spend within 0.3%).

### Validation checklist

The feature is ready for review only when all of the following are true:

- **Account routing:** RHO, RHO4, RHO3-Auto, and DIN Auto resolve to Everflow with the exact offer mappings in the table above. THS resolves explicitly to `revenue_source: "not_tracked"` until its Switchboard offer mapping exists; it must not appear as a zero-revenue or zero-ROI niche.
- **Timezone:** the Everflow request passes `timezone_id=90` for the current five-account scope, or resolves the equivalent Pacific timezone dynamically from the Meta account. No path may silently fall back to the module default of Eastern time.
- **Revenue attribution:** Everflow `sub3` is treated as the Facebook ad set ID and `sub8` as the ad set name. Revenue is accumulated with `Decimal` before output rounding, and no account's Everflow and RedTrack revenue is blended.
- **Niche resolution:** ad sets whose names are generic or CAPI-suffixed still land in the correct niche through the campaign-name fallback. The Painting and Auto Dealer CAPI cases must be included in the validation run; a result that only matches ad-set-name niches is incomplete.
- **Granularity:** the API retains the full day-of-week × hour matrix. The UI may display the four approved dayparts (`12a–6a`, `6a–2p`, `2p–6p`, `6p–12a`), but must not collapse the source data server-side or hide low-confidence cells.
- **Benchmark reproduction:** the RHO 30-day totals above reproduce within a few percent, with the same best-day and best-window direction. Investigate timezone and niche extraction first if they do not.
- **Behavioral sanity:** Painting remains evening-weighted while Car Rental, both Auto Dealer variants, and Limo remain morning-weighted in the audited range. The implementation and copy must not encode a universal “mornings win” rule.
- **UI states:** insufficient cells are visibly gray and labeled as insufficient data; untracked niches have a distinct badge/border and cannot be mistaken for a profitable or unprofitable tracked niche.
- **Regression checks:** existing Campaign Intelligence results still load, the new tab is on-demand only, and no `facebook_service.py` trigger-file edit or database migration is introduced.

---

## Push protocol

No DB migration, no trigger-file edits expected (confirm this stays true — if you end up needing to touch `facebook_service.py`, stop and hand off per `CLAUDE.md`). This is a **medium-sized, multi-file change** (new backend logic + new frontend view) — per `CLAUDE.md`'s pre-push table, needs 2 parallel review agents before push, not 1. Beyond the standard code-correctness pass, explicitly ask one review agent to check the **revenue math specifically**: correct `sub3`/`sub8` field usage, correct timezone application, Decimal accumulation before rounding, and that Everflow vs Meta-only niches are never blended into one number. A believable-but-wrong ROI here directly drives real dayparting/spend decisions — this is not a cosmetic feature.

End your session with: **"Edits done — ready for Claude Code 2-agent review + push."** Do not push this yourself even if it looks trigger-file-clean — final push goes through Claude Code per the standard protocol.

---

## Open questions (Steve to confirm — flag these back rather than guessing)

1. **THS's exact Switchboard offer name** — needed before `SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS` can be updated (Claude Code, via SSH — not Codex's job, just noting it's a dependency for THS ever showing real data in this feature).
2. **RHO3-Auto and DIN Auto weren't part of Abel's original ask** (he was looking at RHO's commercial-auto niches specifically) — confirm whether "Best Times" should launch scoped to all 5 confirmed accounts, or just RHO/RHO4 first, then expand.
3. **Account selector behavior** — if launch scope is all five accounts, should the existing Campaign Intelligence account selector default to the currently selected account, or should Best Times provide an explicit multi-account aggregate view? Do not aggregate across accounts unless the UI makes the account scope unambiguous.
4. **Timezone generalization** — Pacific (`timezone_id=90`) is correct for the current scope. Confirm whether Phase 1 should keep this as an explicit account-derived setting, or whether the initial implementation may remain limited to the five Pacific-time accounts with a clear guard for unsupported timezones.
5. **Benchmark window** — the audited reference range is 2026-08-21 through 2026-09-20. Confirm whether this exact range should be retained as a developer fixture/repro check, or whether validation should use a rolling equivalent once the feature is live.
