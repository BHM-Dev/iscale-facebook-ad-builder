# Codex Brief: Video Fine-Tuning Harness (Phase 0.5)

## Context

`backend/scripts/video_bakeoff_phase0.py` proved the concept (talking-head + B-roll on kie.ai) but every test since has been one-off manual Python snippets run ad hoc. We now have three confirmed fixes that need to become the *default* behavior, not something re-derived by hand each time:

1. **Cast consistency across shots** — `kling-3.0/video`'s `kling_elements` (2-4 reference image URLs per named element, referenced via `@element_name` in the prompt) carries a photo identity into B-roll scenes. Confirmed working 2026-07-31.
2. **AI-text artifact fix** — `kling/ai-avatar-standard` hallucinates garbled text onto clothing unless the avatar generation `prompt` field itself explicitly says "no text, no writing, no logo, no pattern" (putting this only in the *photo* prompt is not enough — the video model reintroduces it). Confirmed fixed on the cheap standard tier; `-pro` tier did NOT fix it, so don't pay for pro to solve this.
3. **Correct model schemas** (already in `video_bakeoff_phase0.py`, carry forward): `kling-3.0/video` (not `kling-3.0`), fields nested under `input`, `duration` as a string; `kling/ai-avatar-standard`/`-pro` need `image_url` + `audio_url` + `prompt`, no text-in mode.

## Goal

Turn today's one-off scripts into a repeatable harness that can churn through **niche × wardrobe/cast variant × script/format** combinations automatically, producing a comparison grid — so fine-tuning prompts becomes "run the harness, look at the grid, adjust one prompt template, rerun" instead of hand-writing a new Python snippet per test.

**Scope guardrail — same as Phase 0:** standalone script only. Does not touch app code, routes, models, or migrations. No R2 upload. No DB writes. Lives at `backend/scripts/video_finetuning_harness.py`, new file, does not modify `video_bakeoff_phase0.py` (that script stays as the historical Phase 0 record — see its own `CODEX_BRIEF_video_bakeoff_phase0.md` for full context).

## What to build

### 1. Cast library generation (new capability, not in Phase 0 script)

For each *cast identity* requested:
- Generate a base photo: `flux-2/pro-text-to-image` (`POST /api/v1/jobs/createTask`, `input: {prompt, aspect_ratio: "9:16", resolution: "1K", nsfw_checker: false}`). Prompt must include the niche-appropriate wardrobe/setting description.
- Generate 1-2 angle/wardrobe variants of the *same* identity: `flux-2/pro-image-to-image` (`input: {input_urls: [base_photo_url], prompt, aspect_ratio, resolution, nsfw_checker}`) — `input_urls` is the identity-preserving edit mechanism, confirmed working 2026-07-31 (produced a genuinely consistent second angle in testing).
- Store all cast photos + their URLs in the manifest so a cast identity can be reused across multiple niche/script combinations without regenerating (cast generation costs real credits — don't regenerate the same identity twice in one run).

### 2. Talking-head generation — bake in the artifact fix

```python
avatar_prompt = (
    f"{tone_and_delivery_instructions} "
    "Plain solid-color outfit with absolutely no text, no writing, no letters, "
    "no logo, no graphic, no pattern printed on it. No on-screen captions, no watermark."
)
```
This "no text/logo/pattern" clause is **mandatory** in every avatar-model prompt, not optional — it's the confirmed fix, not a nice-to-have. Use `kling/ai-avatar-standard` by default (pro tier confirmed NOT to fix the artifact issue, so don't default to it and don't pay the 2x credit cost for this reason).

### 3. B-roll generation with cast consistency

Use `kling-3.0/video` with `kling_elements` referencing the cast identity's 2-3 stored photo URLs:
```python
{
  "model": "kling-3.0/video",
  "input": {
    "prompt": f"... @{element_name} is {action_description} ...",
    "aspect_ratio": "9:16",
    "duration": "8",
    "mode": "std",
    "multi_shots": False,
    "sound": False,
    "kling_elements": [{
      "name": element_name,
      "description": cast_identity_description,
      "element_input_urls": [base_photo_url, angle2_url]
    }]
  }
}
```

### 4. TTS with fallback (ElevenLabs was flaky 2026-07-31, failed twice with `internal error` and 0 credits charged each time)

Try `elevenlabs/text-to-speech-turbo-2-5` first (voice quality is the goal). On failure, fall back to `google/gemini-3-1-flash-tts` (already proven reliable in Phase 0 — reuse that model's confirmed enums: `voice_name` from the 29-value list already documented in `video_bakeoff_phase0.py`'s comments, `style` from `Vocal Smile/Newscaster/Whisper/Empathetic/Promo-Hype/Deadpan`, `accent`, `pace` from `Natural/Rapid Fire/The Drift/Staccato`). Log which provider actually succeeded per clip so we can track ElevenLabs reliability over time and switch the default once it's stable.

### 5. Batch matrix + CLI

```bash
python video_finetuning_harness.py --dry-run           # print plan + cost estimate, no API calls
python video_finetuning_harness.py --niches auto_insurance --formats driving,phone_check --cast-count 2 --yes
```

Config-driven (not hardcoded like Phase 0's 3-niche insurance set) — accept niche/format/action combinations as CLI args or a small JSON config file, since we're now testing auto insurance specifically (per Steve's direction 2026-07-31) and will likely add more verticals later. Each cast identity should be reusable across multiple format variants to control cost — don't regenerate a fresh cast per clip.

### 6. Review grid — extend Phase 0's `review.html` pattern

Group by cast identity (show the base cast photo next to every clip that uses it, so it's easy to visually confirm consistency held), then by niche/format within that group. Same review-questions-as-plain-text pattern as Phase 0, plus one new question: "Does this match the cast photo?"

## Cost guardrails (same discipline as Phase 0)

- `--dry-run` must print total estimated credits/cost before any spend.
- Cast photo generation (`flux-2/pro-text-to-image` + `flux-2/pro-image-to-image`) is cheap (roughly $0.02-0.05/image based on typical kie.ai image pricing — confirm current rate on `kie.ai/pricing` before hardcoding an estimate) — don't let a large matrix silently regenerate cast photos per clip.
- Reuse Phase 0's confirmed per-second costs: talking-head ~$0.04/sec (standard tier), B-roll ~$0.07-0.09/sec.

## Done when

- [ ] Cast library step generates and reuses identities correctly (verify: same face appears in ≥2 different generated clips using that identity)
- [ ] Every avatar-model prompt includes the mandatory no-text/logo/pattern clause
- [ ] TTS fallback logs which provider succeeded per clip
- [ ] `--dry-run` shows an accurate cost estimate before any spend
- [ ] `review.html` groups clips by cast identity for easy consistency-checking
- [ ] Auto insurance niche (driving, checking phone) is the first configured test set, per Steve's current focus
