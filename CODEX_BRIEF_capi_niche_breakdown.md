# Codex Brief — Niche/Account Breakdown on CAPI Performance-by-Pixel

## Why
Joel flagged (Slack, 2026-08-30, group DM w/ Steve+Abel) that the `/performance` pixel-level
CPL/ROAS numbers "seem off" — root cause is real, not a bug: RHO and RHO 4 share one Meta pixel,
so each pixel bucket blends spend/leads/revenue across **both ad accounts and every niche**
running CAPI-tagged ad sets. The blended total is mathematically correct but hides the mix. This
adds a breakdown so the blend is visible instead of hidden.

## Scope
Backend only — no DB migration, no schema change. Pure additive computation on data already
being fetched in `get_pixel_performance()`.

### File: `backend/app/services/capi_quality_service.py`

In `get_pixel_performance()`, the per-adset loop (~line 612, `for fb_adset_id, metrics in
(insights or {}).items():`) already has `aid` (fb_account_id) and `adsets` (which carries
`a.get("name")` for the ad set) in scope. Add a niche sub-bucket:

1. Reuse the existing niche extractor — do NOT reimplement. Import `_extract_niche` from
   `backend/app/api/v1/ad_copy_library.py` (or, if that creates a circular import, move
   `_extract_niche` + `_NON_NICHE_RE` + `_LEADING_EMOJI_RE` into a small shared module, e.g.
   `backend/app/services/niche_extraction.py`, and re-export from `ad_copy_library.py` so nothing
   else breaks).
2. Build an `adset_name` lookup alongside the existing `adset_pixel` dict in the per-account loop:
   `adset_name_map[str(a.get("id"))] = a.get("name")`.
3. Inside each pixel's bucket dict (the `buckets.setdefault(pixel_id, {...})` block), add a nested
   dict keyed by `(fb_account_id, niche)`:
   ```python
   b = buckets.setdefault(pixel_id, {
       "spend": 0.0, "leads": 0, "adset_count": 0,
       "rt_conversions": 0, "rt_revenue": 0.0, "rt_cost": 0.0,
       "breakdown": {},  # NEW: {(account_id, niche): {spend, leads, rt_revenue, rt_cost, rt_conversions, adset_count}}
   })
   niche = _extract_niche(adset_name_map.get(str(fb_adset_id)) or "")
   key = (aid, niche)
   nb = b["breakdown"].setdefault(key, {
       "fb_account_id": aid, "account_name": account_names.get(aid) if 'account_names' in scope else None,
       "niche": niche or "General",
       "spend": 0.0, "leads": 0, "adset_count": 0,
       "rt_conversions": 0, "rt_revenue": 0.0, "rt_cost": 0.0,
   })
   ```
   Accumulate the same fields (`spend`, `leads`, `adset_count`, `rt_conversions`, `rt_revenue`,
   `rt_cost`) into `nb` at the same point they're already accumulated into `b`.
4. In the final `pixels.append({...})` block, serialize the breakdown as a **list**, not a dict
   (dict keys can't be tuples in JSON), each row computing its own `cpl`/`rt_cpl`/`rt_roas` the
   same way the top-level pixel row does:
   ```python
   "breakdown": sorted(
       [
           {
               **{k: v for k, v in nb.items() if k not in ("spend", "rt_revenue", "rt_cost")},
               "spend": round(nb["spend"], 2),
               "cpl": round(nb["spend"] / nb["leads"], 2) if nb["leads"] else None,
               "rt_revenue": round(nb["rt_revenue"], 2),
               "rt_cost": round(nb["rt_cost"], 2),
               "rt_cpl": round(nb["rt_cost"] / nb["rt_conversions"], 2) if nb["rt_conversions"] else None,
               "rt_roas": round(nb["rt_revenue"] / nb["rt_cost"], 4) if nb["rt_cost"] else None,
           }
           for nb in b["breakdown"].values()
       ],
       key=lambda r: r["spend"],
       reverse=True,
   )
   ```
5. **`partial` flag propagation:** if the pixel-level row is `partial` (shared pixel, caller can't
   see all feeding accounts — see existing `restricted_out_accounts` logic), each breakdown row
   for an account the caller CAN see is still a real, complete number for that account+niche slice
   — only the pixel TOTAL is incomplete. Don't mark breakdown rows `partial` individually; the
   existing pixel-level `partial` flag already communicates the caveat.
6. Get `account_names` into scope for this block if it isn't already — it's built earlier in the
   file for the `/latest` sync path (`_account_name_map`); reuse the same helper here rather than
   passing raw account IDs with no label.

### File: `backend/app/api/v1/capi_quality.py`
No change expected — `/performance` already returns whatever `get_pixel_performance()` returns.
Skim the route to confirm it isn't re-serializing/filtering the pixel dict in a way that would
drop the new `breakdown` key.

### Frontend: `frontend/src/components/CapiMatchQualityCard.jsx` (find via Dashboard.jsx import)
Add an expand affordance per pixel row in the "Performance by pixel" table — clicking a row (or a
chevron) reveals the `breakdown` array as a sub-table: Account | Niche | Spend | CPL | RT ROAS,
sorted by spend descending (already sorted server-side). Keep it collapsed by default — this is a
drill-down for exactly the "why does this number look blended" question, not a always-on wall of
rows. Follow existing Tailwind patterns already in that file (don't introduce a new expand/collapse
pattern if one exists elsewhere in the dashboard already — check `Pnl.jsx` first, it's the most
recently built page with similar drill-down tables).

## Explicitly out of scope
- No new DB columns, no migration.
- No change to the `/latest` (EMQ) endpoint — this is `/performance` only.
- Don't touch `CAPI_QUALITY_ACCOUNT_IDS` scoping logic — breakdown only runs within whatever
  accounts are already being queried.

## Verification before handoff to Claude Code for push
- Hit `/api/v1/capi-quality/performance?date_preset=last_30d` locally against the real RHO/RHO4
  pixel and confirm the `breakdown` array sums back to the parent pixel's `spend`/`leads`/
  `rt_revenue`/`rt_cost` (within rounding) — this is the actual correctness check, not just "does
  it 200."
- Confirm niches with no separator (`_extract_niche` returns `None`) collapse into one "General"
  row per account rather than one row per raw ad set name.

## Not a trigger file
`capi_quality_service.py` / `capi_quality.py` are not on the Ad Builder's never-edit-alone list
(that's `BulkAdCreation.jsx`, `AdCreativeStep.jsx`, `facebookApi.js`, `facebook_service.py`) and
this has no migration — normal Codex build. Final push still goes through Claude Code for the
standard pre-push review (small/medium backend change → 1-2 cheap-tier agents, diff inline).
