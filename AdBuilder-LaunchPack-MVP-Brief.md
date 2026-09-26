# Launch Pack MVP

## Executive summary

Joel and Abel should be able to take a prepared Drive package to a paused Meta batch without searching for its destination settings or manually separating valid media from unfinished work. The MVP introduces a launch-ready view in the existing Drive picker, then evolves it into saved reusable Launch Packs and a server-side resumable queue.

## MVP scope

1. Drive launches open with **Launch ready** selected.
2. A launch-ready group must have uploadable media, verified non-ambiguous copy, a valid destination URL, and a supported Meta CTA.
3. Incomplete or blocked groups remain available through explicit filters, but never masquerade as launch candidates.
4. The existing Drive shortcut continues to resolve the last valid account, campaign, ad set, Page, CTA, and destination without any Meta write.

## Next delivery: persisted packs

A saved pack will store its account, campaign, ad set, Page, URL, CTA, naming template, placement policy, and a Drive package identifier. Opening a pack will run preflight and show only exceptions before a single paused-launch confirmation.

## Server queue phase

The final launch action becomes an idempotent server job. It creates paused ads with checkpoints, Meta rate-limit pacing, per-row outcomes, and safe resume/reconciliation after the browser is closed. No automatic activation or spend changes are in scope.
