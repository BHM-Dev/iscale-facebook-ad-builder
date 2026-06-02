# Copy Library — Performance Data Spec

**Status:** Ready to build  
**Priority:** High — turns the library from a voice archive into a performance-weighted creative vault  
**Trigger files touched:** `facebook_service.py` — requires 2-agent pre-push review

---

## Problem

The Copy Library currently stores Joel's ad copy but has no signal on which copy actually converted. Joel can't make a good pin decision (the primary curation action) without knowing CPL. The AI is learning equally from a $19 CPL ad and a $74 CPL ad. That's wrong.

The `AdCopyLibrary` model already has `spend` and `cpl` columns reserved but never populated.

---

## Goal

During every Sync from Meta, pull lifetime ad-level insights (spend + CPL) and store them. Surface them in the table. Let Joel sort by CPL ascending to find proven creative at a glance.

---

## What "CPL" Means Here

Commercial insurance vertical. The relevant conversion action type from Meta is `lead` (or `onsite_conversion.lead_grouped`). CPL = `cost_per_action_type` where `action_type = "lead"`.

If no lead action exists in the response (e.g. a brand awareness ad), CPL is null. Display as `—`.

---

## Backend Changes

### 1. New method: `get_ad_insights_map()` in `facebook_service.py`

```python
def get_ad_insights_map(self, ad_ids: list[str], ad_account_id=None) -> dict:
    """
    Batch-fetch lifetime spend + CPL for a list of ad IDs.
    Returns: { fb_ad_id: {"spend": float, "cpl": float | None} }
    
    Uses the account-level /insights endpoint with level=ad and an IN filter
    on ad IDs. Handles pagination. Falls back gracefully — missing entries
    in the returned dict mean no insight data available (zero-spend or new ad).
    """
```

**Meta API call:**
- Endpoint: `GET /{ad_account_id}/insights`
- Params:
  ```python
  {
      "level": "ad",
      "fields": "ad_id,spend,cost_per_action_type",
      "date_preset": "maximum",   # lifetime data
      "filtering": json.dumps([{
          "field": "ad.id",
          "operator": "IN",
          "value": ad_ids   # list of string IDs — Meta accepts up to 200 in one call
      }]),
      "limit": 500,
  }
  ```
- Paginate with `load_next_page()` (same pattern as `get_adset_name_map`)
- Parse each row:
  ```python
  spend = float(row.get("spend") or 0)
  cpl = None
  for action in (row.get("cost_per_action_type") or []):
      if action.get("action_type") in ("lead", "onsite_conversion.lead_grouped"):
          cpl = float(action["value"])
          break
  ```
- Return `{}` on any exception (non-fatal, sync continues without performance data)

**Batching:** If `len(ad_ids) > 200`, split into chunks of 200 and make multiple calls. Merge results into one dict.

### 2. Update `sync_copy_library()` in `ad_copy_library.py`

After the main ad upsert loop, call `get_ad_insights_map()` with all `fb_ad_id` values in the current sync batch and write spend/CPL back:

```python
# --- Performance data pass ---
all_ad_ids = [ad["fb_ad_id"] for ad in ads]
insights_map = svc.get_ad_insights_map(all_ad_ids, ad_account_id=ad_account_id)

for fb_ad_id, metrics in insights_map.items():
    row = db.query(AdCopyLibrary).filter(
        AdCopyLibrary.fb_ad_id == fb_ad_id
    ).first()
    if row:
        row.spend = metrics.get("spend")
        row.cpl   = metrics.get("cpl")

db.commit()
```

**Why a second pass:** Keeps the upsert loop clean. Insights may not exist for every ad (new ads, zero-spend) — that's fine, those fields stay null.

**Rate limits:** The `/insights` endpoint is async by default for large requests but synchronous for small ones (< ~500 ads). With 149 ads in Joel's account this will be synchronous and fast. If Meta returns a job ID instead of data, the service should raise a warning and return `{}` rather than polling (out of scope for v1).

---

## Frontend Changes (`CopyLibrary.jsx`)

### New columns

Add **Spend** and **CPL** columns, placed between Status and Headline:

```
NICHE ↕ | STATUS ↕ | SPEND ↕ | CPL ↕ | HEADLINE ↕ | BODY | PINNED | DELETE
```

Both columns use `SortHeader`. Both use `w-px whitespace-nowrap`.

**Formatting:**
- Spend: `$${Number(entry.spend).toLocaleString('en-US', { maximumFractionDigits: 0 })}` → `$1,247`
- CPL: `$${Number(entry.cpl).toFixed(2)}` → `$23.50`
- Null value: `—` (em dash, `text-gray-300`)

**Color coding on CPL (optional but useful):**
- CPL < $30 → `text-green-700 font-medium`
- CPL $30–$60 → `text-gray-700`
- CPL > $60 → `text-red-500`
- Null → `text-gray-300`

These thresholds are rough — adjust based on Joel's actual account benchmarks.

### Default sort change

Change default `sortKey` from `'imported_at'` to `'cpl'` and `sortDir` to `'asc'` once data is populated. For the initial release keep `imported_at` desc until Joel has run one sync (otherwise the table looks broken with all `—` CPL values sorted first).

**Suggested UX:** After a successful sync, if `>= 50%` of entries have a CPL value, auto-switch the sort to `cpl asc` and show a toast: "Sorted by CPL — pin your winners."

### colSpan update

Currently `colSpan={6}` on the empty state row. Bump to `8` after adding Spend + CPL.

---

## Migration

**None needed.** `spend` and `cpl` columns already exist in `ad_copy_library` — added in the original `k9g7h3i4j6f2` migration via:
```sql
spend NUMERIC(10, 2)
cpl   NUMERIC(8, 2)
```

---

## Few-Shot Injection Improvement (Phase 2 — not in this build)

Once CPL data is populated, update `_get_library_examples()` in `copy_generation.py`:

```python
# Current: query by niche, limit 5, pinned first
# Phase 2: add CPL preference
q = q.order_by(
    AdCopyLibrary.is_pinned.desc(),
    AdCopyLibrary.cpl.asc().nulls_last(),   # low CPL first, nulls at end
    AdCopyLibrary.imported_at.desc(),
)
```

This means the AI writes like Joel's cheapest-CPL ads, not just his most recently-imported ones. This is the version that closes the loop between "copy library" and "actual campaign outcomes."

---

## Files to Touch

| File | Change | Trigger? |
|------|--------|----------|
| `backend/app/services/facebook_service.py` | Add `get_ad_insights_map()` | ✅ Yes — 2-agent review required |
| `backend/app/api/v1/ad_copy_library.py` | Call insights map in sync, second write pass | No |
| `frontend/src/pages/CopyLibrary.jsx` | Add Spend + CPL columns, sort update | No |

No new env vars. No migration. No new routes.

---

## Build Checklist (for the build session)

- [ ] Read this spec fully before touching any file
- [ ] Read current `facebook_service.py` `get_adset_name_map()` — use same pagination pattern for `get_ad_insights_map()`
- [ ] Check Joel's actual CPL range in Campaign Performance before hardcoding color thresholds
- [ ] Handle >200 ads in the insights batch (chunk into 200s)
- [ ] Handle Meta returning an async job ID instead of inline data (return `{}`, log warning)
- [ ] Run 2-agent pre-push review (facebook_service.py is a trigger file)
- [ ] After push, run Sync from Meta and verify CPL values appear
- [ ] Consider default sort change once data is confirmed populated
