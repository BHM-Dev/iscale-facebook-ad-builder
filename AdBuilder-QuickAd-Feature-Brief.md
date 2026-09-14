# Ad Builder — "Quick Ad" Feature Brief

Scoping only — not built yet. Written after live-comparing Birch and AdEspresso's creative-intake
flows (2026-09-13) against Joel's actual complaint: he has to follow a template to get creative
into the ad launcher.

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
