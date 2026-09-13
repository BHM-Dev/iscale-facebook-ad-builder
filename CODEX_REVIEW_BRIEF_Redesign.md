# Codex Review Brief — Competitor-Synthesis Redesign (Phases 1-5)

Full second-opinion review requested. This is everything shipped from
`AdBuilder-Competitor-Synthesis-Redesign-Brief.md` — 5 phases, 7 commits, all already pushed to
`develop` and confirmed deployed/green. Nothing here is a request to fix-and-push blind — read,
form your own judgment, flag anything you'd push back on, and hand findings back for a decision
before touching any trigger file.

## Scope

```
git log --oneline 1632833..cfb23ed
git diff 1632833..cfb23ed
```

Seven commits, in order:
1. `dc077be` — Phase 1: live variation counter in `AdCreativeStep.jsx`
2. `dfd283d` — persistent Ad Remix right-rail summary (this one was your own earlier build,
   included here for completeness)
3. `e79dc2e` — Phase 2: native ad-preview grid on `BulkAdCreation.jsx` Review screen
4. `f24fa51` — Phase 3: auto-pause rules generalized into a multi-action rules engine
   (Pause/Notify/Increase budget/Decrease budget)
5. `753ce6f` — a same-session fix for a schema drift `f24fa51` introduced (CI caught it)
6. `44b8bae` — Phase 4: "one ad set per media file" creation mode
7. `cfb23ed` — Phase 5: name-search on Campaign Performance

## What already happened before these were pushed

Every commit touching a trigger file (`BulkAdCreation.jsx`, `AdCreativeStep.jsx`,
`facebook_service.py`) or a DB migration went through the mandatory 2-agent pre-push review
(`code-auditor` + `joel-perspective`), plus a Meta-API domain-expert pass for the Phase 3 budget
work. Real findings came back every time and were fixed before push — not rubber-stamped. The
headline ones, so you know what's already been through a pass and don't need to re-litigate from
scratch (though re-checking is welcome — a second reviewer catching something the first missed is
exactly the point of asking you):

- **Phase 2**: a pre-existing bug (not introduced by this pass) where `headlineIndex`/`bodyIndex`
  were positions in the *filtered* (non-empty) headline/body list but both the real Meta payload
  and the new preview card indexed into the *raw* list — a gap anywhere but the tail of the field
  list silently sent the wrong headline/body to Meta. Fixed by carrying the true original array
  index through the filter.
- **Phase 3**: a rule scoped to one ad set under a CBO campaign could silently move budget for
  every OTHER ad set sharing that campaign, with nothing in the Slack alert or audit log saying
  so. Fixed: refuses to fire when another active ad set shares the campaign; explicit
  "CBO campaign budget, shared" language when it does proceed.
- **Phase 4**: per-media mode multiplies ABO budget by however many media files you pick, with no
  warning before this fix. Fixed: explicit `$X × N ad sets = $Y/day` warnings on both the toggle
  and the Review screen.
- **753ce6f**: `AutoPauseRuleLog.created_at` was declared nullable in the model but NOT NULL in
  the migration — CI's `alembic-round-trip` drift check caught this immediately after push (not a
  runtime bug — Deploy to VPS had already succeeded — but real schema drift). Fixed same-session.

Full reasoning and the complete list of lower-severity findings (fixed and deferred) are in
`AdBuilder-Competitor-Synthesis-Redesign-Brief.md` and `AdBuilder-BulkRules-Feature-Brief.md`,
both updated in place as each phase shipped — read those for the "why," not just the diff.

## What's explicitly NOT done, and why — don't "fix" these without flagging first

- **Targeting-variant testing axis** (§4.3 of the redesign brief) — skipped. This needs Joel's
  product confirmation (does he actually want to split-test Gender/Relationship Status/Placement
  as a second combinatorial axis) before it's worth scoping. Not a bug, not an oversight.
- **Comparison-cell metrics on `CampaignPerformance.jsx`** — deliberately not built. Every date
  preset here (`today`, `last_7d`, etc.) is resolved server-side by Meta itself; this app has no
  local knowledge of the exact calendar days each one covers. Building a "previous period"
  comparison would mean guessing Meta's day-boundary convention — risking a silently wrong number
  on Joel's most-used page. If you want to pick this up: verify Meta's exact `date_preset`
  semantics against current Marketing API docs first, then build against confirmed ranges only.
  Don't approximate.

## What to actually do

1. Read the diff and the two brief files.
2. Pressure-test anything you're not convinced by — especially the CBO-refusal logic in
   `facebook_service.py`'s `adjust_adset_budget_by_percent` and the per-media ad-set fan-out in
   `BulkAdCreation.jsx`. Both are new Meta API surface area a second pair of eyes should stress.
3. If you find something real: **do not push a fix yourself.** `facebook_service.py`,
   `BulkAdCreation.jsx`, and `AdCreativeStep.jsx` are trigger files — any change needs the same
   2-agent review + Claude Code push. Report findings back (comment here, or however you and Steve
   normally hand off) rather than committing directly to those files.
4. Anything outside the trigger-file list (e.g. `CampaignPerformance.jsx`, `AdSetStep.jsx`,
   `AutoPauseRules.jsx`, `AdRemix.jsx`) you can fix and commit locally per the normal Codex/Claude
   Code split — just don't push directly per the repo's standing rule (final push goes through
   Claude Code so the hook-gated review runs).
