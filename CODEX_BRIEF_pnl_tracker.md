# Codex Brief: P&L Tracker by Ad Account

**Status:** Phase 1 shipped (schema + permissions). **Phase 2 is your scope.** Phase 3 is directional.
**Migration head:** `t8p6q2r3s5o1`
**First account in scope:** Commercial Insurance (Get Business Coverage)

---

## For Codex — start here

```bash
git pull origin develop        # REQUIRED — PnlCostEntry does not exist without it
```

**Already done — do not rebuild, do not edit, do not push:**
- `backend/app/models.py` → `PnlCostEntry` (end of file)
- `backend/alembic/versions/t8p6q2r3s5o1_add_pnl_cost_entries.py`
- `backend/init_db.py` → `pnl:read` / `pnl:write` permissions + role-permission backfill

**Your scope (Phase 2):**
| File | Change |
|---|---|
| `backend/app/api/v1/pnl.py` | new — 6 endpoints (§5.4) |
| `frontend/src/pages/Pnl.jsx` | new — full page (§3.1) |
| `frontend/src/App.jsx` | `/pnl` route |
| `frontend/src/components/Layout.jsx` | nav entry, `DollarSign`, directly under Dashboard |
| `frontend/src/pages/Dashboard.jsx` | 5-tile MTD strip under the `<h1>` (line ~811) |

**Hand back to Claude Code for:** registering the router in `backend/app/main.py`, and the final push. No trigger files are in scope — if you find yourself editing one, stop.

**The three rules most likely to bite here:** `authFetch` not raw `fetch()`; `useToast()` not `alert()`; custom modal not `confirm()`.

---

## 1. Executive Summary

### The problem

Joel and Abel can see CPL, ROAS, and revenue per ad set, but nobody can answer the only question that matters at the account level: **did this account make money last month, after everything?** Meta spend lives in Ads Manager, revenue lives in RedTrack, and the real costs — Abel's retainer, Abel's commission, the RedTrack subscription, kie.ai credits, any AI video platform — live in Steve's head and a bank statement. Today that reconciliation is manual, monthly, and late.

### The solution

A **P&L page** (`/pnl`) that is the system of record, plus a **compact running P&L strip on the Dashboard** that links into it.

- **Spend** — pulled from Meta insights, per ad account, per period.
- **Revenue** — pulled from RedTrack (`redtrack_cache` / RedTrack report), per ad account, per period. **Not** Meta `action_values` — see §5.1.
- **Other costs** — a new `pnl_cost_entries` ledger Joel/Steve can edit in the UI: recurring retainers, % commissions, flat platform fees, one-off credit top-ups.
- **Net profit / margin** — Revenue − Spend − Other Costs, running MTD and by month.

### Why not just the Dashboard

The Dashboard is a glance surface. A real P&L needs a month selector, an editable cost ledger with add/edit/delete, per-account rows, a month-over-month view, and export. That is a page, not a card. But Joel should not have to navigate anywhere to know whether the account is green today — so the Dashboard gets a **read-only 5-tile strip** (Spend / Revenue / Other Costs / Net Profit / Margin, MTD, active account) that is a link to `/pnl`.

**Decision: build both. `/pnl` is the source of truth; the Dashboard strip is a mirror.**

### Economics

Zero new external API cost — Meta insights and RedTrack are already wired and already synced on a 30-minute cache. The build is a table, a CRUD ledger, one aggregation endpoint, and two UI surfaces.

---

## 2. Flow Diagram

```text
                    ┌──────────────────────────┐
                    │  GET /pnl/summary        │
                    │  ?ad_account_id&period   │
                    └───────────┬──────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
          v                     v                     v
  Meta Insights          RedTrack report        pnl_cost_entries
  (spend, leads)         (conversions,          (retainer, commission,
  per ad account         revenue) per adset      RT fee, kie.ai, video)
          │                     │                     │
          │              roll adsets → account        │
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                v
                    ┌──────────────────────────┐
                    │ Spend  Revenue  Costs    │
                    │ Net = Rev − Spend − Costs│
                    │ Margin = Net ÷ Revenue   │
                    └───────────┬──────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              v                                   v
      /pnl  (full page)                Dashboard  (5-tile strip,
      month picker, ledger CRUD,       MTD, active account,
      MoM table, CSV export            links to /pnl)
```

---

## 3. Detailed Spec

### 3.1 Page: `/pnl` — "Profit & Loss"

**Nav placement:** new top-level sidebar entry `DollarSign` icon, label **"P&L"**, placed directly under **Dashboard**. It is a business surface, not a Facebook surface — do not bury it in the Facebook group.

**Page scope:** always scoped to the **active ad account** from `CampaignContext` (`activeAccountId`), same as every other page. Header shows the account name so there is no ambiguity about whose P&L this is.

#### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Profit & Loss                    [ Commercial Insurance  ▾ ]   │
│  Get Business Coverage · act_XXXXXXXX                            │
│                                                                  │
│  [ ◀ ]  July 2026  [ ▶ ]        ○ Month  ○ MTD  ○ Custom range  │
├─────────────────────────────────────────────────────────────────┤
│  AD SPEND      REVENUE       OTHER COSTS     NET PROFIT   MARGIN │
│  $18,420.11    $27,905.00    $4,362.00       $5,122.89    18.4%  │
│  Meta          RedTrack      6 entries       ▲ vs June    ▲      │
├─────────────────────────────────────────────────────────────────┤
│  Waterfall bar:  Revenue ██████████████████                      │
│                  − Spend  ████████████                           │
│                  − Costs  ███                                    │
│                  = Net    ████                                   │
├─────────────────────────────────────────────────────────────────┤
│  OTHER COSTS                                    [ + Add cost ]   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Label              Category    Type       Amount   Actions │  │
│  │ Abel retainer      Labor       Recurring  $3,000   ✎  🗑   │  │
│  │ Abel commission    Labor       % of spend $  921   ✎  🗑   │  │
│  │ RedTrack           Tooling     Recurring  $  249   ✎  🗑   │  │
│  │ kie.ai credits     Creative    One-off    $  142   ✎  🗑   │  │
│  │ Video platform     Creative    One-off    $   50   ✎  🗑   │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  MONTH OVER MONTH                             [ Export CSV ]     │
│  Month     Spend      Revenue    Costs    Net       Margin  ROAS │
│  Jul 2026  $18,420    $27,905    $4,362   $5,123    18.4%   1.51 │
│  Jun 2026  $16,880    $24,110    $4,201   $3,029    12.6%   1.43 │
│  May 2026  $14,205    $19,340    $3,980   $1,155     6.0%   1.36 │
└─────────────────────────────────────────────────────────────────┘
```

#### Copy rules

- Header: **"Profit & Loss"**. Subhead: **"Meta spend and RedTrack revenue, net of your real costs."**
- Net Profit tile is the visual anchor: larger type, green when positive, red when negative. No gradient.
- Every tile carries its source as a caption (`Meta`, `RedTrack`, `N entries`) so nobody wonders where a number came from.
- Empty state (no cost entries): *"No costs logged for July. Net profit below is gross of retainers, tooling, and creative spend."* — with the Add cost button. **Never show a Net Profit number as if it were final when the ledger is empty** — badge it `Gross`.

#### Add / Edit cost modal

Custom modal, backdrop blur (never `confirm()` / `alert()` — use `useToast`).

| Field | Control | Notes |
|---|---|---|
| Label | text, required | "Abel retainer" |
| Category | select | `labor`, `tooling`, `creative`, `data`, `other` |
| Cost type | select | `one_off`, `recurring_monthly`, `pct_of_spend`, `pct_of_revenue`, `pct_of_gross_profit`, `pct_of_profit` |
| Amount | number | Dollar amount for `one_off` / `recurring_monthly`; percent (0–100) for the `pct_*` types |
| Applies to | radio | **This account only** / **All ad accounts** (writes `ad_account_id = NULL`) |
| Allocation | select, shown only when "All ad accounts" | `by_spend` (default, pro-rata on each account's share of spend) / `even` |
| Effective from | month picker, required | Recurring entries apply from this month forward |
| Effective to | month picker, optional | Blank = ongoing |
| Notes | textarea, optional | |

**Computed-cost preview inside the modal:** for `pct_*` types, show the resolved dollar amount for the currently selected month live as the user types the percent — e.g. `5% of $18,420 spend = $921.00`. Joel should never have to trust an unresolved percentage.

Delete uses a red-button confirm modal.

### 3.2 Dashboard strip

Insert **directly under the page `<h1>` and above the existing stat cards** in `frontend/src/pages/Dashboard.jsx` (h1 at line 811).

- One horizontal row of 5 read-only tiles: Ad Spend · Revenue · Other Costs · Net Profit · Margin.
- Period: **month to date**, active account. Small caption: `MTD · Jul 1 – Jul 27`.
- Whole strip is a link to `/pnl`, with a `View full P&L →` affordance on the right.
- If RedTrack is not configured or returns nothing for the account, render Revenue as `—` and badge Net Profit `Incomplete` — do **not** render a net profit computed from a zero revenue.
- Failure mode: the endpoint returns `{}`-safe defaults; the strip renders skeletons then hides itself entirely rather than showing zeros. The Dashboard must stay usable if the P&L endpoint is down (same rule as `/dashboard/niche-summary`, which returns `[]` on failure).

---

## 4. Data Model

### New table: `pnl_cost_entries` — SHIPPED

Model is live in `backend/app/models.py` (`PnlCostEntry`, end of file). Migration is `backend/alembic/versions/t8p6q2r3s5o1_add_pnl_cost_entries.py`, `down_revision = 's7o5p1q2r4n0'`, `has_table()`-guarded.

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | uuid |
| `ad_account_id` | String, **nullable**, indexed | normalized `act_...`. **NULL = applies to all accounts**, split per `allocation_method` |
| `label` | String, required | |
| `category` | String, default `other` | `labor` \| `tooling` \| `creative` \| `data` \| `other` |
| `cost_type` | String, default `one_off` | `one_off` \| `recurring_monthly` \| `pct_of_spend` \| `pct_of_revenue` \| `pct_of_gross_profit` \| `pct_of_profit` |
| `amount` | Numeric(12,2), required | dollars, or percent (0–100) for `pct_*` |
| `allocation_method` | String, default `by_spend` | `by_spend` \| `even`. Only consulted when `ad_account_id IS NULL` |
| `effective_from` | Date, required | first day of the first month it applies |
| `effective_to` | Date, nullable | NULL = ongoing |
| `notes` | Text, nullable | |
| `vendor` | String, nullable | RESERVED — Phase 3 |
| `source` | String, default `manual` | RESERVED — `manual` \| `auto_kie` \| `auto_video` |
| `created_by` | FK `users.id`, `SET NULL` | audit trail |
| `created_at` / `updated_at` | timestamptz | |

**Reserved fields per Dan's doctrine:** `vendor` and `source` ship null/default in MVP. `source` is what lets Phase 3 auto-write kie.ai and video-platform spend into the same ledger without a migration.

The same migration seeds `pnl:read` / `pnl:write` and grants both to the `admin` and `manager` roles (idempotent raw SQL). `init_db.py` was also amended so `seed_roles_and_permissions()` **backfills** newly-defined permissions onto roles that already exist — previously permissions were attached only at role-creation time, so any permission added after first deploy would never reach production and the feature would silently 403.

**Codex: do not touch `models.py`, the migration, or `init_db.py` — that work is done. Do not push them.**

---

## 5. Integration Spec

### 5.1 Revenue source — RedTrack, not Meta

`get_account_insights_bulk()` already returns a `revenue` field, but it is derived from Meta `action_values` (`facebook_service.py:942–972`). That is Meta's own attributed conversion value and it is **not** what we bill on. The P&L must read revenue from RedTrack:

- Primary: `RedTrackService.get_report_by_adset()` for the period, summed across ad sets that belong to the account.
- Fallback: `redtrack_cache` rows (`fb_adset_id`, `date_from`, `date_to`, `revenue`) when the live call fails, so the page still renders. Badge the Revenue tile `cached` when this path is used.
- Ad set → ad account mapping: `facebook_adsets.fb_account_id` (added in `s7o5p1q2r4n0`). Ad sets with no account mapping are excluded and reported in a `unmapped_adsets` count on the response so silent revenue loss is visible.

Ignore RedTrack's own `cost` and `profit` columns for the P&L. RedTrack cost is its own click-cost view; **Meta spend is the cost of record.**

### 5.2 Spend source

`FacebookService().get_account_insights_bulk(ad_account_id=..., date_from=..., date_to=...)`, summed. `FacebookService()` takes no constructor args.

For a closed prior month, spend is final and can be cached; MTD must be live.

### 5.3 Percent-cost resolution order

Resolve in this fixed order so a commission never compounds on itself:

1. Sum `spend` (Meta) and `revenue` (RedTrack) for the period, for this account.
2. `gross_profit = revenue − spend`.
3. Resolve `pct_of_spend`, `pct_of_revenue`, `pct_of_gross_profit` against those fixed bases.
4. Sum the **non-commission** costs: `one_off` + `recurring_monthly` + the percents from step 3. Call it `other_costs`.
5. `profit_base = revenue − spend − other_costs`. Resolve every `pct_of_profit` entry against `profit_base`. **A `pct_of_profit` cost never sees another `pct_of_profit` cost** — that's what keeps it non-circular. If `profit_base` is negative, `pct_of_profit` resolves to **$0**, never a negative cost.
6. `total_costs = other_costs + pct_of_profit costs`.
7. `net_profit = revenue − spend − total_costs`; `margin = net_profit ÷ revenue` (null when revenue is 0).

**Abel's commission is `pct_of_profit` at 5%** — base is revenue − spend − retainer − tooling − creative, i.e. **net profit**, same basis everyone else is paid on. Abel is paid **first**; the remainder is split downstream. Negative profit resolves his commission to **$0**, never a negative cost. The modal must show the resolved dollar figure live (`5% of $9,483 net profit = $474.15`) so this is never ambiguous at entry time.

**Do not log downstream profit splits (Joel/Steve) as cost entries.** The P&L stops at net profit; distribution of that net is out of scope. If a future phase does model it, it needs a *second* tier that resolves against profit-after-Abel — all `pct_of_profit` entries at the current tier share one base and are computed in parallel, which is exactly what makes "Abel first" correct today.

`recurring_monthly` in a partial (MTD) month: charge the **full** monthly amount, not prorated. A retainer is owed for the month regardless of what day it is. Label it in the ledger as `full month` so the MTD net is understood to be conservative.

### 5.3b Account-spanning costs

Abel's retainer covers **whatever accounts he's working on — currently all of them**. Those entries are stored with `ad_account_id = NULL` and split at read time:

- `by_spend` (default): each account is charged its share of the period's spend. `account_share = account_spend ÷ total_spend_all_accounts`. An account with zero spend in the period is charged **nothing** — the retainer follows the work.
- `even`: divided equally across all accounts that had any spend in the period.
- If **no** account had spend in the period, fall back to an even split across all known accounts so the cost never silently vanishes.

The split denominator is total spend across **all** accounts, which means computing an account-spanning cost requires reading spend for accounts the current user may not be scoped to. Do this in the service layer with an unscoped Meta call; **return only the resolved dollar amount for the permitted account** — never leak the other accounts' spend figures into the response.

In the ledger table, account-spanning rows render with an `All accounts` pill and show both the full amount and this account's share: `$3,000 → $1,240 (41% of spend)`.

### 5.4 API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/pnl/summary` | `?ad_account_id&period=month\|mtd\|custom&month=YYYY-MM&date_from&date_to` → spend, revenue, costs breakdown, net, margin, roas, flags (`revenue_source`, `unmapped_adsets`, `has_costs`) |
| `GET` | `/pnl/months` | Last 6–12 closed months + MTD, one row each. Powers the MoM table and CSV export. |
| `GET` | `/pnl/costs` | List cost entries for an account, optionally filtered by month |
| `POST` | `/pnl/costs` | Create |
| `PATCH` | `/pnl/costs/{id}` | Update |
| `DELETE` | `/pnl/costs/{id}` | Delete |

All under `/api/v1`, new file `backend/app/api/v1/pnl.py`, router registered at module level in `main.py`.

**Account scoping is mandatory.** Reuse the existing `_resolve_scoped_default_account(current_user, ad_account_id)` pattern from `dashboard.py`, and enforce that a scoped user cannot read or write cost entries for an account they are not assigned to (`user_ad_accounts`). A P&L leak across accounts is worse than a broken page.

**Permission gate.** Every endpoint above depends on `require_permission("pnl:read")` (`app.core.deps`); the four mutating cost endpoints additionally require `pnl:write`. Both permissions ship in migration `t8p6q2r3s5o1`, granted to the `admin` and `manager` roles. `User.has_permission()` returns True unconditionally for superusers, so Steve has access with no role change. **Joel's account must hold `admin` or `manager`** — verify before the UI ships, or the page 403s for him. The Dashboard strip must check the same permission client-side and render nothing (not an error) when absent.

### 5.5 Frontend

- `import { authFetch } from '../lib/facebookApi'` — never raw `fetch()`.
- `useToast()` for every success/error. Never `alert()`.
- New page `frontend/src/pages/Pnl.jsx`, route `/pnl` in `App.jsx`, nav entry in `Layout.jsx`.
- Re-fetch on `activeAccountId` change.

---

## 6. Tracking & Analytics

- Log every cost-entry create/update/delete with `created_by` so there is an audit trail on who changed the numbers.
- Surface `revenue_source` (`live` | `cached`) and `unmapped_adsets` on the summary response and render both as small captions. A P&L that quietly under-reports revenue is worse than one that admits it is incomplete.

---

## 7. Build Priority

**Phase 1 — Claude Code (migration + model + push)**
1. `PnlCostEntry` in `models.py`
2. Migration off head `s7o5p1q2r4n0`, `has_table()` guard, `check_alembic_heads.py` passes

**Phase 2 — Codex (routes + UI), Claude Code reviews and pushes**
3. `backend/app/api/v1/pnl.py` — six endpoints, scoped
4. `frontend/src/pages/Pnl.jsx` — tiles, month picker, cost ledger CRUD, MoM table, CSV export
5. Nav + route registration
6. Dashboard 5-tile strip

**Phase 3 — Directional, not scoped yet**
7. Auto-capture creative platform costs (`source = auto_kie` / `auto_video`) so kie.ai and video-generation spend lands in the ledger without manual entry — see §8.
8. Second account onboarding (RHO) once Commercial Insurance is validated for a full month.
9. Per-niche P&L (join the existing `/dashboard/niche-summary` niche rollup to the cost ledger with an allocation rule).

---

## 8. Video Generation — Reference and P&L Hook

Per Steve: this brief must carry the reference forward to building a **real video generation template inside Ad Builder**.

**Current state in the repo:**
- `frontend/src/pages/VideoAds.jsx` exists (212 lines) and is a **wizard shell only** — Brand → Product → Profile → Video Style → Generate, with no generation backend behind it. Nav entry is live at `/video-ads` under Build Creatives.
- `CODEX_BRIEF_ugc_video_mvp.md` is the written spec: Commercial Insurance UGC MVP, 9:16, 20–30s, niches = barber shops / trucking / religious organizations, hybrid UGC (talking-head hook → B-roll → captions → CTA overlay), kie.ai video first with the provider abstraction kept open.
- `COMPETITIVE_TEARDOWN_arcads.md` is the competitive reference.

**What is still missing to "truly generate video from within the Ad Builder":** a **video ad template system** — the reusable, niche-parameterized shot plan that turns a script into an assembled video. Same structural role that `ad_styles` / `WinningAd` templates play for static image ads today. Concretely:

- A `video_templates` concept: named template = hook style + shot sequence + caption style + CTA overlay + aspect/length, parameterized by niche and offer line.
- A provider abstraction layer (`video_service.py`) so kie.ai can be swapped for a specialist avatar/lip-sync provider without touching the page.
- Assembly + storage to R2, then into the Generated Ads library, then Push to Meta — reusing the paths that already exist for images.

**The P&L tie-in — build the hook now, not later:** every video generation has a hard per-render provider cost, and it will be the fastest-growing line item in the creative category. The `source` and `vendor` columns on `pnl_cost_entries` exist so that when video generation ships, each render can write a `source='auto_video'`, `vendor='kie.ai'` cost row automatically and the P&L stays honest without anyone logging receipts. Same applies to existing kie.ai image credits (`source='auto_kie'`).

**This brief does not scope the video build.** It reserves the schema for its cost and points at `CODEX_BRIEF_ugc_video_mvp.md` as the spec of record. Recommend sequencing it after P&L Phase 2 ships, so the first month of real video spend is already being tracked when it starts.

---

## 9. Open Questions & Dependencies

**Resolved by Steve 2026-07-27:**

- ~~Abel's commission structure~~ → **5% of net profit** — the same basis everyone is paid on. Abel is paid first, remainder split downstream (out of scope for this build). Negative profit → $0. Implemented as `pct_of_profit`. See §5.3.
- ~~Retainer account allocation~~ → **spans all accounts he's involved in, currently all of them**. Implemented as `ad_account_id = NULL` + `allocation_method = by_spend`. See §5.3b.
- ~~Who sees the P&L~~ → **Joel and Steve**. Implemented as `pnl:read` / `pnl:write` on the `admin` and `manager` roles. Joel has admin — no role change needed. See §5.4.

**Still open:**

1. **Meta spend vs. invoiced spend** — Meta insights spend can drift from the actual invoice (credits, refunds, currency). Should closed months support a manual **spend override** so the P&L reconciles to the bank? Recommend yes, as a Phase 2 nice-to-have: one nullable `spend_override` per account-month.
4. **RedTrack revenue vs. paid revenue** — RedTrack revenue is attributed at conversion time; buyers can claw back. Same question as #3: does a closed month need a revenue true-up field?
5. **Do Joel and Abel both see the P&L, or Steve only?** Cost entries include a retainer and a commission. Recommend gating `/pnl` and the Dashboard strip behind a permission (`view_pnl`) rather than showing every scoped user their own comp line.
6. **RedTrack account coverage** — confirm the Commercial Insurance campaigns are fully tagged in RedTrack (sub2 = `fb_adset_id`). Any untagged ad set shows as spend with no revenue and will make the account look unprofitable. `unmapped_adsets` on the summary response is the canary.

---

## 10. Files Touched

| File | Change | Owner |
|---|---|---|
| `backend/app/models.py` | `PnlCostEntry` | Claude Code |
| `backend/alembic/versions/<new>.py` | create table, guarded | Claude Code |
| `backend/app/api/v1/pnl.py` | new, 6 endpoints | Codex |
| `backend/app/main.py` | register router | Claude Code |
| `frontend/src/pages/Pnl.jsx` | new page | Codex |
| `frontend/src/App.jsx` | `/pnl` route | Codex |
| `frontend/src/components/Layout.jsx` | nav entry | Codex |
| `frontend/src/pages/Dashboard.jsx` | 5-tile strip under h1 | Codex |

No trigger files touched. No new env vars — `REDTRACK_API_KEY` is already live on the VPS. No message to Golden required.
