# GCP Setup — Ad Builder Google Drive Service Account

One-time setup, ~10 minutes. You do this in the Google Cloud Console and Google Drive; nothing
here needs Golden or Codex.

## 1. Use the existing `BHM Automations` project
No new project needed — checked the org's project list and **`BHM Automations`
(`bhm-automations-494217`)** is already the right home: you're Owner on it, the Drive API is
already enabled, and it already hosts the same pattern (an `everflow-cleanup` service account
running a scoped automation script). Select it in the top project picker at
[console.cloud.google.com](https://console.cloud.google.com) before continuing — skip creating a
new project or enabling the Drive API, both are already done.

## 2. ~~Enable the Drive API~~ — already enabled on this project, skip.

## 3. Create the service account
1. Left nav → **APIs & Services → Credentials**.
2. **+ Create Credentials → Service account**.
3. Name: `ad-builder-drive-sync` (anything descriptive is fine — this becomes part of its email).
4. Skip the optional "grant this service account access to project" and "grant users access" steps
   — not needed. Click **Done**.
5. You'll land back on the Credentials page. Click into the new service account.
6. Copy its email address — looks like
   `ad-builder-drive-sync@bhm-ad-builder.iam.gserviceaccount.com`. You'll need this in step 5.

## 4. Generate the key
1. Still inside the service account → **Keys** tab.
2. **Add Key → Create new key → JSON** → Create.
3. A `.json` file downloads automatically. **Treat this like a password** — it's the credential
   the Ad Builder backend uses to authenticate as this service account indefinitely (no expiry,
   unlike the Meta token).
4. Don't rename the contents, don't paste it into Slack or ClickUp. Two ways to get it to me
   securely:
   - Drop the file path and I'll read it directly if it's on this Mac, or
   - Paste the JSON into a message here (this session) and I'll write it straight to the VPS `.env`
     without echoing it back or storing it anywhere else.

## 5. Share the Drive folder with the service account — STILL NEEDS DOING
Correction (2026-08-18): this was previously marked done in error — the folder was only browsed
under Steve's own Google account, which is not the same as sharing it with the service account.
The service account has zero Drive access until this step happens.

Joel already has the master folder set up: `1SfyeCOcW5HWTjbv5a2scJnoix_U0Ah1e`, with
`Commercial Insurance` as the first Brand-level subfolder.

1. Open `https://drive.google.com/drive/folders/1SfyeCOcW5HWTjbv5a2scJnoix_U0Ah1e`
2. Share → paste `ad-builder-drive-sync@bhm-automations-494217.iam.gserviceaccount.com`
3. Role: **Viewer**. Uncheck "Notify people". Share.

Sharing the top folder covers everything nested under it — no need to repeat per-subfolder.

Note: the actual structure below the Brand folder is free-form (niche/angle → creative-concept
folders, no fixed depth, no dedicated Format folder) — see `CODEX_BRIEF_gdrive_creative_sync.md`
for how the sync handles that. Nothing needs to change about how Joel organizes it.

## 6. Folder ID — DONE
`GOOGLE_DRIVE_ROOT_FOLDER_ID` = `1SfyeCOcW5HWTjbv5a2scJnoix_U0Ah1e`

## 7. Hand off — DONE 2026-08-18
`GOOGLE_SERVICE_ACCOUNT_JSON` (base64-encoded) added to the VPS `.env` over SSH. Once the folder ID
above is also added and the backend container restarted, Codex can build against the real live
folder rather than a guess.

## What Joel needs to know
Nothing changes for Joel — he keeps organizing creative however he already does (Brand folder at
the top, free-form niche/creative-concept folders below). The sync adapts to his structure, not the
other way around. No new naming convention to learn.
