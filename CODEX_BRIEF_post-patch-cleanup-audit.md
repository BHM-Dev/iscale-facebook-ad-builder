# Codex Brief — Post-Patch Cleanliness Audit

## Context
Heavy iterative patching just happened on `BHM-Dev/iscale-facebook-ad-builder` (`develop` branch,
current head should be `93aaa49` or later — `git pull` first). Multiple fix-on-fix rounds landed in
quick succession: Bulk Match Import build, a wiring fix, several UX fixes, and a wizard
state-persistence fix that itself needed two follow-up corrections after live testing caught bugs
static review missed. This is exactly the kind of sequence that leaves behind: dead code, stale
comments describing bugs that no longer exist, inconsistent patterns (a fix applied to 3 files but
not the 4th that needed it too), leftover debug logging, and duplicated logic.

This is a **read-only audit** — report findings, don't fix anything yet. I'll decide what to act on
after seeing the list.

## Highest-priority files (touched most recently, most likely to have cruft)
- `frontend/src/components/BulkMatchImport.jsx` — built fresh this session, patched 3 times
- `frontend/src/components/AdCreativeStep.jsx` — patched 4 times in one sitting (cache scoping,
  then two corrections to the same effect)
- `frontend/src/components/CampaignStep.jsx` / `AdSetStep.jsx` — mode-restoration + auto-select
  logic added
- `frontend/src/context/CampaignContext.jsx` — `createDefaultCampaignData`/`createDefaultAdsetData`
  factories added, `resetWizard()` exists but is confirmed dead code (zero callers anywhere)
- `frontend/src/pages/FacebookCampaigns.jsx` — split into outer/inner components, batch-mode logic
  moved between steps twice
- `frontend/src/components/Wizard.jsx` — **confirmed entirely dead** (imported in `App.jsx`
  historically but never rendered; the import itself was already removed). Confirm nothing else
  references it, then flag it as a deletion candidate — don't delete it yourself, just confirm and
  report.

## What to check, specifically

1. **Dead code from superseded fixes.** Any remnant of the `prevCampaignCacheIdRef`/`cacheChanged`
   approach in `AdCreativeStep.jsx` that got replaced — check imports, comments, or helper
   functions left behind after logic was swapped out.
2. **Stale comments.** Several fixes have long comments narrating a bug that's now resolved (e.g.
   "confirmed still live via manual repro" language). Once the fix is stable, comments explaining
   *why* the current approach is correct are valuable; comments purely narrating the debugging
   journey are noise — flag (don't remove) any that read as changelog rather than documentation.
3. **Inconsistent pattern application.** The `safeLocalStorageGet`/`safeLocalStorageSet` try/catch
   wrapper was added to `CampaignStep.jsx`, `AdSetStep.jsx`, `AdCreativeStep.jsx` — check whether
   any OTHER file in the app does raw unguarded `localStorage.getItem/setItem` calls that should
   get the same treatment for consistency (e.g. `CampaignContext.jsx`'s own ad-account caching, or
   anywhere in `BulkMatchImport.jsx`).
4. **Duplicated logic.** `createDefaultCampaignData()`/`createDefaultAdsetData()` were extracted in
   `CampaignContext.jsx` — confirm nothing else in the codebase still hand-lists the same default
   field set inline (would drift out of sync over time).
5. **The `creativesScopeId` mechanism** on `creativeData` (added to fix the image cross-campaign
   leak) — confirm it's not colliding with or duplicating any other per-campaign scoping key
   already in use, and that it's actually read/cleared correctly everywhere `creativeData` gets
   reset (search `resetWizard()` and any other full-reset path).
6. **General lint pass**: unused imports, unused variables, `console.log`/`console.error` calls left
   in from debugging that aren't meaningful error handling, any `// TODO` or `// FIXME` introduced
   during this session's work.
7. **Broader codebase health** (not just the touched files) — if you have budget after the above,
   a general pass for: obviously dead exports, duplicated utility functions across components that
   should be shared, and any other Ad Builder trigger file
   (`frontend/src/components/BulkAdCreation.jsx`, `frontend/src/lib/facebookApi.js`,
   `backend/app/services/facebook_service.py`) showing similar patch-fatigue symptoms.

## Do NOT do
- Do not fix anything — this is audit-only. Report findings with file:line.
- Do not touch `.github/workflows/` — those are separate infra, not part of this cleanliness pass.
- Do not attempt to delete `Wizard.jsx` yourself even if confirmed dead — just report it clearly so
  a human decides.

## Output
A prioritized list: what's actually risky/confusing to a future reader vs. cosmetic. Note which
findings are trivial one-line fixes vs. which would need a real pre-push review pass given they'd
touch a trigger file.
