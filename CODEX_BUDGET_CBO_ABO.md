# Budget Editing + CBO/ABO Switching — Codex Brief

**Repo:** BHM-Dev/iscale-facebook-ad-builder  
**Branch:** develop  
**Files to change:** `frontend/src/pages/CampaignPerformance.jsx`, `backend/app/api/v1/facebook.py`  
**Do NOT touch:** `BulkAdCreation.jsx`, `AdCreativeStep.jsx`, `facebookApi.js`, `facebook_service.py`  
**Do NOT push** — commit locally, hand off to Claude Code for Sonnet review + push.

---

## Context

Joel Welch (media buyer, primary user) runs both CBO and ABO campaigns.

- **CBO (Campaign Budget Optimization)** — budget is set at the campaign level. Individual adsets do not have their own budgets.
- **ABO (Ad Set Budget Optimization)** — no campaign-level budget. Each adset has its own daily budget.

Joel recently switched some campaigns from ABO to CBO and wants to be able to:
1. Edit the campaign-level daily budget for CBO campaigns without leaving Campaign Performance
2. Switch a campaign between CBO and ABO from the same UI

Adset-level inline budget editing already exists on the adset rows (the `$ Budget` button). That covers ABO. This brief covers the CBO side + the switch mechanic.

---

## Current State (understand before changing)

### Backend
- `GET /facebook/adsets/saved` returns adsets with `campaign_id`, `fb_campaign_id`, `campaign_name`, `campaign_status`
- `PATCH /facebook/adsets/{fb_adset_id}/budget` exists — updates adset-level budget via Meta API (already built)
- No campaign-level budget endpoint exists yet

### Frontend — CampaignPerformance.jsx
- `groupedCampaigns` useMemo groups adsets by `campaign_id`, produces groups with `campaignName`, `campaignStatus`, `totalSpend`, etc.
- Campaign header row renders: campaign name, ACTIVE/PAUSED badge, active adset count, aggregated Spend/Leads/CPL/ROAS
- Adset rows are a `<table>` with columns: AD SET NAME | STATUS | SPEND | LEADS | CPL | ROAS | PROFIT | BRAND | ACTIONS
- Budget column currently shows `— CBO` (italic gray) for every adset row (hardcoded — doesn't know actual budget type)
- Existing adset inline budget editor: `editingBudget` state, `budgetInput` state, `saveBudget()` function, `$ Budget` button in STATUS cell

---

## What to Build

### 1. Backend — New endpoint: PATCH /facebook/campaigns/{fb_campaign_id}/budget

File: `backend/app/api/v1/facebook.py`

```python
from pydantic import BaseModel, Field

class CampaignBudgetUpdateRequest(BaseModel):
    daily_budget_cents: int | None = Field(None, ge=100)  # None when switching to ABO
    budget_optimization: str = Field(..., pattern="^(CBO|ABO)$")

@router.patch("/campaigns/{fb_campaign_id}/budget")
def update_campaign_budget(
    fb_campaign_id: str,
    body: CampaignBudgetUpdateRequest,
    service: FacebookService = Depends(get_facebook_service),
    current_user: User = Depends(require_permission("campaigns:write")),
):
    from facebook_business.adobjects.campaign import Campaign
    campaign = Campaign(fbid=fb_campaign_id, api=service.api)

    if body.budget_optimization == "CBO":
        # Set or update campaign budget
        campaign.api_update(fields=[], params={
            "daily_budget": int(body.daily_budget_cents),
        })
    else:
        # Switch to ABO — remove campaign budget
        campaign.api_update(fields=[], params={
            "daily_budget": 0,
        })

    return {"success": True, "fb_campaign_id": fb_campaign_id, "budget_optimization": body.budget_optimization}
```

**Note:** `FacebookService()` takes NO constructor args. Use `service.api` for the SDK api object (same pattern as the existing adset budget endpoint at line ~241).

---

### 2. Backend — Add campaign budget data to GET /facebook/adsets/saved

File: `backend/app/api/v1/facebook.py`, function `read_saved_adsets`

The adset response already includes `campaign_id` and `fb_campaign_id`. Add two fields to each adset dict:

```python
"campaign_budget_optimization": a.campaign.budget_optimization if a.campaign else None,
# "CBO" or "ABO" or None — stored on FacebookCampaign model
"campaign_daily_budget": a.campaign.daily_budget if a.campaign else None,
# integer cents, or None
```

**Check first:** look at the `FacebookCampaign` model in `backend/app/models.py` to confirm whether `budget_optimization` and `daily_budget` columns exist. If they do NOT exist:
- Add them as nullable columns to `FacebookCampaign` in `models.py`
- Create an Alembic migration using raw SQL (`ADD COLUMN IF NOT EXISTS`)
- **STOP and hand off to Claude Code** — migrations require the 2-agent review + push flow

If the columns DO exist, just read them in the response — no migration needed.

---

### 3. Frontend — Campaign header row: budget button (Option B popover)

File: `frontend/src/pages/CampaignPerformance.jsx`

**New state to add:**
```js
const [budgetPopover, setBudgetPopover] = useState(null); // fb_campaign_id of open popover, or null
const [campaignBudgetInput, setCampaignBudgetInput] = useState('');
const [campaignBudgetType, setCampaignBudgetType] = useState('CBO'); // 'CBO' or 'ABO'
const [savingCampaignBudget, setSavingCampaignBudget] = useState(null);
```

**groupedCampaigns useMemo** — extend each group to include budget data from the first adset in the group (all adsets in a group share the same campaign):
```js
// Add to each group object:
campaignBudgetOptimization: group.adsets[0]?.campaign_budget_optimization ?? null,
campaignDailyBudget: group.adsets[0]?.campaign_daily_budget ?? null,
fbCampaignId: group.adsets[0]?.fb_campaign_id ?? null,
```

**saveCampaignBudget function:**
```js
const saveCampaignBudget = async (fbCampaignId) => {
  const isCBO = campaignBudgetType === 'CBO';
  if (isCBO) {
    const dollars = parseFloat(campaignBudgetInput);
    if (!dollars || dollars < 1) { showError('Enter a valid budget ($1 minimum)'); return; }
  }
  setSavingCampaignBudget(fbCampaignId);
  try {
    const res = await authFetch(`${API_BASE}/facebook/campaigns/${fbCampaignId}/budget`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        daily_budget_cents: isCBO ? Math.round(parseFloat(campaignBudgetInput) * 100) : null,
        budget_optimization: campaignBudgetType,
      }),
    });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
    showSuccess(isCBO
      ? `Campaign budget set to $${parseFloat(campaignBudgetInput).toFixed(0)}/day`
      : 'Campaign switched to ABO — set budgets on each ad set below'
    );
    setBudgetPopover(null);
    loadAdsets(); // refresh to get updated campaign_budget_optimization
  } catch (e) { showError(e.message); }
  finally { setSavingCampaignBudget(null); }
};
```

**Campaign header row** — replace the current right-side KPI strip render. Currently it shows Spend/Leads/CPL/ROAS. Add the budget button after ROAS, before the collapse chevron area:

```jsx
{/* Campaign budget button — only show when fb_campaign_id is known */}
{group.fbCampaignId && (
  <div className="relative">
    <button
      onClick={e => {
        e.stopPropagation();
        if (budgetPopover === group.fbCampaignId) {
          setBudgetPopover(null);
        } else {
          setBudgetPopover(group.fbCampaignId);
          setCampaignBudgetType(group.campaignBudgetOptimization || 'CBO');
          setCampaignBudgetInput(
            group.campaignDailyBudget
              ? (group.campaignDailyBudget / 100).toFixed(0)
              : ''
          );
        }
      }}
      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 transition-colors text-gray-700 hover:text-indigo-700 text-xs font-medium shadow-sm"
    >
      <DollarSign size={12} />
      {group.campaignBudgetOptimization === 'CBO' && group.campaignDailyBudget
        ? `$${(group.campaignDailyBudget / 100).toFixed(0)}/day`
        : group.campaignBudgetOptimization === 'ABO'
          ? 'ABO'
          : 'Budget'
      }
    </button>

    {/* Popover */}
    {budgetPopover === group.fbCampaignId && (
      <div
        className="absolute right-0 top-10 w-64 bg-white rounded-xl border border-gray-200 shadow-lg p-4 z-50"
        onClick={e => e.stopPropagation()}
      >
        <div className="text-xs font-semibold text-gray-700 mb-3">Campaign Budget Settings</div>

        {/* CBO / ABO toggle */}
        <div className="mb-3">
          <div className="text-[10px] text-gray-400 uppercase tracking-wide mb-1.5">Budget Type</div>
          <div className="grid grid-cols-2 gap-1 bg-gray-100 rounded-lg p-0.5">
            {['CBO', 'ABO'].map(type => (
              <button
                key={type}
                onClick={() => setCampaignBudgetType(type)}
                className={`py-1.5 rounded-md text-xs font-semibold transition-all ${
                  campaignBudgetType === type
                    ? 'bg-white text-indigo-700 shadow-sm'
                    : 'text-gray-500'
                }`}
              >
                {type}
                <span className="text-[10px] font-normal text-gray-400 block">
                  {type === 'CBO' ? 'Campaign level' : 'Ad set level'}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Daily budget input — only shown for CBO */}
        {campaignBudgetType === 'CBO' && (
          <div className="mb-3">
            <div className="text-[10px] text-gray-400 uppercase tracking-wide mb-1">Daily Budget</div>
            <div className="flex items-center gap-1.5 border border-gray-200 rounded-lg px-2.5 py-1.5 focus-within:ring-1 focus-within:ring-indigo-400 focus-within:border-indigo-300">
              <span className="text-gray-400 text-xs">$</span>
              <input
                type="number"
                min="1"
                step="1"
                value={campaignBudgetInput}
                onChange={e => setCampaignBudgetInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') saveCampaignBudget(group.fbCampaignId);
                  if (e.key === 'Escape') setBudgetPopover(null);
                }}
                placeholder="e.g. 500"
                className="flex-1 text-sm font-semibold focus:outline-none text-gray-800 w-full"
                autoFocus
              />
              <span className="text-gray-400 text-xs">/day</span>
            </div>
          </div>
        )}

        {/* ABO warning */}
        {campaignBudgetType === 'ABO' && (
          <div className="mb-3 text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-2.5 py-2">
            Removes campaign budget. Set budgets on each ad set individually using the $ Budget button on each row.
          </div>
        )}

        <div className="flex gap-2">
          <button
            onClick={() => setBudgetPopover(null)}
            className="flex-1 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={() => saveCampaignBudget(group.fbCampaignId)}
            disabled={savingCampaignBudget === group.fbCampaignId}
            className="flex-1 py-1.5 text-xs rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-700 disabled:opacity-50"
          >
            {savingCampaignBudget === group.fbCampaignId ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    )}
  </div>
)}
```

**Close popover on outside click** — add this useEffect:
```js
useEffect(() => {
  if (!budgetPopover) return;
  const handler = () => setBudgetPopover(null);
  document.addEventListener('click', handler);
  return () => document.removeEventListener('click', handler);
}, [budgetPopover]);
```

---

### 4. Frontend — Adset Budget column: show real amount vs CBO indicator

Currently every adset Budget cell shows `— CBO` regardless of campaign type. Update it to reflect reality:

```jsx
// In the Budget <td> of each adset row:
{group.campaignBudgetOptimization === 'CBO'
  ? <span className="text-gray-400 italic text-[11px]">— CBO</span>
  : adset.daily_budget
    ? <span className="text-gray-700 text-xs font-medium">${(adset.daily_budget / 100).toFixed(0)}/day</span>
    : <span className="text-gray-400 italic text-[11px]">No budget</span>
}
```

Note: `adset.daily_budget` is in cents (already added to the adsets/saved response in a previous session).

---

## Patterns You Must Follow

- All API calls: `authFetch` from `'../lib/facebookApi'` — never raw `fetch()`
- Notifications: `showSuccess` / `showError` from `useToast()` — never `alert()`
- `FacebookService()` takes NO constructor args — use `Depends(get_facebook_service)`
- `DollarSign` is already imported from lucide-react in CampaignPerformance.jsx

---

## Out of Scope for This Brief

- Dashboard budget editing — Joel confirmed Campaign Performance is the primary tool. Skip Dashboard for now.
- Lifetime budgets — Meta also supports lifetime budgets but Joel only uses daily. Ignore.
- Adset-level budget editing on ABO campaigns — already exists via the `$ Budget` inline editor on each adset row. No changes needed there.

---

## Definition of Done

- [ ] `PATCH /facebook/campaigns/{fb_campaign_id}/budget` endpoint works
- [ ] Campaign header row shows `$500/day` button (CBO) or `ABO` badge
- [ ] Clicking button opens popover with CBO/ABO toggle + budget input
- [ ] Switching CBO→ABO shows warning, Save calls endpoint, triggers `loadAdsets()`
- [ ] Adset Budget column shows `— CBO` for CBO campaigns, actual amount for ABO
- [ ] `npm run build` passes with no errors
- [ ] No push — commit locally and hand off to Claude Code

---

## End With

> "Edits done — ready for Claude Code Sonnet review + push."
