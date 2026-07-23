# CBO Sweep — Codex Chrome Brief

**Scope:** Verification + targeted fixes only. No new features. No backend changes unless a clear bug is found.

**Preflight:**
```bash
git pull origin develop
```

**App:** `https://adbuilder.velocitymx.io` (live — sign in as Joel)

---

## Background

A CBO detection fix was shipped today (`8e060a5`). It fixed the Dashboard Top Performers section — campaigns created in Meta Ads Manager (no `budget_type` in DB) now correctly infer as CBO when `daily_budget` is populated. The isCBO fallback logic and sublabels were applied to Dashboard.jsx.

**The question is whether the same gaps exist in other parts of the app.**

---

## Sweep Tasks

### Task 1 — Campaign Performance page (`/campaign-performance`)

**Open the page and look at the Budget column for ad set rows.**

Check in code: `frontend/src/pages/CampaignPerformance.jsx`

Search for `isCBO` or `campaign_budget_optimization` — there should be a similar check. The Dashboard fix was:
```javascript
// OLD — misses campaigns created outside the app
const isCBO = adset.campaign_budget_optimization === 'CBO';

// FIXED — also checks if daily_budget exists
const isCBO = adset.campaign_budget_optimization === 'CBO' || !!adset.campaign_daily_budget;
```

**If CampaignPerformance.jsx has the old pattern:** apply the same fix everywhere it appears in that file.

**Also check:** Does CampaignPerformance have "Sync Meta" and "Sync RedTrack" as separate buttons? If yes — merge them into a single "Sync" button (same pattern as Dashboard: `Promise.all`, Meta drives toast, RT is best-effort `.catch(() => null)`).

---

### Task 2 — "Needs Attention" section on Dashboard

**Open Dashboard (`/`), scroll to Needs Attention.**

Budget column there — does it show the same `$X/day` + small "campaign" sublabel for CBO rows? Or does it show bare `CBO` or a number without the sublabel?

Check in code: `frontend/src/pages/Dashboard.jsx` — search for the Needs Attention section's budget rendering. It may use a different code path than Top Performers.

**If it's missing the sublabel:** apply the same `<span className="flex flex-col items-end leading-tight">` pattern used in the BudgetButton component.

---

### Task 3 — +20% scale payload

**In Dashboard, hover a Top Performers CBO row. Click +20% on one.**

Watch the network request in Chrome DevTools (Network tab → XHR). The request should be a PATCH or POST to something like `/facebook/adsets/{id}/budget`.

**Verify:** Is the payload sending the *campaign* daily_budget value (e.g., `35000` cents → `$350`) × 1.2? Or is it sending the ad set's own `daily_budget` (which might be null for CBO ad sets)?

If the wrong value is being sent, check the handler in Dashboard.jsx that fires on +20% click and trace what `budget` value it uses.

---

### Task 4 — Budget display cents check

In Chrome, open DevTools → Console on the Dashboard page. Run:
```javascript
// Quickly check what raw values are coming back for a CBO row
window.__dashboardRows = null; // check if there's any exposed debug state
```

Look at a Top Performers row that shows e.g. `$350/day`. Confirm `campaign_daily_budget` in the API response is `35000` (cents), not `350` (dollars). The display code divides by 100 — if the backend already stores dollars, it would show `$3.50`.

If you can, open Network tab, find the `/api/v1/dashboard` request, look at one ad set's `campaign_daily_budget` value.

---

## Validation Checklist

Before handing off:

- [ ] Campaign Performance: `isCBO` uses the `|| !!adset.campaign_daily_budget` fallback
- [ ] Campaign Performance: Sync buttons merged (or noted if separate is intentional)
- [ ] Needs Attention: CBO rows show `$X/day` + "campaign" sublabel (or no budget rendering = not applicable)
- [ ] +20% action: confirmed it sends campaign budget × 1.2 (not adset budget)
- [ ] Budget values are in cents (÷100 = correct dollar display)
- [ ] `npm run build` passes clean

```bash
npm run build
```

**When done:** "Sweep done — ready for Claude Code review + push" + commit hash(es) + list any bugs found but not fixed (with reason).
