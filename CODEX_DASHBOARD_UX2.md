# Dashboard UX Improvements — Round 2

File: `frontend/src/pages/Dashboard.jsx`
No backend changes needed — all data is already available.

---

## Change 1: Consolidate Needs Attention duplicates

**Problem:** The current logic pushes one item per issue per ad set. An ad set with two issues (e.g. RT ROAS < 1 AND high CPL) appears as two rows. Joel sees the same ad set twice and has to act on it twice.

**Fix:** Group all issues for the same `fb_adset_id` into a single row. Display multiple issues as stacked text lines (or comma-separated) in the Issue column.

### Current logic (lines ~460–554):
The `needsAttention` array is built by pushing one object per triggered condition. Then `attentionList` deduplicates by `item.id` — but each issue gets a unique ID (`freq-${a.id}`, `roas-${a.id}`, `cpl-${a.id}`), so the dedup never fires for multiple issues on the same adset.

### New logic:

Replace the `needsAttention` array build + dedup with a Map-based grouping:

```js
// Build a map: fb_adset_id → { item metadata, reasons[] }
const attentionMap = new Map(); // key = fb_adset_id or rule-${r.id}

// Auto-paused rules (no fb_adset_id — keep as individual entries)
triggeredRules.forEach(r => {
  const key = `rule-${r.id}`;
  attentionMap.set(key, {
    id: key,
    label: r.adset_name || 'Ad set',
    campaignName: '',
    fb_adset_id: null,
    adset: null,
    reasons: [{ severity: 'red', text: `Auto-paused: ${r.trigger_reason}` }],
  });
});

// Active adsets — group by fb_adset_id
adsets
  .filter(a => a.status === 'ACTIVE' && a.fb_adset_id && !pausedOverrides.has(a.fb_adset_id))
  .forEach(a => {
    const ins = bulkInsights[a.fb_adset_id];
    if (!ins) return;
    const rt = ins.redtrack;
    const issues = [];

    if (ins.frequency >= 5) {
      issues.push({ severity: 'red', text: `Freq ${ins.frequency.toFixed(1)} — fatigue risk` });
    } else if (ins.frequency >= 3) {
      issues.push({ severity: 'orange', text: `Freq ${ins.frequency.toFixed(1)} — monitor` });
    }

    if (ins.spend > 50 && ins.leads === 0) {
      issues.push({ severity: 'red', text: `$${ins.spend.toFixed(0)} spent, 0 leads` });
    }

    if (rt?.roas != null && rt.roas < 1 && ins.spend > 30) {
      issues.push({ severity: 'red', text: `RT ROAS ${rt.roas.toFixed(2)}x — losing money` });
    }

    if (blendedCpl != null && ins.cpl != null && ins.cpl > blendedCpl * 1.5 && ins.spend > 30) {
      const rtRoasVal = rt?.roas;
      if (rtRoasVal == null || rtRoasVal < 1) {
        issues.push({ severity: 'orange', text: `CPL $${ins.cpl.toFixed(0)} — ${Math.round(ins.cpl / blendedCpl)}x avg` });
      }
    }

    if (issues.length === 0) return;

    const topSeverity = issues.some(i => i.severity === 'red') ? 'red' : 'orange';
    attentionMap.set(a.fb_adset_id, {
      id: `adset-${a.id}`,
      label: a.name,
      campaignName: a.campaign_name || '',
      fb_adset_id: a.fb_adset_id,
      fb_campaign_id: a.fb_campaign_id || '',
      adset: a,
      severity: topSeverity,
      reasons: issues,
    });
  });

const attentionList = Array.from(attentionMap.values()).slice(0, 8); // bump cap to 8 since deduped
```

### Render change for the Issue cell:

Replace the single `<span>` in the Issue `<td>` with:
```jsx
<td className="px-3 py-3">
  <div className="flex flex-col gap-0.5">
    {item.reasons.map((r, i) => (
      <span key={i} className={`text-xs ${r.severity === 'red' ? 'text-red-600' : 'text-orange-500'}`}>
        {r.text}
      </span>
    ))}
  </div>
</td>
```

Also update the severity dot in the Ad Set cell to use `item.severity` (already computed as the worst issue).

---

## Change 2: Scale button on Top Performers

**Goal:** Add a "+20%" quick-scale button next to Iterate. Bumps the budget by 20% without opening a popover. CBO → scales campaign budget. ABO → scales adset budget. No budget known → button disabled with tooltip "Set budget first".

### New state:
```js
const [scalingAdset, setScalingAdset] = useState(new Set());
```

### New function (add after `saveAdsetBudget`):
```js
const scaleAdset = async (a) => {
  const isCBO = a.adset.campaign_budget_optimization === 'CBO';
  const currentCents = isCBO
    ? a.adset.campaign_daily_budget  // campaign-level budget in cents
    : a.adset.daily_budget;          // adset-level budget in cents

  if (!currentCents || currentCents <= 0) {
    showError('Set a budget first before scaling');
    return;
  }

  const newCents = Math.round(currentCents * 1.2);
  const scaleKey = isCBO ? `cbo-${a.fb_campaign_id}` : a.fb_adset_id;
  setScalingAdset(prev => new Set(prev).add(scaleKey));

  try {
    if (isCBO) {
      const res = await authFetch(`${API_URL}/facebook/campaigns/${a.fb_campaign_id}/budget`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ daily_budget_cents: newCents, budget_optimization: 'CBO' }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
      showSuccess(`Campaign budget scaled to $${(newCents / 100).toFixed(0)}/day (+20%)`);
    } else {
      const res = await authFetch(`${API_URL}/facebook/adsets/${a.fb_adset_id}/budget`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ daily_budget_cents: newCents }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
      showSuccess(`Ad set budget scaled to $${(newCents / 100).toFixed(0)}/day (+20%)`);
    }
    load(activeRange);
  } catch (e) {
    showError(e.message || 'Scale failed');
  } finally {
    setScalingAdset(prev => { const next = new Set(prev); next.delete(scaleKey); return next; });
  }
};
```

### Render change — Action cell in Top Performers table:

Replace the single Iterate button with a flex row of two buttons:
```jsx
<td className="px-3 py-3">
  <div className="flex items-center gap-1.5">
    {/* Scale +20% */}
    {(() => {
      const isCBO = a.adset.campaign_budget_optimization === 'CBO';
      const hasBudget = isCBO ? !!a.adset.campaign_daily_budget : !!a.adset.daily_budget;
      const scaleKey = isCBO ? `cbo-${a.fb_campaign_id}` : a.fb_adset_id;
      const isScaling = scalingAdset.has(scaleKey);
      return (
        <button
          onClick={() => scaleAdset(a)}
          disabled={isScaling || !hasBudget}
          title={hasBudget ? '+20% budget' : 'Set budget first'}
          className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-green-700 border border-green-200 bg-green-50 hover:bg-green-100 transition-colors disabled:opacity-40"
        >
          {isScaling ? <RefreshCw size={11} className="animate-spin" /> : '+20%'}
        </button>
      );
    })()}
    {/* Iterate */}
    <button
      onClick={() => navigate(`/batch-generate?adsetName=${encodeURIComponent(a.name)}&adsetId=${encodeURIComponent(a.fb_adset_id)}&campaignId=${encodeURIComponent(a.fb_campaign_id)}`)}
      className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-indigo-600 border border-indigo-100 bg-indigo-50 hover:bg-indigo-100 transition-colors"
    >
      <Repeat2 size={11} /> Iterate
    </button>
  </div>
</td>
```

---

## Change 3: Frequency column in Top Performers

**Goal:** Show frequency alongside ROAS so Joel knows whether a winner is about to fatigue.

### Data mapping — add `frequency` to topPerformers (line ~582–594):
```js
return {
  // ... existing fields ...
  frequency: ins?.frequency ?? null,  // ADD THIS LINE
};
```

### Table header — add Freq column after RT ROAS:
```jsx
<th className="px-3 py-2 text-right">Freq</th>
```

### Table cell — add after RT ROAS td:
```jsx
<td className="px-3 py-3 text-right text-xs font-medium">
  {a.frequency != null ? (
    <span className={
      a.frequency >= 4 ? 'text-red-600' :
      a.frequency >= 2.5 ? 'text-orange-500' :
      'text-gray-400'
    }>
      {a.frequency.toFixed(1)}
    </span>
  ) : <span className="text-gray-300">—</span>}
</td>
```

---

## Summary of changes
- `Dashboard.jsx`: 3 isolated changes, all frontend only
- No new API calls (frequency already in `bulkInsights`, budget scale uses existing endpoints)
- No new imports needed except `TrendingUp` already imported; `RefreshCw`, `Repeat2` already imported

## Validation checklist
- [ ] Needs Attention: ad set with 2 issues shows as 1 row with 2 issue lines
- [ ] Needs Attention: ad set with 1 issue still shows correctly
- [ ] Top Performers: +20% button shows for adsets with a known budget
- [ ] Top Performers: +20% disabled/grayed for "Set budget" adsets
- [ ] Top Performers: Freq column shows values, colored correctly
- [ ] No regressions on Budget button (BudgetButton component untouched)
