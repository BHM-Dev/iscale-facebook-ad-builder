# CBO Clarity + Sync UX Fixes — Session Log

**Date:** 2026-06-16  
**Commits:** `8e060a5` · `f0cc9bc` · `39cb76a` · `a33f687`

---

## What was broken

Joel's Dashboard showed budget data like `$ CBO` (no dollar amount) for campaigns that were **created in Meta Ads Manager** rather than through the Ad Builder. The app's CBO detection relied on a `budget_type` DB field that only gets populated for campaigns created *inside* the app — so any campaign built externally looked like ABO and displayed wrong budget info.

Separately, the Dashboard had two sync buttons (**Sync Meta** and **Sync RedTrack**) that had to be clicked independently. Redundant.

---

## What was fixed

### 1. CBO detection — backend (`8e060a5`)

**File:** `backend/app/api/v1/facebook.py` line ~242

**Before:**
```python
"campaign_budget_optimization": a.campaign.budget_type if a.campaign else None,
```

**After:**
```python
"campaign_budget_optimization": (
    a.campaign.budget_type or ('CBO' if a.campaign.daily_budget else None)
) if a.campaign else None,
```

**Why it works:** Meta only puts `daily_budget` at the campaign level for CBO campaigns. If `budget_type` wasn't set (external campaign), the fallback infers CBO from whether a `daily_budget` exists.

---

### 2. CBO UI clarity — Dashboard (`8e060a5` + `f0cc9bc`)

**File:** `frontend/src/pages/Dashboard.jsx`

- **`isCBO` fallback:** All three `isCBO` checks now treat a row as CBO if `campaign_daily_budget` is populated, even if `campaign_budget_optimization` is null.
- **Budget button sublabel:** CBO rows now show `$350/day` with a small **"campaign"** label underneath so Joel knows it's the campaign budget, not the ad set's.
- **Blue context banner:** When Top Performers contains CBO campaigns, a blue notice appears: *"All budgets are campaign-level (CBO) — +20% scales the full campaign, not just this ad set."*
- **+20% tooltip:** Updated to: *"+20% campaign budget — affects all ad sets in this campaign"* for CBO rows.

---

### 3. Sync Meta added to Dashboard (`39cb76a`)

The Sync Meta button (pulls fresh campaign + ad set data from Meta) existed on the Campaign Performance page but was missing from the Dashboard. Added it to the Dashboard toolbar.

---

### 4. Sync Meta + Sync RedTrack merged into one button (`a33f687`)

**File:** `frontend/src/pages/Dashboard.jsx`

Replaced two separate sync buttons with a single **Sync** button that fires both API calls in parallel via `Promise.all`. Meta sync drives the success/error toast; RedTrack sync is best-effort and silently swallows failures. One click does both.

---

## Potential areas still worth checking (Codex sweep targets)

- [ ] **Campaign Performance page** — does it have the same `isCBO` detection gap? Check whether CBO fallback is applied there too (separate `isCBO` logic exists in that page).
- [ ] **+20% scale action** — does the actual budget-scale API call send the right budget value when the row was inferred as CBO via `daily_budget` fallback? Trace: click +20% on an inferred-CBO row → what payload is sent?
- [ ] **"Needs Attention" section** — budget column there should also reflect the CBO sublabel fix. Was it covered by the same component or does it have its own budget rendering?
- [ ] **Sync button on Campaign Performance** — that page still has separate Sync Meta / Sync RedTrack buttons. Should they be merged there too for consistency?
- [ ] **Budget display when `daily_budget` is in cents** — the display converts `/100`, e.g. `$35000 → $350/day`. Verify no off-by-100 edge case.
