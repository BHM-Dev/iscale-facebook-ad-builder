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
- "Create ads paused" toggle when parents are ACTIVE — **not building it for now (2026-10-25).** Slack history shows Abel never asks for paused-by-default; he schedules launches to go live at midnight PT (start time on the ad set, "so they get a full day of testing"). The launcher now shows that schedule on Review instead (see Changelog). Steve approved that direction; Abel was asked in a DM and has not replied. Revisit only if someone asks for create-paused.
- Partial-failure box should also list created-but-unsaved ads and failed ad names.
- Component tests for blocked-card keyboard, partial-failure panel, hard-block vs acknowledge flow.
- Codex working brief: [`CODEX_BRIEF_launcher-ux.md`](../../CODEX_BRIEF_launcher-ux.md).

## Changelog (newest first)
- 2026-11-17 **Drive copy: the file name is the only rule** (Steve approved the rewrite). `bind_handoff_manifest()` in `drive_sync_service.py` is now the one inline-manifest binder, and the validator uses it too.
  - **How it binds:** every `##` ad block attaches its copy to exactly the files it lists, in any layout. Ad numbers, heading shapes and fixed placement pairs are no longer required, and a single placement is fine.
  - **What still blocks a file:**
    - the file is missing from the package, or two files share its name;
    - the size or media type doesn't match its label;
    - the same file is listed under two ads;
    - the file is named for another ad, or carries another AD number;
    - an ID-only ad's file isn't named for it;
    - the ad's copy is unreadable, or a label was left empty.
  - **Each ad is all-or-nothing:** a typo never leaves half a pair launchable, and the package's other ads still import. Before this, one bad block blocked the whole package.
  - **Unchanged:**
    - Copy IDs stay `AD-NN` when every heading has a unique number.
    - Landing page and Meta Button are read from anywhere in the document.
    - A `## Files` or notes sub-heading stays part of the ad above it.
  - **Also fixed:**
    - `16X9` labels no longer leak into primary text.
    - Windows line endings parse.
  - The template instructions now state the one rule.

- 2026-11-17 Drive copy, two new manifest layouts (Abel: "refresh just hangs" on the AUTO ads):
  - **AUTO-18 Life Events.** The parser only accepted 4X5/16X9 + 9X16 video, so `1X1 VIDEO` + `9X16 VIDEO` blocks rejected the whole package. All 16 files were left out, and 182 files retried on every sync.
  - **AUTO-20V Kitchen Video Hook Test.** ID-only headings like `## AUTO-20V-HC-B1-C1` (hook × body × CTA, no ad number) weren't read, so all 88 videos imported without copy. These headings now bind one block at a time. A file belongs to the longest label it's named for, unless that label is a parent of the block's own label, so B1 can't take B2's files. An ID-only heading with no PRIMARY TEXT under it is still ignored, as before.
  - **Validator.** It shares the parser's heading regex, placement rules and ownership rule.
  - *Read-only dry run on prod, new code against the real packages:* AUTO-18 matched 16 of 16 files across 8 blocks; AUTO-20V matched 88 of 88 across 44 blocks.
- 2026-11-17 **Nightly Drive check, 23:00 America/New_York** (`drive_nightly_check`). Covers every package with a file changed in the last 26h:
  - dry-runs the copy parser and runs the manifest validator;
  - lists files not yet in the library;
  - runs the picker's Refresh where the parser resolves copy the library lacks. That re-attaches copy and imports missing package media. It waits for a running sync rather than reporting a false failure.
  - DMs Steve every night, including when everything is clean. Never writes to Drive or Meta.
  - *Read-only dry run on prod (48h window):* 10 packages, all ready, about 5 min.

- 2026-11-14 Live-spend confirmation (review S2, Steve approved): launching into an existing campaign whose delivery state is LIVE needs a "Yes, deliver now" tick above Launch (and above "Retry remaining"); resets on target change. Paused / scheduled / new campaigns unaffected. *Build + unit tests only; not exercised in a browser.*
- 2026-11-14 RedTrack tracking can no longer be silently dropped (review S3): if building the creative's `url_tags` fails, the creative still gets the full `sub1={{ad.id}}&sub2={{adset.id}}&sub3={{campaign.id}}` set and Steve gets a DM (at most one per 10 min). Normal path unchanged. *Unit-tested only.*
- 2026-11-12 Duplicate-on-retry (review S1): a 5xx carrying Meta code 1 or 2 on campaign / ad set / ad create now counts as "may have been created" (`writeOutcomeUnknown` in `facebookApi.js`), so the launch stops for reconciliation instead of offering a retry. Uploads and creatives keep the old rule (a repeat only leaves an unused asset). Budget/status PATCH errors with code 1/2 no longer claim "nothing was changed". *Unit-tested only — Meta code 1/2 can't be triggered on demand.*
- 2026-11-12 Convention-named files without a sequence number (Joel's video hook tests, `AUTO-20V-H1-B1-C2-NoTickets-VID-9x16.mp4`) are now used verbatim too: two leading codes plus a trailing `-IMG|VID-1x1|4x5|9x16` tag counts as a finished ad name. Before, they fell back to the template and came out as `{wave_code}-{niche_code}-01-AUTO-20V-...` on accounts with no preset (DIN Auto). *Unit-tested only.*
- 2026-11-10 Drive picker: amber "Winner #N · +$X est." badges on proven creatives and a "Winners (N)" filter that shows them across all folders (data from `/winners`, 14 days, 10+ leads, profitable only; account-gated; failure shows "Winners unavailable"). *Verified locally on real RHO data: 23 winner cards, no negative-profit badges.*
- 2026-11-08 Naming templates: shared per-account naming setup (`/naming-presets`), Wave/Niche/Angle inputs build campaign, ad set and ad names in the buyers' convention (`RHO v1 | ABO | VEHICLE W2 FUNERAL HOMES | CAPI | date`, `VW-FUN | FLEET AND CREW`, ad = Drive filename). Convention-named Drive files are used verbatim. Server strips any unresolved `{token}` from names before Meta and the local save. *Verified locally on real RHO data up to Review (nothing sent to Meta); preset not yet saved by Abel.*
- 2026-10-25 **Review step understands scheduled starts.** A new ad set with a future start time (or an existing ad set whose Meta `start_time` is in the future, read by the live check) now shows a blue **SCHEDULED** state: "Ads are ACTIVE but scheduled: nothing spends before Mon, Oct 26, 12:00 AM PT, then they start delivering" — instead of the red "may start spending immediately" LIVE banner. Shown in Pacific time (the team's frame); if the browser isn't in PT the local equivalent is appended, because the date field is read in the browser's timezone (typing "12:00 AM" in ET is 9:00 PM PT). Safety rules: SCHEDULED only upgrades a LIVE state (never softens PAUSED/unknown/unverified); a past start time stays LIVE with an explicit "already passed" note; the screen re-checks every 15 s and **Launch re-checks at click time** and refuses if the start passed since the last render; Meta's `-0700` offset form is normalized so Safari/Firefox parse it. Backend: `GET /facebook/adsets/{id}` also returns `start_time`. Unit-tested only (`lib/liveStatus.test.js`, 13 tests); **not browser-verified, not exercised on a real scheduled launch** — first real check is Abel's next midnight-PT launch (never click Launch just to test).
- 2026-10-08 Launch Creatives landing page now names approved Drive creative as the recommended workflow; route and
  generation tools are unchanged.
- 2026-10-06 `248ad38` ticking checked-age, `liveStatus.js` + tests · `41a6918` single-object status endpoints,
  ARCHIVED/DELETED hard block, quiet focus refresh · `fac96bf` launch gate on live status · `ea081f0`/`9631664`
  keyboard/accessible Drive cards, Feed+Stories counts, status-accurate paused/live copy.
