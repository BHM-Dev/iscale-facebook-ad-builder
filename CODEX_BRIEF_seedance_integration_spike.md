# Codex Brief — Seedance 2.0 spike: quality + motion-flexibility test

## Why

Two things converged: (1) Joel flagged a noticeable quality jump in ByteDance's Seedance 2.5 update, and (2) we've been fighting Kling's tendency to hallucinate fake on-screen text/CTA graphics by shrinking every shot to tight chest-up/interior-only framing — which kills the "show a person walking, driving, etc." flexibility the harness is supposed to support. Those two problems might have the same fix: a different model whose motion is anchored to a real reference clip instead of freely improvised from text.

Seedance 2.5 isn't API-accessible yet (Kie.ai lists it "coming soon"). **Seedance 2.0 is live now, on the same Kie.ai account/API key already configured** — no new vendor, no new billing setup. This spike is about proving whether Seedance 2.0 is a better fit before we invest more in patching Kling's framing.

## Model facts (verified live on kie.ai, 2026-08-02)

- Model IDs: `bytedance/seedance-2-fast` (cheaper/faster, use this for the spike) and `bytedance/seedance-2` (standard, higher quality/cost).
- Same job endpoints as everything else in the harness: `POST {JOBS_URL}/createTask`, `GET {JOBS_URL}/recordInfo` — `create_task`/`poll_task` in `video_finetuning_harness.py` should work unchanged.
- Input schema (differs from Kling — see mapping below):
  - `prompt` (string)
  - `reference_image_urls` (list — cast identity/consistency)
  - `reference_video_urls` (list, up to 3, combined ≤15s — **guides camera path/blocking/motion from a real clip instead of the model improvising**)
  - `reference_audio_urls` (list, up to 3, combined ≤15s)
  - `generate_audio` (bool — whether Seedance generates its own audio; set `false` since we supply our own TTS track)
  - `resolution` (`480p` | `720p`)
  - `aspect_ratio` (`9:16` for us)
  - `duration` (seconds)
- Pricing (credits/sec), per kie.ai's published tiers:
  - 480p: 9 credits/s (~$0.045/s) **with** a reference video input, 15.5 credits/s (~$0.0775/s) without
  - 720p: 20 credits/s (~$0.10/s) with reference video, 33 credits/s (~$0.165/s) without
  - For comparison, current Kling costs ~120 credits for a 15s talking-head clip (~8 credits/s) and ~112 credits for an 8s broll clip (~14 credits/s) — so Seedance at 480p-with-reference is in the same ballpark; 720p or no-reference is meaningfully pricier.

## Current integration points (read these before touching anything)

`backend/scripts/video_finetuning_harness.py`:
- `build_clip_plans()` (~line 494-535) — sets `model="kling/ai-avatar-standard"` for talking-head, `model="kling-3.0/video"` for broll. This is where a plan would get a Seedance model instead.
- `run_talking_head()` (~line 763) — builds Kling's payload shape: `input.image_url` (single string), `input.audio_url` (single string, from our TTS), `input.prompt`.
- `run_broll()` (~line 792) — builds Kling's payload shape: `input.prompt`, `aspect_ratio`, `duration`, `mode`, `multi_shots`, `sound`, and `kling_elements` (a list with `name`/`description`/`element_input_urls` for character consistency — Kling-specific, has no Seedance equivalent).
- `parse_result_urls()` — already generic (parses the job's `recordInfo` response), should work as-is for Seedance's response, but verify against a real response before assuming.
- `create_task`/`poll_task`/`JOBS_URL` — fully generic, no changes needed.

## Scope for this spike — do NOT do a full rebuild yet

1. Add a `provider` concept (simplest: branch on `plan.model.startswith("bytedance/seedance")` , or add an explicit `provider` field to `ClipPlan` if that's cleaner given the dataclass shape) so `run_talking_head`/`run_broll` can build the right payload shape per provider without disturbing the existing Kling path at all. Default behavior for every existing format stays on Kling — this is additive, not a replacement.
2. Add `run_talking_head_seedance()` and/or extend `run_talking_head()` with a provider branch, mapping our existing cast/TTS assets into Seedance's shape:
   - `reference_image_urls: [cast["photo_urls"][0]]`
   - `reference_audio_urls: [tts["url"]]`
   - `generate_audio: false`
   - `resolution: "480p"`, `aspect_ratio: "9:16"`, `duration: 15`
3. For the broll side, **first pass without a reference video** (simplest to test quickly) — same prompt content we already use for Kling broll, just on the Seedance payload shape, at 480p. Getting a reference-video-guided walking/driving clip working is the actual goal but depends on sourcing a real reference clip first (see Open question below) — don't block the initial quality/hallucination comparison on that.
4. Add a CLI way to pick the provider per test run without permanently changing any existing format's default — e.g. `--video-provider kling|seedance` flag that only affects which `run_*` function gets called, or a temporary one-off test format in the config. Whichever is less invasive to the existing dataclasses/flow is fine; use your judgment.

## The actual test to run (once wired up)

Direct side-by-side against a known baseline: regenerate `mapped_why_pay_more` (the one clip that already came back clean from Kling) through Seedance 2.0 Fast instead, same cast, same script/tone, at 480p, no reference video for this first pass. This gives a real quality comparison on identical creative content instead of comparing across different scripts.

Cost: 1 clip, 15s, 480p, no video-input tier = 15.5 credits/s × 15s ≈ 233 credits (~$1.16) if cast/TTS aren't reused, likely less since the existing `auto_insurance_cast_1` cast and cached TTS for this script should both be reusable — expect closer to the clip-only cost, roughly $0.60-0.80. Run a `--dry-run` first to confirm the actual estimate before spending, same as every other batch.

## Open question — reference video sourcing (not blocking the first test)

To actually use `reference_video_urls` for walking/driving motion guidance, we need short (≤15s combined), public-use reference clips of a person walking and a person getting into/driving a car. Options to raise with Steven once the basic Seedance payload is proven out: a small licensed stock clip purchase, or a quick self-shot phone reference (doesn't need to look good — it's motion guidance, not the final visual). Don't source anything yet; confirm the basic integration works first.

## Validation before push

- `python3 -m py_compile backend/scripts/video_finetuning_harness.py`
- `--dry-run` showing the new Seedance-routed clip plan with correct model ID and estimated cost
- Live single-clip test only after Steven/Claude sign off on the dry-run estimate (same spend-approval pattern as every prior live batch)
- `git diff --check`

No DB migration, no trigger files, no models.py — this is entirely within `backend/scripts/`. Normal push flow applies (Claude Code does the final push + review per repo protocol).
