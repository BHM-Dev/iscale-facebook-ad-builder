# CBO Detection Fix + Top Performers Clarity — Codex Brief

**Scope:** 2 files. No new API calls. No DB migrations. No trigger files.

**Preflight:** `git pull origin develop`

**Files to edit:**
- `backend/app/api/v1/facebook.py`
- `frontend/src/pages/Dashboard.jsx`

---

## Context

All of Joel's active campaigns are CBO (confirmed via Meta API). The app has two issues:
1. **CBO detection**: relies on `budget_type` DB field, which is only set for campaigns created *through the app*. Campaigns created in Meta Ads Manager have `budget_type = null`, so the app treats them as ABO and shows wrong budget info.
2. **Top Performers UX**: shows ad sets with budget and +20% button, but Joel doesn't know the dollar amount is the *campaign* budget (not the ad set's), and that +20% scales the *entire campaign*.

---

## Change 1 — Backend CBO detection fix

**File:** `backend/app/api/v1/facebook.py`

**Find line ~242** (inside the ad set response serialization):
```python
"campaign_budget_optimization": a.campaign.budget_type if a.campaign else None,
"campaign_daily_budget": a.campaign.daily_budget if a.campaign else None,
```

**Replace with:**
```python
"campaign_budget_optimization": (
    a.campaign.budget_type or ('CBO' if a.campaign.daily_budget else None)
) if a.campaign else None,
"campaign_daily_budget": a.campaign.daily_budget if a.campaign else None,
```

**Why:** If `budget_type` wasn't set (campaign created outside the app), infer CBO from whether the campaign has a `daily_budget`. Meta only puts `daily_budget` at the campaign level for CBO campaigns.

---

## Change 2 — Frontend Dashboard.jsx

### 2a — Update `isCBO` detection everywhere in Dashboard.jsx

There are 3 places that check `campaign_budget_optimization === 'CBO'`. All need the same fallback: also treat as CBO if `campaign_daily_budget` is populated.

**Find and replace all 3 occurrences:**

```javascript
// OLD (appears at lines ~406, ~622, ~989):
const isCBO = a.adset.campaign_budget_optimization === 'CBO';
// or:
const isCBO = adset.campaign_budget_optimization === 'CBO';

// NEW (same pattern, just add the fallback):
const isCBO = a.adset.campaign_budget_optimization === 'CBO' || !!a.adset.campaign_daily_budget;
// or (for the adset form):
const isCBO = adset.campaign_budget_optimization === 'CBO' || !!adset.campaign_daily_budget;
```

Note: line ~989 is inside an IIFE `(() => { const isCBO = ...; ... })()` — update that one too.

### 2b — `hasBudget` fix for CBO rows (line ~990)

After fixing `isCBO`, the `hasBudget` check should still work. Verify line ~990 reads:
```javascript
const hasBudget = isCBO ? !!a.adset.campaign_daily_budget : !!a.adset.daily_budget;
```
No change needed if it already looks like this.

### 2c — BudgetButton: add "campaign" sublabel for CBO rows

**File:** `frontend/src/pages/Dashboard.jsx`

**Find line ~641** (inside the `BudgetButton` component, CBO branch):
```jsx
{adset.campaign_daily_budget ? `$${(adset.campaign_daily_budget / 100).toFixed(0)}/day` : 'CBO'}
```

**Replace with:**
```jsx
{adset.campaign_daily_budget ? (
  <span className="flex flex-col items-end leading-tight">
    <span>${(adset.campaign_daily_budget / 100).toFixed(0)}/day</span>
    <span className="text-[9px] text-gray-400 font-normal">campaign</span>
  </span>
) : 'CBO'}
```

### 2d — CBO context note below the section header

Add a one-line CBO note between the section header and the table — only shown when the list contains CBO campaigns.

**Find line ~944** (the `<div className="overflow-x-auto">` that wraps the table):
```jsx
<div className="overflow-x-auto">
  <table className="w-full text-sm">
```

**Replace with:**
```jsx
<div className="overflow-x-auto">
  {topPerformers.some(a => a.adset.campaign_budget_optimization === 'CBO' || !!a.adset.campaign_daily_budget) && (
    <div className="px-5 py-2 bg-blue-50 border-b border-blue-100 text-[11px] text-blue-600">
      All budgets are campaign-level (CBO) — +20% scales the full campaign, not just this ad set.
    </div>
  )}
  <table className="w-full text-sm">
```

### 2e — +20% button tooltip

**Find line ~997** (the `title` attribute on the +20% button):
```jsx
title={hasBudget ? '+20% budget' : 'Set budget first'}
```

**Replace with:**
```jsx
title={hasBudget ? (isCBO ? '+20% campaign budget — affects all ad sets in this campaign' : '+20% ad set budget') : 'Set budget first'}
```

---

## Validation checklist

```bash
npm run build   # frontend must pass clean
```

Chrome checks:
1. Dashboard Top Performers: budget buttons should show `$X/day` with a small "campaign" sublabel underneath.
2. Blue note appears above the table: "All budgets are campaign-level (CBO) — +20% scales the full campaign…"
3. Hover the +20% button — tooltip says "campaign budget — affects all ad sets…"
4. No rows showing bare "CBO" (without a dollar amount) for active campaigns that have a budget.
5. No console errors.

**When done:** "Edits done — ready for Claude Code review + push" + commit hash.
