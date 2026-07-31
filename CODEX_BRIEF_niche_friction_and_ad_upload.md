# Codex Brief: Kill Niche-Selection Friction + "Upload an Ad You Like"

## Context

Joel feedback (2026-07-31) on Image Ad / Video Ad wizards:
1. Selecting a niche is friction, especially for a niche BHM has never run before.
2. He wants to upload an ad he found (not from BHM's Research scraper, not from BHM's own Meta account) and have Ad Builder use it as inspiration/structure for a new ad.

Both are already directionally on the backlog (`CLAUDE.md` "Still pending": *ImageAds Quick Generate* and *Template-first Quick Generate*) — this brief makes them concrete and scoped.

## Item 1: Niche friction

### Root cause (confirmed by reading the code, not guessing)

`frontend/src/pages/ImageAds.jsx` seeds ad-copy angles from a hardcoded `ANGLE_TEMPLATES` object (line 24) with exactly 5 keys: `commercial_insurance`, `auto_insurance`, `home_services`, `personal_loans`, `debt_relief`. The vertical is inferred from the brand via `inferBrandVertical()` (`frontend/src/lib/verticals.js`), which pattern-matches brand/product/profile text against a fixed keyword list per vertical.

When a brand's niche doesn't match any of those 5 (i.e. a genuinely new niche), `inferBrandVertical()` returns `null`, and `usingFallbackAngles` (`ImageAds.jsx:1963`) goes true — Joel gets shown **Commercial Insurance angle copy by default** with a small notice, and has to manually notice it's wrong and hand-write everything instead. It's not a hard block, but it's a bad, easy-to-miss default that reads as "the tool assumes I run Commercial Insurance."

The Video Ad spec (`CODEX_BRIEF_ugc_video_mvp.md`) makes this worse by design: niche is a **required, hardcoded 3-option segmented control** (barber shops / trucking / religious orgs) with no escape hatch at all. A new niche literally has nowhere to go.

### Fix

**ImageAds.jsx / AnglePicker (line ~1847):**
- Add a "Write my own — skip suggested angles" option, shown prominently whenever `usingFallbackAngles` is true (i.e. whenever the vertical can't be confidently inferred) — not just a small notice text, an actual button that clears the angle picker and drops straight into blank headline/body/CTA fields.
- Don't default-populate Commercial Insurance copy silently when the vertical is unknown. Show an explicit "New niche — no seeded angles yet" state instead of quietly falling back to a wrong vertical's copy.

**VideoAds.jsx (once Phase 1 video work starts, see `CODEX_BRIEF_ugc_video_mvp.md` §3):**
- Niche field must NOT be a closed 3-option control. Make it a free-text field with the 3 known niches as quick-select chips (barber shops / trucking / religious orgs) plus a "Custom niche" text input that's always available. The niche-specific prompt tables (`CODEX_BRIEF_ugc_video_mvp.md` §4) become optional enrichment when the niche matches a known key — for a custom niche, fall back to a generic risk-framing prompt template with the niche name interpolated in, rather than blocking generation entirely.
- This only matters once Phase 1 video build starts (still gated behind P&L Phase 2 per `CLAUDE.md`) — implement now in the spec/wireframe understanding, build when Phase 1 actually starts.

**Scope for Codex right now:** the `ImageAds.jsx` / `AnglePicker` fix only. The VideoAds niche-input design is noted here so it's not re-litigated when Phase 1 starts, but there's no VideoAds UI to fix yet since it's still a placeholder shell.

## Item 2: "Upload an ad I found" as inspiration

### What already exists (confirmed by reading the code — don't rebuild this)

- `POST /uploads/` (`backend/app/api/v1/uploads.py:65`) already accepts an arbitrary file upload and returns a URL (R2 if configured, else local `/uploads/`).
- `POST /ad-remix/reconstruct-from-url` (`backend/app/api/v1/ad_remix.py:151`) already takes any `source_image_url` + brand/product/profile IDs and deconstructs-then-reconstructs a new ad concept from it. This is the exact same endpoint the Campaign Performance "Remix" drawer uses today for ads pulled from BHM's own Meta account, and that Research's "Use as Inspiration" uses for scraped competitor ads (via the `pendingResearchInspiration` localStorage handoff into `AdRemix.jsx`, see `AdRemix.jsx:165-180`).

**The gap is a missing front door, not a missing capability.** Neither the Dashboard nor `AdRemix.jsx`/`ImageAds.jsx` currently let Joel drop in an ad image that came from outside BHM's Meta account and outside the Research scraper.

### Fix

Add a new entry point — a "Start from an ad you found" option, most natural next to the existing brand-selection first step of `AdRemix.jsx` (the page already renamed "Build New Ad" in nav, still `/ad-remix` internally):

1. New UI: a dropzone/upload button on the `AdRemix.jsx` landing step (or a small modal launched from the Dashboard's tool cards) — "Upload an ad screenshot or image."
2. On upload: `POST` the file to the existing `/uploads/` endpoint (reuse the exact same fetch pattern already used for logo upload in `ImageAds.jsx` — see the `overlayLogoPreview`/`uploadingLogo` handler around `ImageAds.jsx:240`).
3. Take the returned URL and write it to `localStorage` as `pendingUploadedInspiration` (new key, same pattern as `pendingResearchInspiration`), then navigate to `/ad-remix`.
4. In `AdRemix.jsx`, add a read block alongside the existing `pendingResearchInspiration` read (`AdRemix.jsx:165`) that checks for `pendingUploadedInspiration` and, if present, passes it as `source_image_url` straight into the `reconstruct-from-url` payload — same code path Campaign Performance's Remix already uses, just a different image source.
5. Show a banner similar to the existing research-inspiration banner (`AdRemix.jsx:730`) so Joel can see/clear which uploaded ad is driving the current reconstruction.

**Do not build a new deconstruct/reconstruct pipeline.** This is 100% wiring an existing, already-proven capability (`reconstruct-from-url` already handles arbitrary external image URLs — it doesn't care if the URL came from Meta, Research, or a fresh upload) to a UI surface that doesn't exist yet.

## Not in scope for this brief

- Anything under `VideoAds.jsx` beyond the niche-input note above — video build is still gated behind the Phase 0 quality verdict + P&L Phase 2.
- No migration needed for either fix — no new persisted fields, `pendingUploadedInspiration` is a localStorage key like its siblings.

## Done when

- [ ] `ImageAds.jsx` AnglePicker shows an explicit "new niche, write your own" path instead of silently defaulting to Commercial Insurance copy.
- [ ] Upload-an-ad entry point exists, uploads via `/uploads/`, and successfully drives a `reconstruct-from-url` call exactly like Research inspiration and Meta-ad Remix already do.
- [ ] Pre-push checklist run (frontend-only change, no trigger files touched — should not need the 2-agent review, but confirm no `BulkAdCreation.jsx`/`AdCreativeStep.jsx`/`facebookApi.js`/`facebook_service.py` edits crept in).
