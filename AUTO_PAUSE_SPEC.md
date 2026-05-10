# Auto-Pause Feature — Implementation Spec

**Date:** 2026-04-23  
**Status:** Backend complete. Frontend page built but not wired in. 4 issues to resolve before push.

---

## What This Feature Does

Allows Joel to define rules per ad set: "if CPL exceeds $X after spending at least $Y, pause the ad set automatically." Rules are checked every 30 minutes by a background scheduler (APScheduler) and can also be triggered manually. Live Meta Insights data is surfaced on the same screen so Joel can see performance without leaving the app.

---

## What's Already Built (do not rebuild, do not touch)

### Backend — all files exist and are correct

| File | What it does |
|------|-------------|
| `backend/app/api/v1/auto_pause.py` | Full router: GET/POST/PATCH/DELETE rules, GET insights, POST check |
| `backend/app/models.py` | `AutoPauseRule` model added |
| `backend/app/services/facebook_service.py` | `get_adset_insights()` and `update_adset_status()` methods appended |
| `backend/app/main.py` | Router registered at `/api/v1/auto-pause`, APScheduler wired into startup/shutdown |
| `backend/alembic/versions/a1b3c5d7e9f2_add_auto_pause_rules_table.py` | Migration for `auto_pause_rules` table |
| `backend/requirements.txt` | `apscheduler>=3.10.0` added |

### Frontend — page exists

| File | Status |
|------|--------|
| `frontend/src/pages/CampaignPerformance.jsx` | Built. Not yet registered as a route or in the nav. |

---

## Issues to Fix Before Pushing

### Issue 1: `authFetch` is not exported from `facebookApi.js` — WILL CRASH

**File:** `frontend/src/lib/facebookApi.js`  
**Problem:** `CampaignPerformance.jsx` does `import { authFetch } from '../lib/facebookApi'` but `authFetch` is defined as `const authFetch = ...` (no `export`). This is a named import of an unexported symbol — React will compile but `authFetch` will be `undefined` at runtime, causing every API call to fail.  
**Fix:** Change `const authFetch = async ...` to `export const authFetch = async ...` in `facebookApi.js`.  
**Risk:** Zero — `authFetch` is a module-internal helper. Adding `export` only exposes it; no existing callers change behavior.

---

### Issue 2: Wrong data source for ad set list — page will show empty or wrong data

**File:** `frontend/src/pages/CampaignPerformance.jsx` line 176  
**Problem:** The page calls `GET /api/v1/facebook/adsets` expecting objects with `{ id, name, fb_adset_id, status }` where `id` is our internal DB UUID and `fb_adset_id` is Meta's adset ID. But `/api/v1/facebook/adsets` calls `service.get_adsets()` which fetches **live from Meta**, returning objects with `{ id }` (Meta's ID) and no `fb_adset_id` field. The `activeAdsets` filter (`adsets.filter(a => a.fb_adset_id)`) will return an empty array every time.  
**Fix:** The page should call `GET /api/v1/facebook/adsets/saved` — a DB-backed endpoint that returns our stored adsets with both the internal `id` and `fb_adset_id`. This endpoint **already exists** in `facebook.py` (the `/adsets/save` POST at line 216 is for saving; we need a GET equivalent). 

**Two options — pick one:**

**Option A (preferred, minimal change):** Add a GET `/api/v1/facebook/adsets/saved` endpoint to `facebook.py` that queries `db.query(FacebookAdSet).all()` and returns `[{id, name, fb_adset_id, status, campaign_id}]`. Change the one URL in `CampaignPerformance.jsx` from `/facebook/adsets` to `/facebook/adsets/saved`.

**Option B:** Change `CampaignPerformance.jsx` to call the existing Meta-live endpoint and re-map the fields: `fb_adset_id = adset.id` (since Meta's `id` IS the fb_adset_id). Use a separate call to get DB adsets for rule association. More complex, Option A is cleaner.

---

### Issue 3: CSS utility classes don't exist — buttons and inputs will be unstyled

**File:** `frontend/src/pages/CampaignPerformance.jsx` (modal: `btn-primary`, `btn-secondary`, `input-base`)  
**Problem:** Classes `input-base`, `btn-primary`, `btn-secondary` are used in the `AddRuleModal` component but are not defined anywhere in `index.css` or `App.css`. These will render as completely unstyled elements.  
**Fix:** Add them to `frontend/src/index.css` as Tailwind `@layer components`. Styles should match the rest of the app (uses indigo/purple as primary action color, gray borders):

```css
@layer components {
  .input-base {
    @apply w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500;
  }
  .btn-primary {
    @apply px-4 py-2 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed;
  }
  .btn-secondary {
    @apply px-4 py-2 rounded-lg text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 transition-colors;
  }
}
```

**Risk:** Zero — additive only. No existing page uses these class names (confirmed by grep).

---

### Issue 4: Route and nav not wired — page is unreachable

**File A:** `frontend/src/App.jsx`  
**Change needed:** Import `CampaignPerformance` and add route `path="campaign-performance"`.

**File B:** `frontend/src/components/Layout.jsx`  
**Change needed:** Add nav item to `menuItems` array.

**Placement decision:**  
The `Facebook Campaigns` item currently sits alone at the bottom of the main nav. Best UX is to make it a sub-nav parent with two children:
- `Facebook Campaigns` → `/facebook-campaigns` (existing wizard)
- `Performance & Auto-Pause` → `/campaign-performance` (new page)

This mirrors how `Research` and `Brands` work (expandable with sub-items). Icon: `TrendingDown` from lucide-react (already imported in `CampaignPerformance.jsx`, needs to be imported in `Layout.jsx`).

**Alternative (simpler):** Keep `Facebook Campaigns` as a standalone link, add `Performance` as its own top-level item below it with a `BarChart2` icon. Less elegant but zero risk of breaking the existing expand/collapse logic.

**Recommendation:** Go with the sub-nav approach — it groups related functionality and is the same pattern already in use.

---

## Data Flow Summary

```
User opens /campaign-performance
  → Page mounts → loadAdsets() → GET /api/v1/facebook/adsets/saved (DB query)
  → Page mounts → loadRules()  → GET /api/v1/auto-pause/rules (DB query)
  → For each adset with fb_adset_id:
      InsightsCard mounts → GET /api/v1/auto-pause/insights/{fb_adset_id}?date_preset=last_7d
        → backend: AdSet(fbid).get_insights([spend, leads, cpl, ctr]) → Meta API
        → returns: { spend, leads, cpl, clicks, ctr }

User clicks "Add Rule" → AddRuleModal
  → POST /api/v1/auto-pause/rules { adset_id, metric, operator, threshold, min_spend }
  → backend: validates, creates AutoPauseRule row, returns { id }

User clicks "Check Now"
  → POST /api/v1/auto-pause/check
  → backend _run_check(): for each active rule, fetch insights, evaluate threshold
  → if breached: calls Meta API update_adset_status('PAUSED'), sets rule.is_active=False
  → returns: { paused: [...], skipped: [...], errors: [...] }

APScheduler (every 30 min)
  → calls _run_check() in background thread
  → logs results to Railway console
```

---

## What Does NOT Change

- `FacebookCampaigns.jsx` — untouched
- `facebook_service.py` campaign/adset/ad creation logic — untouched
- All existing routes — untouched
- All existing DB migrations — untouched
- The wizard flow — untouched

The only files that get modified are:
1. `frontend/src/lib/facebookApi.js` — export `authFetch` (1 word change)
2. `frontend/src/index.css` — add 3 utility classes (additive)
3. `frontend/src/App.jsx` — add 1 import + 1 route
4. `frontend/src/components/Layout.jsx` — restructure `Target` nav item to sub-nav
5. `backend/app/api/v1/facebook.py` — add 1 GET endpoint for DB adsets

---

## New Endpoint Spec: GET /api/v1/facebook/adsets/saved

**Purpose:** Return all ad sets stored in our DB (with their Meta IDs), for use by the performance page.  
**Route:** `GET /api/v1/facebook/adsets/saved`  
**Auth:** `get_current_user` (same as all other endpoints)  
**Query params:** `campaign_id` (optional filter)  
**Response:**
```json
[
  {
    "id": "uuid-internal",
    "name": "Commercial Insurance - Mon-Thu",
    "fb_adset_id": "120212345678",
    "status": "ACTIVE",
    "campaign_id": "uuid-internal-campaign"
  }
]
```
**Implementation:** `db.query(FacebookAdSet).order_by(FacebookAdSet.created_at.desc()).all()`

---

## Deployment Checklist

- [ ] Fix `authFetch` export in `facebookApi.js`
- [ ] Add GET `/adsets/saved` endpoint to `facebook.py`
- [ ] Update `CampaignPerformance.jsx` to use `/facebook/adsets/saved`
- [ ] Add CSS utility classes to `index.css`
- [ ] Register route in `App.jsx`
- [ ] Add nav entry in `Layout.jsx`
- [ ] Commit all changes (backend + frontend together in one commit)
- [ ] Push to `sunbunzz627` fork → PR to `BHM-Dev:develop`
- [ ] Notify Golden on Slack (#C041GSZD1NG): migration `a1b3c5d7e9f2` needs `alembic upgrade head` — creates `auto_pause_rules` table

---

## Risks

**Low risk overall.** The backend is entirely additive (new table, new routes, new scheduler). The frontend changes are:
- 1 export keyword — no behavioral change to existing callers
- 3 new CSS classes — additive only
- 1 new route — additive only
- Nav restructure — only affects the `Target` (Facebook Campaigns) nav item, which currently has no sub-items

The only spot with any structural change is the `Layout.jsx` nav: converting `Facebook Campaigns` from a simple `Link` to an expandable sub-nav. The same pattern is used for `Research` and `Brands` so the implementation is well-understood. If something goes wrong, the worst case is the Facebook Campaigns link disappears from the nav — trivially reverted.

---

## Open Questions

1. **Ad Account ID field on performance page** — Joel will need to enter his ad account ID to fetch live insights. Should this be pre-populated from the connected ad account in settings, rather than requiring manual entry each time? Not blocking — the field works — but would improve UX.

2. **Re-arming a triggered rule** — When a rule fires and pauses an adset, `is_active` is set to `False` to prevent re-firing. If Joel fixes the campaign and wants the rule monitoring again, he needs to toggle it back on (PATCH). Is this the expected UX or should it auto-re-arm when the adset is manually un-paused? Current behavior is fine for MVP.

3. **Insights for DB adsets without `fb_adset_id`** — Ad sets that were saved locally but never launched to Meta won't have `fb_adset_id`. The page correctly filters these out (`activeAdsets = adsets.filter(a => a.fb_adset_id)`). They'll just not appear in the performance table. Acceptable.
