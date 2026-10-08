# Codex brief — Research: fixes + close the loop (state as of `5d2d14e`)

`git pull origin develop` first. Source: `docs/features/research.md` (read its **Audit findings — OPEN** and **Product perspective**). Backend safety batch already shipped (caps, locks, delete gates, working rate limiter) — don't redo it. Commit locally; hand back to Claude Code for 2-agent review + push. **Do not** create Meta ads, run live searches/captures, or click "Run"/"Launch" anywhere; dev session only. Don't hammer one ad account (Meta rate limits).

Hand back to Claude Code (don't do alone): anything in `backend/app/services/facebook_service.py`, `backend/alembic/versions/`, `backend/app/models.py`, `BulkAdCreation.jsx`, `AdCreativeStep.jsx`, `frontend/src/lib/facebookApi.js`.

## Part A — small fixes (do all; mostly frontend, one tiny backend)

1. **Handoff payload** — `Research.jsx` `handleUseAsInspiration` (~2223) writes the whole ad object to `localStorage.pendingResearchInspiration`:
   - Whitelist the fields AdRemix actually reads (`SourceAdReferenceCard`, reconstruct payload, `cta_type`/`creative_tags`/`taxonomy_source`/`creativeIntel`/headline/body/media URL/advertiser/ids). Drop video URL lists and long free text (`analystTakeaway`, `watchlistBrief`) unless AdRemix uses them; if it does, truncate (e.g. 2,000 chars).
   - Wrap the `setItem` in try/catch → `showError('Could not hand this ad to Build New Ad (browser storage full). Clear site data and retry.')` and do NOT navigate on failure.
   - Add `savedAt: Date.now()`; in `AdRemix.jsx` (~313-317, the consume-on-mount code) ignore + delete payloads older than 30 min and show an info toast.
2. **Brand switch keeps competitor context** — `AdRemix.jsx` (~149 `researchInspiration` state, ~199 draft persistence, ~412 offer auto-fill from the competitor angle). Store `brand_id` alongside `researchInspiration` in the draft; when `wizardData.brand` changes to a different brand than the one the research was started under, clear `researchInspiration` AND any offer/angle fields that were auto-filled from it, and show an info toast ("Research reference cleared — you changed brand."). Don't clear on first brand selection when none was set before.
3. **422 toasts** — Research.jsx handlers do `new Error(err.detail || ...)` (e.g. ~1641, 2049, 2176). A FastAPI 422 has `detail` as an array → `[object Object]`. Reuse the pattern in `frontend/src/lib/autoPauseRules.js` `parseApiError` (move to a shared `lib/apiErrors.js`, keep the existing export working + its tests) and use it in every Research fetch error path. Also surface the new 429 ("Rate limit: N Meta call(s) left…") and 409 ("already running") messages verbatim — they are written for users.
4. **Honest labels** (copy only):
   - "N new this week" → "N newly cataloged (7d)" (`Research.jsx` ~2605); it's `first_seen`, not advertiser launch date.
   - Rename the green "SOURCE REVIEWED" pill to "Imported" (keep the tooltip); stop using "reviewed" for three things — card-menu "Add to Research Brief" stays, watchlist "Mark reviewed" stays, but the import pill must not say reviewed.
   - Show the **capture date on each card** ("Captured Oct 3"), not only in a tooltip. Don't call an old capture "recent" anywhere; if a count says recent, say "captured in last 30 days".
   - Guessed tags: `taxonomy_source === 'rules_v1'` chips get an "(auto)" suffix or a dashed border + tooltip "Guessed from keywords in the ad copy", so they don't read like analyst-verified tags.
5. **Filter/count consistency** — `filterResearchAds` ~273: drop the `!ad.first_seen ||` fallback in `newOnly` (server excludes null `first_seen`; browse and search mode must agree). When the browse result hits the server cap (500) show "Showing first 500 — narrow the filters". Apply the review filter client-side AFTER the server's `ads_per_advertiser` is documented in a tooltip ("1 per advertiser is applied before review filters").
6. **Saved ads load failure** — `loadSavedAds` (~1822) swallows errors, so the saved library looks empty and stars show unsaved. Keep previous data on failure, add `savedError` + a banner with Retry. In `handleSave`/`handleUnsave` (~2119/2144): per-ad pending `Set` to block double clicks; roll back from a snapshot (not by removing the ad unconditionally); make unsave roll back on failure.
7. **Block advertiser** (`handleBlockPage` ~2267) is team-wide: confirm dialog ("Hide <name> for everyone on the team?") and fix the toast. No new backend.
8. **Unknown sentinels at write time (backend, small, not a trigger file):** in `research.py` normalise unclassified `cta_type` / `page_type` to NULL on write (taxonomy inference returns `"unknown"` for unrecognised text — change `_infer_creative_taxonomy` callers/ import paths so only NULL is stored). Keep read-side tolerance for existing `'unknown'` rows (already handled in the filter). Add a unit test in `backend/tests/`.
9. **SSRF allow-list (backend, small):** `backend/app/api/v1/ad_remix.py` ~463 `deconstruct_template` does `requests.get(source_image_url)` on a client-supplied URL. Allow only `https` and hosts ending in `fbcdn.net`, `facebook.com`, `fbsbx.com`, plus our R2 public host (see `core/config.py`); block private/loopback/link-local IPs after DNS resolution; 10 s timeout, 10 MB cap. On failure keep the generic-blueprint fallback but return `blueprint_fallback: true` + reason, and show it in AdRemix ("Couldn't read the source image — used a generic structure"). Also change the AdRemix line "the source image is never used in the generated ad" to "The source image is analyzed for structure; it is never placed in the generated ad." Add tests for allowed/blocked URLs.

## Part B — close the loop (product; the highest-value work)

Context: the Test Backlog row (`GET /research/test-backlog`) already links a competitor source → hypothesis → our `generated_ad` (with `fb_ad_id`, `revenue`, `profit`, `last_synced_at`). It does **not** show what Joel decides on: spend, leads, CPL, ROAS, or a verdict. Nothing aggregates results across tests.

**B1 — Outcome on the test row (small).**
- First check whether `generated_ads` already stores spend/leads/CPL from a sync (`models.py` GeneratedAd + the P&L / `/generated-ads` sync code). If yes: return them in `bhm_ad`. If no: **don't add per-row Meta calls** (rate limits). Add one backend endpoint that, for the current user's linked tests, makes ONE account-level read per ad account (reuse `GET /auto-pause/ads-bulk` semantics: `include_status`, 60 s cache, 500-row pages) and maps by `fb_ad_id`. Meta-touching service code → hand that part to Claude Code; you may write the route + tests against a mocked service.
- UI: on the test row show Spend · Leads · CPL · ROAS (same colour rules Campaign Performance uses) next to the existing revenue/profit chip, with "as of <time>" and a clear "not synced yet" state — never show 0 for unknown.
- **Result-ready prompt:** a test is "result ready" when spend ≥ $50 (constant at the top of the file, easy to change) or ≥ 5 days since launch. Show an amber "Result ready — read it" chip and sort those first. Win/lose chip: CPL ≤ the account's target is a Steve decision — **do not hard-code a target**; show raw CPL vs the account average CPL from the same bulk read, and label it "vs account avg", not "win".
- Replace the free-text-only outcome with: Verdict (Win / Lose / Inconclusive — manual, required before archiving) + the existing "BHM learning" note.

**B2 — Learnings by attribute (medium; after B1).**
- New collapsed section "What's working for us" (default closed): a table across the user's completed tests grouped by **hook type / promise / angle / persona** (tags already stored on the source ad: `creative_tags`, `hook_type`, `promise`, `persona` — check `scraped_ads` columns and `creative_intel`): tests count, total spend, total leads, blended CPL, total profit. Min 2 tests per row before showing a rate, otherwise "n=1 — too early". Sort by profit.
- Backend: one read-only aggregation endpoint (`GET /research/learnings`) built from the B1 data; no new tables, no migration. Unit-test the grouping with fixtures.
- Don't feed it into copy generation yet — that is a Claude Code follow-up (Copy Library CPL-weighted few-shot is the template).

**B3 — One-click "Build test" (small/medium).** Watchlist "Build from this creative" and "Draft test brief" are two paths from the same card. Replace with one primary "Build test" button on every card and watchlist item that creates the test-backlog row (if none exists) and opens Build New Ad prefilled via the (now whitelisted) handoff. Keep the existing idempotency (`launch_claim_id`, one-link-per-test) — do not change the claim logic. Keep "Draft test brief" only inside the card overflow menu.

## Part C — declutter (only after A and B1 are done; ask Steve before deleting anything)
Do NOT delete features. Do: default the page to the Feed (new creatives from watched advertisers, newest first) with one "Build test" action; collapse Advertiser Directory / Compare / Boards / Ask Research / Targeted Refresh / Capture Receipts behind a "More" menu; show Targeted Refresh + receipts as one line "Last captured N days ago · Refresh". Merge visually Next Actions + Watchlist + Test Backlog into one "My queue" list (same data, one list). Report what you collapsed so Steve can approve removals.

## Do NOT build
More taxonomy filters, evidence-coverage scores / "N/4 evidence", review-value ranking, more provenance/receipt UI, smarter Ask Research, more compare/boards features, new Research test suites for panels slated to be collapsed, vendor-signal ingestion beyond what exists.

## Verify
`cd frontend && npm run test:unit && npm run build && npx eslint <touched files>` (Research.jsx already has 10 pre-existing lint errors — don't add more, don't mass-fix). `cd backend && DATABASE_URL=postgresql://u:p@localhost:5432/x SECRET_KEY=test python3 -m pytest tests/test_research_safety.py <your new tests> -q`. Browser-check on dev only: open the cards/menus/modals, never trigger a capture or launch.
Update `docs/features/research.md` Changelog/Open items for what you ship (docs/ edits: leave uncommitted for Claude Code).
End with: "Edits done — ready for Claude Code 2-agent review + push."
