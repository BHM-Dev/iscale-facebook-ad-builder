# Ad Builder — "Quick Ad" Feature Brief

Written after live-comparing Birch and AdEspresso's creative-intake flows (2026-09-13) against
Joel's actual complaint: he has to follow a template to get creative into the ad launcher. Scoped,
built, reviewed, fixed, and live-verified same session — see §7 for what actually shipped and how
it differs from the original plan below.

## 0. Research — how Birch and AdEspresso actually handle creative intake

Live-tested both tools directly (not from memory/docs) before scoping anything, since Joel's
complaint was specifically about being forced through a template.

**Birch (`app.bir.ch`)** — its bulk-launch path ("Stage") is not free-form:
- The upload screen accepts either a pasted Google Drive folder/file link, or "Continue with
  Google Sheets." The real, in-use example sheet (`Birch Stage Test - Planning Sheet`) has exactly
  3 columns: `Google Drive link` | `Headline` | `Primary text` — one row per ad, one Drive **file**
  link per row (confirmed against real production row data, not a placeholder).
- So Birch does require a template too — just a much lighter one (a 3-column spreadsheet) than
  this app's Ad Remix (an AI-vision-deconstructed structural blueprint). Birch never scans a
  folder or infers anything from folder names — Joel (or whoever preps the sheet) has to get an
  explicit link to each individual file.

**AdEspresso (`app.adespresso.com`)** — the default "Create all permutations" campaign path needs
no template at all: free-text `Headlines` field, free-text `Ad Texts` field, a plain "Upload new
images" button. Its separate "Test Ad Templates" option is confirmed **optional** — live UI copy:
*"Your Ad Account does not have suitable Ad Templates... please create a new Ad Template **or**
select 'Create all Permutations'"* — i.e. a saved-preset convenience, never a gate on launching.
- Checked for a native Google Drive integration (Tools → Asset Manager): none exists. Asset
  Manager only manages Saved Audiences, not creative. Creative is always a direct upload or pulled
  from AdEspresso's own internal gallery (previously-uploaded assets) — never a live-synced folder.

**Conclusion this session reached (not previously written down anywhere):** neither competitor
attempts what this app's own `drive_sync_service.py` already does — bulk-ingesting a whole,
messily-organized Google Drive folder and making it browsable. AdEspresso skips the problem
entirely (no Drive integration at all); Birch skips it by requiring one explicit link per file
(no folder scanning, no brand inference). This app is the only one of the three that lets Joel
drop a whole folder in — the cost of that capability is the brand-folder-name-match requirement
and the manifest convention for full copy auto-fill, both already documented in
`CODEX_BRIEF_gdrive_creative_sync.md` and `CODEX_BRIEF_drive_picker_ux_feedback.md`. This is not
over-engineering relative to competitors — it's capability neither of them offers.

## 1. What's actually happening today (grounded in the real codebase, not assumed)

There are **two separate, already-built ad-launch flows** in this app, and Joel's daily routing
only ever sends him into one of them:

| | `/ad-remix` (`AdRemix.jsx`) | `/facebook-campaigns` (`FacebookCampaigns.jsx`) |
|---|---|---|
| Steps | Template → Brand → Product → Profile → Campaign → Generate → Results | Ad Account → Campaign → Ad Set → **Creative** → Bulk Ads → Review & Launch |
| Creative input | Pick a winning ad image → Claude Vision deconstructs it into a structural blueprint (`deconstruct_template`) → new copy is reconstructed *into* that blueprint | Free-text headline/body fields + direct media upload or Drive picker (`AdCreativeStep.jsx`) — no blueprint, no template |
| How Joel gets there | Remix drawer's "Build Ad ↗" button, every time | Nothing in Joel's daily flow links here at all |

**The gap isn't a missing capability — it's a missing door.** `AdCreativeStep.jsx` +
`BulkAdCreation.jsx` already do exactly what Birch and AdEspresso do by default: raw
headline/body text fields, direct image/video upload, a media × headline × body permutation
grid, straight to launch. Joel just never lands there from where he actually works.

## 2. What "Quick Ad" is

Not a new creative-input system. A new **entry point** into the flow that already exists, that
skips `/ad-remix`'s template step entirely:

- A "Quick Ad" action next to "Build Ad ↗" in the Remix drawer (`CampaignPerformance.jsx`), and/or
  directly on a Campaign Performance ad-set row.
- Clicking it writes a `pendingQuickAd` localStorage payload — same handoff pattern already used
  for `pendingRemixCreative`/`pendingBatchCopy` — carrying whatever's already resolvable at that
  row: `ad_account_id`, `fb_campaign_id`, `fb_adset_id`, `brand_id`. (Confirmed live: `AdsBreakdown`
  in `CampaignPerformance.jsx` already builds this exact object at line ~380 for the existing Remix
  button — nothing new to fetch.)
- Navigates to `/facebook-campaigns`.
- `FacebookCampaignWizardInner` reads `pendingQuickAd` on mount (same pattern `AdRemix.jsx` already
  uses for its own handoffs), and when present:
  - Pre-fills `formData.adAccountId` / `campaignId` / `adSetId` from the payload.
  - Jumps `currentStep` straight to **4 (Creative)** instead of starting at 1 (Ad Account) — this
    IS the "skip the template" fix, since Creative is the free-text/direct-upload step with zero
    blueprint requirement.
  - Deletes the localStorage key immediately after reading, same convention as every other
    `pending*` handoff.

## 3. Open question to verify before building (don't assume)

`CampaignStep`/`AdSetStep` may do side-effect data loading keyed to being visited (fetching the
campaign/ad set's own display details, budget, etc. for later steps to read). Jumping straight to
step 4 skips those mount effects. Needs a quick trace: does `AdCreativeStep`/`BulkAdCreation`
actually need anything those two steps' effects populate, or do they only need the IDs already in
`formData`? If the former, pre-fetch that data in the same mount effect that reads
`pendingQuickAd`, rather than have Bulk Ads silently render with a blank campaign/ad-set name.

## 4. Free upgrade this unlocks

Once Joel is in `AdCreativeStep` via Quick Ad, the existing Drive Creative Library picker already
auto-fills headline/body/CTA/landing page from `soft_tags` when the source folder has a handoff
manifest (see the Google Drive answer below) — so for manifest-backed packages, Quick Ad can mean
picking a creative pair and hitting Launch with **zero typing**, not just "no template."

## 5. Scope boundaries

- No backend changes, no migration.
- Frontend-only: `CampaignPerformance.jsx` (add the action + localStorage write — not a trigger
  file), `FacebookCampaigns.jsx` (read the handoff, pre-fill `formData`, jump `currentStep` — not a
  trigger file itself, but its children are).
- Does **not** touch `AdCreativeStep.jsx`/`BulkAdCreation.jsx`'s actual logic — they're consumed
  as-is. Still counts as touching trigger-file territory by association (they're what step 4/5
  render), so this gets the standard pre-push review, just sized to what it actually is: a small
  routing/state-prefill change, not new business logic. Cheap-tier code-audit + joel-perspective,
  no Meta-API domain-expert pass needed (no new Meta API surface).
- Does **not** replace `/ad-remix` — that stays the AI-assisted path for when Joel wants a winning
  ad remixed into new copy. Quick Ad is the parallel path for when he already has his own creative
  and copy ready and just wants to launch it.

## 6. Build priority

Small (frontend-only, no migration, no new API surface). One session, one review pass.

## 7. Shipped 2026-09-13/14 (commit `2b98962`) — what actually got built, and why it differs from §2

§2's plan ("jump `currentStep` straight to 4") turned out to be wrong once traced against the real
components, and §3's open question resolved to "yes, the side effects matter":

- `CampaignStep`/`AdSetStep` don't just hold display data — mounting them is what actually
  populates `CampaignContext` (`campaignData`/`adsetData`) with real Meta-fetched data via their
  own existing "restore last selection from cache" effects. Skipping past them would have meant
  `AdCreativeStep`/`BulkAdCreation` (which read from `CampaignContext`, not the wizard's local
  `formData` — confirmed by grep, `formData` is essentially unused downstream) landing on Creative
  with no real account/campaign/ad set behind it.
- **Real fix:** seed the exact `lastSelectedAdAccountId` / `lastSelectedCampaignId_*` /
  `lastSelectedAdSetId_*` localStorage keys those steps already read for their own "restore last
  used" behavior, let each step mount and run its existing logic, and auto-advance `currentStep`
  the instant each one resolves to the intended target. Button renamed **"Launch Own Ad"** in the
  UI (kept "Quick Ad" as the internal/doc name) — a tooltip alone wasn't enough to distinguish it
  from the other three "Quick *" buttons already on the same row.

**Pre-push review (2 cheap-tier agents: code-audit + joel-perspective) caught a real BLOCKING bug
before push:** `CampaignStep`/`AdSetStep` gate their own cache-restore effect behind a local `mode`
state that defaults to `'new'` and only ever flips to `'existing'` on a manual click — the
auto-advance would have silently stalled on a blank "Create New Campaign" form on every single
real use (the one and only case Quick Ad exists for: an ad row always implies an existing
campaign/ad set). Fixed with a `forceExistingMode` prop. Also fixed: a HIGH (AdAccountStep
silently falls back to the first account in the list if the seeded id isn't found, no visible
error — added a fast-fail check in the auto-advance watcher instead of waiting out the full
timeout), a MEDIUM (a manual Next/Back click could race the auto-advance chain — manual navigation
now always stops Quick Ad first), and joel-perspective's P0 (no confirmation anywhere of which
account/campaign/ad set it actually landed on — added a persistent breadcrumb banner). Re-audited
after fixes to confirm each one actually held, not just assumed fixed — caught and reverted my own
attempted "cleanup" of a cosmetic dev-only lint issue that would have silently broken the real
stall-timeout warning in production (a stale-closure bug), since the correctness cost wasn't worth
the cosmetic gain.

**Live-verified 2026-09-14, not just reviewed:** logged into the Ad Builder myself (Chrome Mini
browser), clicked "Launch Own Ad" on a real ad row in the RHO 4 - Commercial (New CAPI) account,
and watched it auto-advance Ad Account → Campaign → Ad Set → Creative in ~3 seconds with zero
manual clicks, correctly forcing "Use Existing Campaign"/"Use Existing Ad Set" mode at each step,
landing on the free-text Creative form with the ad set's name pre-filled and the persistent
breadcrumb banner reading exactly: *"Quick Ad loaded: RHO 4 - Commercial (New CAPI) → RHO v2 |
CBO | LEADS | AUTO DEALERSHIP CAPI → RHO v2 - AUTO DEALERSHIP COMP REQ CTRL - CAPI."* Nothing was
submitted (no media uploaded, no ad created), so no cleanup was needed.
