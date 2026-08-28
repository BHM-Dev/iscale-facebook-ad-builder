# Codex Review Request — CAPI Match Quality Monitoring

Third review pass (two Claude Code agents already reviewed + fixes applied — see below).
Read-only audit, please don't fix anything — report findings.

## What this is
Daily snapshot of Meta's Dataset Quality API (Event Match Quality) per pixel, so BHM can
compare CAPI match quality across ad accounts — specifically: is RHO 4's advertiser-run CAPI
matching better than Everflow's CAPI on the other RHO accounts. Pushed to `develop` at `36cfca2`.

Files:
- `backend/app/models.py` — new `CapiQualitySnapshot` model
- `backend/alembic/versions/y3u1v7w8x0t6_add_capi_quality_snapshots.py` — migration
- `backend/app/services/capi_quality_service.py` — Meta API integration + sync logic
- `backend/app/api/v1/capi_quality.py` — 3 endpoints (`/latest`, `/history`, `/sync`)
- `backend/app/main.py` — router registration + daily 14:00 UTC scheduler job

Get the full diff with: `git show 36cfca2`

## Already reviewed and fixed (don't re-report these)
1. **Account scoping** — endpoints now filter by `current_user.allowed_account_ids()` matching
   `facebook.py`/`pnl.py` convention (was missing initially — Abel/Joel would've seen every
   advertiser's data).
2. **Response shape** — first draft assumed Meta returns `{"data": [...]}` with a flat
   `event_match_quality` number. Verified against Meta's live docs: root key is `"web"`,
   `event_match_quality` is `{"composite_score": N, "match_key_feedback": [...]}`. Fixed and
   confirmed against a real API call.
3. **No aggregate row** — Meta returns EMQ per `event_name` with no "all events" row. First
   draft picked `data[0]` arbitrarily. Fixed: now stores one row per (pixel, account, event, day)
   and lets the frontend pick which event to headline.
4. **Session-poisoning failure mode** — a bad row's `db.flush()` could abort the whole sync loop
   silently. Fixed: each row's write is wrapped in its own try/except/rollback.
5. **Stale error state** — a failed re-sync left old metrics + a new `fetch_error` on the same
   row. Fixed: metrics are nulled when `fetch_error` is set.
6. **Pixel discovery** — first draft read `FacebookAdSet.pixel_id` from our local DB cache.
   Live-checked and confirmed that column is empty for every RHO ad set (they were created
   directly in Ads Manager, not through this app's wizard) — the cached-lookup version would
   have tracked zero RHO pixels on day one. Fixed: `get_tracked_pixels()` now reads
   `promoted_object.pixel_id` live from Meta across every visible ad account.
7. **API version bump** — `v24.0` → `v25.0` default to match the docs this was verified against.

## Live-verified before push (not just unit-level)
- Ran the actual `get_tracked_pixels()` against all 12 real ad accounts — found 26 distinct
  (pixel, account) pairs.
- Ran the actual `fetch_dataset_quality()` + `_parse_dataset_quality()` against two real pixels
  (RHO's own pixel and the RHO4/RHO-shared "Commercial Insurance - CAPI" pixel) — confirmed
  real EMQ scores come back correctly parsed (e.g. Lead event: 9.3 vs 9.1).
- Confirmed RHO's own account already has a few ad sets pointed at the exact same pixel RHO 4
  uses — this is real, not a bug — added `pixel_name` to every row specifically so this is
  visible on the Dashboard card instead of two accounts silently showing identical numbers.

## What to focus this pass on
1. **Anything the two prior review passes might have missed** — fresh eyes, don't just
   re-confirm what's already listed above.
2. **`_parse_dataset_quality` defensive parsing** (`capi_quality_service.py`) — `acr` and
   `event_coverage`'s exact field shape isn't 100% first-party-confirmed by Meta's docs (only
   `event_match_quality`'s nested shape was directly verified against a live call). Check
   `_extract_percentage`/`_extract_freshness` handle every plausible shape Meta might actually
   return without crashing, not just the ones anticipated.
3. **The `/latest` endpoint's grouping/join logic** (`capi_quality.py`) — the NULL-safe
   self-join via `COALESCE(..., '__none__')` sentinel, used because Postgres' plain `IS` doesn't
   support column-to-column comparison. Verify this is actually correct SQL and doesn't have an
   edge case with a pixel/account/event that happens to literally be the string `"__none__"`
   (vanishingly unlikely, but worth a sanity check) or any other NULL-handling gap.
4. **`get_tracked_pixels()` cost at scale** — it now calls `svc.get_adsets(ad_account_id=aid)`
   once per ad account (12 accounts currently, up to hundreds of ad sets each, e.g. RHO alone
   has 201). This runs once daily via the scheduler. Flag if this looks likely to hit Meta rate
   limits or become slow enough to matter as the account count grows — not blocking today, but
   worth knowing the ceiling.
5. **Idempotency under concurrent calls** — the daily scheduled job and a manual "Sync now" call
   could theoretically overlap. Check whether the existing-row-lookup-then-write pattern in
   `sync_capi_quality` has a race condition if two syncs run at the same moment (unlikely in
   practice given it's a single-instance backend, but worth confirming there's no TOCTOU gap).
6. **General code quality** — dead code, unused imports, anything inconsistent with this repo's
   own conventions (see `CLAUDE.md` at repo root for patterns: `has_table()` migration guard,
   `ADD COLUMN IF NOT EXISTS` for future columns, account-scoping convention, etc.)

## Known open items (not bugs — already flagged to Steve, no action needed from this review)
- EMQ is a property of the pixel, not the account — if RHO 4 and other RHO accounts ever fully
  converge onto one pixel, this comparison stops being meaningful. Documented in the model
  docstring. Not something to "fix" in code.
- `acr` came back `None` on every event in the live test — may be a conditional field that needs
  different request params, or may just not be populated for these event types. Not blocking;
  EMQ is the primary metric this feature exists to track.

## Do NOT do
- Do not fix anything — audit only, report findings with file:line.
- Do not touch the frontend brief (`CODEX_BRIEF_capi_match_quality_card.md`) — that's a separate,
  not-yet-built task for a different Codex session.
