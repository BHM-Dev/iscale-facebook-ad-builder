# Lead counting (cross-cutting)

Meta insights `actions` return **both** `lead` and `offsite_conversion.fb_pixel_lead`, usually with the same
value. `lead` is Meta's aggregate, so adding the lead types together double-counts. RHO
(`act_521142087204815`) on 2026-11-04 at ad-set level: lead=167 and fb_pixel_lead=167 on 51 of 71 ad sets,
which summed to 334. The real figure is 167. *Verified in production* against Meta on 2026-11-05.

**Rule:** count leads with `app.services.meta_actions.count_leads(actions)`. It uses `lead` when that is
non-zero and otherwise the largest single variant, so it returns 0 only when the old sum was 0. Auto-pause's
zero-lead kill depends on that. `proposal_service.count_leads` is the same function, re-exported for
older callers. Never sum `LEAD_TYPES`.

## Where leads are counted (as of 2026-11-06)

| Code | Feeds | Before | Now |
|---|---|---|---|
| `facebook_service.get_ad_lifetime_insights` | Research test outcomes | Counted once (local copy of the rule) | `count_leads` |
| `facebook_service.get_adset_insights` | Auto-pause single ad-set fallback, `/auto-pause/insights/{id}` | Leads ×2 | `count_leads` (CPL: see below) |
| `facebook_service._fetch_account_insights_bulk` | Campaign Performance Leads column and totals row, Dashboard niche summary, AI insights, CAPI quality, auto-pause | Leads ×2. Totals-row CPL and niche-summary CPL (spend ÷ leads) were about half the real value | `count_leads` (CPL: see below) |
| `facebook_service.get_account_daily_insights` | Dashboard trend: daily leads, CPL, revenue per lead | Leads ×2, CPL and RPL about half the real value | `count_leads` |
| `facebook_service.get_account_campaign_state_insights` | Intelligence → Geography | State leads ×2 | `count_leads` |
| `facebook_service.get_account_ads_insights_bulk` | Campaign Performance ad rows, ad-level auto-pause, AI insights | Leads ×2 | `count_leads` (CPL: see below) |
| `facebook_service.get_ad_insights_map` | Ad Copy Library CPL | CPL fallback only, ÷ summed leads | `count_leads` |
| `intelligence._fetch_meta_insights` | Intelligence niche/ad-set profitability: leads, CPL, confidence | Leads ×2, CPL about half the real value | `count_leads` |
| `intelligence._fetch_best_times_meta` | Intelligence → Best Times | Hourly leads ×2 | `count_leads` |
| `proposal_service.fetch_inputs`, `max_cpl_service`, `daily_close_service` | Approvals queue, Max CPL, Daily close | Already fixed in `ce70c8a` | unchanged |
| Frontend (`Dashboard.jsx` niche summary, `CampaignPerformance.jsx` totals) | Recompute CPL as spend ÷ summed backend leads | Inherited the ×2 | Correct once the backend is fixed; no frontend change |

How "Before" was established: by reading the code, plus the verified 2026-11-04 RHO numbers above.

**Verified in production 2026-11-06** (after `a69b8de` went live): RHO on 2026-11-05, read from the live API.

| Source | Leads |
|---|---|
| Dashboard trend | 184 |
| Campaign Performance, ad-set rows summed | 184 |
| Campaign Performance, ad rows summed | 184 |
| Daily close | 184 |
| RedTrack conversions | 182 |
| Switchboard Everflow `Lead Rev` events | 190 |

Before the fix the app would have shown about 368. Intelligence (default last 7 days, 10-31 to 11-06) shows
887 leads against 923 RedTrack conversions.

- The P&L "conversions" figure (359) is NOT a lead count: 190 `Lead Rev` + 161 `Click` + 8 `Call` events.
- RedTrack (−1%) and Everflow (+3%) are independent counts, not expected to tie exactly. Likely causes are the
  day boundary (Everflow buckets on Eastern, Meta on Pacific) and click vs pixel tracking. Neither cause has
  been confirmed. The check rules out a 2× error; it is not a reconciliation to the lead.
- Not checked live: Geography and Best Times (unit-tested only), and Ads Manager in the browser. 184 is the
  Meta API's `lead` action, which is assumed (not verified here) to be what Ads Manager's Leads column shows.

Ratios are unaffected wherever both sides doubled. Examples: Geography's "state CPL ≥ 1.5× blended", ROAS,
profit, and revenue (read from `action_values`, first match, never summed). Absolute lead gates did shift,
because counts were doubled: Geography's `leads >= 2`, Intelligence confidence tiers, and the trend's
`leads >= 5` RPL flag.

## Auto-pause CPL — proposal, NOT shipped (needs Steve + Joel/Abel sign-off)

Auto-pause rules read `insights['cpl']`, not leads. That CPL comes from Meta's `cost_per_action_type`, using
the first lead-type entry, so in the normal case **the rules were not under-firing by 2×**. The zero-lead
breach (`leads == 0`) is also unaffected, because 0 doubled is still 0.

Two residual paths still differ from the real CPL. Both are left exactly as they were in this change. The
fallback deliberately keeps the old summed count via `_legacy_summed_leads`.

1. **Fallback when Meta returns no lead entry in `cost_per_action_type`:** CPL = spend ÷ *summed* leads,
   which is about half the real value. A `cpl greater_than` rule would under-fire on those rows. How often
   Meta omits the entry while `actions` has leads is **unknown**. The probe counts it.
2. **First-match ordering:** if Meta lists `offsite_conversion.fb_pixel_lead` before `lead`, the rule uses
   the pixel CPL. That only matters on ad sets where the two counts differ (20 of 71 on 2026-11-04). Which
   way it moves is **unknown** until the probe runs.

**Proposed change:** CPL = `cost_per_action_type['lead']` when present, otherwise spend ÷ `count_leads`.
Applies in `get_adset_insights`, `_fetch_account_insights_bulk` and `get_account_ads_insights_bulk`. Run the
probe first to size how many rules would change state. Then get sign-off, ship, and delete
`_legacy_summed_leads`.

## Downstream data that used the old numbers
- `bhm-context/projects/facebook-ad-builder/buyer-behavior.md` baselines (for example "median kill ~$25 CPL")
  came from `proposal_service.fetch_inputs` before `ce70c8a`. CPL there is likely about half the real value
  and lead counts about double. ROI, ROAS and profit are unaffected. Re-run
  `scripts/ops/buyer_behavior_profile.py` and correct that file.

## Changelog
- 2026-11-06 — all remaining lead counts moved to `meta_actions.count_leads`. The auto-pause CPL fallback is
  held on the legacy sum pending sign-off. Tests: `tests/unit/test_lead_counting.py`. 8 of its 9 tests fail
  on the pre-fix code. *Verified in production* 2026-11-06 for RHO 2026-11-05: 184 leads on every surface, cross-checked
  against RedTrack (182) and Everflow Lead Rev (190).
- 2026-11-05 `ce70c8a` — `count_leads` added; Max CPL, daily close and proposals switched to it.
