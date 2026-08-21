# Review Request — Real Feed+Stories Dual-Placement (Abel's #2)

I (Claude Code) implemented this directly since it touches two locked trigger files
(`AdCreativeStep.jsx`, `BulkAdCreation.jsx`). Not pushed — want your review first.

## Context
Abel's actual complaint: the Drive picker's "Feed + Stories pair" was cosmetic — selecting a
pair created 2 separate ads in 2 separate ad sets, each spending independently, confirmed by
his own screenshots. He wants Meta's real Placement Asset Customization: one ad, Meta shows
the right image per placement.

## Why this was smaller than it looks
`facebook_service.py::create_creative` **already has a complete, working, Meta-doc-confirmed
dual-placement implementation** (`secondary_image_hash` → `asset_feed_spec` +
`asset_customization_rules`, feed_image/story_image labels, feed/story position specs) — it
shipped for the Bulk Match Import flow (`BulkMatchImport.jsx`). `createCompleteAd` in
`facebookApi.js` already uploads `creativeData.secondaryImageUrl` and threads
`secondary_image_hash` through end-to-end. None of that needed touching.

The gap was purely that the standard campaign-builder flow (`AdCreativeStep.jsx` →
`BulkAdCreation.jsx`, which is what the Drive picker feeds) never set `secondaryImageUrl` on
anything — it only ever produced two independent creative objects with `format: 'feed'` /
`format: 'stories'`, which `BulkAdCreation.jsx`'s existing multi-adset-split logic
(`isMixedFormat`/`feedAds`/`storiesAds`) correctly turned into 2 ads/2 ad sets, exactly as
designed for *unrelated* feed and stories creatives — just wrong for a *linked* pair.

## What changed
**`AdCreativeStep.jsx`** — `addDriveSelectionToCreatives`: when a Drive group `isPair` AND
both sides are images (never video — `create_creative`'s dual-placement path is image-only per
its own docstring), it now produces **one** creative object with `imageUrl` (feed) +
`secondaryImageUrl` (stories) + `dualPlacement: true` + `format: 'feed'`, instead of two
separate creative objects. Falls back to today's two-creative behavior for anything that isn't
a real image/image pair.

Also updated the review-grid card for `dualPlacement` creatives: no placement-toggle pill (there's
nothing to toggle — it's already both), no "Dupe as Stories/Feed" button (doesn't apply to an
already-dual creative), a purple "Feed + Stories linked" badge instead.

**`BulkAdCreation.jsx`** — one line: `adSpecificCreativeData.secondaryImageUrl` now reads
`specificCreative?.secondaryImageUrl` (never set for video), so it reaches `createCompleteAd`
exactly the way Bulk Match Import already does.

**Nothing else changed.** No backend touched, no schema, no migration, no new Meta API surface
— this reuses the existing reviewed path through one more entry point.

## What to check
1. Trace `format: 'feed'` on the merged creative through `BulkAdCreation.jsx`'s
   `feedAds`/`storiesAds` split (lines ~54-57, ~88-91) — confirm a dual-placement creative
   correctly lands in the single feed ad set and never triggers the mixed-format/second-ad-set
   path, for both the live preview banner and the actual submit-time adset routing.
2. Confirm the ad-count preview (`BulkAdCreation.jsx:405`, driven by `adsData.length` from the
   permutation generator) now shows the right reduced count for a pair (1 permutation, not 2)
   given headlines × bodies multiplication still applies correctly.
3. Sanity-check the video guard on both sides (`group.feedAsset?.format !== 'video'` /
   `group.storiesAsset?.format !== 'video'` in `AdCreativeStep.jsx`, and
   `!isVideo ? specificCreative?.secondaryImageUrl : undefined` in `BulkAdCreation.jsx`) —
   confirm no path lets a video ever reach `secondary_image_hash`.
4. Anything in `removeCreative`/`duplicateCreative` that could still be invoked on a
   `dualPlacement` creative through a path other than the now-hidden button (keyboard nav,
   some other button reusing the same handler).

Diff at `/tmp/dual_placement_wiring.diff` (also just `git diff` on the two files — nothing else
in the working tree is part of this change). `npm run build` already passes.

---

## Round 2 — fixed both findings from your review

**P1 (placement targeting):** added `dualPlacementTargeting` (identical shape to
`BulkMatchImport.jsx`'s), applied when a **new** single ad set's feed bucket is entirely
dual-placement creatives (`feedAdsToCreate.every(ad => ad.dualPlacement)`). Deliberately does
NOT widen targeting when the bucket mixes plain feed creatives with dual-placement ones —
opening a plain single-image creative's ad set to Stories would let Meta serve its square
image into Stories, reintroducing the exact bug `feedTargeting` exists to prevent for it. That
mixed case falls through to today's default, unchanged. For an **existing** ad set (can't
retroactively patch its targeting from this flow), added a `showWarning` toast instead of
silently assuming compatibility.

**P2 (local save):** `secondaryImageUrl` now included in the `/facebook/ads/save` body,
matching `BulkMatchImport.jsx`'s exact field name.

Updated diff at `/tmp/dual_placement_wiring_v2.diff` (216 lines now, same two files).
`npm run build` still passes.

**Please re-check specifically:**
1. `feedAdsToCreate` is referenced inside the new `hasDualPlacementAds` computation before its
   own definition point in the diff view (git diff context can be misleading about ordering) —
   confirm in the actual file that `feedAdsToCreate`/`storiesAdsToCreate`/`isMixed`/`isAllStories`
   (defined ~line 88-91) are lexically before `dualPlacementTargeting`/`hasDualPlacementAds`
   (~line 160-188), both within the same `handleSubmit` function scope.
2. The new `else if (hasDualPlacementAds)` warning-toast branch for existing ad sets — confirm
   it can never ALSO fire for the pure-new-ad-set path (i.e., confirm the `if
   (!adsetData.isExisting)` / `else if (isMixed)` / `else if (hasDualPlacementAds)` chain is
   mutually exclusive and doesn't double-fire or fall through unexpectedly).
3. Whether the "mixed bucket, don't guess" limitation (a batch combining plain feed + dual-
   placement creatives in one launch gets no placement fix) is likely to actually happen given
   how Abel/Joel build campaigns today — if it's a real near-term case, worth flagging as a
   known follow-up rather than something to silently accept.
