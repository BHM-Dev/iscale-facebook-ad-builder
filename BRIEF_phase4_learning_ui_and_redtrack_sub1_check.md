# Phase 4 — Learning UI (Codex)

## STATUS (2026-07-17): Phases 0–3 are DONE and live. This is now GO for Codex.

- **Phase 0** (RedTrack sub1 = live ad IDs): resolved.
- **Phases 1+2** (schema + push instrumentation + `url_tags` macros): shipped & production-verified.
- **Phase 3** (ad-level revenue/profit sync onto `generated_ads`): shipped & live (30-min job + `POST /redtrack/sync-ad-performance`).
- The **RedTrack sub1 check below is already completed** — kept for reference only; you do NOT need to run it.

**This is frontend-only work. Do not touch backend, migrations, or the four trigger files.** Hand the final `git push` to Claude Code.

### Actual `/generated-ads` response fields you get (shipped — use these exact names)
```json
{
  "id": "ga_...", "brand_id": "...", "image_url": "...", "headline": "...", "body": "...",
  "niche": "...", "ad_bundle_id": "...", "size_name": "Square 1080x1080", "created_at": "...",
  "fb_ad_id": "120...",        // present once pushed via instrumented path; else null
  "fb_adset_id": "120...",     // rollups only
  "fb_campaign_id": "120...",
  "fb_creative_id": "120...",
  "angle": "rate_shock",       // NOTE: field is `angle` (no `angle_tag` — use `ad.angle` and fall back to '—')
  "source_ad_id": "...",       // remix provenance, may be null
  "profile_id": "...",
  "revenue": 210.00,           // null until Phase 3 sync matches this ad's fb_ad_id in RedTrack
  "profit": 64.77,             // null until matched
  "last_synced_at": "2026-07-17T..."  // null until matched
}
```

### CRITICAL caveat — expect blank data at first
As of 2026-07-17, **0 of 67 existing generated ads have `fb_ad_id`** (they predate instrumentation), so `revenue`/`profit`/`angle`/`last_synced_at` are **null across the board right now**. The columns populate only as Joel/Abel push *new* ads through the instrumented paths and the 30-min sync matches them. Build every new UI element to degrade gracefully to an empty/"—" state, and make the "Top Angles by Profit" module render its "No tracked creative performance yet." empty state cleanly. Do NOT assume any row has revenue.

---

## Appendix (reference only — already completed)

Two findings that were resolved during Phases 1–3:

1. Ad Builder now sets RedTrack macros on the creative's `url_tags` (`sub1={{ad.id}}` / `sub2={{adset.id}}` / `sub3={{campaign.id}}`) — verified expanding in production. (It does NOT mutate the destination link.)
2. Generated Ads response now exposes `angle`, `revenue`, `profit`, and tracking fields (shape above).

## RedTrack sub1 Finding

### What the code does today

Push flows pass `websiteUrl` / `website_url` into creative creation:

- `frontend/src/lib/facebookApi.js` passes `creativeData.websiteUrl` to `/facebook/creatives`.
- `backend/app/services/facebook_service.py` reads `website_url` and puts it into Meta creative `object_story_spec.link_data.link`.
- For standard link ads, the URL is used directly as both the link and CTA link.

There is no code path that appends:

```text
sub1={{ad.id}}
sub2={{adset.id}}
sub3={{campaign.id}}
```

or any equivalent RedTrack macro.

### What that means

If RedTrack `sub1` is populated in production, it is coming from one of these places:

- Joel's saved/entered `websiteUrl` already includes RedTrack macros.
- A RedTrack campaign/tracking template expands the parameters server-side.
- A Meta account/ad URL parameter template is configured outside Ad Builder.

It is **not enforced by Ad Builder today**.

### Current evidence for sub1

The app already expects ad-level RedTrack data:

- `backend/app/api/v1/redtrack.py` exposes `/redtrack/report/sub1`.
- That endpoint comment says `sub1={{ad.id}}` is already set in the tracking URL template.
- `frontend/src/pages/CampaignPerformance.jsx` fetches `/redtrack/report/sub1` for ad-level creative breakdown.

But the code audit cannot prove that live RedTrack rows actually contain `sub1`.

## Phase 0 Recommendation

Before Claude builds attribution hygiene, answer this with data:

```text
Does /api/v1/redtrack/report/sub1 return rows keyed by real Meta ad IDs for the same date range Joel is viewing?
```

If yes:

- Multiple creatives per ad set can be supported later via ad-level RedTrack joins.
- One creative per ad set is still cleaner for v1, but not mandatory forever.

If no:

- The v1 learning loop should require one creative per ad set.
- Or Claude must first add/enforce RedTrack URL parameters in every push path, which is materially larger and touches Meta creative payloads.

## Quick Verification For Claude

Use the live authenticated API or browser network console:

```text
GET /api/v1/redtrack/report/sub1?date_preset=last_7d
GET /api/v1/redtrack/report?date_preset=last_7d
```

Compare:

- `sub1` report `ad_count`
- `sub2` report `adset_count`
- Sample keys

Valid `sub1` keys should look like Meta ad IDs, not blank, `0`, ad set IDs, or generic labels.

If running from server shell, the raw RedTrack call pattern is:

```bash
curl "https://api.redtrack.io/report?api_key=$REDTRACK_API_KEY&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&group=sub1"
```

Do not paste the API key into chat or files.

## Codex Phase 4 UI Scope

Only start this after Claude has populated fields in `/generated-ads`:

Expected fields on each generated ad:

```json
{
  "angle": "structure_gap",
  "angle_tag": "structure_gap",
  "revenue": 210.00,
  "profit": 64.77,
  "fb_ad_id": "120...",
  "fb_adset_id": "120...",
  "fb_campaign_id": "120...",
  "last_synced_at": "2026-07-17T..."
}
```

### Generated Ads Page

File:

```text
frontend/src/pages/GeneratedAds.jsx
```

Current structure:

- Fetches `/generated-ads` into `ads`.
- Groups rows by `ad_bundle_id`.
- Grid cards show creative image, niche/date metadata, and size chips.
- List view columns today:
  - Ad Creative
  - Headline
  - Body
  - Created
  - Actions
- Bundles currently sort newest-first by `created_at`.

### UI Additions

Add a compact performance strip to grid cards:

```text
Tracked | Angle | Revenue | Profit
```

Behavior:

- `Tracked`: green if `fb_ad_id` exists and `last_synced_at` exists, amber if `fb_ad_id` exists but no sync, gray if not pushed/untracked.
- `Angle`: use `angle` or `angle_tag`; fallback `—`.
- `Revenue`: currency, fallback `—`.
- `Profit`: green if positive, red if negative, gray if missing.

Add list-view columns:

- Angle
- Revenue
- Profit
- Tracking

Keep columns compact; the list already has limited horizontal room.

### Sorting

Add a simple sort select near the existing search/filter controls:

```text
Newest
Profit high to low
Revenue high to low
Untracked first
```

Sort at the bundle level using the square/main ad:

```js
const mainAd = bundle.find(ad => ad.size_name?.includes('Square')) || bundle[0];
```

Do not build complex multi-column table sorting in v1.

### Top Angles By Profit

Add a small summary module above the gallery:

```text
Top Angles by Profit
```

Group by:

```js
ad.angle || ad.angle_tag || 'Untagged'
```

Metrics:

- total profit
- total revenue
- pushed count
- tracked count

Guardrails:

- Hide angles with no tracked revenue/profit.
- Show at most 5.
- If no data: "No tracked creative performance yet."

### Angle Picker Follow-up

After the gallery UI lands, reorder Quick Generate's Angle Picker by realized profit:

1. Angles with positive profit and enough tracked pushes.
2. Static default angles.
3. Untested angles.

Do not remove manual choice. Joel still needs exploration.

## Claude / Codex Handoff

Claude should own:

- Phase 0 live RedTrack `sub1` verification.
- Phases 1+2 migration and push instrumentation.
- Phase 3 performance sync.

Codex should own after that:

- Generated Ads learning columns.
- Top Angles by Profit UI.
- Angle Picker ordering once backend data exists.

## Risk

If we show profit columns before Claude closes the push attribution gaps, Joel will see mostly blank/untracked rows. That is useful as an audit state but not useful as a product feature. Prefer waiting until Phases 1+2 are live unless the goal is explicitly to expose tracking gaps.
