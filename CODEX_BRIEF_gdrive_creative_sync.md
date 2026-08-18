# Codex Brief — Google Drive Creative Sync

## Goal
Joel drops creative into a shared Google Drive folder. Ad Builder polls that folder on a schedule,
pulls new/changed files down into existing R2 storage (same bucket `uploads.py` already writes to —
do not introduce a second storage path), and makes them selectable in the ad-creation flow as a
"Drive Library" asset source alongside AI-generated and manually-uploaded creative.

**Real folder structure (verified live in Drive 2026-08-18 — do not assume a cleaner convention):**
```
Master (shared root)
 └─ Commercial Insurance          ← top-level = Brand (only one populated so far, more will appear as siblings)
     ├─ Trucking                  ← niche/angle folder, arbitrary name, no fixed taxonomy
     ├─ Auto Body
     ├─ Auto Dealerships
     ├─ Religious Organizations
     ├─ Horse and Stable | Fresh Creative
     ├─ Welders | Winner Variations
     ├─ 07 - General Commercial Insurance
     └─ Commercial Van Insurance
          ├─ Winner Variations - Market Comparison   ← creative-concept folder, arbitrary name
          └─ Winner Variations - Comparison Shock
               └─ (actual image/video files live here, or possibly nested deeper — depth is not fixed)
```
There is **no dedicated Format folder anywhere**. Joel names folders after niche/angle and creative
concept, however he sees fit — don't assume a fixed depth or a fixed set of folder-name categories.
**Format must come from the file's mime-type/extension, never from folder name.** Only the
**top-level folder under the shared root is reliably the Brand** — everything below that is a
free-form tag path with variable depth.

Auth: Google Cloud **service account**. Steve creates the GCP project + service account and shares
the Drive folder with the service account's email (Viewer). The service account JSON key goes into
`.env` on the VPS directly via SSH (self-serve now — see project CLAUDE.md, no Golden DM needed).

## Do NOT touch (hand back to Claude Code)
- `frontend/src/components/AdCreativeStep.jsx`
- `frontend/src/components/BulkAdCreation.jsx`
- `frontend/src/lib/facebookApi.js`
- `backend/app/services/facebook_service.py`
- Any Alembic migration file

Build everything up to "assets are synced and browsable in a library UI." The last-mile wiring of
a Drive-synced asset into the actual ad-creation picker happens in Claude Code (trigger-file rule).

## Backend

**New file: `backend/app/services/drive_sync_service.py`**
- Auth via `google-auth` + `google-api-python-client`, service account credentials from
  `GOOGLE_SERVICE_ACCOUNT_JSON` env var (base64-encoded JSON, decode at load time — same pattern
  as any other secret-from-env in this codebase, check `core/config.py` for the convention).
- Root folder ID from `GOOGLE_DRIVE_ROOT_FOLDER_ID` env var.
- Use Drive API **`changes.list`** with a persisted `startPageToken`, not a full `files.list` scan
  every run — cheaper, avoids re-processing unchanged files, and gives a natural incremental
  checkpoint. Store the token in a small singleton table or a row in an existing key/value config
  table if one exists (check `models.py` first — don't add a new table for a single token if
  something reusable exists).
- Walk each changed file's `parents` chain up to the shared root (recursive `files.get` on parent
  IDs, cache resolved paths per run — don't re-walk the same parent twice). The **immediate child of
  the shared root is the Brand**; everything between that and the file itself is a free-form path —
  store it verbatim as a `folder_path` string (e.g. `"Trucking/Winner Variations - Market Comparison"`)
  rather than trying to force it into named tag columns. Do not assume a fixed depth.
- Match the resolved Brand folder name against existing `Brand` records (fuzzy match on name; if no
  match, skip the file and log it — do NOT auto-create brands). There is no reliable Product-level
  folder, so don't attempt to resolve `product_id` from the path — leave it null; a person can tag
  it in the library UI later if that turns out to be needed.
- **Format comes from the file's mime-type/extension** (`image/*` → `image`, `video/*` → `video`;
  if you need to distinguish `9x16` from standard video, that has to come from actual pixel
  dimensions via a lightweight probe — e.g. ffprobe/Pillow — not from any folder name).
- Download the file bytes, push to the existing R2 client (reuse whatever `uploads.py` uses — do
  not add a second S3/R2 client instantiation), and record the asset.
- **Idempotency:** keyed on Drive `file_id` (unique). If `modifiedTime` unchanged since last sync,
  skip re-download but do nothing else. If a previously-synced file is deleted/trashed in Drive,
  mark the local record `archived=True` — never hard-delete (an asset may already be attached to a
  live ad).
- **Failure handling:** any auth failure, quota error, or folder-not-found must fail loudly — reuse
  `slack_service.py`'s existing alert pattern to post to whatever channel the auto-pause alerts
  already use (check `scheduler_service.py` / existing Slack alert calls for the pattern and target
  channel — don't invent a new channel).

**New model (draft only — Claude Code owns the actual migration):**
Sketch a `DriveAsset` model in a scratch note (do not touch `models.py` or `alembic/versions/`)
with these fields, and reserve nullable placeholders per house style:
`id, drive_file_id (unique), brand_id (FK), product_id (FK, nullable — no reliable source in the
current folder structure), format, folder_path (string, verbatim path from Brand folder down —
this is the fallback for anything the parser can't cleanly categorize), file_name, r2_key,
thumbnail_r2_key, drive_modified_time, synced_at, archived (bool, default False),
soft_tags (nullable, future), variant (nullable, future), geo (nullable, future)`.
Hand this sketch to Claude Code — don't write the migration yourself.

**New route: `backend/app/api/v1/drive_assets.py`**
- `GET /api/v1/drive-assets` — list synced assets, filterable by brand_id/product_id/format,
  `archived=false` by default.
- `POST /api/v1/drive-assets/sync-now` — manually trigger one sync pass outside the schedule
  (Joel/media buyers will want this instead of waiting on the interval).
- Follow the existing route file conventions (auth dependency, response schemas in
  `backend/app/schemas/`) — check `uploads.py` and `generated_ads.py` for the pattern.

**Scheduled job:**
- Register a new interval job in `scheduler_service.py`'s existing APScheduler setup (same pattern
  as the 30-min auto-pause check) — every 15–30 min is plenty for a polling sync, this is not
  time-sensitive. Confirm the actual interval with Steve if the auto-pause job's cadence isn't a
  clean fit.

## Frontend

**New page or section: "Creative Library"**
- Grid/gallery view of synced Drive assets, grouped by Brand → `folder_path` (render as a
  breadcrumb, e.g. `Trucking / Winner Variations - Market Comparison`) with a Format filter chip
  row, thumbnail, filename, sync timestamp, and a manual "Sync now" button hitting the new endpoint.
- Since `folder_path` is free-form and Joel's naming isn't standardized, include a text filter/search
  over `file_name` + `folder_path` — grouping alone won't be enough to find things at scale.
- Reuse `authFetch` from `lib/facebookApi.js` for all calls (read-only import, do not edit that file).
- Reuse `useToast` for sync-now success/failure feedback — never `alert()`.
- This is a browsable library only in this phase — it does NOT need to plug into
  `AdCreativeStep.jsx` yet. That wiring is a separate, Claude-Code-owned follow-up once this is
  live and Joel has creative flowing through it.

## What "done" looks like for this Codex pass
1. Service account auth works against the real shared folder (master folder ID
   `1SfyeCOcW5HWTjbv5a2scJnoix_U0Ah1e`, already shared with `ad-builder-drive-sync@bhm-automations-494217.iam.gserviceaccount.com`
   as Viewer).
2. A sync pass correctly resolves Brand from the top-level folder, format from mime-type, stores
   the rest of the path verbatim as `folder_path`, and lands files in R2. Test against the real
   `Commercial Insurance` brand folder and its actual messy subfolder structure — don't build
   against a clean synthetic fixture that doesn't reflect it.
3. Re-running sync with no Drive changes does nothing (verify via logs — zero re-downloads).
4. A file trashed in Drive gets `archived=True` locally, not deleted.
5. A forced auth failure (bad service account key) produces a Slack alert, not a silent log line.
6. Creative Library page renders synced assets grouped correctly, manual sync-now button works.
7. Commit locally. Do NOT push. Hand off note: "Drive sync + library UI done — needs migration +
   AdCreativeStep.jsx wiring in Claude Code before this reaches ad launch."

## Explicitly out of scope for Codex
- Wiring Drive assets as a selectable source inside `AdCreativeStep.jsx` / `BulkAdCreation.jsx`
- The Alembic migration itself
- VPS env var setup (Claude Code adds `GOOGLE_SERVICE_ACCOUNT_JSON` / `GOOGLE_DRIVE_ROOT_FOLDER_ID` via SSH once Steve has the service account key — see project CLAUDE.md)
