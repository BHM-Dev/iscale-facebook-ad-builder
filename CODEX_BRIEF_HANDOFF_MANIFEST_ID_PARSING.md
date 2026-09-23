# Codex Brief — Generalize handoff-manifest Copy ID parsing (7 live packages currently unparseable)

## Why

Ran the app's own `refresh_copy_metadata()` live against production (SSH + `docker exec` into
`ad-builder-api`, per this repo's standard verification pattern) to check whether Drive copy
pairing actually works across every currently-synced package. Result: `{'processed': 80, 'updated':
61, 'errors': 7, ...}`. All 7 errors are the same failure — `RuntimeError("Drive handoff manifest
contained no copy entries")` from `_handoff_folder_copy_metadata` (`drive_sync_service.py:1107`) —
across these real, currently-active packages:

- Florist | Fresh Creative
- Florist | Legacy Control Relaunch
- Barber Shops | Fresh Creative
- Barber Shops | Legacy Control Relaunch
- Welders | Winner Variations
- Auto Dealerships | Compliance Requirement
- Auto Dealerships | Claim Denial Fear

Confirmed this isn't a stale-data artifact: every `drive_assets` row in these packages has
`soft_tags IS NULL` — they have **never** successfully auto-paired, not once. If Joel/Abel try to
bulk-launch from any of these 7 packages via the Drive-based flow today, copy pairing silently
produces nothing.

## Root cause

`_parse_handoff_manifest()` (`drive_sync_service.py:1779-1806`) and `_parse_copy_file()`
(`drive_sync_service.py:1808-1828`) both extract a per-ad "Copy ID" using the same regex:
`[A-Z]{2,5}\s*F\d{2}`, anchored to require the ID be effectively alone on its line (manifest side)
or at the start of a block (copy-file side). This was clearly built around one specific format
("FLR F01" alone on a line, or "HST F01 | BOARDING BARN | ..." at a block's start) and returns
**zero matches, silently, for anything else** — no error surfaced anywhere until the manifest-level
"no copy entries" check fires downstream.

Pulled the real manifest text for all 7 failing packages live (same SSH/docker pattern). They use
**four different ID/formatting conventions**, none of which fit the current regex:

1. **Florist (both variants):** header line is a single underscore-joined slug with no separator
   before the description — `FLR_F01_PEAK_WEEK_BLIND_SPOT` — and the ID also appears again inline,
   never alone: `Copy: Ad Copy/Florist_Fresh_Creative_Ad_Copy_FINAL.txt | FLR F01`. Field values
   also carry a folder prefix: `1x1: 1x1 Images/FLR_F01_peak_week_blind_spot_1x1.png` — **check
   whether `media_by_name` lookup at `drive_sync_service.py:1156` is keyed by bare filename only;
   if so, this is a second latent bug to fix in the same pass, not just the ID regex.**
2. **Barber Shops (both variants):** ID matches the current regex shape fine — `BSR F01` — but the
   line doesn't end there: `BSR F01 | Policy Assumption`. The trailing `| description` breaks the
   `\s*:?\s*$` end-anchor.
3. **Welders | Winner Variations:** `WLD TRK 01` / `WLD HOT 01` / `WLD FEM 01` — a 3-token scheme
   (brand prefix + subgroup word + number) with **no "F" or "L" letter before the number at all**.
   Also note the manifest has an unrelated numbered list a few lines above the real IDs —
   `01 - Truck Winner Variations` / `02 - Hot Work Winner Variations` — that must NOT be mistaken
   for a per-ad ID by whatever generalized pattern you write.
4. **Auto Dealerships (both variants):** `AD DEALER CR 00` / `AD DEALER CD 00` — a 4-token ID,
   numbering starts at `00` not `01`, and the field labels are a **different structural style
   entirely** — `1x1` and `9x16` appear alone on their own line, with the actual filename on the
   **next** line, not `label: value` on one line:
   ```
   1x1
   AD-DEALER-CR-00-DealerOperations-1x1.jpg
   ```
   There's also a `Copy concept` label (same alone-then-next-line style) instead of `Copy file:` —
   that field isn't required by the parser today (copy text comes from the separate copy-file
   lookup), but note it as evidence of how structurally different this format is.

## Do not build four more special cases

Four already exist implicitly (the current regex is really "format #0"); bolting on four more
`elif` branches produces a parser that breaks again on the next new format Abel/Joel's team invents.
Build one generalized extractor instead. Suggested shape — verify and adjust once you're actually
looking at all the real text, don't take this as gospel:

1. **A single shared ID-extraction helper**, used by both `_parse_handoff_manifest` and
   `_parse_copy_file` (today they duplicate the same regex independently — a prior version of this
   exact duplication is why `_parse_copy_file`'s comment at line 1811-1818 had to explain a subtle
   anchoring difference from the manifest parser; keep them from drifting again by sharing one
   function). Both call sites need to produce the **same normalized key** for a given real-world ID
   or pairing breaks even when both individually "work."
2. **ID grammar, generalized:** a leading run of 1-3 uppercase alpha tokens (2-6 letters each, e.g.
   `FLR`, `BSR`, `WLD`, `AD DEALER`) followed by a 1-3 digit number, any of {space, underscore,
   hyphen} as the separator between tokens, case-insensitive, number may start at `00` or `01`.
   Normalize to one canonical form (e.g. uppercase, single-space-joined) — and use that same
   normalization in both parsers.
3. **ID can appear in any of these positions** (all four are real, confirmed above) — don't assume
   one:
   - Alone on a line (current supported case)
   - Alone on a line, followed by a separator (`|`, `:`, `-`, em dash) and trailing description text
   - As the leading token-run of an underscore/slug-joined header line, followed immediately by more
     description tokens with no separator at all
   - Embedded inline elsewhere on a line (e.g. after a `Copy:` label pointing at a copy file)
4. **Guard against false positives.** A numbered section header (`01 - Truck Winner Variations`)
   must not be picked up as a per-ad ID. The real signal that distinguishes a genuine ID line from
   a section header: a genuine ID's prefix token(s) repeat identically across every real entry in
   the package (`WLD` recurs on every Welders ID; a section header like `01 - Truck...` has no
   letter prefix at all before the number). Consider requiring the candidate line to also have a
   plausible `1x1`/`9x16` pairing nearby (same generalization you're building for field extraction)
   before accepting it as a real entry, rather than accepting any line that merely matches the ID
   shape in isolation.
5. **Field extraction, generalized:** support both `label: value` on one line (current, keep
   working) AND `label` alone on a line with the value on the next non-blank line (Auto Dealer
   format) for the `1x1`/`9x16`/`copy file`-equivalent fields.
6. **Trace the consumer**, don't just fix the two parsers in isolation: `_handoff_folder_copy_metadata`
   (`drive_sync_service.py:1102-1177`) uses `entry.get("1x1")`/`entry.get("9x16")` values to look up
   `media_by_name.get(file_name.lower())` (line 1156) and `copy_blocks.get(copy_id.lower(), {})`
   (line 1151) — both lookups depend on exact string agreement with whatever your generalized
   extractor produces. Confirm end-to-end, not just that parsing returns non-empty entries.

## Verify against the real account, not just these 7 samples

Before writing code, pull **every** currently-synced handoff manifest and category/ad-copy doc live
(same SSH/`docker exec` pattern used to find this bug — `DriveSyncService(db)._client()` +
`_initial_folder_walk` + `_download_text_file`) and catalog every ID/field format actually in use
today. Treat the 4 formats above as a floor, not the ceiling — there may be more variants among
packages that currently succeed by accident or among ones outside the 7 that errored. A format that
currently "succeeds" only because it happens to satisfy the narrow existing regex is still worth
knowing about, so your generalized replacement doesn't accidentally narrow support for it.

## Regression requirement

`refresh_copy_metadata()` reported `updated: 61` on the 73 non-erroring files it processed —
whatever currently works must keep working. After your fix, run the exact same live check again
(`DriveSyncService(db).refresh_copy_metadata()` via `docker exec`) and confirm:
1. `errors` drops to 0 (or, if some remaining error is a genuinely different/unrelated cause, name
   it explicitly — don't silently suppress a real new failure).
2. Spot-check at least 2 of the 7 previously-broken packages by reading their now-populated
   `soft_tags` in the DB and confirming the `copy_id`/`1x1`/`9x16`/headline/primary_text actually
   line up correctly with what the manifest and copy file really say — not just that the row is
   non-null.
3. Spot-check at least 1 previously-working package the same way, to confirm no regression.

## Explicitly out of scope

- Don't touch the separate short-code family-matching logic (`_matches_category_short_code`,
  `_category_alias_replacements`, `_CATEGORY_KEYWORD_ALIASES`) — that's a different, already-closed
  issue (deliberately strict, confirmed via live audit 2026-09-19 that zero live packages need it
  loosened). This brief is specifically about the handoff-manifest/copy-file ID-and-field parser.
- Don't change `_parse_category_copy_doc`'s numbered-heading format (the older 7-category legacy
  doc type) unless you find it shares the same bug — check, but it's a different code path
  (`_category_folder_copy_metadata` vs `_handoff_folder_copy_metadata`).

## Hand-off

`drive_sync_service.py` is not one of this repo's four hard trigger files, but it sits directly in
the ad-launch copy-pairing path (money-adjacent — wrong pairing means wrong ad copy goes live).
Commit locally, then:

> "Edits done — ready for Claude Code 2-agent review + push."

Claude Code will size the review to the diff and re-run the live `refresh_copy_metadata()` check
against production before pushing.
