# Codex Brief: Phase 0 Video Provider Bakeoff (Standalone Script)

## Goal

Answer one question before any UGC video UI/backend gets built: **is kie.ai's video output good enough to build on?** Generate a small batch of test clips across niches/formats, produce a local review page, get a yes/no from Steve + Joel.

This is a throwaway research script, not a shipped feature. It must NOT touch any app code, models, migrations, or trigger files — it runs standalone and never needs to go through the pre-push review gate. Full context: `CODEX_BRIEF_ugc_video_mvp.md` §7 "Phase 0 Provider Bakeoff."

## Scope guardrail

- New file only: `backend/scripts/video_bakeoff_phase0.py` (+ a `backend/scripts/bakeoff_output/` gitignored output dir).
- Do not touch `models.py`, any router, `main.py`, `facebook_service.py`, or anything under `alembic/versions/`.
- No R2 upload — save clips locally and review from disk. Skips the "does R2 support mp4" dependency entirely for this phase.
- No DB writes. Standalone script only, run manually from a terminal.
- Because nothing here touches the never-push list, this script CAN be committed/pushed directly without the 2-agent review — but confirm with Steve before pushing since it's new repo surface.

## Model specs — confirmed live from docs.kie.ai and kie.ai/pricing (2026-07-30)

These were pulled directly from an authenticated-adjacent browse of `docs.kie.ai` and `kie.ai/pricing` — no more guessing needed on model names/schema. Two items are still open (marked below).

### Talking-head: Kling AI Avatar

Two tiers, identical request schema, both under `POST https://api.kie.ai/api/v1/jobs/createTask`:

```json
{
  "model": "kling/ai-avatar-standard",
  "callBackUrl": "https://your-domain.com/api/callback",
  "input": {
    "image_url": "<presenter still image, jpeg/png, max 10MB>",
    "audio_url": "<pre-generated audio, mp3/wav/aac/mp4/ogg, max 100MB, max 5 min>",
    "prompt": "<up to 5000 chars>"
  }
}
```

Swap `"model": "kling/ai-avatar-pro"` for the Pro tier (same schema, higher quality).

**Confirmed: `audio_url` is a required field, not optional.** There is no text-in/built-in-TTS mode on this endpoint — the script needs a real audio file uploaded somewhere kie.ai can fetch it before calling `createTask`. This resolves the old open question about text vs. audio input: **audio is required.**

- **TTS dependency:** kie.ai also sells TTS directly (`Gemini 2.5 Pro TTS` / `Gemini 3.1 Flash TTS`, ~$14 per million output tokens — trivially cheap for a few short scripts). Generate the hook line audio via one of those, upload it (kie.ai has a File Upload API at `docs.kie.ai` — use it, or R2/any public URL works since `audio_url` just needs to be fetchable), then feed the resulting URL into the avatar call. This is a second kie.ai call before the video call, not a separate vendor.
- **Pricing (confirmed from kie.ai/pricing):** Kling AI Avatar Standard = **$0.04/sec, 720p, up to 15 seconds** (~8 credits/sec). A single 15-sec talking-head clip ≈ $0.60. Pro tier pricing wasn't visible in the same pass — check the dashboard before running Pro clips, budget the same ballpark until confirmed.
- **Presenter image:** no source image exists yet. Generate one placeholder via the *existing* kie.ai `flux-kontext-pro` image flow already working in this repo (see image generation patterns in `backend/app/services/`), neutral prompt like "professional adult in business casual attire, friendly expression, plain background, portrait orientation, facing camera." Reuse one placeholder image across all talking-head clips in this batch — Phase 0 is testing lip-sync/voice quality, not casting.

### B-roll: Kling 3.0 (use this instead of Veo3 — same vendor, pricing already confirmed)

```json
{
  "model": "kling-3.0",
  "callBackUrl": "https://your-domain.com/api/callback",
  "input": {
    "prompt": "<scene description, 9:16>",
    "aspect_ratio": "9:16",
    "duration": 8
  }
}
```

Confirmed via docs: 9:16 supported, 3-15 sec range. **Pricing (confirmed):** without audio at 720p = **$0.09/sec** (14 credits/sec listed, effectively ~$0.07-0.09/sec across resolutions) — an 8-sec 720p B-roll clip ≈ $0.56-0.72. Skip the "with audio" variant for B-roll in Phase 0 (talking-head clips carry the voice; B-roll doesn't need dialogue) to save ~30% per clip. If `kling-3.0` behaves oddly, `kling 3.0 turbo` is the same family at similar 720p pricing ($0.09/sec image-to-video or text-to-video) and is a safe fallback — no need to test Veo3 for Phase 0, it adds a second model family to debug for no clear benefit over Kling here.

### Resolved (confirmed 2026-07-30, logged into kie.ai dashboard directly)

1. **`KIE_AI_API_KEY` video access — CONFIRMED.** The account's one API key ("Default", created 2026-04-13) is scoped to **"All Models"** — no allow-list restriction. It will work against `kling/ai-avatar-standard`, `kling/ai-avatar-pro`, and `kling-3.0` without any account/plan changes. Still worth a cheap 1-clip smoke test as the first `--dry-run` call, but this is not expected to be a blocker.
2. **Credit balance — CONFIRMED.** 4,698 credits on the account as of 2026-07-30. That's roughly 10-20x the estimated Phase 0 batch cost below — plenty of headroom, no top-up needed before running.
3. **Where the key lives.** Still true: there is no `.env.local` in this repo checkout on Steve's Mac — the key lives on the VPS. Either (a) Steve/Golden hand you the value to drop in a local `.env.local` (gitignored, never commit it), or (b) run the script inside the VPS container via `docker exec` per the VPS pattern in `CLAUDE.md`. Ask Steve directly.

**Estimated total cost for the full Phase 0 batch:** 3 talking-head clips (~15s Standard tier) ≈ $1.80, 3 B-roll clips (~8s Kling 3.0, no audio) ≈ $1.70-2.16, plus TTS for 3 short scripts (~$0.05). **Total ≈ $3.60-4** — well within the 4,698-credit balance. Print this estimate in `--dry-run` before spending anything anyway, as a sanity check.

## What to build

### `backend/scripts/video_bakeoff_phase0.py`

A single CLI script, no app imports required (standalone `requests`-based script, reuse nothing from `video_generation_service` since that doesn't exist yet).

```bash
python video_bakeoff_phase0.py --dry-run     # prints planned calls + cost estimate, makes no API calls
python video_bakeoff_phase0.py --yes         # actually runs the batch
```

**Test matrix (6-10 clips, per the source brief):**

| Niche | Format | Clip type |
|---|---|---|
| Barber shops | Business owner risk | talking-head hook |
| Barber shops | Cost shock / rate check | B-roll only |
| Trucking | Business owner risk | talking-head hook |
| Trucking | Niche testimonial | B-roll only |
| Religious organizations | Business owner risk | talking-head hook |
| Religious organizations | Niche testimonial | B-roll only |

(3 niches × 2 formats = 6 minimum; if credits allow, add 2 more talking-head variants for the niches that skipped it above — 8 total is ideal per the source brief's "6-10" range.)

**Prompts** — pull directly from `CODEX_BRIEF_ugc_video_mvp.md` §4 tables (niche risk framing, B-roll scenes, proof angle, hook style per format). Do not invent new copy — reuse exactly what's already been decided so the compliance-safe language rules in §3 are respected. Hardcode these as a Python dict at the top of the script (niche → risk framing / B-roll scenes / proof angle; format → hook style / body structure / CTA).

**Talking-head clips:**
- Model: `kling/ai-avatar-standard` (exact schema above).
- Step 1: generate the presenter placeholder image once via `flux-kontext-pro` (reuse for all talking-head clips).
- Step 2: generate the hook-line audio via kie.ai TTS (`Gemini 3.1 Flash TTS` — cheapest tier), upload/host the resulting audio file somewhere `audio_url` can fetch it.
- Step 3: `createTask` with `model: "kling/ai-avatar-standard"`, the placeholder `image_url`, the TTS `audio_url`, and `prompt` describing tone/delivery (e.g. "speaking directly to camera, serious but approachable tone").
- Target 15 sec (the tier's cap) — don't try to force 20-30 sec in Phase 0, that's a Phase 1 assembly problem.

**B-roll clips:**
- Model: `kling-3.0`, `input: {prompt, aspect_ratio: "9:16", duration: 8}`, no audio.
- Prompt built from the B-roll scene list + proof angle in the niche table, text-to-video, 9:16, 8 sec.

**Flow per clip:**
1. `POST https://api.kie.ai/api/v1/jobs/createTask` (Bearer auth, `KIE_AI_API_KEY`) with the model + input for that clip (talking-head clips need the TTS sub-call first, see above).
2. Poll `GET /api/v1/jobs/recordInfo?taskId=...` every ~5s until `state` is `success` or `fail`. Timeout after 5 minutes per clip — log and continue to the next clip rather than hanging the whole batch.
3. On success, download `resultUrls[0]` to `backend/scripts/bakeoff_output/{niche_slug}_{format_slug}_{clip_type}.mp4`.
4. Append a row to `backend/scripts/bakeoff_output/manifest.json`: `{niche, format, clip_type, model, prompt, task_id, result_url, status, error, credits_spent}`.

**On failure:** don't crash the batch — log the error (kie.ai's error message, not just the status code) and move to the next clip. Print a summary at the end: N succeeded, N failed, list of failures with reasons.

### Review artifact: `backend/scripts/bakeoff_output/review.html`

Generate this automatically at the end of the run (or via a `--build-review` flag that reads `manifest.json` and regenerates it without re-running generation). Single static HTML file, no server needed — open directly in a browser:

- One card per clip: niche + format + clip_type label, inline `<video controls>` pointing at the local mp4, and the exact prompt used underneath (so Steve/Joel can judge output against what was actually asked for).
- Below each video, print the 5 review questions from the source brief as plain text (not interactive — this is for eyeballing, not data entry):
  - Does the person look believable?
  - Is lip sync acceptable?
  - Does commercial-insurance context read correctly?
  - Is the first 3 seconds strong enough?
  - Are captions/overlays needed to make it usable?

## Decision gate (Steve + Joel, after watching the clips)

Per `CODEX_BRIEF_ugc_video_mvp.md` §7:

```
If kie.ai talking-head quality is acceptable → build hybrid UGC flow on kie.ai.
If kie.ai B-roll is good but talking-head is weak → use kie.ai for B-roll, add a specialist avatar/lip-sync provider for the hook.
If kie.ai video quality is broadly weak → pause in-app video build, evaluate a dedicated UGC vendor (MakeUGC, Predis.ai, Arcads-style) instead.
```

This script's only job is to produce the clips needed to make that call. Do not start on `video_generation_service.py`, the `/video-ads/*` routes, or any `VideoAds.jsx` UI work until this decision is made — that's Phase 1, sequenced behind P&L Tracker Phase 2 per `CLAUDE.md` "Still pending."

## Done when

- [ ] 6-8 clips generated and saved locally with a complete `manifest.json`
- [ ] `review.html` opens cleanly and plays all clips inline
- [ ] Total credits spent logged and reported to Steve
- [ ] Any unexpected auth/model errors documented in a short note back to Steve, even if the batch didn't fully complete (model access + credits are pre-confirmed, so any failure here is a real bug, not a known gap)

## Follow-up (2026-07-31): presenter image step needs a fallback

First two live `--yes` runs both failed at the same spot: `submit_flux_presenter_image()` — the `POST /api/v1/flux/kontext/generate` call returns a `taskId`, but `recordInfo` comes back `successFlag: 3, errorCode: 500, "internal error, please try again later."` every time (confirmed twice, ~40s apart). Credits were deducted anyway despite the failure (4698 → 4602 after run 1).

**Root cause confirmed kie.ai-side, not a script bug.** I reproduced the identical failure with a raw curl using the exact schema this same repo's `generated_ads.py` already has in production (`model: flux-kontext-pro`, `aspectRatio: "1:1"`, same prompt style) — same `errorCode: 500` on `flux-kontext-pro` specifically. So this isn't something wrong with `video_bakeoff_phase0.py`'s payload; the model is erroring out for this account right now.

**Fix: add a fallback presenter-image path using the OTHER proven-working kie.ai image model already in this codebase**, so Phase 0 isn't blocked on `flux-kontext-pro` recovering. `generated_ads.py`'s `_kie_generate_image()` (around line 600) uses a second, independently-proven-working path:

```
POST /api/v1/jobs/createTask
{
  "model": "flux-2/pro-text-to-image",
  "prompt": "...",
  "aspect_ratio": "9:16",      // NOTE: flat snake_case here, NOT camelCase like flux-kontext-pro
  "output_format": "png"
}
```
Poll via the generic `GET /api/v1/jobs/recordInfo?taskId=` (same endpoint the video clips already use — this model does NOT use the `/flux/kontext/record-info` endpoint).

**What to change in `submit_flux_presenter_image()`:**
1. Try `flux-kontext-pro` via `/flux/kontext/generate` first (current behavior), but with only 1 retry (not indefinite) — if `successFlag` comes back `2` or `3` (create_failed/generate_failed), don't immediately raise.
2. On failure, fall back to `flux-2/pro-text-to-image` via the generic `/jobs/createTask` + `/jobs/recordInfo` flow (same `create_task`/`poll_task` helpers already in this script — just a different `payload` shape: snake_case `aspect_ratio`/`output_format`, no `promptUpsampling`/`enableTranslation` fields).
3. Only raise if BOTH models fail. Log which model actually succeeded in the manifest (`presenter_model` field) so the review notes which path was used.
4. Keep `--presenter-image-url` as the manual override it already is — that still bypasses both generation attempts entirely.

Don't touch the B-roll (`kling-3.0/video`) or talking-head (`kling/ai-avatar-standard`) logic — those haven't been exercised yet since the batch never got past the shared presenter image step. Once this fallback is in, re-run `--yes` and see how far the batch gets; if `kling/ai-avatar-standard` or `kling-3.0/video` also 500, that's new information to report back, not something to silently retry around.
