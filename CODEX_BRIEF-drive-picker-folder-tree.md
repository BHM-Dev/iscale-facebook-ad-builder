# Codex Review Brief — Drive Creative Picker (folder tree + unit fixes)

**Repo:** `BHM-Dev/iscale-facebook-ad-builder`, branch `develop`
**File touched:** `frontend/src/components/AdCreativeStep.jsx` only (trigger file — all six commits below went through the mandatory 2-agent pre-push review before landing)
**Status:** all six commits deployed to production and live-verified in Chrome (`ad-builder-api` confirms each commit SHA served after deploy)

## Commits, in order

1. `ae78050` — Collapse the legacy archive on the Drive health page (separate page, `DrivePackageHealth.jsx` — not the picker, listed for completeness)
2. `3434819` — Format pills (`All / Images / Videos`) now count creative groups, not raw files, and are group-aware so a mixed-format Feed+Stories pair can't be split into a phantom half-group with the same id as the merged pair
3. `f7e9736` — Surfaced that 893 of 964 Drive tiles have no copy at all (only 71 have complete headline+primary_text) via a "No copy in Drive" badge and a "Needs copy (N)" filter, mutually exclusive with the existing "Blocked (N)" filter
4. `34a3b2c` — First pass at grouping tiles into 144 flat folder sections (superseded by commit 6 below, per Steve's follow-up feedback)
5. `15873c8` — Pre-push review fixes for #4 (stale-collapse-vs-search bug, footer count disagreeing with a collapsed section's real selection, section labels)
6. `d73b1c2` — Restructured into a real two-level tree: 16 top-level Drive folders, 6 "flat" (no subfolders, straight to tiles), 10 with 2–101 real subfolders each. Replaces the flat 144-row list from #4/#5.

## What changed and why (functional summary)

- **Unit consistency.** Everything on the picker toolbar — format pills, folder counts, blocked count, needs-copy count, "Select N" — now counts the same thing (creative groups/tiles), computed through the same search/filter pipeline the grid uses. Previously the format pills counted raw Drive files (1034) while the grid counted tiles (964), which read as a data bug when it was a unit mismatch.
- **Copy-completeness visibility.** 893/964 tiles have no ad copy sourced from Drive. This isn't a bug — those tiles are selectable and launch fine once someone types the headline/body — but it was previously invisible (no badge at all). Now flagged with a "No copy in Drive" badge and a dedicated filter.
- **Folder structure.** The picker now mirrors Drive's actual folder hierarchy instead of one flat 964-tile grid: 16 top-level folders → either straight to tiles (flat) or into real subfolders (up to 101 for the largest, "Commercial Insurance Master - Abel," 464 tiles). Matches the folder-count semantics `drive_health.py`'s package report already uses.

## Known-good, reviewed and live-verified

- Format-filter selection can no longer resolve a group id that means two different things depending on filter state (was a real money bug in an earlier draft — a mixed-format pair's image half and video half shared one group id; selecting the visible half silently added the invisible half to the launch. Fixed by making format filtering group-aware, not asset-aware.)
- Selecting a collapsed folder no longer moves the footer with no visible change — selecting auto-expands, and every header states how many of its tiles are selected.
- A collapse made while searching no longer survives search-clear as a stuck-empty section.
- Parent-level "Select N" is worded "Select all N" (acts on every child, expanded or not, with a toast warning above 30 creatives) vs. folder-level "Select N shown" (scoped to the current filter) — these were previously worded identically, which a review agent flagged as a real "select 464 creatives without noticing" risk on the 101-subfolder folder.
- The 101-subfolder folder now defaults collapsed on open (every other parent tops out at 16 children); everything else defaults open.

## What Codex should look at

Nothing is currently broken or pending — this is a completed, deployed, live-verified change. If asked to review:
- Confirm `drivePackageSection`'s 2-segment truncation (`Auto Dealerships/Two Winner Expansion` etc.) doesn't need to key off `package_folder_id` instead of `folder_path` string-splitting for robustness if Drive's folder depth ever changes (flagged as a known limitation, not a bug — current library is uniformly 1 or 2 levels deep under each top folder, verified against production data).
- "Expand all" at the picker level renders every matching tile unvirtualized (964 max) — no windowing. Not a problem today; flag if it becomes one as the library grows.
