# Codex Brief — Prioritized Code Audit

Steve wants confidence the codebase is clean given how much has been layered on recently
(Drive sync, dual-placement, similarity guard, nav restructure). Run this **in parallel** with
Claude Code's own pass — two independent reviewers, not a relay. Report findings back to Steve
directly (or to this repo as a dated `AUDIT_*.md` file) rather than fixing inline — this is a
find pass, not a fix pass, so nothing gets changed without review first.

## Why prioritized, not exhaustive
Today's session found real bugs repeatedly in the same shape: something that reads correctly in
isolation, passes a synthetic test, and only breaks against real production data (a folder
structure assumption, a regex fit to one example, a stale cache silently winning over new data).
Static code reading alone won't catch that class of bug — but it will catch the other real class
of risk: dead code, inconsistent patterns, deprecated Meta API usage, unhandled error paths. This
brief is scoped to what code reading can actually find well. Live-data verification (running real
flows against real accounts) is Claude Code's own pass, not yours, given account/API-credential
access.

## Priority 1 — money-path code (highest stakes, review these first)

**Auto-Pause Rules** (`backend/app/services/scheduler_service.py`'s auto-pause job,
`frontend/src/pages/AutoPauseRules.jsx`, whatever pulls live Meta Insights for the threshold
checks):
- Trace every threshold comparison (CPL, CTR, ROAS) for off-by-one/wrong-direction logic (e.g. a
  rule meant to pause on CPL *above* a value that actually fires *below* it).
- Check what happens on a missing/null/zero-denominator metric from Meta's Insights API (does a
  metric that's temporarily unavailable get silently treated as 0, potentially triggering a false
  pause?).
- Confirm the 30-min job's idempotency — could a transient failure mid-run double-pause the same
  ad set or skip one entirely on the next tick?

**P&L / revenue attribution** (`backend/app/api/v1/pnl.py`, `Pnl.jsx`, and anywhere RedTrack vs.
Switchboard-Everflow revenue source gets chosen per account):
- Confirm the source-selection logic (which accounts use which revenue source) hasn't drifted from
  what's actually configured — a wrong source here means wrong profit numbers with nobody noticing
  until a reconciliation.
- Check the commission/retainer math (Abel's % split logic mentioned in project docs) for
  correctness against what's actually documented as the agreed structure.
- Any place a currency/number gets formatted or rounded in a way that could compound into a
  meaningfully wrong total over many rows.

**Campaign Builder's OTHER creative paths** (not the Drive-picker path we just spent today
hardening — the manual-upload path, "Browse Generated Ads Library" push, Winning Ads → Ad Remix →
Campaign Builder path):
- These share `AdCreativeStep.jsx`/`BulkAdCreation.jsx`/`facebookApi.js`/`facebook_service.py` with
  the Drive path. Confirm today's changes (the `copyFieldsTouched` cache-touch tracking,
  `dualPlacement`/`secondaryImageUrl` handling, the placement-toggle UI changes) didn't silently
  regress the non-Drive paths — e.g. does a plain manual-upload creative still get the placement
  toggle/dupe-as-stories controls it always had (should NOT be hidden — that hide logic is
  supposed to be `dualPlacement`-only)?
- Confirm `secondaryImageUrl`/`dualPlacement` fields never leak onto creatives from these other
  paths where they shouldn't exist (would silently break something if a plain creative somehow got
  treated as dual-placement).

## Priority 2 — everything else (code-quality pass, lighter depth)

Research, Brands/Products/Customer Profiles CRUD, Copy Library, Image Ad/Batch Generate/Video Ad
generation tools, User Management, Settings. For each: dead code, duplicated logic that should be
shared, error paths that swallow exceptions silently instead of surfacing them, any remaining
deprecated Meta API field usage (grep for anything matching patterns Meta has deprecated — check
against current Marketing API docs rather than assuming what's in the code is still valid), and
stale comments/TODOs that no longer reflect what the code does.

## What NOT to do
- Don't fix anything found — report it, let Steve/Claude Code decide what to act on and in what
  order.
- Don't touch the four locked trigger files' actual logic even to "fix" something found in them —
  flag it, hand off.
- Don't attempt live verification (running real flows, real API calls) — that's explicitly out of
  scope for this pass.

## Output format
A findings list, most severe first, grouped by the priority tier above. For each: file/line,
what's wrong, why it matters (concrete failure scenario, not just "this looks off"), and a
confidence level if you're not fully sure it's a real bug vs. a stylistic choice.
