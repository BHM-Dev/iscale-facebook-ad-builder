# Codex Brief — Drive Picker Fixes (Round 2, Urgent)

Review of `16980f2` found real bugs, ranked by severity. This is going in front of Joel/Abel
again very soon — fix P0 and P1 before anything else ships. P2 is quick, fix if time allows.
P3 is a scope question for Steve, not yours to guess at — see the note at the bottom.

## P0 — breaks the entire point of the feature, fix first

### P0.1 — localStorage cache silently blocks manifest copy from ever applying
`AdCreativeStep.jsx` reloads `headlines`/`bodies`/`description`/`websiteUrl`/`cta` from
localStorage on mount, keyed by `defaultX_{adAccountId}_{campaignCacheId}` — and
`campaignCacheId` falls back to the literal string `'new'` for any not-yet-created campaign.
Joel/Abel build new campaigns on the same ad accounts constantly, so that cache is almost
always already populated with copy from whatever they built last.

`addDriveSelectionToCreatives`'s "don't clobber what's already typed" guards
(`prev.headlines?.[0] ? prev.headlines : ...`) treat that stale cached text as "the buyer
already typed something" and silently keep it — discarding the manifest copy the buyer just
picked, with **zero indication anything was dropped.** The "Copy matched" badge shows in the
picker, the buyer trusts it, and the campaign launches with leftover copy from last week's
niche. This is worse than the original "0 ads will be created" bug because it fails
silently with a plausible-looking result.

**Fix:** the guard needs to distinguish "buyer manually typed/edited this in the current
session" from "this came from the stale mount-time cache load." Options, your call on
implementation:
- Track whether the current `headlines`/`bodies`/etc. value came from the cache-load effect
  vs. real user input (e.g. a `copyFieldsTouched` flag set on any manual edit, checked before
  deciding whether Drive copy is allowed to overwrite), or
- Simpler: when Drive-sourced copy exists for the just-added creative(s), always apply it and
  show a clear toast (e.g. "Applied copy from Drive — this replaced your previous
  headline/body/description") so the buyer sees the overwrite happen rather than it silently
  not happening.
Either is acceptable — silent-drop is not.

### P0.2 — `_extract_copy_field` pollutes the last copy field with trailing visual-scene text
Confirmed live: a real copy file has `DESCRIPTION` followed by `1X1 VISUAL SCENE` and
`9X16 VISUAL SCENE` sections, neither of which is in `_extract_copy_field`'s stop-list
(`PRIMARY TEXT|HEADLINE|DESCRIPTION` or end-of-block). The lazy match runs all the way to
`\Z`, so `description` ends up containing the actual description text *plus* both full
visual-scene paragraphs appended — that garbage becomes the ad's description prefill.
**Fix:** add `1X1 VISUAL SCENE`/`9X16 VISUAL SCENE` to the stop-list regex, or (more robust)
stop at *any* all-caps line matching `^[A-Z0-9 ]{3,40}$` rather than an enumerated list, so
future copy-doc sections don't reproduce this bug.

## P1 — real silent-wrong-data risks, fix before shipping

### P1.1 — Copy ID regex can false-match on plausible domain tokens
`r"(?:Copy ID\s*:\s*)?([A-Z]{2,5}\s*F\d{2})\b"` matches anywhere a line *starts* with a
2-5-letter code + "F" + 2 digits, with no end anchor. In an insurance-vertical manifest, a
line like `"CA F01 filing note..."` or `"TX F01 renewal notice"` is a realistic thing to
appear and would silently start a bogus Copy ID entry, corrupting whichever real entry comes
next. **Fix:** anchor the header match to the full line (require the line to *equal* the
Copy ID token, optionally with trailing whitespace/colon) rather than just its start.

### P1.2 — `_refresh_folder_copy_metadata`'s UPDATE can hit the wrong asset
The SQL scopes by `brand_id + folder_path (relative string) + LOWER(file_name)`, no
`drive_file_id` check at all. Two different physical Drive folders for the same brand that
happen to produce the same relative path (e.g. both organized as `"Final/Batch 1"`, or both
landing at brand root with `folder_path == ""`) plus a generic shared filename like
`hero_1x1.jpg` will cause this UPDATE to silently overwrite `soft_tags` on the wrong asset.
**Fix:** scope the UPDATE by `drive_file_id` (there's already a `SELECT id FROM drive_assets
WHERE drive_file_id = ...` pattern used elsewhere in this file — reuse it) instead of
name-based matching.

### P1.3 — Filename-fallback pairing can merge two unrelated assets
When there's no manifest `copy_id`, the grouping key falls back to
`file:${brand_id}:${folder_path}:${normalizedBase}`. `folder_path` is often coarse (root-
level drops, or a shared generic subfolder like `"Final"`), and two *completely unrelated*
manifest drops both containing e.g. `hero_1x1.jpg` / `hero_9x16.jpg` will get merged into one
false "Feed + Stories pair" and bulk-added together — silently pairing the wrong story crop
to the wrong feed image. This is exactly the failure mode the manifest/copy_id path exists to
prevent, reintroduced by the fallback. **Fix:** when there's no manifest-derived `copy_id`,
either don't auto-pair at all (show both as singles, let the buyer manually confirm/pair), or
require additional corroboration before pairing (e.g. `modifiedTime` within a few minutes of
each other) — don't pair on filename alone with no manifest backing it.

### P1.4 — Unguarded Drive API call breaks the "never block" design goal
`_folder_copy_metadata`'s `drive.files().list(...).execute()` call (used to find manifest/
copy files in a folder) has no try/except, unlike the manifest/copy-file *read* calls right
after it which are properly guarded. It's called from `_process_file` *after* the media file
has already been downloaded and uploaded to R2 but *before* the DB insert — so a transient
Drive API hiccup (rate limit, brief permission blip) while just listing a sibling folder
aborts the whole file's sync: orphaned R2 object, and the media silently never appears in the
picker, for what was supposed to be best-effort metadata. **Fix:** wrap that call the same
way the reads after it already are.

## P2 — quick, fix if time allows

- **"Copy matched" badge is a false positive when parsing found no real text.** Backend sets
  `copy: copy_blocks.get(copy_id, {})` — an empty dict is still truthy, so the badge shows
  even when nothing actually parsed. Gate the badge (and the "copy matched" concept generally)
  on at least one of `headline`/`primary_text`/`description` being a non-empty string, not
  just the dict's presence.
- **CTA fallback treats `LEARN_MORE` as "unset."** `prev.cta && prev.cta !== 'LEARN_MORE' ?
  prev.cta : ...` silently overwrites a buyer's deliberate `LEARN_MORE` choice with the
  manifest's CTA. Track whether CTA was actually touched this session instead of using
  `LEARN_MORE` as a sentinel for "empty."
- **Only the first selected group's copy applies when multi-selecting across niches.** If a
  buyer selects assets from two different manifest-backed folders in one picker session, one
  set of copy silently wins with no indication which. At minimum, show a toast naming which
  source's copy was applied when more than one selected group has copy.

## P3 — scope question for Steve, don't build without confirming

`drivePairId` is written onto the creative object but never read anywhere downstream —
confirmed nothing in `BulkAdCreation.jsx` or elsewhere consumes it. Once a "Feed + Stories
pair" is added to the campaign, the two resulting creatives are functionally identical to
manually clicking "Dupe as Stories" today: two independent ad creatives in two ad sets, not
one linked ad object. The picker UI visually groups them (nice, saves a few clicks), but
doesn't actually change what happens downstream.

**Don't build real ad-level linkage without Steve confirming that's wanted** — it's a bigger
lift (would mean changing how `BulkAdCreation.jsx` treats a pair, possibly Meta-API-adjacent).
For now, ship the P0/P1/P2 fixes with the pairing exactly as-is (a convenience grouping in the
picker), and Steve will handle telling Joel/Abel it's still two ads to manage individually
downstream — that's a communication fix, not a code fix, for this round.

## Hand off
Commit locally, don't push. Given the severity of P0.1 especially, call out specifically in
your hand-off note how you implemented the touched-vs-cached distinction, since that's the
one most likely to need a careful look in review.
