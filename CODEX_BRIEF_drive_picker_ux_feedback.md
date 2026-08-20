# Codex Brief — Drive Creative Picker UX Fixes (Joel/Abel Feedback, Friday Deadline)

Real feedback from Abel and Joel testing the Drive Creative Library picker in
`AdCreativeStep.jsx` (Slack, `C0BG015BAJU`, 2026-08-20). Four items, prioritized. Launch
target is tomorrow — ship #1 and #2 no matter what; #3 and #4 are high-value but scope
them exactly as described below so they don't become open-ended.

## 1. No search/filter in the picker modal (ship this — trivial, high value)
The standalone Drive Imports page (`pages/CreativeLibrary.jsx`) already has a search box +
brand filter + format filter. The **picker modal** inside `AdCreativeStep.jsx`
(`openDriveLibraryModal`/`fetchDriveAssets`/the modal JSX) has none of that — Abel's exact
complaint: "we currently have to scroll down to find Horses and Stable etc." Port the same
pattern into the modal: a search input (filter client-side on `file_name` + `folder_path` +
`brand_name`, same logic as `CreativeLibrary.jsx`'s `filteredAssets` useMemo) and, if there's
room, the same format filter chips. Don't add a brand filter to the modal — dedupe hasn't
been needed there since campaigns are usually single-brand already.

## 2. Pair matching 1x1 / 9x16 assets as one ad, two placements
Abel: "How do we connect the 9:16 to the 1x1?" Right now picking both versions of the same
creative concept from Drive just adds two unrelated image cards, each independently
defaulting to Feed (1:1) — there's no way to tell the tool "these two are the same ad, one
placement each" short of manually flipping the placement pill and deleting the duplicate
Facebook creates per image.

**Build a filename-based pairing heuristic** — this is the one that covers the whole Drive
library, not just packages with a manifest (see #3 for the richer, opportunistic version):
- Two Drive assets pair when their filenames are identical except for a `1x1`/`9x16` token
  (case-insensitive, allow `_1x1`/`-1x1`/`1x1` and `_9x16`/`-9x16`/`9x16` as separators —
  confirmed live naming examples: `HST_F05_working_stable_routine_1x1.png` /
  `HST_F05_working_stable_routine_9x16.png`, and `07-GCI-CF6-Broad-Callout-1x1.jpg`).
- In the picker modal, when both halves of a pair are visible, show them as one card (or
  visually grouped) with a "Feed + Stories pair" badge instead of two separate cards.
- Selecting a pair adds them to `creativeData.creatives` as one linked unit that already
  carries the correct `format: 'feed'` / `format: 'stories'` tags per existing convention
  (check `AdCreativeStep.jsx`'s placement-tag pill logic — reuse that, don't invent a new
  placement concept), so Abel never has to manually flip the pill or hit "Dupe as Stories" for
  Drive-sourced pairs — that manual flow stays exactly as-is for single/unpaired assets.
- An asset with no match on the other side (e.g. only a 1x1 exists) behaves exactly like
  today — no regression for unpaired creative.

## 3. Auto-pull copy from Drive (best-effort — do NOT block on this being complete)
Abel: "How do we sync the correct ad copy from the drive to the ad on this step? Right now
it looks like we have to manually enter the copy either typing or copy and paste."

**Confirmed live 2026-08-20** that at least some of Joel's packages include a structured
handoff format — verify against the real files before building, but here's what one real
package looks like:
- A `*_HANDOFF_MANIFEST.txt` file per package, containing an "ASSET MAP" section that maps
  a `Copy ID` (e.g. `HST F01`) to a `1x1:` filename, a `9x16:` filename, and a `Copy file:`
  reference, plus a top-level `Landing page:` URL and a `Meta button:` CTA label.
- A separate `*_Ad_Copy_FINAL.txt` (name varies) containing one section per Copy ID,
  separated by `====` lines, each with labeled `PRIMARY TEXT` / `HEADLINE` / `DESCRIPTION`
  blocks in plain text.

**This convention will NOT be present in every folder** — older/informal packages (e.g. the
`Winner Variations - X` folders under `Trucking`, `Auto Body`, etc.) likely have no manifest
at all. Build this as opportunistic enrichment, not a required data source:
- During Drive sync, when a `*_HANDOFF_MANIFEST.txt`-ish file exists alongside a copy `.txt`
  file in the same folder, parse both and build a Copy-ID → `{headline, primary_text,
  description, cta, landing_page}` map for that folder.
- Match each image/video `DriveAsset` in that folder to a Copy ID via the manifest's
  `1x1:`/`9x16:` filename references (this also gives you the pairing from #2 for free when a
  manifest exists — prefer manifest-based pairing over the filename heuristic when both are
  available, since it's authoritative).
- Store the extracted copy fields somewhere queryable per asset — reuse the reserved
  `soft_tags` column on `DriveAsset` as a JSON-encoded blob if that's the fastest path given
  the deadline, or add new nullable columns if you're already touching a migration for this
  (check with Claude Code before adding a migration — this brief is Codex-only scope, no
  migration should ship without review).
- In the picker modal and in `AdCreativeStep.jsx`'s add-to-campaign handler, when a selected
  asset (or paired asset) has matched copy, pre-fill Primary Text / Headline / Description
  (and the Website URL field, see #4) — same pattern already used for the Generated Ads
  Library and Winning Ads copy-carry (`prev.headlines[0] ? prev.headlines : ...` style
  "don't clobber what the buyer already typed" guard).
- **If parsing fails or the format doesn't match what you find** (don't assume the one real
  example above is universal — inspect a few real folders first), fail silently: no copy
  prefill, exactly today's manual-entry behavior. Never block the picker or throw an error
  over a malformed manifest.
- Do not build a general-purpose document parser. Scope narrowly to this one observed
  convention; if a folder's manifest doesn't match the shape you find, skip it.

## 4. Pull the landing page URL into the launcher
Joel: "if we can pull the campaign URL to the launcher would be good."
Two independent sources, do both:
- **Quick win, ship regardless of #3:** `Product.default_url` already exists in the schema
  (`backend/app/models.py`) but check whether `AdCreativeStep.jsx`'s "Website URL (Landing
  Page)" field ever reads it — if not, prefill from the selected brand's product default_url
  when the field is empty, same "don't clobber" guard as everywhere else.
- **When a Drive manifest was parsed (#3):** prefer its `Landing page:` value over
  `default_url` for that specific asset, since it's the deliberately-approved URL for that
  exact creative package (e.g. `https://www.getbusinesscoverage.com/quote-v2`).

## Priority order given the Friday/tomorrow deadline
1. Search bar in picker modal — ship first, trivial, no ambiguity.
2. Filename-based 1x1/9x16 pairing — ship next, covers the whole library.
3. Product default_url prefill (the independent half of #4) — quick, ship alongside #2.
4. Manifest parsing for copy + landing page (the harder half of #3 and #4) — build it, but
   if you're running out of time, ship 1-3 first and hand off #4 as its own follow-up rather
   than rushing the parser and shipping something that silently fails on real data.

## Hand off
Commit locally, don't push. Note in your hand-off exactly which of the 4 items you completed
and which (if any) you're deferring, given the deadline. This will get a review pass sized to
what actually shipped — if it's just #1-3, that's a small/medium UI review; if #4 lands too,
expect the same 2-agent treatment prior Ad Remix changes got, since it touches sync/parsing
logic that could silently misfire on real data.
