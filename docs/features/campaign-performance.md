# Campaign Performance (`/campaign-performance`)

Joel's home base: live Meta insights + RedTrack conversions per ad set, brand assignment, remix
drawer, budget edits, pause/resume, auto-pause rules. Code: `frontend/src/pages/CampaignPerformance.jsx`;
API: `backend/app/api/v1/{facebook,auto_pause}.py`; Meta calls: `backend/app/services/facebook_service.py`.

## What's on the page (data freshness matters)
- **Structure data** (ad set/campaign status, budgets, CBO flag) comes from the **local DB**, refreshed
  only by the **Sync** button. **Spend / leads / CPL / ROAS are live** (Meta Insights + RedTrack).
- **Sync badge** next to Sync: "Synced N min ago" (green ≤ 30 min, amber after) from `synced_at` on
  `facebook_adsets`/`facebook_campaigns`. Shows the oldest refreshable row; "· N not refreshed" = rows Sync
  can't reach (legacy, deleted in Meta, another account). Hover for explanation.
- Ad rows (expand an ad set) show real delivery status from one account-level Meta read.

## Layout (2026-11-07)
- One-line **close strip** (`DailyCloseCard variant="strip"`); Details opens the full card in a drawer.
- Tabs: **Ad sets** / **Creative Compass** / **Intelligence** (`?tab=`).
- Sticky toolbar: **goal line** (spending · under / over / no Max CPL, each with its spend; a chip click filters),
  search, Filters popover (status, niche, metric, Rotation queue / Needs attention / Top performers presets),
  sort (incl. "Over Max CPL first"), Group-by-campaign toggle, Proposals button. Active filters show as
  removable chips; the old dashboard deep-link banner is gone. Removing a chip never resets the date range.
- Goal-line rule: 0 leads counts as **over** once spend ≥ one Max CPL. This is a display rule only; it does
  not change auto-pause triggers.
- **Proposals rail** docks beside the table only at viewport ≥ 1800px. Below that it is an overlay and the
  button turns solid "Review proposals (n)". The Brand column hides while the rail is docked.
- Sticky ad-set name column (truncated at 280px, full name on hover) and sticky Actions column, so
  Iterate/Pause stay on screen at 1440px.
- *Verified in production data* (local frontend → prod API, 2026-11-07): goal-line counts matched an
  independent API recompute (117 / 51 / 66 / 0, last 7d RHO Commercial); deep links and the nav badge
  were re-tested after review fixes. *Not verified:* true phone width (Chrome min 606px).

## Money safeguards (all enforced server-side unless noted)
| Action | Guard |
|---|---|
| **Edit ad set / campaign daily budget** | Server re-reads the **live** budget from Meta first (fails closed on throttle/timeout — never a blind write). Rejects lifetime-budget ad sets and CBO-child ad sets with a clear message. **>3× up or <⅓ of live** → 409 until the UI's second red "Yes, apply N× change" confirm. **Hard ceiling $5,000/day** (`MAX_DAILY_BUDGET_CENTS`, env; changing it needs `docker compose up -d`, not `restart`). UI confirm shows live "from $X" (amber "last synced" if the live read failed) and the % change. |
| **Pause / Resume ad set** | Both confirm. Target status comes from the dialog the user saw (never re-derived). Only ACTIVE⇄PAUSED; ARCHIVED/other shows a disabled status label. Resume warns when the parent campaign is paused. |
| **Pause / Resume ad** | Real status from Meta (no more "everything is ACTIVE"). Resume confirms. Configured `status` drives the button; ads on-but-parent-paused are dimmed with an explanation; archived ads disabled. |
| **Auto-pause rules** | Modal: no preselected ad set, per-metric defaults reset on metric change, 2-step confirm naming the ad set and action. Server bounds: threshold > 0 and ≤ cap (CPL/CPA 10000, CTR 100, ROAS 20); pause/decrease need min spend ≥ $1; re-arming re-validates. A rule only auto-disables when a direct read confirms its ad set is DELETED/ARCHIVED (a lost-permission 100/33 alone never disarms rules); disable alerts Slack. |
| **Remove ad set from app** | Local-only (does not touch Meta); account-scoped; needs `campaigns:write`. |
| Pause/resume, budget, delete, sync/cleanup routes | Require `campaigns:write` (admin/manager/superuser). All current users are admins. |
| Meta errors | Throttle (4/17/32/341/613/80000-80014) → 429; transient/none → 502; token (190/102) → 502 (not 401, which would log the user out); permission (10/200-299) → 403; else 400 with Meta's message. |

## Endpoints worth knowing
`GET /facebook/campaigns/{id}`, `GET /facebook/adsets/{id}` (cheap single-object status+budget reads) ·
`PATCH /facebook/adsets/{id}/budget`, `/campaigns/{id}/budget` · `PATCH /facebook/{adsets,ads}/{id}/status` ·
`GET /auto-pause/ads-bulk?include_status=true` (ad insights + status; 60s cache, whole pagination inside a 55s budget,
500-row pages) · `POST /facebook/sync` (refreshes every duplicate local row per Meta id).

## Verified vs not
- **Verified in production (2026-10-07, browser + API):** sync badge; archived ad set shows disabled label; budget
  confirm shows live "from $60 … +900%" (cancelled, not saved); rule modal defaults/validation/metric reset;
  ad rows load with real status; `ads-bulk` 7d 30.5s→8.4s, 30d 58s→9.8s, repeat 0.1s.
- **Verified live, server-side large-change guard (2026-10-07):** a 10× budget request ($50 → $500) on a paused ad set
  (RHO v1 | ABO | Trucking- dont use, paused under a paused campaign) returned **409 `LARGE_BUDGET_CHANGE`**
  (`current_cents` 5000, `requested_cents` 50000, ratio 10) and the budget stayed $50 — nothing was written.
- **Unit-tested only:** the $5,000 ceiling; rule validation; Meta error mapping; ads insights pagination/fallback.
- **Not verified:** clicking Pause/Resume on an ad or ad set end to end (deferred until close to real use).

## Open items
- Pause/Resume live click-through (deferred until close to real use).
- CBO→ABO campaign switch very likely fails on Meta — needs a throwaway-campaign test before relying on it.
- Rule thresholds are integers (ROAS 1.5 / CTR 0.5 impossible) — needs a DB migration.
- Dashboard budget edits show a clear message on a large change but have no second-confirm dialog yet.
- Status overrides (local optimistic state) are not cleared by Sync.

## Changelog (newest first)
- 2026-11-10 Proposals: budget raises are now visible to and approvable by Joel and Abel (`PROPOSALS_PUBLIC_ACTIONS`, default `budget_increase`; set it to empty to hide again). Pause proposals and the shadow report stay with shadow viewers. The "first spend in 7+ days, no revenue yet" pause trigger is disabled: in the Nov 2-10 shadow week those 19 ad sets made +$430 over the next 3 days. Do not add `pause` to the public list without re-checking that data.
- 2026-11-10 Winning ads tab (`GET /winners`): creatives ranked by est. profit = leads × niche revenue-per-lead − spend (ads with no rpl excluded, row marked partial), 10-lead floor, Creative/Concept/Headline grouping, RedTrack revenue secondary. Relaunch opens Launch Ads at the Campaign step (never the last-used ad set) with the Drive file preselected; multi-niche concept rows can't relaunch as a group. *Verified on prod data (scratch run): 35/563 creatives ranked over 14d, est. profit reconciled by hand; 26/35 relaunchable, the rest are no longer in Drive.*
- 2026-11-07 Layout pass: close strip, tabs, sticky toolbar + chips, Max CPL goal line, proposals rail, total row, effective status, group-by toggle (Codex build; Claude review fixes for deep-link state, rail width, RT-missing profit).
- 2026-10-07 live-verified the 409 large-change guard on a paused ad set (see Verified).
- 2026-10-07 `merge_duplicate_rows.py` run in prod: merged 14 legacy duplicate campaign/ad-set row pairs, removed
  CLAUDE TEST leftovers (local DB only; backup `/home/ubuntu/backups/pre-dedupe-20261007-172535.sql` on the VPS).
- 2026-10-07 ad status read now **unfiltered** (verified: filter hid 848 of 1,302 ads — parent-paused ones).
- 2026-10-07 `dbf2610` sync badge colours by refreshable rows; `ae3f32d` ads-bulk perf + sync refreshes duplicate rows.
- 2026-10-07 `9916460` last-synced badge (+ `synced_at` migration `d6e8f0a2b4c6`), real ad status, Resume confirm.
- 2026-10-07 `d286cc0` rule validation/2-step modal, `campaigns:write` on status/delete, Meta error mapping.
- 2026-10-07 `8106e24` live budget pre-read + large-change guard, ad set Pause/Resume fixes, sync refreshes budgets.
- Audit that drove all of this: [`CampaignPerformance-MoneySafety-Audit.md`](../../CampaignPerformance-MoneySafety-Audit.md).
## Max CPL and daily close (2026-11-05)

- **Max CPL column:** niche from the campaign name (`services/niche_resolver.py`), then 30 complete PT days
  (ending yesterday) of Switchboard revenue ÷ Meta leads ÷ 1.30. Niches under 40 leads, or with no attributed
  revenue, use the account figure and say "acct avg". Cached 1 h per account; failures cached 2 min and shown
  as "—", never $0. Endpoint `GET /api/v1/insights/max-cpl`. *Unit-tested only.*
- **Leads are counted with `proposal_service.count_leads`**, which prefers Meta's `lead` action. Meta also
  returns `offsite_conversion.fb_pixel_lead` with the same value (RHO 2026-11-04: 167 real leads, 334 if
  summed). *Verified in production* against Meta for that day. Since 2026-11-06 every Leads figure in the app
  uses it (`meta_actions.count_leads`). Before that, the Leads column was 2× and the totals-row CPL was about
  half the real value. See [lead-counting.md](lead-counting.md).
- **Daily close card:** the scheduler writes versions of yesterday's PT close at 00:15–06:15 PT
  (`daily_close_versions`). Topline uses the P&L page's own spend and revenue functions. The card shows the
  newest *available* version; an Everflow failure never replaces a good read, and unavailable month-to-date or
  last-month revenue shows "—", not $0. Movers are colour only. The endpoint never computes a close; before
  the first run it says so. Copy for Slack matches Joel's format. *Unit-tested only.*
- **Not verified yet:** parity with the P&L page to the cent, the first scheduled run, Max CPL spot checks.
