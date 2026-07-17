# Ad Builder CAPI + Learning Loop Brief

## Executive Summary

Shaun's recommendation is directionally right: the Ad Builder should send conversion truth back to Meta and then learn which creative/niche/angle combinations produce profit. The build should not start with XGBoost, LightGBM, or CatBoost. Those models need a larger clean dataset than the app likely has today.

The right MVP path is:

1. Close attribution gaps so every pushed ad can be joined back to a local `GeneratedAd`.
2. Send server-side conversion events through Meta Conversions API, including offline events via a Meta dataset.
3. Build a clean creative-performance fact table/view.
4. Start optimization with a UCB/contextual bandit scoring layer.
5. Use winner/loser patterns to guide copy/image generation.

Economics: this makes the app move from "generate ads faster" to "generate the next best test based on observed profit." Joel should see fewer random tests, faster winner iteration, and clearer stop/scale decisions.

## Current-State Audit

### What Already Exists

Generated ads already store enough basic creative fields to be the nucleus of a learning table:

- `GeneratedAd.brand_id`, `product_id`, `template_id`, `image_url`, `headline`, `body`, `cta`, `prompt`, `ad_bundle_id`, `fb_ad_id`, `niche`, overlay fields in `backend/app/models.py:283`.
- `fb_ad_id` writeback route exists at `backend/app/api/v1/generated_ads.py:1112`.
- Batch Push writes the Meta ad ID back when `item.generatedAdId` exists in `frontend/src/components/BatchPushModal.jsx:260`.
- RedTrack revenue cache exists by ad set ID: `RedTrackCache.fb_adset_id`, `revenue`, `profit`, `roas`, `cpl`, `quality_rate` in `backend/app/models.py:568`.
- RedTrack service supports grouped report pulls by arbitrary sub fields, including ad-level grouping via `get_report_by_sub(..., group_field="sub1")`.

### Main Gaps

1. **Single-ad Push to Meta can lose the local join**
   - Generated Ads single push opens `PushToMetaModal` without passing `generatedAdId`: `frontend/src/pages/GeneratedAds.jsx:987`.
   - ImageAds result push also opens `PushToMetaModal` without local generated ad ID: `frontend/src/pages/ImageAds.jsx:2381`.
   - `PushToMetaModal` has `onSuccess`, but it does not receive/write `generatedAdId`; it only calls `onSuccess()` after push.
   - Symptom: an ad can exist in Meta but the local `generated_ads.fb_ad_id` remains null, so learning/iteration cannot attribute performance to the generated creative.

2. **Adset-level revenue exists; ad-level revenue is not yet productized**
   - Current dashboards use RedTrack grouped by `sub2` = Meta ad set ID.
   - RedTrack endpoint `/redtrack/report/sub1` says `sub1={{ad.id}}` is already set in the tracking URL template, but the cache table only stores adset-level rows.
   - Symptom: niche/adset profitability works, but creative-level profit attribution is incomplete.

3. **GeneratedAd metadata is close but not complete**
   - Existing: brand/product/template/copy/image/niche/overlay.
   - Missing or inconsistent for learning:
     - `angle_id` or `angle_tag`
     - `source_type` (`research`, `campaign_performance`, `copy_library`, `manual`, `angle_picker`)
     - `source_ad_id` / `source_fb_ad_id`
     - `fb_campaign_id`
     - `fb_adset_id`
     - `fb_creative_id`
     - `pushed_at`
     - `last_performance_synced_at`
   - Symptom: the system cannot reliably answer "Which angle/template/source created this profitable ad?"

4. **Meta CAPI is not present**
   - No service currently sends server-side conversion/offline events to Meta.
   - Current setup pulls performance from Meta/RedTrack but does not push RedTrack/offline truth back into Meta for optimization.

## Target Flow

```text
Generated concept
  -> GeneratedAd row
  -> Push to Meta
  -> write fb_ad_id + fb_adset_id + fb_campaign_id + fb_creative_id back locally
  -> RedTrack receives clicks/conversions with sub1=fb_ad_id, sub2=fb_adset_id
  -> app syncs ad/adset performance
  -> app sends conversion truth to Meta CAPI dataset
  -> learning layer scores niche x angle x template x copy pattern
  -> generator uses winners/losers to create next tests
```

## Phase 1 — Attribution Hygiene

This is the first thing Claude should build.

### Backend

Extend the generated ad Meta writeback endpoint to accept more fields:

```json
{
  "fb_ad_id": "120...",
  "fb_adset_id": "120...",
  "fb_campaign_id": "120...",
  "fb_creative_id": "120...",
  "pushed_at": "2026-07-17T..."
}
```

Recommended model additions to `GeneratedAd`:

```python
angle_id = Column(String, ForeignKey("creative_angles.id", ondelete="SET NULL"), nullable=True)
angle_tag = Column(String, nullable=True)
source_type = Column(String, nullable=True)       # research | campaign_performance | copy_library | manual | angle_picker
source_ad_id = Column(String, nullable=True)      # local scraped/generated/source record when available
source_fb_ad_id = Column(String, nullable=True)   # original Meta ad ID when iterating/remixing
fb_campaign_id = Column(String, nullable=True, index=True)
fb_adset_id = Column(String, nullable=True, index=True)
fb_creative_id = Column(String, nullable=True)
pushed_at = Column(DateTime(timezone=True), nullable=True)
last_performance_synced_at = Column(DateTime(timezone=True), nullable=True)
```

Migration rules:

- Use `ADD COLUMN IF NOT EXISTS`.
- Do not create a branched Alembic head.
- Run `python3 scripts/check_alembic_heads.py`.

### Frontend

Patch all push paths:

- `BatchPushModal`: already writes `fb_ad_id`; extend body to include adset/campaign/creative if available.
- `PushToMetaModal`: accept `generatedAdId`; after successful push, call the writeback endpoint.
- `GeneratedAds.jsx`: pass `generatedAdId={pushModal.ad.id}` into `PushToMetaModal`.
- `ImageAds.jsx`: when pushing directly from a just-generated result, ensure the generated ad row ID is available and passed into `PushToMetaModal`. If the image has not been saved yet, save first or block push until saved.
- `AdRemix.jsx`: direct `/facebook/push-to-meta` flow should either create/update a GeneratedAd record or write a separate launch record. Today it pushes but does not obviously write the Meta ID back to a local generated ad.

Done condition:

- Every successful Push to Meta produces a local row with `fb_ad_id`, `fb_adset_id`, and `fb_campaign_id`.
- No Meta ad launched from the app is invisible to the learning loop.

## Phase 2 — Meta CAPI / Offline Events

Use current Meta Conversions API, not deprecated Offline Conversions API language.

Required env vars:

```text
META_CAPI_ACCESS_TOKEN
META_CAPI_DATASET_ID
META_CAPI_TEST_EVENT_CODE
META_CAPI_API_VERSION
```

Backend service:

```text
backend/app/services/meta_capi_service.py
```

Endpoint candidates:

```text
POST /api/v1/meta-capi/events
POST /api/v1/meta-capi/test-event
GET  /api/v1/meta-capi/status
```

Event MVP:

- `Lead`: first-party lead submit or Meta lead event.
- `QualifiedLead`: RedTrack/aggregator accepted lead.
- `Purchase` or `CompleteRegistration`: only if that maps cleanly to paid/revenue-confirmed conversion.

Minimum event payload shape:

```json
{
  "event_name": "QualifiedLead",
  "event_time": 1784310000,
  "action_source": "system_generated",
  "event_id": "redtrack-conversion-id-or-dedupe-key",
  "user_data": {
    "em": ["sha256_email_if_available"],
    "ph": ["sha256_phone_if_available"],
    "client_ip_address": "if_available",
    "client_user_agent": "if_available",
    "fbc": "if_available",
    "fbp": "if_available"
  },
  "custom_data": {
    "currency": "USD",
    "value": 70.00,
    "content_name": "commercial_insurance",
    "ad_id": "120...",
    "adset_id": "120...",
    "campaign_id": "120..."
  }
}
```

Notes:

- Hash PII server-side with SHA-256 after trimming/lowercasing.
- Store event send attempts and responses in a `meta_capi_events` table for audit/retry.
- Use Meta test event code in staging/manual test.
- Do not put tokens in frontend code.

## Phase 3 — Learning Data Layer

Create one queryable backend surface, either as a SQL view or endpoint:

```text
GET /api/v1/learning/creative-performance?date_preset=last_30d
```

Join:

- `GeneratedAd.fb_ad_id` -> RedTrack ad-level `sub1` rows when available.
- fallback to `GeneratedAd.fb_adset_id` -> RedTrack adset-level `sub2` rows when ad-level missing.
- Meta ad insights by `fb_ad_id` for spend, impressions, clicks, CTR, leads.
- GeneratedAd metadata for niche, angle, source, template, prompt, copy.

Output row:

```json
{
  "generated_ad_id": "...",
  "fb_ad_id": "120...",
  "brand_id": "...",
  "niche": "Religious Organizations",
  "angle_tag": "structure_gap",
  "source_type": "research",
  "headline": "...",
  "body": "...",
  "spend": 145.23,
  "leads": 5,
  "revenue": 210.00,
  "profit": 64.77,
  "cpl": 29.05,
  "roas": 1.45,
  "confidence": "medium"
}
```

## Phase 4 — Optimization Model

Start with UCB/contextual bandit, not supervised ML.

Why:

- Joel has small, shifting datasets by niche.
- Bandits handle exploration vs. exploitation better for creative testing.
- XGBoost/LightGBM/CatBoost become useful later once there are hundreds/thousands of labeled creative outcomes.

Recommended MVP score:

```text
score = normalized_profit_rate + exploration_bonus

profit_rate = profit / max(spend, 1)
exploration_bonus = c * sqrt(log(total_tests + 1) / tests_for_group)
```

Group by:

- vertical
- niche
- angle_tag / angle_id
- template_id or style archetype
- source_type

UI recommendations:

- "Scale this angle"
- "Generate 3 more like this"
- "Keep testing: low confidence"
- "Stop repeating this hook"
- "Tracking gap: pushed ad has no RedTrack match"

## Phase 5 — Performance-Aware Generation

Update generation prompts to include:

- Top 3 winners by profit/ROAS in same niche.
- Top 3 losers with enough spend.
- Winning angle/template patterns.
- Explicit avoidance rules from losers.

Example instruction:

```text
Write a new commercial insurance ad for Religious Organizations.
Use the structure of winning examples, but do not copy wording.
Winners use structure-gap framing and direct risk language.
Avoid generic "save money" hooks; they spent $X with no qualified leads.
```

## UI Plan For Joel

1. **Campaign Performance**
   - Add a "Generate More Like This" action on profitable ad rows.
   - Show whether a row has local generated-ad lineage.

2. **Generated Ads**
   - Add performance badges once pushed:
     - spend
     - CPL
     - revenue
     - profit
     - confidence
   - Flag "Not tracked" when `fb_ad_id` or RedTrack match is missing.

3. **Image Ads / Quick Generate**
   - Angle Picker should show "Recommended" angles first based on UCB.
   - Keep manual angle selection available.

4. **Dashboard**
   - Add Creative Learning panel:
     - Top angles
     - Wasted angles
     - Tracking gaps
     - Recommended next tests

## Open Questions For Steve / Claude

1. Does RedTrack reliably receive `sub1={{ad.id}}` for all traffic today?
2. Does RedTrack have lead-level data or only aggregate reports via API?
3. Which event should Meta optimize toward first: `Lead`, `QualifiedLead`, or revenue-confirmed conversion?
4. Which Meta dataset/pixel should receive CAPI events?
5. Does BHM have sufficient hashed user data for CAPI match quality, or mostly click IDs/ad IDs?
6. Should CAPI events be sent from RedTrack conversions only, or from app-side lead events too?

## Claude Build Order

### Claude Task 1 — Attribution Hygiene

Fix local join gaps before CAPI.

Files likely touched:

- `backend/app/models.py`
- Alembic migration
- `backend/app/api/v1/generated_ads.py`
- `frontend/src/components/PushToMetaModal.jsx`
- `frontend/src/components/BatchPushModal.jsx`
- `frontend/src/pages/GeneratedAds.jsx`
- `frontend/src/pages/ImageAds.jsx`
- `frontend/src/pages/AdRemix.jsx`

Deliverable:

- Migration-safe metadata fields.
- Every push path writes Meta IDs back locally.
- No push to Meta succeeds without either linking to a generated ad or explicitly logging why it is unlinked.

### Claude Task 2 — RedTrack Ad-Level Cache

Add an ad-level cache using RedTrack `sub1`.

Files likely touched:

- `backend/app/models.py`
- Alembic migration
- `backend/app/services/redtrack_service.py`
- `backend/app/api/v1/redtrack.py`

Deliverable:

- `redtrack_ad_cache` keyed by `fb_ad_id`.
- Manual sync endpoint.
- Creative-performance endpoint joins `GeneratedAd.fb_ad_id` to RedTrack sub1.

### Claude Task 3 — Meta CAPI Spec/Service

Only after Tasks 1 and 2 are done.

Deliverable:

- CAPI service with test-event mode.
- Send/retry log table.
- No frontend secrets.
- Golden env var list.

## My Recommendation

Do **not** start with XGBoost/LightGBM/CatBoost.

Start with:

1. Attribution cleanup.
2. RedTrack ad-level cache.
3. CAPI event sender.
4. UCB/contextual bandit recommendation endpoint.

Once Joel has 60-90 days of clean creative-level data, revisit CatBoost or LightGBM as a ranking model.
