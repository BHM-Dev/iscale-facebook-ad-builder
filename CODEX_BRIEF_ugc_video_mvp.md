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

**Confirmed via Phase 0 bakeoff (2026-07-30/31) — these replace the earlier placeholders:**

| Need | Confirmed model | Notes |
|---|---|---|
| Talking-head hook | `kling/ai-avatar-standard` (`-pro` for higher quality) | Requires `image_url` + `audio_url` + `prompt` — **no built-in TTS, no text-in mode.** Prompt controls delivery tone only, NOT wardrobe/appearance (docs' own example ships `prompt: ""`). $0.04/sec, up to 15s, 720p. Takes 300-355s to generate — longer than a naive 300s timeout, budget 6+ min per clip. |
| B-roll clips | `kling-3.0/video` (NOT `kling-3.0` — exact string matters) | `input: {prompt, aspect_ratio, duration, mode, multi_shots, sound}` — all fields nested under `input`, `duration` is a string. 9:16 supported, 3-15s. ~$0.07-0.09/sec without audio. |
| Voiceover | ~~kie.ai native audio~~ **TTS required as separate call** — used `google/gemini-3-1-flash-tts` in Phase 0 | **Recommend switching to `elevenlabs/text-to-speech-turbo-2-5`** (also on kie.ai) for Phase 1 — Arcads' own voice quality is closer to ElevenLabs than Gemini TTS, and it's a same-vendor swap, not a new integration. Gemini TTS enum fields (`voice_name`, `style`, `accent`, `pace`) are strict — see confirmed enums below if sticking with Gemini. |
| Presenter identity/wardrobe | **Not a video-model input.** Controlled entirely by the source `image_url` fed to the avatar model. | See "Actor/Casting" section below — this is the real gap vs. Arcads, not raw video quality. |
| Final assembly | backend ffmpeg/moviepy service — **still not built** | Required for: continuous voice-over during B-roll cuts, styled/editable captions, music bed, end-card CTA. See "Assembly Requirements" below. |

**Confirmed Gemini TTS enums** (if not switching to ElevenLabs): `voice_name` — Achernar, Achird, Algenib, Algieba, Alnilam, Aoede, Autonoe, Callirrhoe, Charon, Despina, Enceladus, Erinome, Fenrir, Gacrux, Iapetus, Kore, Laomedeia, Leda, Orus, Puck, Pulcherrima, Rasalgethi, Sadachbia, Sadaltager, Schedar, Sulafat, Umbriel, Vindemiatrix, Zephyr, Zubenelgenubi. `style` — Vocal Smile, Newscaster, Whisper, Empathetic, Promo/Hype, Deadpan. `accent` — Neutral, American (Gen), American (Valley), American (South), British (RP), British (Brixton), Transatlantic, Australian. `pace` — Natural, Rapid Fire, The Drift, Staccato.

### Actor/Casting — RESOLVED (2026-07-31 follow-up testing)

Joel's feedback after watching the Phase 0 clips: hard to control the actor's outfit/setting, and garbled AI text artifacts appeared in the videos. Both are now solved with confirmed, tested fixes — no specialist avatar vendor needed:

**1. Identity consistency across talking-head AND B-roll — CONFIRMED WORKING.** `kling-3.0/video` supports `kling_elements`: define a named element with 2-4 reference image URLs of the same person, then reference it via `@element_name` in the B-roll prompt. Tested: generated a cast photo via `flux-2/pro-text-to-image`, a second angle via `flux-2/pro-image-to-image` (same face, different pose), fed both as one element into a `kling-3.0/video` driving scene — the resulting B-roll driver is clearly the same person as the cast photo and the separately-generated `kling/ai-avatar-standard` talking-head clip. This is the in-house equivalent of Arcads'/HeyGen's "consistent character" feature, at kie.ai's raw per-second pricing.

**2. Garbled AI text artifacts — ROOT CAUSE FOUND, CONFIRMED FIXED.** This is NOT an image-generation problem — a clean, artifact-free cast photo (verified by direct visual inspection) still came out with garbled text on the shirt after `kling/ai-avatar-standard` animated it. The hallucination is introduced by the **avatar video model itself** at generation time. Tested and ruled out: switching to `kling/ai-avatar-pro` did NOT fix it (arguably worse). **The actual fix: put explicit "no text, no writing, no logo, no pattern" language directly in the avatar generation `prompt` field**, not just the source photo's prompt — this produced a completely clean result on the cheaper **standard** tier. No pro-tier upgrade needed for this specific problem.

**Revised recommendation:** build the cast library via kie.ai's own image models (`flux-2/pro-text-to-image` for the base photo, `flux-2/pro-image-to-image` for angle/wardrobe variants of the same identity) — no real-photo sourcing or rights-clearance process needed after all, since the identity-consistency and artifact problems both have confirmed kie.ai-native fixes. Real-photo sourcing remains a fallback if synthetic cast quality proves insufficient at scale, but is no longer the required next step.

### Arcads.ai feature comparison (2026-07-31)

| Arcads feature | kie.ai path | Status |
|---|---|---|
| AI Avatar talking (seconds-based) | `kling/ai-avatar-standard`/`-pro` | Built, tested in Phase 0 |
| AI video clips (B-roll) | `kling-3.0/video` | Built, tested in Phase 0 |
| ElevenLabs voices | `elevenlabs/text-to-speech-turbo-2-5` etc., same kie.ai account | Available, not yet swapped in (still on Gemini TTS) |
| Natural AI Actors (curated library) | Build our own via `flux-2/pro-text-to-image` + `kling_elements` for cross-shot consistency | **Resolved** — see Actor/Casting above, confirmed working 2026-07-31 |
| Custom Actors: clone your own actor | `kling_elements` with a synthetic or real photo works identically | Resolved — no vendor dependency |
| AI Avatar Reactions | No dedicated kie.ai product | Approximate via targeted avatar prompts if needed later |
| Remove background + AI captions | No confirmed kie.ai bg-removal model; captions not burned in by any model | Captions should be rendered by us (see Assembly Requirements) — full control, since we own the script text (zero ASR/typo risk) |
| Workflows: automate full pipeline | N/A | This is what Phase 1 of this brief builds |

### Assembly Requirements (new — from Joel's post-bakeoff feedback)

None of kie.ai's models do these; all require the `video_assembly_service` (ffmpeg/moviepy) already flagged in §5:

1. **Continuous voice-over through B-roll cuts.** Generate the full narration as ONE TTS file before calling any video model. Keep that single audio file as the master track for the whole assembled clip — video track cuts from talking-head → B-roll, audio track never cuts. B-roll must be generated muted (`sound: false`, already the default).
2. **Captions with real styling control (font, color, no typos).** Render captions ourselves from the exact TTS script text we already control — no ASR needed, no spelling risk, full control over styling since we own the renderer. Do not rely on any model's burned-in captions.
3. **Music bed.** Mix a stock/generated track under the narration in the assembly step — not a video-model capability.
4. **End-card CTA ("Call Now" etc.) in the final ~5 seconds.** Reuse the existing `text_overlay_service.py` pattern from image ads — a static/animated overlay applied to the final segment, not a new capability.

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

### DONE: Phase 0 Provider Bakeoff (2026-07-30/31)

Standalone script `backend/scripts/video_bakeoff_phase0.py` (never touched app code/models/migrations — see `CODEX_BRIEF_video_bakeoff_phase0.md` for full build history). 6 clips generated: 3 talking-head (`kling/ai-avatar-standard`) + 3 B-roll (`kling-3.0/video`), all 3 niches, delivered to Steve + posted to Joel in #media-buying.

**Joel's review verdict (first pass):** raw video quality (lip-sync, motion) was acceptable enough to keep going, but flagged real gaps: no control over actor wardrobe/setting, no voice continuity across the B-roll cut, no caption control, no music, no CTA card, and visible AI-artifact garbling on the actor. See "Actor/Casting", "Arcads.ai feature comparison", and "Assembly Requirements" above — all of that feedback has been triaged and folded into this spec.

**Updated decision, given the verdict:** not a clean "yes/no" on kie.ai — it's "yes, keep building on kie.ai, but the gaps are in casting and the assembly layer, not the raw generation models." Original three-way decision tree below is now moot (kie.ai wasn't broadly weak, and B-roll/talking-head weren't split — feedback was about the workflow layer around both):

```text
Superseded — kept for history:
If kie.ai talking-head quality is acceptable: Build hybrid UGC flow on kie.ai.
If kie.ai B-roll is good but talking-head is weak: Use kie.ai for B-roll + specialist avatar provider.
If kie.ai video quality is broadly weak: Pause in-app video build, integrate a dedicated UGC vendor.
```

**Recommended next test before Phase 1 build starts:** re-run a small batch (2-3 clips) with (a) a real, rights-cleared presenter photo instead of a Flux-generated one, and (b) ElevenLabs voice instead of Gemini TTS. Both are cheap, no-new-integration swaps in the existing script. If that closes the perceived gap to Arcads-level quality, Phase 1 scope stays as originally sized (UI + provider abstraction + assembly service). If it doesn't, that's new information before committing to the assembly-layer build.

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

- [x] **`KIE_AI_API_KEY` video access** — confirmed. Key is scoped to "All Models," no plan upgrade needed.
- [x] **Model names and job API shape** — confirmed live against docs.kie.ai (see Provider Decision Logic table above). Do not re-derive from memory — kie.ai's docs are the source of truth and the exact model strings matter (`kling-3.0/video` not `kling-3.0`, `kling/ai-avatar-standard` not a guessed variant).
- [x] **Cost per video** — confirmed: talking-head ~$0.60/clip (15s), B-roll ~$0.56-0.72/clip (8s). Full Phase 0 batch cost ~$5.70 in practice (some of that was debugging churn, not steady-state cost).
- [ ] Confirm whether existing R2 upload helper supports MP4 — still open, Phase 0 stored clips locally, never touched R2
- [ ] Confirm whether existing Generated Ads gallery can display video cards cleanly — still open
- [ ] **New**: source 1-3 real, rights-cleared presenter photos (stock license or quick photoshoot) — blocks the recommended next validation test and, if that test succeeds, blocks Phase 1's actor/casting approach
- [ ] **New**: decide Gemini TTS vs. ElevenLabs for Phase 1 default voice — recommend ElevenLabs pending a quick side-by-side cost/quality check

### Notes From Research

Dedicated UGC ad tools compete on workflow, not only raw generation:

- MakeUGC emphasizes script → actor/avatar → captions/music/B-roll/trims.
- Predis.ai advertises product-link/image ingestion, scripts, talking avatars, voiceover, captions, B-roll, and browser editing.
- AdCreative.ai positions AI video around ad-ready output and UGC/avatar flows.
- kie.ai appears useful as a multi-model generation API, including modern video models, but it should be treated as the model layer rather than the full product layer.

Primary practical takeaway: build Ad Builder's commercial-insurance UGC workflow around Joel's actual niches and performance context, then plug in whichever provider produces good enough raw video.
