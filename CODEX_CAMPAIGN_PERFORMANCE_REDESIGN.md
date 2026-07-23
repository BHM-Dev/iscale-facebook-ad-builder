# Campaign Performance — Redesign Brief

**File:** `frontend/src/pages/CampaignPerformance.jsx` (1599 lines)  
**Repo:** BHM-Dev/iscale-facebook-ad-builder, push to `develop`  
**Do NOT push** — commit locally and hand off to Claude Code for 2-agent review + push.

---

## Background

Joel Welch (media buyer, primary user) gave 4 pieces of feedback on Campaign Performance:

1. **Inline budget editing** — he wants to change daily budget per ad set without leaving the page
2. **Deep link from Dashboard doesn't land on the right row** — clicking "Needs Attention" or "Top Performers" on Dashboard filters the list but doesn't scroll to or highlight the specific ad set
3. **Table format** — "hard to read, things get lost." He shared a RedTrack screenshot showing a clean flat table with one row per campaign. Wants metrics in columns, not scattered in a flex wrap. Campaign-level stats visible without toggling.
4. **Campaign stats without toggling** — currently, the campaign header row only shows total spend. Clicking it reveals/hides ad sets underneath. Joel wants to see campaign-level CPL, ROAS, etc. on the header row itself.

---

## Current Structure (understand before changing)

```
CampaignPerformance.jsx exports default function CampaignPerformance()

State:
- adsets: FacebookAdSet[] (fetched from GET /facebook/adsets/saved)
- bulkInsights: { [fb_adset_id]: InsightRow } (fetched from GET /auto-pause/insights-bulk)
- adsBulk: { [fb_adset_id]: Ad[] } (fetched from GET /facebook/ads-bulk)
- collapsedCampaigns: Set<string> — campaigns start open
- expandedAdsets: Set<string> — adsets start collapsed

Render tree:
  groupedCampaigns (array of { key, campaignName, campaignStatus, adsets, totalSpend })
    └─ Campaign header row (button, toggles collapse)
         └─ group.adsets.map(adset =>
              AdSet row (shows name, status badge, inline KPIs: Spend/CPL/ROAS/Profit, brand pill, pause button)
                └─ expanded: InsightsCard (Meta + RT flex stats), AdsBreakdown (table of ad-level data)

InsightsCard renders: Meta row (Spend, Leads, CPL, Reach, Frequency, Impressions, Clicks, CTR, ROAS)
                      RT row (Convs, Revenue, ROAS, RT CPL, Quality, Profit)
```

Campaign header KPIs come from `group.totalSpend` — currently just spend, no other metrics.

---

## Change 1 — Campaign header row: show campaign-level KPIs

**What to add:** On the campaign header row (the button that toggles open/close), show aggregated campaign-level metrics inline.

Compute them from `bulkInsights` data for all adsets in the group:
```js
const campaignInsights = group.adsets.reduce((acc, a) => {
  const d = bulkInsights?.[a.fb_adset_id];
  if (!d) return acc;
  acc.spend += d.spend || 0;
  acc.leads += d.leads || 0;
  acc.revenue += d.redtrack?.revenue || 0;
  acc.rtRoas = acc.spend > 0 && acc.revenue > 0 ? acc.revenue / acc.spend : null;
  return acc;
}, { spend: 0, leads: 0, revenue: 0, rtRoas: null });
const campaignCpl = campaignInsights.spend > 0 && campaignInsights.leads > 0
  ? campaignInsights.spend / campaignInsights.leads : null;
```

Show on the right side of the campaign header row: **Spend | Leads | CPL | ROAS** (if available). Keep the existing active-adset-count text on the left.

Existing campaign header already renders `${group.totalSpend.toFixed(0)} spent` on the right — replace with the richer KPI strip. The `totalSpend` value is already computed in `groupedCampaigns` derivation — you can extend that same derivation to add `totalLeads`, `totalRevenue`, `avgRoas` using the same `bulkInsights` reference.

---

## Change 2 — Deep link: scroll to + highlight specific ad set

**How deep links work today:**  
Dashboard passes `?view=attention` or `?view=top-performers` in the URL.  
CampaignPerformance reads `searchParams.get('view')` and sets `statusFilter = 'flagged'` or `'has_spend'`.

**What's missing:** Dashboard doesn't pass a specific adset ID, so the user just lands on the filtered list.

**Fix — two parts:**

**Part A: Dashboard.jsx** — when Joel clicks on a specific item in Needs Attention or Top Performers, include `adsetId` in the URL:

```js
// In Dashboard.jsx, the perfLink() function currently builds:
// /campaign-performance?view=attention  (no adset ID)
// Change to pass adsetId when available:
const perfLink = (view, adsetId = '') => {
  const params = new URLSearchParams({ view });
  if (adsetId) params.set('adsetId', adsetId);
  // ... existing date params
  return `/campaign-performance?${params.toString()}`;
};
```

In the Needs Attention list, `item.fb_adset_id` is already available on each item. Pass it to `perfLink()`.  
In the Top Performers list, `a.fb_adset_id` is already available.

**Part B: CampaignPerformance.jsx** — on mount (or when adsets load), if `searchParams.get('adsetId')` is set:
1. Find the adset row with that `fb_adset_id`
2. Auto-expand it (`setExpandedAdsets` to include it)
3. Scroll to it (`useRef` on the row div, call `ref.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })`)
4. Apply a brief highlight (add a `highlighted` state, clear after 2 seconds)

The row divs already have `key={adset.id}`. Add a `ref` callback to the matching row.

---

## Change 3 — Table format redesign

**Joel's complaint:** "Campaign Performance is hard to read and things get lost." He attached a RedTrack screenshot showing a clean table with one row per campaign, metrics in clearly labeled columns.

**Goal:** Keep the campaign → adset hierarchy but make the adset rows look like proper table rows with fixed metric columns — not ad-hoc inline KPI chips.

**Approach:** Convert the adset rows into a proper HTML `<table>` layout inside each campaign group. Keep the campaign header as a collapsible section above the table.

**Table columns for adset rows:**
| Ad Set Name | Status | Spend | Leads | CPL | ROAS | Profit | Brand | Actions |
|---|---|---|---|---|---|---|---|---|

- **Spend**: from `bulkInsights[adset.fb_adset_id]?.spend`
- **Leads**: from `bulkInsights?.leads`
- **CPL**: from `bulkInsights?.cpl` (color red if >60, or >1.5x account avg)
- **ROAS**: prefer `d.redtrack?.roas`, fall back to `d?.roas`. Color green ≥2x, red <1x. Show "RT" label if from RT.
- **Profit**: from `d.redtrack?.profit`. Color red if negative.
- **Brand**: keep the existing brand pill select dropdown
- **Actions**: Pause/Resume button + Iterate button

Header row (the `<thead>`) should be sticky within the campaign section or at minimum aligned.

**Expanded row (ad-level breakdown):** Keep the existing `AdsBreakdown` component but render it in a `<tr>` with `colSpan={8}` below the adset row when expanded. The click-to-expand behavior stays on the adset name cell.

**Loading states:** While `bulkInsightsLoading`, show `—` in metric cells (not a separate spinner per row).

**Remove:** The `InsightsCard` component's flex-wrap layout is no longer needed for the main row. The flat table columns replace it. The InsightsCard can be removed or kept only for the expanded detail view if you want to preserve the RT sub-row — but for MVP, the table row captures the essential metrics.

---

## Change 4 — Inline budget editing

**Where to add it:** In the adset row, in the Actions column (or as a separate inline edit triggered by clicking on a budget value).

**UX:** Add a small `$[budget]/day` display next to the Status badge. Clicking it turns it into an inline input (number, min 1). Pressing Enter or clicking a checkmark saves it. Pressing Escape cancels.

**Data needed:** The `adset` object from `/facebook/adsets/saved` currently returns: `id, fb_adset_id, fb_campaign_id, name, status, brand_id, brand_name`. It does NOT currently return `daily_budget`. You need to add `daily_budget` to the backend endpoint response.

**Backend change needed (add to GET /facebook/adsets/saved):**

File: `backend/app/api/v1/facebook.py`  
In the `GET /adsets/saved` route, the adset data comes from the local DB table `facebook_adsets`. The `daily_budget` is NOT stored locally — it needs to be pulled from Meta or stored. The simplest approach:

**Option A (simpler):** Add a `PATCH /facebook/adsets/{fb_adset_id}/budget` endpoint that calls Meta directly:

```python
@router.patch("/adsets/{fb_adset_id}/budget")
async def update_adset_budget(fb_adset_id: str, body: BudgetUpdateRequest, current_user=Depends(get_current_active_user)):
    svc = FacebookService()
    adset = AdSet(fb_adset_id)
    adset.api_update(fields=[], params={"daily_budget": int(body.daily_budget_cents)})
    return {"success": True}
```

Where `daily_budget_cents` = dollars × 100 (Meta uses cents). `BudgetUpdateRequest` is a Pydantic model with `daily_budget_cents: int`.

**Note:** `FacebookService()` takes NO constructor args.

For the frontend, just hit this new endpoint. Don't worry about reading current budget from Meta (it would require an extra API call per row). Show an empty input initially. Joel knows his budgets — he just needs to be able to type in a new value and save it.

**UI pattern:**
```jsx
// In adset row — small budget edit button/display
const [editingBudget, setEditingBudget] = useState(null); // adset.fb_adset_id if editing
const [budgetInput, setBudgetInput] = useState('');

// In render:
{editingBudget === adset.fb_adset_id ? (
  <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
    <span className="text-xs text-gray-400">$</span>
    <input
      type="number" min="1" step="1"
      value={budgetInput}
      onChange={e => setBudgetInput(e.target.value)}
      onKeyDown={e => {
        if (e.key === 'Enter') saveBudget(adset.fb_adset_id);
        if (e.key === 'Escape') setEditingBudget(null);
      }}
      className="w-20 text-xs border border-gray-200 rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-indigo-400"
      autoFocus
    />
    <span className="text-xs text-gray-400">/day</span>
    <button onClick={() => saveBudget(adset.fb_adset_id)} className="text-green-600 hover:text-green-700 text-xs">✓</button>
    <button onClick={() => setEditingBudget(null)} className="text-gray-400 hover:text-gray-600 text-xs">✕</button>
  </div>
) : (
  <button
    onClick={e => { e.stopPropagation(); setEditingBudget(adset.fb_adset_id); setBudgetInput(''); }}
    className="text-xs text-gray-400 hover:text-indigo-600 px-1.5 py-0.5 rounded border border-transparent hover:border-indigo-200 transition-colors flex items-center gap-1"
    title="Edit daily budget"
  >
    <DollarSign size={11} /> Budget
  </button>
)}
```

Add `DollarSign` to lucide imports.

**saveBudget function:**
```js
const saveBudget = async (fbAdsetId) => {
  const dollars = parseFloat(budgetInput);
  if (!dollars || dollars < 1) { showError('Enter a valid budget ($1 minimum)'); return; }
  try {
    const res = await authFetch(`${API_BASE}/facebook/adsets/${fbAdsetId}/budget`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ daily_budget_cents: Math.round(dollars * 100) }),
    });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
    showSuccess(`Budget updated to $${dollars.toFixed(0)}/day`);
    setEditingBudget(null);
  } catch (e) { showError(e.message); }
};
```

---

## Patterns you MUST follow

- All API calls: `authFetch` from `'../lib/facebookApi'` (already imported). Never raw `fetch()`.
- Notifications: `showSuccess/showError` from `useToast()` (already imported). Never `alert()`.
- Confirmations: `window.confirm()` is already used in this file for pause — keep consistency, don't add a modal for budget edits (not destructive enough to warrant one).
- `FacebookService()` constructor takes NO arguments.
- All state is local to this component. No new context providers needed.

## Files to change

1. `frontend/src/pages/CampaignPerformance.jsx` — main changes (all 4 items)
2. `frontend/src/pages/Dashboard.jsx` — Change 2 Part A only (pass `adsetId` in perfLink)
3. `backend/app/api/v1/facebook.py` — Change 4 only (new PATCH /adsets/{id}/budget endpoint + Pydantic model)

**Do NOT touch:** `BulkAdCreation.jsx`, `AdCreativeStep.jsx`, `facebookApi.js`, `facebook_service.py` — those require 2-agent review and must go through Claude Code.

## Do NOT push

Commit locally only. End your session with: "Edits done — ready for Claude Code 2-agent review + push."

Claude Code will run the pre-push agent review and push to BHM-Dev:develop.
