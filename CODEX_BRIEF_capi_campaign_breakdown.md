# Codex Brief — Campaign-Level Breakdown on CAPI Performance-by-Pixel

## Why
Joel's actual ask (Slack thread, 2026-08-31, on the niche/account breakdown we shipped):
> "That data is not needed at this level, it was more about correlating what campaigns are
> running on each setup to see the difference."

He wants to see which real Meta **campaigns** feed each pixel (old vs. new CAPI), not
regex-extracted niches. Niche stays useful (it's what caught the Painting Batch 2 dip on RHO 4)
— this adds campaign as a second, selectable lens on the same drill-down, it doesn't replace it.

## Scope
Backend + frontend, no migration, no schema change. `get_adsets()` (`facebook_service.py:258`)
already injects `adset['campaign'] = {'name': ..., 'objective': ...}` into every ad set it
returns — `get_pixel_performance()` already calls `get_adsets()` for the niche breakdown, so the
campaign name is already in memory. No new Meta API calls.

### File: `backend/app/services/capi_quality_service.py`

In `get_pixel_performance()`, alongside the existing niche `adset_name_map` built in the
per-account loop (~line 599-601), also capture campaign identity per ad set:

```python
adset_campaign_map = {}
for a in adsets:
    ...
    campaign = a.get('campaign') or {}
    if adset_id:
        adset_campaign_map[adset_id] = {
            'campaign_id': a.get('campaign_id'),
            'campaign_name': campaign.get('name') or 'Unnamed Campaign',
        }
```

In the per-adset accumulation loop where the niche `breakdown` dict is built (~line 629 onward),
add a **second, parallel** breakdown dict on the same bucket, keyed by `(aid, campaign_id)` instead
of `(aid, niche)`:

```python
b = buckets.setdefault(pixel_id, {
    ...,
    "breakdown": {},            # existing: by (account, niche)
    "breakdown_by_campaign": {},  # NEW: by (account, campaign_id)
})
...
camp = adset_campaign_map.get(str(fb_adset_id)) or {}
campaign_key = (aid, camp.get('campaign_id') or 'unknown')
cb = b["breakdown_by_campaign"].setdefault(campaign_key, {
    "fb_account_id": aid,
    "account_name": account_names.get(aid),
    "campaign_id": camp.get('campaign_id'),
    "campaign_name": camp.get('campaign_name') or 'Unnamed Campaign',
    "spend": 0.0, "leads": 0, "adset_count": 0,
    "rt_conversions": 0, "rt_revenue": 0.0, "rt_cost": 0.0,
})
```

Accumulate the same fields (`spend`, `leads`, `adset_count`, `rt_conversions`, `rt_revenue`,
`rt_cost`) into `cb` at the exact same point they're already accumulated into `b` and the niche
`nb`. Three accumulator targets per ad set now (`b`, `nb`, `cb`), all identical field names —
straightforward copy-paste of the existing niche accumulation block, not new logic.

In the final `pixels.append({...})` block, serialize `breakdown_by_campaign` as a **list**, sorted
by spend descending, computing `cpl`/`rt_cpl`/`rt_roas` per row — copy the existing
`"breakdown": sorted([...])` block pattern exactly, just reading from `b["breakdown_by_campaign"]`
instead of `b["breakdown"]`, and keep the account/niche fields swapped for account/campaign
fields. Both `breakdown` and `breakdown_by_campaign` ship in the same response — no query param,
no second round trip when the frontend toggles.

### File: `backend/tests/unit/test_capi_quality_service.py`
Extend `test_get_pixel_performance_adds_breakdown_that_sums_to_parent` (or add a sibling test) to
also assert `breakdown_by_campaign` sums back to the parent pixel's totals, same as the existing
niche assertions. Use the existing `FakeFacebookService.get_adsets()` fixture ad sets — they
already have `promoted_object` set; add a `campaign` dict and `campaign_id` to each fixture ad set
so the new field has something real to group on. Also add one ad set with no `campaign` key at
all, asserting it falls back to `campaign_name: 'Unnamed Campaign'` and doesn't crash.

### Frontend: `frontend/src/pages/Dashboard.jsx` (the `CapiMatchQualityCard` breakdown table,
~line 363-392, the `isExpanded && hasBreakdown` block)

Add a small segmented toggle **inside the expanded drill-down**, not anywhere else on the page:

- Two pills, e.g. `Niche` / `Campaign`, styled consistent with the existing date-range pill toggle
  pattern already used for `Last 7 Days` / `Last 30 Days` / `This Month` a few lines above this
  component (same visual language, smaller scale).
- New state: `const [breakdownDimension, setBreakdownDimension] = useState('niche')` — a single
  piece of state shared across all expanded pixel rows is fine (Joel is looking at one pixel's
  drill-down at a time; don't over-engineer per-row dimension state).
- Render source: `p.breakdown` when `breakdownDimension === 'niche'`, `p.breakdown_by_campaign`
  when `'campaign'`. Swap the "Niche" column header for "Campaign" and render
  `row.campaign_name` instead of `row.niche` when in campaign mode — everything else (Account,
  Spend, CPL, RT CPL, RT ROAS columns) stays identical, this is a pure data-source + one-column
  label swap, not a new table.
- Default to `'niche'` — it's the proven-useful lens (caught the Painting Batch 2 issue), campaign
  is the added lens for Joel's specific cross-pixel correlation ask.

## Explicitly out of scope
- No new Meta API calls — campaign name is already fetched.
- No new DB columns, no migration — this is a response-shape change only, nothing persisted.
- Don't touch the `/latest` (EMQ) endpoint, the top-of-page account selector, or the
  `Performance by Niche` dashboard section lower on the page — those are separate, unrelated to
  this pixel-level drill-down.
- Don't make the toggle per-row — one shared toggle for whichever pixel row(s) are expanded is
  simpler and matches how Joel actually uses this (comparing one pixel's mix at a time).

## Verification before handoff to Claude Code for push
- Hit `/api/v1/capi-quality/performance?date_preset=last_7d` locally against the real RHO/RHO4
  pixel and confirm `breakdown_by_campaign` rows sum back to the parent pixel's totals (same check
  as the niche breakdown got before its last push) — this is the actual correctness check, not
  just "does it 200."
- Confirm an ad set with no campaign name resolved falls back to "Unnamed Campaign" and doesn't
  throw.
- Toggle between Niche/Campaign in the browser and confirm the table re-renders without
  re-fetching (both arrays are already in the same API response).

## Not a trigger file
`capi_quality_service.py` / `capi_quality.py` / `Dashboard.jsx` are not on the Ad Builder's
never-edit-alone list, and this has no migration — normal Codex build. Final push still goes
through Claude Code for the standard pre-push review (small/medium change → 1-2 cheap-tier agents,
diff inline).
