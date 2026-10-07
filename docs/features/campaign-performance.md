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
- **Unit-tested only:** the server-side 409 large-change guard and ceiling (live test needs an explicit OK for one
  real PATCH on a paused ad set); rule validation; Meta error mapping; ads insights pagination/fallback.
- **Not verified:** clicking Pause/Resume on an ad or ad set end to end (deferred until close to real use).

## Open items
- Pause/Resume live click-through; the 409 live test.
- CBO→ABO campaign switch very likely fails on Meta — needs a throwaway-campaign test before relying on it.
- Rule thresholds are integers (ROAS 1.5 / CTR 0.5 impossible) — needs a DB migration.
- Dashboard budget edits show a clear message on a large change but have no second-confirm dialog yet.
- Status overrides (local optimistic state) are not cleared by Sync.

## Changelog (newest first)
- 2026-10-07 `merge_duplicate_rows.py` run in prod: merged 14 legacy duplicate campaign/ad-set row pairs, removed
  CLAUDE TEST leftovers (local DB only; backup `/home/ubuntu/backups/pre-dedupe-20261007-172535.sql` on the VPS).
- 2026-10-07 ad status read now **unfiltered** (verified: filter hid 848 of 1,302 ads — parent-paused ones).
- 2026-10-07 `dbf2610` sync badge colours by refreshable rows; `ae3f32d` ads-bulk perf + sync refreshes duplicate rows.
- 2026-10-07 `9916460` last-synced badge (+ `synced_at` migration `d6e8f0a2b4c6`), real ad status, Resume confirm.
- 2026-10-07 `d286cc0` rule validation/2-step modal, `campaigns:write` on status/delete, Meta error mapping.
- 2026-10-07 `8106e24` live budget pre-read + large-change guard, ad set Pause/Resume fixes, sync refreshes budgets.
- Audit that drove all of this: [`CampaignPerformance-MoneySafety-Audit.md`](../../CampaignPerformance-MoneySafety-Audit.md).
