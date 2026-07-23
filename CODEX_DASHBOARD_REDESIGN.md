# Dashboard Redesign — Codex Brief

**Repo:** BHM-Dev/iscale-facebook-ad-builder  
**Branch:** develop  
**File to change:** `frontend/src/pages/Dashboard.jsx`  
**Do NOT touch:** `BulkAdCreation.jsx`, `AdCreativeStep.jsx`, `facebookApi.js`, `facebook_service.py`  
**Do NOT push** — commit locally, hand off to Claude Code for review + push.

---

## Context

Joel Welch (media buyer) logs into the Dashboard to answer two questions:
1. What do I need to scale? (top performers)
2. What do I need to cut? (needs attention)

Then he acts immediately — change a budget, pause an adset — without navigating away.

The current dashboard shows these panels side-by-side in a 2-column grid. The redesign stacks them full-width and adds a CBO-aware budget button to each row.

---

## Current State

- `adsets` state: array from `GET /facebook/adsets/saved` — each item has:
  - `id`, `name`, `fb_adset_id`, `fb_campaign_id`, `campaign_name`, `status`, `daily_budget`
  - `campaign_budget_optimization` — `"CBO"`, `"ABO"`, or `null`
  - `campaign_daily_budget` — integer cents or `null`
- `bulkInsights` state: keyed by `fb_adset_id` → `{ spend, leads, cpl, redtrack: { roas, cpl, conversions } }`
- `topPerformers` — computed array (adsets with spend ≥ $50 and rtRoas > 0, sorted by rtRoas, sliced to 4)
- `attentionList` — computed array (flagged adsets with reason/severity)
- `pauseAdset(fb_adset_id, label)` — exists, calls `PATCH /facebook/adsets/{id}/status`
- `perfLink(view, adsetId)` — exists, returns Campaign Performance URL with params
- `pausingAdsets`, `pausedOverrides` — Set state for pause button loading/optimistic state
- Two panels currently in a `grid grid-cols-1 lg:grid-cols-2 gap-6`
- Quick Actions section exists below the panels

---

## What to Build

### 1. Layout change — stack panels full-width

Replace the `grid grid-cols-1 lg:grid-cols-2 gap-6` wrapper with a `space-y-4` div. Both panels become full-width. **Top Performers goes first, Needs Attention second.**

### 2. Add budget state to Dashboard component

Add these state variables (same as CampaignPerformance):

```js
const [budgetPopover, setBudgetPopover] = useState(null);       // fb_campaign_id of open popover
const [campaignBudgetInput, setCampaignBudgetInput] = useState('');
const [campaignBudgetType, setCampaignBudgetType] = useState('CBO');
const [savingCampaignBudget, setSavingCampaignBudget] = useState(null);
const [editingBudget, setEditingBudget] = useState(null);       // fb_adset_id of open inline editor
const [budgetInput, setBudgetInput] = useState('');
const [savingBudget, setSavingBudget] = useState(null);
```

### 3. Add close-popover-on-outside-click effect

```js
useEffect(() => {
  if (!budgetPopover) return;
  const handler = () => setBudgetPopover(null);
  document.addEventListener('click', handler);
  return () => document.removeEventListener('click', handler);
}, [budgetPopover]);
```

### 4. Add saveCampaignBudget function

```js
const saveCampaignBudget = async (fbCampaignId) => {
  const isCBO = campaignBudgetType === 'CBO';
  const dollars = parseFloat(campaignBudgetInput);
  if (isCBO && (!dollars || dollars < 1)) {
    showError('Enter a valid budget ($1 minimum)');
    return;
  }
  setSavingCampaignBudget(fbCampaignId);
  try {
    const res = await authFetch(`${API_URL}/facebook/campaigns/${fbCampaignId}/budget`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        daily_budget_cents: isCBO ? Math.round(dollars * 100) : null,
        budget_optimization: campaignBudgetType,
      }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
    showSuccess(isCBO ? `Campaign budget set to $${dollars.toFixed(0)}/day` : 'Switched to ABO');
    setBudgetPopover(null);
    load(activeRange);
  } catch (e) {
    showError(e.message || 'Failed');
  } finally {
    setSavingCampaignBudget(null);
  }
};
```

### 5. Add saveAdsetBudget function (ABO inline editor)

```js
const saveAdsetBudget = async (fbAdsetId) => {
  const dollars = parseFloat(budgetInput);
  if (!dollars || dollars < 1) { showError('Enter a valid budget'); return; }
  setSavingBudget(fbAdsetId);
  try {
    const res = await authFetch(`${API_URL}/facebook/adsets/${fbAdsetId}/budget`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ daily_budget_cents: Math.round(dollars * 100) }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
    showSuccess(`Budget set to $${dollars.toFixed(0)}/day`);
    setEditingBudget(null);
    setBudgetInput('');
    load(activeRange);
  } catch (e) {
    showError(e.message || 'Failed');
  } finally {
    setSavingBudget(null);
  }
};
```

### 6. Add BudgetButton component (inline, above the return statement)

This renders the context-aware budget button for each row. For CBO adsets it shows the campaign-level popover; for ABO it shows the inline adset editor.

```jsx
const BudgetButton = ({ adset }) => {
  const isCBO = adset.campaign_budget_optimization === 'CBO';
  const fbCampaignId = adset.fb_campaign_id;

  if (isCBO) {
    return (
      <div className="relative" onClick={e => e.stopPropagation()}>
        <button
          onClick={() => {
            if (budgetPopover === fbCampaignId) {
              setBudgetPopover(null);
            } else {
              setBudgetPopover(fbCampaignId);
              setCampaignBudgetType('CBO');
              setCampaignBudgetInput(
                adset.campaign_daily_budget ? (adset.campaign_daily_budget / 100).toFixed(0) : ''
              );
            }
          }}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-white border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 text-gray-600 hover:text-indigo-700 transition-colors shadow-sm font-medium"
        >
          <DollarSign size={11} />
          {adset.campaign_daily_budget
            ? `$${(adset.campaign_daily_budget / 100).toFixed(0)}/day`
            : 'CBO'}
        </button>

        {budgetPopover === fbCampaignId && (
          <div
            className="absolute right-0 top-9 w-64 bg-white rounded-xl border border-gray-200 shadow-lg p-4 z-50 text-left"
            onClick={e => e.stopPropagation()}
          >
            <div className="text-xs font-semibold text-gray-700 mb-3">Campaign Budget Settings</div>
            <div className="mb-3">
              <div className="text-[10px] text-gray-400 uppercase tracking-wide mb-1">Daily Budget</div>
              <div className="flex items-center gap-1.5 border border-gray-200 rounded-lg px-2.5 py-1.5 focus-within:ring-1 focus-within:ring-indigo-400">
                <span className="text-gray-400 text-xs">$</span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={campaignBudgetInput}
                  onChange={e => setCampaignBudgetInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') saveCampaignBudget(fbCampaignId);
                    if (e.key === 'Escape') setBudgetPopover(null);
                  }}
                  placeholder="e.g. 500"
                  className="flex-1 text-sm font-semibold focus:outline-none text-gray-800 w-full"
                  autoFocus
                />
                <span className="text-gray-400 text-xs">/day</span>
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setBudgetPopover(null)}
                className="flex-1 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
              >Cancel</button>
              <button
                onClick={() => saveCampaignBudget(fbCampaignId)}
                disabled={savingCampaignBudget === fbCampaignId}
                className="flex-1 py-1.5 text-xs rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-700 disabled:opacity-50"
              >
                {savingCampaignBudget === fbCampaignId ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ABO — inline adset budget editor
  if (editingBudget === adset.fb_adset_id) {
    return (
      <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
        <span className="text-xs text-gray-400">$</span>
        <input
          type="number"
          min="1"
          step="1"
          value={budgetInput}
          onChange={e => setBudgetInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') saveAdsetBudget(adset.fb_adset_id);
            if (e.key === 'Escape') { setEditingBudget(null); setBudgetInput(''); }
          }}
          className="w-20 text-xs border border-gray-200 rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-indigo-400"
          autoFocus
        />
        <span className="text-xs text-gray-400">/day</span>
        <button
          onClick={() => saveAdsetBudget(adset.fb_adset_id)}
          disabled={savingBudget === adset.fb_adset_id}
          className="text-green-600 hover:text-green-700 disabled:opacity-40 text-xs"
        >✓</button>
        <button
          onClick={() => { setEditingBudget(null); setBudgetInput(''); }}
          className="text-gray-400 hover:text-gray-600 text-xs"
        >✕</button>
      </div>
    );
  }

  return (
    <button
      onClick={e => {
        e.stopPropagation();
        setEditingBudget(adset.fb_adset_id);
        setBudgetInput(adset.daily_budget ? String(Math.round(adset.daily_budget / 100)) : '');
      }}
      className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-white border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 text-gray-600 hover:text-indigo-700 transition-colors shadow-sm font-medium"
    >
      <DollarSign size={11} />
      {adset.daily_budget ? `$${Math.round(adset.daily_budget / 100)}/day` : 'Set budget'}
    </button>
  );
};
```

**Add `DollarSign` to the lucide-react import** at the top of Dashboard.jsx.

### 7. Rebuild Top Performers panel — full-width table

Replace the current Top Performers card JSX with this full-width panel. The `topPerformers` array already exists — extend each item to include the adset object for the BudgetButton:

**Update topPerformers computed array** to include the full adset object:

```js
const topPerformers = adsets
  .filter(a => a.fb_adset_id && bulkInsights[a.fb_adset_id])
  .map(a => {
    const ins = bulkInsights[a.fb_adset_id];
    const rt  = ins?.redtrack;
    return {
      adset: a,                           // full adset for BudgetButton
      id: a.id,
      name: a.name,
      campaignName: a.campaign_name || '',
      fb_adset_id: a.fb_adset_id || '',
      fb_campaign_id: a.fb_campaign_id || '',
      status: a.status,
      spend: ins?.spend || 0,
      leads: ins?.leads || 0,
      cpl: ins?.cpl,
      rtRoas: rt?.roas,
      rtCpl: rt?.cpl,
      rtConvs: rt?.conversions || 0,
    };
  })
  .filter(a => a.spend >= 50 && a.rtRoas != null && a.rtRoas > 0)
  .sort((a, b) => b.rtRoas - a.rtRoas)
  .slice(0, 8);
```

**Top Performers JSX:**

```jsx
{/* Top Performers */}
<div className="bg-white border-b border-gray-200">
  <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
    <h2 className="font-semibold text-gray-900 flex items-center gap-2 text-sm">
      <TrendingUp size={15} className="text-green-500" />
      Top Performers
      <span className="text-xs text-gray-400 font-normal">by RT ROAS · has spend</span>
    </h2>
    <Link to={perfLink('top-performers')} className="text-xs text-indigo-600 hover:underline flex items-center gap-1">
      View all in Performance <ArrowRight size={11} />
    </Link>
  </div>
  {loading ? (
    <div className="px-5 py-6 text-center text-sm text-gray-400">Loading...</div>
  ) : topPerformers.length === 0 ? (
    <div className="px-5 py-6 text-center text-sm text-gray-400">
      No RT data yet — sync RedTrack from the Performance page.
    </div>
  ) : (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 border-b border-gray-100">
          <th className="px-5 py-2 text-left">Ad Set</th>
          <th className="px-3 py-2 text-right">Spend</th>
          <th className="px-3 py-2 text-right">CPL</th>
          <th className="px-3 py-2 text-right">RT ROAS</th>
          <th className="px-3 py-2 text-left">Budget</th>
          <th className="px-3 py-2 text-left">Action</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-50">
        {topPerformers.map((a, i) => (
          <tr key={a.id} className="hover:bg-gray-50 transition-colors">
            <td className="px-5 py-3">
              <Link to={perfLink('top-performers', a.fb_adset_id)} className="block">
                <div className="font-medium text-gray-900 truncate max-w-[280px]" title={a.name}>
                  {a.name}
                </div>
                {a.campaignName && (
                  <div className="text-xs text-gray-400 truncate max-w-[280px]">{a.campaignName}</div>
                )}
              </Link>
            </td>
            <td className="px-3 py-3 text-right font-medium text-gray-800">
              ${a.spend.toFixed(0)}
            </td>
            <td className="px-3 py-3 text-right text-gray-600">
              {a.rtCpl != null ? `$${a.rtCpl.toFixed(2)}` : '—'}
            </td>
            <td className="px-3 py-3 text-right font-bold text-green-600">
              {a.rtRoas.toFixed(2)}x
            </td>
            <td className="px-3 py-3">
              <BudgetButton adset={a.adset} />
            </td>
            <td className="px-3 py-3">
              <button
                onClick={() => navigate(`/batch-generate?adsetName=${encodeURIComponent(a.name)}&adsetId=${encodeURIComponent(a.fb_adset_id)}&campaignId=${encodeURIComponent(a.fb_campaign_id)}`)}
                className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-indigo-600 border border-indigo-100 bg-indigo-50 hover:bg-indigo-100 transition-colors"
              >
                <Repeat2 size={11} /> Iterate
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )}
</div>
```

### 8. Rebuild Needs Attention panel — full-width table

**Update attentionList** items to include the full adset object. In the `needsAttention.push(...)` calls, add `adset: a` to each item object.

**Needs Attention JSX:**

```jsx
{/* Needs Attention */}
<div className="bg-white border-b border-gray-200">
  <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
    <h2 className="font-semibold text-gray-900 flex items-center gap-2 text-sm">
      <AlertTriangle size={15} className="text-orange-500" />
      Needs Attention
    </h2>
    <Link to={perfLink('attention')} className="text-xs text-indigo-600 hover:underline flex items-center gap-1">
      View all in Performance <ArrowRight size={11} />
    </Link>
  </div>
  {loading ? (
    <div className="px-5 py-6 text-center text-sm text-gray-400">Loading...</div>
  ) : attentionList.length === 0 ? (
    <div className="px-5 py-6 text-center text-sm text-gray-400">
      <span className="text-green-500 font-medium">All clear</span> — no issues flagged.
    </div>
  ) : (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 border-b border-gray-100">
          <th className="px-5 py-2 text-left">Ad Set</th>
          <th className="px-3 py-2 text-left">Issue</th>
          <th className="px-3 py-2 text-right">Spend</th>
          <th className="px-3 py-2 text-right">CPL</th>
          <th className="px-3 py-2 text-left">Budget</th>
          <th className="px-3 py-2 text-left">Action</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-50">
        {attentionList.map(item => {
          const isPausing = item.fb_adset_id && pausingAdsets.has(item.fb_adset_id);
          const ins = bulkInsights[item.fb_adset_id] || {};
          return (
            <tr key={item.id} className="hover:bg-gray-50 transition-colors">
              <td className="px-5 py-3">
                <Link to={perfLink('attention', item.fb_adset_id)} className="block">
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${item.severity === 'red' ? 'bg-red-500' : 'bg-orange-400'}`} />
                    <div className="font-medium text-gray-900 truncate max-w-[260px]" title={item.label}>
                      {item.label}
                    </div>
                  </div>
                  {item.campaignName && (
                    <div className="text-xs text-gray-400 truncate max-w-[260px] pl-4">{item.campaignName}</div>
                  )}
                </Link>
              </td>
              <td className="px-3 py-3">
                <span className={`text-xs ${item.severity === 'red' ? 'text-red-600' : 'text-orange-500'}`}>
                  {item.reason}
                </span>
              </td>
              <td className="px-3 py-3 text-right font-medium text-gray-800">
                {ins.spend != null ? `$${ins.spend.toFixed(0)}` : '—'}
              </td>
              <td className="px-3 py-3 text-right text-red-600 font-semibold">
                {ins.cpl != null ? `$${ins.cpl.toFixed(2)}` : '—'}
              </td>
              <td className="px-3 py-3">
                {item.adset && <BudgetButton adset={item.adset} />}
              </td>
              <td className="px-3 py-3">
                {item.fb_adset_id && (
                  <button
                    onClick={() => pauseAdset(item.fb_adset_id, item.label)}
                    disabled={isPausing}
                    className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-gray-500 border border-gray-200 hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors disabled:opacity-40"
                  >
                    {isPausing ? <RefreshCw size={11} className="animate-spin" /> : <PauseCircle size={11} />}
                    Pause
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  )}
</div>
```

**Note:** `item.campaignName` — add `campaignName: a.campaign_name || ''` to each `needsAttention.push({...})` call.

### 9. Remove Quick Actions section

Delete the entire Quick Actions `<div>` block (search for `{/* Quick Actions */}`).

### 10. Move Performance by Niche below both panels

The Niche section currently renders somewhere after the panels. Ensure it renders **after** both Needs Attention and Top Performers, not between them and the KPI cards.

---

## Patterns to follow

- All API calls: `authFetch` from `'../lib/facebookApi'`
- Notifications: `showSuccess` / `showError` from `useToast()`
- `DollarSign` icon: add to lucide-react import
- `Repeat2`, `PauseCircle`, `RefreshCw` already imported
- Do NOT add `navigate` — it already exists in Dashboard

---

## Definition of Done

- [ ] Top Performers panel is full-width table above Needs Attention
- [ ] Needs Attention panel is full-width table below Top Performers
- [ ] Each row shows adset name + campaign name subtitle
- [ ] CBO rows show campaign budget button (`$400/day` or `CBO`) with popover
- [ ] ABO rows show adset inline budget editor (`Set budget`)
- [ ] Pause button works on Needs Attention rows
- [ ] Iterate button works on Top Performers rows
- [ ] Quick Actions section removed
- [ ] Performance by Niche is below both panels
- [ ] `npm run build` passes with no errors

---

## End With

> "Edits done — ready for Claude Code review + push."
