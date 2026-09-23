# Codex Brief — Close a real false-positive gap in the new handoff-ID extractor

## Status of `f87127d`

Committed locally, not pushed. Pre-push review (2 parallel agents) plus a live validation I ran
against every real production manifest/copy-file (8 handoff manifests, all their referenced copy
files — pulled live via SSH/docker exec, same pattern as the original brief) confirms the core fix
is good: **zero false positives, zero missing entries, across every real package in production
today**, including a bonus fix (Horse and Stable's manifest now also resolves, previously untested).
`_find_package_folder`'s stricter has-manifest-AND-has-media check was also confirmed safe against
real folder layouts for all 8 packages — not a regression.

One real gap remains, demonstrated with a reproducible repro (not hypothetical):

## The bug

`_extract_handoff_copy_id`, when called from `_parse_copy_file`'s per-line heading scan
(`drive_sync_service.py`, the `headings = [...]` comprehension), accepts a bare `PREFIX NUMBER` line
with **nothing else on it** as a valid new copy-ID heading. Repro:

```python
copy_file = """AD DEALER CR 00
PRIMARY TEXT
Dealer primary text line one.
Batch 3
More primary text after the stray line.
HEADLINE
Dealer headline
1X1 IMAGE
AD-DEALER-CR-00-DealerOperations-1x1.jpg
"""
# _parse_copy_file(copy_file) produces TWO blocks:
#   'ad dealer cr 00' -> primary_text truncated to "Dealer primary text line one."
#   'batch 3'          -> steals "Dealer headline" as its own headline
```

A bare line like `Batch 3` / `Phase 2` / `V2` mid-body silently splits the real ad's copy block and
fabricates a bogus one that steals whatever headline/field text follows. This repo already has
documented precedent for exactly this line shape appearing in real Joel/Abel content — see
`_NON_NICHE_RE` in `research_service.py`, which exists specifically to filter "Batch 3", "V2",
"SCALE", "PHASE 2", "RETARGET" out of ad-set names for the same reason. It hasn't hit any of the 8
real packages currently in production (verified — see above), but it's a live landmine, not a
theoretical one.

## Fix direction — verify and adjust, don't take as gospel

The real signal that distinguishes a genuine bare heading (Welders' `WLD TRK 01`, Auto Dealer's
`AD DEALER CR 00`, both legitimately alone on their line) from an incidental prose/label line like
`Batch 3`: a genuine heading is immediately followed by recognizable structure — the next non-blank
line is either another recognized field label (`PRIMARY TEXT`, `HEADLINE`, `DESCRIPTION`, `1x1`,
`9x16`, `Copy ID`, `Copy file`, or the aspect-ratio variants already in `_COPY_FIELD_STOP_LABELS`)
or another valid-shaped ID line. `Batch 3` in the repro above is followed by ordinary prose
("More primary text..."), which is neither.

Suggested approach: when `_extract_handoff_copy_id` is about to accept a **bare, nothing-following**
match (the current `if remainder and not re.match(...)` branch's *empty-remainder* case
specifically — the pipe/colon/dash-suffixed case is already a strong signal and probably doesn't
need this extra check), require the caller to confirm the next non-blank line looks like a field
label before committing to it as a real heading. This likely means passing a lookahead line (or the
next line) into `_extract_handoff_copy_id`, or moving this corroboration check into
`_parse_copy_file`'s heading-collection loop where the next line is already available via index
arithmetic. Your call on where it lives — just don't lose the fix for the manifest-side loop too
(`_parse_handoff_manifest` has the same acceptance logic via the same shared helper, so the same
gap likely exists there; check with an equivalent repro before assuming it's copy-file-only).

## Do not regress what already works

Re-run the exact validation after your fix and confirm it still holds:
```python
# All 8 real manifests currently parse with zero false positives / zero missing entries
# (verified live 2026-09-19 against production Drive content). Your fix must not change that.
```
Add both as permanent regression tests in `backend/tests/unit/test_drive_handoff_manifest.py`:
1. The `Batch 3`-style stray-line repro above — assert it does NOT produce a `'batch 3'` block and
   does NOT truncate the real entry's `primary_text`/`headline`.
2. The equivalent case for `_parse_handoff_manifest` (a manifest with a bare non-label line between
   real ID blocks) if you find the same gap exists there.

## Explicitly out of scope

- Don't touch anything else in `f87127d` — the ID grammar, token-glue heuristic, field-value
  basename stripping, and `_find_package_folder` change are all confirmed correct against real data.
  This is a narrow, additive guard on top of already-good work.

## Hand-off

Same as before — this is in the ad-launch copy-pairing path. Commit locally (amend `f87127d` or a
new commit, your call), then:

> "Edits done — ready for Claude Code 2-agent review + push."

Claude Code will re-run the live production validation (both the manifest/copy-file parse check and
the new Batch-3-style repro) before pushing.
