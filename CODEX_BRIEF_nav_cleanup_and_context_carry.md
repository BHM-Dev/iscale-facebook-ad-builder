# Codex Brief — Nav Cleanup + Winning Ads Copy Context Carry

Two independent, low-risk frontend fixes. No backend/migration/trigger-file changes in either.

---

## Part 1 — Nav restructure (`frontend/src/components/Layout.jsx`)

**Problem:** the sidebar mixes two patterns inconsistently. Most sections (Research, Build
Creatives, Brands, Facebook) are collapsible groups. But `Ad Library`, `Creative Library`, and
`Copy Library` sit as three flat top-level items between `Brands` and `Facebook`, with names that
don't make their distinct purposes obvious:
- **Ad Library** (`/generated-ads`) — finished, AI-generated ads with performance data (revenue/
  profit per bundle), brand/niche/angle filters, push-to-campaign. The output of the generation
  tools.
- **Creative Library** (`/creative-library`) — raw, unprocessed creative synced from Google Drive.
  No copy, no performance data. Input material, not finished ads.
- **Copy Library** (`/copy-library`) — saved copy snippets.

**Fix:**
1. Collapse these three into one new collapsible group, same pattern as the existing groups
   (`{ icon: ..., label: 'Libraries', children: [...] }` — follow the exact shape already used for
   `Research`/`Build Creatives`/`Brands`/`Facebook` in the `navItems` array around line 50-93 of
   `Layout.jsx`).
2. Rename **"Creative Library"** → **"Drive Imports"** in its nav label only. Do NOT rename the
   route (`/creative-library` stays as-is — don't touch the URL, just the sidebar label and the page
   `<h1>`/heading text on `pages/CreativeLibrary.jsx` if it says "Creative Library" there too, so
   the label is consistent between nav and page).
3. Order within the new "Libraries" group: Ad Library, Drive Imports, Copy Library (in that order —
   matches the natural flow: raw material → finished ad → copy).
4. Don't change `Ad Library`'s or `Copy Library`'s labels or routes — only regroup them and add the
   new parent.

Resulting top-level nav: `Dashboard → Profit/Loss → Research → Build Creatives → Brands →
Libraries (Ad Library / Drive Imports / Copy Library) → Facebook`.

**Verify:** all three routes still resolve correctly from inside the new group, active-state
highlighting still works when on any of the three pages, and the group expands/collapses like the
other four groups (check `expandedMenus` state handling — should need zero changes there, it's
already generic per-label).

---

## Part 2 — Winning Ads copy context carry (`frontend/src/pages/WinningAds.jsx` → `frontend/src/pages/AdRemix.jsx`)

**Problem:** `WinningAd` records (`backend/app/schemas/template.py`) already have
`copy_analysis` (AI analysis of what makes the ad's copy work) and `copy_patterns` (structured
JSON of extracted copy patterns) computed and stored at upload time. But
`WinningAds.jsx`'s "Build Ad from This" button (around line 165) only writes
`id, name, image_url, recreation_prompt` into `pendingWinningAdTemplate` in localStorage —
`copy_analysis` and `copy_patterns` are silently dropped, even though they exist specifically to
inform new copy. This is inconsistent with every other similar hand-off in the app — check
`Research.jsx`'s `handleUseAsInspiration` (~line 695) and `CampaignPerformance.jsx`'s
`handleQuickVariations` (~line 397) for the pattern this should match: they carry real copy/
analysis fields forward, not just the image.

**Fix:**
1. In `WinningAds.jsx`, add `copy_analysis: selectedTemplate.copy_analysis || null` and
   `copy_patterns: selectedTemplate.copy_patterns || null` to the object written into
   `pendingWinningAdTemplate`.
2. In `AdRemix.jsx`'s consumption effect (~line 138-158, the `pendingWinningAdTemplate` handler),
   read those two new fields off `tmpl` and store them in `wizardData` (or wherever the component
   already holds prefill context for this flow — follow the existing `wizardData.template` shape,
   just add the two fields alongside `id`/`name`/`image_url`).
3. Find wherever `AdRemix.jsx` actually calls copy generation (search for the generate-copy /
   generate-image request — currently just sends `recreation_prompt` for the visual side) and pass
   `copy_analysis`/`copy_patterns` through as additional context in that request payload, IF the
   backend endpoint already accepts extra freeform context fields. If it doesn't, don't invent a
   new backend field yourself — that's outside this brief's scope (frontend-only) — instead surface
   `copy_analysis`/`copy_patterns` as read-only reference text somewhere visible in the AdRemix UI
   (e.g. an expandable "Reference copy notes" panel) so the media buyer sees them even if the
   backend doesn't consume them programmatically yet.
4. Do not touch `recreation_prompt` handling — that part already works, this is additive.

**Verify:** upload a Winning Ad with non-empty `copy_analysis`/`copy_patterns` (or find an existing
one in the live data), click "Build Ad from This," confirm those fields survive into AdRemix
(console-log or visible-panel check — whichever the implementation lands on).

---

## Out of scope for this brief (flagged separately, not yours to fix here)
- The video-upload double-hop (browser → R2 → server re-downloads from R2 → re-uploads to Meta)
  touches `backend/app/services/facebook_service.py`, a locked trigger file — Claude Code handles
  that as a separate pass.

## Hand off
Commit locally, don't push. Note what changed in each file for the Claude Code review pass.
