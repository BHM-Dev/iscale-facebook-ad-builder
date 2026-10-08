# Ad Launcher (Campaign → Ad Set → Drive picker → Review → Launch)

Code: `frontend/src/components/{AdCreativeStep,BulkAdCreation,BulkMatchImport}.jsx`, `adCreativeConstants.js`,
`frontend/src/lib/liveStatus.js`. Trigger files — any change needs the 2-agent pre-push review.

## What it does
Joel picks an account → campaign (new or existing) → ad set (new or existing) → Feed + Stories creatives from the
Drive library → reviews → launches. New campaigns are created **paused**; new ad sets/ads are created ACTIVE;
ads added to an existing ad set take that ad set's status.

The `/build-creatives` landing page presents this approved-creative Drive workflow as the recommended path. Generation
tools remain available as secondary options for teams that need to create new assets.

## Safeguards
- **Live Meta status gate (existing campaign):** Review re-reads the campaign (and ad set) from Meta via
  `GET /facebook/campaigns/{id}` / `/adsets/{id}`. **Launch is disabled until it succeeds**, with a reason line under
  the button. 15 s timeout. Failure → Retry check + "I checked Ads Manager" acknowledgement (except a hard block).
- **Hard block:** object ARCHIVED/DELETED (returned as a normal 200 by Meta) or 404 with Meta code 100 → no
  acknowledge, go back and reselect. Focus refreshes are quiet (keep last good state, never clear a hard block or
  the acknowledgement) and are throttled to 30 s / skipped mid-launch.
- **Delivery line:** says LIVE / PAUSED only when every status involved is plain ACTIVE/PAUSED and not effectively
  blocked; otherwise "status unclear — check Ads Manager". Red banner when ads will spend immediately; gray note
  when a paused parent means they won't. Shows "checked HH:MM, N min ago" (ticks every 30 s) with Refresh + Ads
  Manager link; budgets follow Meta exactly (CBO campaign budget shown, "Using campaign budget" for CBO children).
- **Partial failure:** reconciliation lock, "Retry N remaining ads", created/uncertain/failed rows named.
- **Drive picker:** whole-card select button (keyboard focusable, blocked cards still focus and toast the reason),
  visible No-copy / Blocked pills, `Clear selection (N)` clears only the pending selection, Preview is separate.

## Verified vs not
- **Browser-verified in production (2026-10-06):** account → existing campaign → ad set flow, 566 Drive groups,
  Feed+Stories pair, preview (selection preserved), Clear, Review shows PAUSED/PAUSED/PAUSED + CBO $1/day, manual
  refresh, no "manifest" wording. No Meta ad was created during testing.
- **Logic unit-tested (`liveStatus.test.js`):** hard-block rule, LIVE/PAUSED claim, ARCHIVED/DELETED detection.
- **Not verified:** archived-campaign hard block in the UI (mocked test only), blocked-card keyboard toast (production
  has no blocked assets), partial-failure panel (needs a forced failure — never trigger with real ads).

## Open items
- Re-check status at click time (check runs on open + quiet focus refresh only).
- "Create ads paused" toggle when parents are ACTIVE — **product decision pending (Steve)**.
- Partial-failure box should also list created-but-unsaved ads and failed ad names.
- Component tests for blocked-card keyboard, partial-failure panel, hard-block vs acknowledge flow.
- Codex working brief: [`CODEX_BRIEF_launcher-ux.md`](../../CODEX_BRIEF_launcher-ux.md).

## Changelog (newest first)
- 2026-10-08 Launch Creatives landing page now names approved Drive creative as the recommended workflow; route and
  generation tools are unchanged.
- 2026-10-06 `248ad38` ticking checked-age, `liveStatus.js` + tests · `41a6918` single-object status endpoints,
  ARCHIVED/DELETED hard block, quiet focus refresh · `fac96bf` launch gate on live status · `ea081f0`/`9631664`
  keyboard/accessible Drive cards, Feed+Stories counts, status-accurate paused/live copy.
