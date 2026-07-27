# Codex Brief: Commercial Insurance UGC Video MVP

## 1. Executive Summary

### Problem

Joel believes Ad Builder will need substantially stronger video tooling to compete with dedicated UGC ad platforms such as MakeUGC, Predis.ai, AdCreative.ai, Creatify, and Arcads-style workflows. He is directionally right: the hard part is not only generating video clips. The product value is the workflow around scripts, avatars, B-roll, captions, offer overlays, revisions, exports, and fast variation testing.

### Solution

Build a narrow **Commercial Insurance UGC Video MVP** inside Ad Builder. The MVP should create testable 9:16 vertical video ads for Meta using:

- Commercial insurance as the first vertical
- First niches: **barber shops**, **trucking**, **religious organizations**
- Output length: **20-30 seconds**
- Format: **9:16 vertical first**
- Style: **hybrid UGC**: talking-head hook when quality is acceptable, followed by B-roll/service scenes, captions, and CTA overlay
- First CTA language: **"Compare coverage options"** and **"Check your rate"**
- Provider approach: test kie.ai video generation first, but keep the abstraction open for a specialist avatar/lip-sync provider if kie.ai output is not good enough

### Economics

This is a performance test, not a full editor build. The goal is to learn whether AI-generated UGC-style video beats or complements current static image workflows for Joel's commercial insurance campaigns.

If the first videos are credible enough to test, the upside is high: faster creative volume, more native-looking Meta placements, and reusable commercial-insurance templates. If video quality is weak, the MVP still produces useful learning on what provider class is required before heavier investment.

## 2. Flow Diagrams

### MVP User Flow

```text
Video Ad page
  |
  v
Select account + brand + niche
  |
  v
Choose UGC format
  |
  v
Generate 3 scripts
  |
  v
Select / lightly edit script
  |
  v
Generate shot plan
  |
  v
Run model bakeoff / generate assets
  |
  v
Assemble 20-30 sec 9:16 video
  |
  v
Save to Generated Ads library
  |
  v
Phase 2: Push to Meta
```

### Provider Architecture

```text
Frontend Video Ad UI
  |
  v
POST /video-ads/scripts
  |
  v
POST /video-ads/shot-plan
  |
  v
POST /video-ads/generate
  |
  +--> VideoProvider interface
          |
          +--> KieVideoProvider (MVP)
          |
          +--> Future AvatarProvider / LipSyncProvider
  |
  v
Video assembly service
  |
  v
R2 storage + generated_ads record
```

## 3. Detailed Spec With Wireframes + Copy

### Route

Use the existing Video Ad page if it exists and is incomplete. Otherwise create:

```text
/video-ad
```

Do not build a landing page. The first screen should be the usable video generation workflow.

### Header Copy

```text
Video Ad
Commercial insurance UGC-style ads for Meta
```

### Controls

Use existing account switcher context. The page should respect the app-wide active Meta account.

Fields:

- Brand: dropdown
- Niche: segmented control or dropdown
  - Barber shops
  - Trucking
  - Religious organizations
- UGC format:
  - Business owner risk
  - Cost shock / rate check
  - Niche testimonial
- CTA:
  - Compare coverage options
  - Check your rate
- Length:
  - Locked to 20-30 seconds for MVP
- Format:
  - Locked to 9:16 vertical for MVP

### Wireframe

```text
┌─────────────────────────────────────────────────────────────┐
│ Video Ad                                      [Account menu] │
│ Commercial insurance UGC-style ads for Meta                 │
├─────────────────────────────────────────────────────────────┤
│ Brand              [Get Business Coverage v]                │
│ Niche              [Barber shops] [Trucking] [Religious]    │
│ Format             [Business owner risk v]                  │
│ CTA                [Compare coverage options v]             │
│                                                             │
│ [Generate Scripts]                                         │
├─────────────────────────────────────────────────────────────┤
│ Script Options                                              │
│ ○ Script 1                                                  │
│ ○ Script 2                                                  │
│ ○ Script 3                                                  │
│                                                             │
│ [Generate Shot Plan]                                       │
├─────────────────────────────────────────────────────────────┤
│ Shot Plan                                                   │
│ 0-3s     Talking-head hook                                  │
│ 3-9s     Niche risk B-roll                                  │
│ 9-16s    Coverage/problem explanation                       │
│ 16-24s   Proof / reassurance                                │
│ 24-30s   CTA                                                │
│                                                             │
│ [Generate Video]                                           │
├─────────────────────────────────────────────────────────────┤
│ Preview                                                     │
│ [9:16 video player]       [Save to Library]                 │
└─────────────────────────────────────────────────────────────┘
```

### On-Screen Copy Rules

Keep copy plain and compliance-safe:

- Do not guarantee savings
- Do not imply everyone qualifies
- Do not say the business is uninsured unless phrased hypothetically
- Avoid "cheap" as the main promise
- Use "coverage options," "business insurance," "general liability," and niche-specific risk language

## 4. Routing / Decision Logic Tables

### Niche Prompt Inputs

| Niche | Risk framing | B-roll scenes | Proof angle |
|---|---|---|---|
| Barber shops | Slip/fall, equipment damage, client injury, lease/vendor requirements | barber chair, tools, storefront, stylist cleaning station, customer waiting area | "A small incident can become expensive fast." |
| Trucking | Liability, cargo, downtime, contract requirements | truck yard, driver checking cab, loading area, road shot, paperwork | "One claim or lapse can put the route at risk." |
| Religious organizations | Property, events, volunteers, gatherings | church exterior, fellowship hall, volunteers setting chairs, community event setup | "Events and facilities create risks many teams overlook." |

### UGC Format Templates

| Format | Hook style | Body structure | CTA |
|---|---|---|---|
| Business owner risk | "If you run a [niche], check this before your next busy day." | overlooked risk → consequence → coverage reminder | Compare coverage options |
| Cost shock / rate check | "I didn't realize [niche] insurance could vary this much." | rate variation → why comparing matters → no-pressure check | Check your rate |
| Niche testimonial | "We thought we were covered until we looked closer." | scenario → gap/risk → coverage option → CTA | Compare coverage options |

### Provider Decision Logic

| Need | MVP path | Fallback |
|---|---|---|
| Talking-head hook | kie.ai model with audio/lip-sync support | Use generated still/avatar + voiceover + captions |
| B-roll clips | kie.ai text/image-to-video | Stock-like generated scenes with no identifiable brands |
| Voiceover | kie.ai native audio if available | Browser/player muted version with captions, or add specialist TTS later |
| Final assembly | backend ffmpeg/moviepy service | Store separate clips + shot plan if assembly fails |

## 5. Integration Specs

### Backend

Create a new router:

```text
backend/app/api/v1/video_ads.py
```

Endpoints:

```text
POST /api/v1/video-ads/scripts
POST /api/v1/video-ads/shot-plan
POST /api/v1/video-ads/generate
GET  /api/v1/video-ads/jobs/{job_id}
```

Keep generation async. kie.ai video tasks may take longer than image generation.

### Data Model

Prefer adding video fields to existing generated ad storage only if already supported. If a migration is needed, follow Ad Builder migration rules:

- single Alembic head
- `down_revision` points to current head
- `op.create_table()` must have `has_table()` guard
- use `ADD COLUMN IF NOT EXISTS` for new columns

Candidate fields:

```text
generated_ads.media_type = "video"
generated_ads.video_url
generated_ads.thumbnail_url
generated_ads.video_script
generated_ads.shot_plan
generated_ads.provider
generated_ads.provider_job_id
generated_ads.duration_seconds
generated_ads.aspect_ratio
```

If these fields do not exist, consider a separate `generated_videos` table for MVP to reduce risk.

### Storage

Use existing R2 storage path if enabled. Generated videos must store durable URLs, not temporary provider URLs.

Suggested R2 path:

```text
generated-videos/{date}/{uuid}.mp4
generated-videos/{date}/{uuid}.jpg
```

### Provider Abstraction

Do not call kie.ai directly from the route. Add a service abstraction:

```text
backend/app/services/video_generation_service.py
```

Interface:

```python
class VideoGenerationService:
    def create_video_task(self, prompt: str, *, aspect_ratio: str, duration: int, image_url: str | None = None) -> dict:
        ...

    def get_video_task(self, task_id: str) -> dict:
        ...
```

The abstraction must allow swapping to a specialist avatar/lip-sync provider later.

## 6. Tracking & Analytics Spec

Track MVP events from day 1:

| Event | Properties |
|---|---|
| `video_script_generate_clicked` | account_id, brand_id, niche, format, cta |
| `video_script_selected` | script_index, niche, format |
| `video_shot_plan_generated` | shot_count, has_talking_head |
| `video_generation_started` | provider, model, duration, aspect_ratio |
| `video_generation_failed` | provider, error_code, stage |
| `video_generation_completed` | provider, duration_seconds, cost_estimate_if_available |
| `video_saved_to_library` | generated_video_id, niche, format |

If the app does not have a central telemetry endpoint, log these in the same style as adjacent generation workflows and defer durable analytics to Phase 2.

## 7. Build Priority / Phased Rollout

### Ready For Review: Phase 0 Provider Bakeoff

Before building the full UI, create a thin backend/provider test script or admin-only endpoint that generates 6-10 test assets:

- 3 niches × 2 formats minimum
- 9:16
- 20-30 sec target, or model-limited clip segments if the provider caps duration
- include at least one talking-head/hybrid attempt

Steven/Joel visually review:

- Does the person look believable?
- Is lip sync acceptable?
- Does commercial-insurance context read correctly?
- Is the first 3 seconds strong enough?
- Are captions/overlays needed to make it usable?

Decision after bakeoff:

```text
If kie.ai talking-head quality is acceptable:
  Build hybrid UGC flow on kie.ai.
If kie.ai B-roll is good but talking-head is weak:
  Use kie.ai for B-roll and add specialist avatar/lip-sync provider.
If kie.ai video quality is broadly weak:
  Pause in-app video build and integrate a dedicated UGC vendor first.
```

### Ready For Review: Phase 1 MVP

- UI for commercial insurance video generation
- 3 niches
- 3 UGC formats
- 3 script options
- shot plan preview
- async video generation
- save video to library
- no push-to-Meta yet

### Phase 2 Directional

- Push video ads to Meta
- Use winning ads as source prompts
- Add avatar selector
- Add caption editor
- Add voice selector
- Add timeline-level edits
- Add batch variations
- Add performance columns for video creatives

## 8. Open Questions & Dependencies

### Confirmed Decisions

- First vertical: commercial insurance
- First niches: barber shops, trucking, religious organizations
- Style: hybrid UGC
- Length: 20-30 seconds
- Format: 9:16 vertical first
- CTA language: "Compare coverage options" / "Check your rate"
- kie.ai credits can be used for provider testing

### Dependencies

- Confirm live `KIE_AI_API_KEY` supports video endpoints/models, not only current Flux Kontext image workflow
- Confirm model names and job API shape from current kie.ai docs before coding
- Confirm expected cost per video before high-volume generation
- Confirm whether existing R2 upload helper supports MP4
- Confirm whether existing Generated Ads gallery can display video cards cleanly

### Notes From Research

Dedicated UGC ad tools compete on workflow, not only raw generation:

- MakeUGC emphasizes script → actor/avatar → captions/music/B-roll/trims.
- Predis.ai advertises product-link/image ingestion, scripts, talking avatars, voiceover, captions, B-roll, and browser editing.
- AdCreative.ai positions AI video around ad-ready output and UGC/avatar flows.
- kie.ai appears useful as a multi-model generation API, including modern video models, but it should be treated as the model layer rather than the full product layer.

Primary practical takeaway: build Ad Builder's commercial-insurance UGC workflow around Joel's actual niches and performance context, then plug in whichever provider produces good enough raw video.
