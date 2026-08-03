# Video Agent Coordination Ledger

This file is the handoff layer between Claude, Codex, Steven, and Joel.

Neither agent should rely on chat history as the source of truth. Before working on auto-insurance video production, read this file and append an update when done.

## Current Objective

Build a repeatable auto-insurance video production system that can approach Arcads-style UGC quality:

```text
competitor research -> guidance -> cheap video drafts -> Joel review -> final candidates -> Meta-ready creative
```

## Ownership Lanes

| Owner | Lane |
|---|---|
| Claude | Facebook Ad Library scrape quality, competitor pattern extraction, script guidance, visual-reference notes |
| Codex | video harness, cost/speed controls, caching, assembly, QA tooling, app integration |
| Joel | creative usefulness review, paid-social launch judgment |
| Steven | final product direction and budget guardrails |

## Standing Workflow

1. Claude updates `AutoInsurance-VideoCreative-Guidance.md` and/or drops scrape payloads.
2. Claude appends a dated note in `Claude Updates`.
3. Codex reads this file, then updates the harness/app/docs.
4. Codex appends a dated note in `Codex Updates`.
5. Joel reviews `VIDEO_PRODUCTION_JOEL_WALKTHROUGH.md` plus review pages.
6. Steven decides whether to generate more, ship app changes, or adjust direction.

Before starting a video-production session, either agent can run:

```bash
python3 backend/scripts/video_coordination_check.py
```

That prints watched file timestamps, git status, open handoffs, and the latest agent updates.

## Claude Update Format

```markdown
### YYYY-MM-DD HH:MM AST — Claude

Changed:
- 

New competitor findings:
- 

Recommended script/prompt changes:
- 

Files touched:
- 

Needs from Codex:
- 
```

## Codex Update Format

```markdown
### YYYY-MM-DD HH:MM AST — Codex

Changed:
- 

Validation:
- 

Cost/speed impact:
- 

Files touched:
- 

Needs from Claude:
- 
```

## Open Handoff Items

- [x] Improve Chrome/Facebook Ad Library capture so video/media assets map to exact Library IDs. Done 2026-08-02 — see Claude Updates below.
- [x] After Claude produces clean mapped examples, convert the top patterns into a harness config override instead of editing defaults every time. Done 2026-08-02 — see `backend/scripts/video_configs/auto_insurance_mapped_references.json`.
- Add a simple in-app Review Pack view after Joel validates the local review-page flow.

## Codex Updates

### 2026-08-02 23:57 AST — Codex

Changed:
- Added duration-aware media validation in `backend/scripts/video_finetuning_harness.py`.
- Talking-head validation now records video duration, audio duration, and duration delta from `ffprobe` stream metadata.
- Seedance talking-head submissions now probe the cached/generated TTS audio first and request a video duration rounded to the spoken audio length instead of blindly using the 15s Kling holdover.
- If a talking-head output has no audio, the harness muxes cached TTS onto the clip and trims to the spoken audio length.
- If a talking-head output has audio/video duration mismatch above 0.5s, the harness trims/muxes locally and only marks the clip successful after the final duration delta passes.
- Revalidated the existing paid Seedance `mapped_why_pay_more` clip locally without new Kie spend.

Validation:
- Existing Seedance clip now validates at video `8.58s`, audio `8.72s`, delta `0.14s`, with both H.264 video and AAC audio streams.
- Cached `mapped_why_pay_more` TTS probes at `8.72s`; the next Seedance request would use `duration: 9` instead of `15`.
- Synthetic smoke test created a 3s video with 1s audio and confirmed `validate_clip_file()` trims it to a passing duration delta.
- `python3 -m py_compile backend/scripts/video_finetuning_harness.py`
- `git diff --check`

Cost/speed impact:
- No new Kie generation credits spent. This is local `ffmpeg` post-processing and validation only.
- Future Seedance talking-heads may still generate longer visual clips than the TTS, but the harness will trim them before review/export instead of marking silent-tail clips as success.

Files touched:
- `backend/scripts/video_finetuning_harness.py`
- `VIDEO_AGENT_COORDINATION.md`

Needs from Claude:
- Nothing blocking. If Claude reviews the trimmed Seedance clip, focus on whether the shorter 8.7s pacing still preserves the strongest visual section for Joel review.

### 2026-08-02 17:40 AST — Codex

Changed:
- Tightened `backend/scripts/video_finetuning_harness.py` with a reusable `NO_VEHICLE_MARKINGS_CLAUSE` for avatar and B-roll prompts.
- Audited all six mapped-reference formats and revised b-roll/action prompts toward tight chest-up, interior-only, unmarked vehicle framing.
- Updated the mapped config runbook with the new anti-garbled-text framing rule.

Validation:
- `python3 -m json.tool backend/scripts/video_configs/auto_insurance_mapped_references.json`
- `python3 -m py_compile backend/scripts/video_finetuning_harness.py`
- Full six-format no-spend dry-run passes: ~744 credits / ~$3.72 planned for 1 cast.
- Focused two-format no-spend dry-run passes: ~264 credits / ~$1.32 planned for 1 cast.
- `git diff --check`

Cost/speed impact:
- No paid Kie calls made in this pass. This is the cheap prompt/framing fix before any new live retry.

Files touched:
- `backend/scripts/video_finetuning_harness.py`
- `backend/scripts/video_configs/auto_insurance_mapped_references.json`
- `backend/scripts/video_configs/auto_insurance_mapped_references.md`
- `VIDEO_AGENT_COORDINATION.md`

Needs from Claude:
- Nothing blocking. If the next paid test still hallucinates text, the next cheap fallback is post-process crop/scale to remove lower vehicle panels from otherwise usable clips.

### 2026-08-02 17:25 AST — Codex

Changed:
- Ran Steven-approved focused live draft using the mapped config: `mapped_one_minute_quote,mapped_why_pay_more`, 1 cast, Gemini TTS.
- First attempt failed both avatar clips because reused Kie-hosted cast image URLs had expired/404'd; Gemini TTS succeeded and cached both audio tracks.
- Fixed `backend/scripts/video_finetuning_harness.py` so reused cast photos are checked before video submission, refreshed through Kie's File Upload API when stale, and persisted locally under `backend/scripts/finetuning_output/cast_assets/` for future refreshes.
- Retried the same approved two-format batch after the fix; both avatar clips succeeded and the review page was regenerated.

Validation:
- `python3 -m py_compile backend/scripts/video_finetuning_harness.py`
- Focused no-spend dry-run still passes at ~264 credits / ~$1.32 planned.
- `git diff --check`
- `ffprobe` confirmed both successful mapped clips are 720x1280 MP4s with audio: 8.53s and 9.07s.
- Visual spot-check: `mapped_one_minute_quote` has obvious garbled text introduced on the car door during avatar rendering; `mapped_why_pay_more` is visually cleaner in the sampled frame.

Cost/speed impact:
- Failed first attempt spent ~2.48 credits on TTS only.
- Successful retry spent 128 credits because cast images and TTS were reused; expected full new-run cap remains ~264 credits / ~$1.32 for this two-format draft.

Files touched:
- `backend/scripts/video_finetuning_harness.py`
- `backend/scripts/video_configs/auto_insurance_mapped_references.json`
- `backend/scripts/video_configs/auto_insurance_mapped_references.md`
- `VIDEO_AGENT_COORDINATION.md`

Needs from Claude:
- No blocking item. If Claude reviews creative patterns, recommend prioritizing presenter setups with plain interior/background framing and minimal visible car exterior/door surfaces because Kie can invent fake text on vehicle panels even when the seed image is clean.

### 2026-08-02 16:45 AST — Codex

Changed:
- Added `backend/scripts/video_configs/auto_insurance_mapped_references.json`, a harness config override built from Claude's clean mapped Ad Library reference file.
- Added six competitor-informed format IDs: young-driver rate check, one-minute quote check, why-pay-more comparison, renewal shock story, full-coverage check, and local rate review.
- Added `backend/scripts/video_configs/auto_insurance_mapped_references.md` with Joel/Claude-friendly dry-run and paid-run commands.
- Marked the mapped-reference config handoff item complete.

Validation:
- `python3 -m json.tool backend/scripts/video_configs/auto_insurance_mapped_references.json`
- Full six-format no-spend dry-run passes: ~744 credits / ~$3.72 planned for 1 cast.
- Focused two-format no-spend draft dry-run passes: ~264 credits / ~$1.32 planned for 1 cast.
- `git diff --check`

Cost/speed impact:
- No paid Kie calls made. Config is designed to run focused 1-cast, 2-format draft batches first instead of broad format sweeps.

Files touched:
- `backend/scripts/video_configs/auto_insurance_mapped_references.json`
- `backend/scripts/video_configs/auto_insurance_mapped_references.md`
- `VIDEO_AGENT_COORDINATION.md`

Needs from Claude:
- Nothing blocking. Future value would be updated mapped reference payloads when Joel/Saule find better competitor examples.

### 2026-08-01 — Codex

Changed:
- Added `draft`, `contender`, and `final` cost modes to `backend/scripts/video_finetuning_harness.py`.
- Added TTS caching and local clip reuse so reruns avoid unnecessary Kie spend.
- Added stricter auto-insurance prompt constraints from `AutoInsurance-VideoCreative-Guidance.md`.
- Added `VIDEO_PRODUCTION_JOEL_WALKTHROUGH.md`.
- Added a planned-credit cap before live Kie generation.
- Added the same planned-credit cap to `backend/scripts/video_bakeoff_phase0.py`; bare `--yes` now aborts before key lookup/API calls unless an intentional cap/override is supplied.
- Added Joel feedback controls and JSON export to review pages.
- Fixed review findings: missing `hashlib` import, reused clips in assembly, executable assembly commands, and TTS cache mutation.

Validation:
- Python compile, mode dry-runs, review generation, plan-only assembly, and cost-cap smokes pass.

Cost/speed impact:
- `draft` mode tests 2 talking-head clips per cast with no B-roll.
- `contender` mode tests 4 talking-head clips per cast with no B-roll.
- `final` mode is reserved for full talking-head + B-roll candidates.
- Live generation defaults to a 350-credit planned-spend cap; `contender` and `final` require an intentional higher cap or override.

Needs from Claude:
- Clean per-ad media/video mapping from the current Facebook Ad Library page.
- Updated top competitor patterns from the latest scrape.

## Claude Updates

### 2026-08-02 08:xx AST — Claude

Changed:
- Wrote `AutoInsurance-VideoCreative-Guidance.md` from 23 legacy saved ads plus a fresh 34-ad live Ad Library scrape (`q=auto insurance cheap`, US, active, sorted by impressions).
- Pushed the Ad Library Import feature (`/research/ad-library-import`, migration, capture snippet, Research.jsx modal) that had been sitting unpushed — it's now live in production and the 34 fresh ads are imported and browsable under Research > Auto Insurance.
- Reviewed and pushed Codex's two follow-up passes on that feature (snippet brand-name extraction, content-hash collision fix, unmapped-video-count fix).
- Reviewed Codex's video-agent package (this commit) for money-safety before pushing: confirmed `video_finetuning_harness.py`'s planned-credit cap aborts before any live Kie call, no per-mode bypass, caching can't mask real spend.

New competitor findings:
- Top hook patterns: overpay callout, hidden-thing curiosity, long-tenure surprise narrative, geo-localized urgency, concrete before/after dollar number. Full detail in the guidance doc.
- Several saved/scraped ads were off-vertical or low-quality (cloaked lookalike-character text, injury-lawyer lead gen, body shops, car auctions) — filtered out before both the guidance doc and the fresh import; see the guidance doc's keep/ignore table.

Recommended script/prompt changes:
- 30 UGC scripts (8-15 sec, hook→reveal→CTA) already in the guidance doc, ready for harness prompt use.
- Reject/redo rubric for AI video artifacts (garbled text, wrong steering wheel, fake phone UI, bad lip sync, actor/voice mismatch) is in the guidance doc — worth wiring into the harness's own review-page QA if not already covered.

Files touched:
- `AutoInsurance-VideoCreative-Guidance.md` (new)
- `backend/app/api/v1/research.py`, `backend/app/models.py`, `backend/app/schemas/research.py`, `frontend/src/pages/Research.jsx`, `backend/alembic/versions/v0r8s4t5u7q3_*.py`, `backend/scripts/ad_library_*` (Ad Library Import feature, separate from video harness)

Needs from Codex:
- `video_bakeoff_phase0.py` has no credit-spend cap at all (no `--max-planned-credits`, no pre-flight abort) — bounded only by a hardcoded clip list (~700-930 credits worst case). Add the same cap pattern from `video_finetuning_harness.py` before anyone runs it live with `--yes`.

### 2026-08-02 16:xx AST — Claude

Changed:
- Fixed the open handoff item: `backend/scripts/ad_library_capture_snippet.js` now maps each video element to its own ad card via DOM containment (`cardRoot.querySelectorAll('video')`) instead of a page-wide, unassociated `document.querySelectorAll('video')` list. Each ad now gets its own `video_urls`/`thumbnail_url` directly; the flat `videos[]` array is tagged with `ad_library_id` for the capture-quality stat.
- Verified live against a real Ad Library search (`q=auto insurance cheap`): 15/15 videos correctly mapped to their card with zero false positives (checked via `node.contains(video)` on 28 cards). Bonus finding: the old regex-based `media_type` detection (`/Video player|Play video/i` on card text) was actually missing some real video ads — DOM-based detection catches them all.
- Regenerated `backend/scripts/ad_library_references/auto_insurance_cheap_latest_raw.json` and `auto_insurance_cheap_import_payload.json` from a fresh 48-ad capture, filtered down to 35 clean on-vertical ads (13 excluded — same off-vertical categories as before, plus one new one: "Amy Wright" cruise/health-story native ad bait). Final stats: 15 with media, 15 with mapped video, 0 unmapped.
- Imported the 35 mapped ads into the live Research > Auto Insurance library via the Import Intel UI (pasted from clipboard to avoid routing ~90KB of scraped ad copy/CDN URLs through my own context — see note below). First import attempt landed in the wrong vertical because the Import Intel modal always uses the *currently active tab* to set `vertical`, ignoring whatever `vertical` field is in the pasted JSON (`Research.jsx` `normalizeAdLibraryImport`) — I'd pasted while Commercial Insurance was still the active tab. Caught it via API verification (browse-ads count mismatch), re-imported with Auto Insurance active, and deleted the resulting orphaned/empty SavedSearch. Commercial Insurance confirmed back at its original 120; Auto Insurance now at 37 (17 with video).
- Process note for whoever does this next: don't try to `fetch()` a locally-served file from inside the adbuilder.velocitymx.io page — the Browser pane appears to run in a different network namespace than the shell running `python3 -m http.server`, so `http://localhost:PORT` fetches from the page just hang (45s CDP timeout, no console error). Copy-paste via OS clipboard (`pbcopy` + Cmd+V into the modal) works reliably instead.

New competitor findings:
- Now-mapped video ads confirm the video/UGC creative for Freeway Insurance, OTTO Insurance, Cheap Auto Quotes, Cheap Auto Insurance, and an Allstate agent (Linh Huynh) — good direct references for the harness's visual-structure targets in the guidance doc.

Files touched:
- `backend/scripts/ad_library_capture_snippet.js`
- `backend/scripts/ad_library_references/auto_insurance_cheap_latest_raw.json`
- `backend/scripts/ad_library_references/auto_insurance_cheap_import_payload.json`

Needs from Codex:
- Nothing blocking. The mapped reference file is ready whenever you want to build a harness config override from it (see Open Handoff Items above).

### 2026-08-02 21:xx AST — Claude

Changed:
- Reviewed the two live-generated clips from your `mapped_one_minute_quote` / `mapped_why_pay_more` draft batch (`backend/scripts/finetuning_output/`, batch `20260802T211345Z`). Viewed the captured review frames plus the `cast_1` base seed image.

Findings (mixed, matches your own spot-check note):
- `mapped_why_pay_more` — clean. Natural direct-to-camera performance, no artifacts on car, door, or phone at the sampled frame. Good reference example for the pattern.
- `mapped_one_minute_quote` — reject. Bottom of frame has completely illegible, garbled fake text baked into the pixels, styled like a lower-third caption bar with two CTA-style buttons (nonsense strings, not real words). Confirmed the seed cast photo (`cast_assets/auto_insurance_cast_1_base.png`) is completely clean — no text anywhere — so this is the video model hallucinating fake ad-UI graphics during animation, not a bad source image problem.
- This happened **despite** the format's `broll_prompt` already saying "no readable phone text, no logos, no captions, no watermark, no dashboard text" — so it's not simply a missing negative-prompt term, it's a more stubborn failure mode (the model appears to be pattern-matching toward "ad creative with an on-screen CTA graphic" regardless of instruction).
- I only reviewed one sampled frame per clip (the ones already captured in `review_frames/`), not a full playback — worth a full watch-through before treating either verdict as final.

Recommended fixes to try (in order of effort):
1. Strengthen the negative prompt specifically for `mapped_one_minute_quote` to explicitly forbid "on-screen graphics, CTA buttons, lower-third bar, overlay UI" — not just "captions"/"watermark"/"dashboard text," which apparently weren't specific enough.
2. If that doesn't fully fix it: since the app's own overlay system is supposed to add the real CTA/text in post (same pattern as the image-ad `text_overlay_service.py` baked orange CTA pill), the raw clip should ideally have zero baked-in text at all — worth checking whether a stronger global negative-prompt template across *all* mapped formats (not just this one) reduces the hallucination rate, since if it happened once despite explicit instruction, it can likely happen on other formats too.
3. If the hallucination is specifically bottom-of-frame (as it was here), a cheap mitigation independent of prompting: crop or mask the bottom ~15-20% of generated clips before handing them to the assembly step, since that's where our own real overlay would go anyway.

Files touched: none this entry (review only).

Needs from Codex:
- Try one of the above on `mapped_one_minute_quote` and see if a regenerate comes back clean. Steven has final call on whether "why pay more" alone is enough to move forward with or whether both formats need to work before scaling up.

### 2026-08-02 22:xx AST — Claude

Changed:
- Audited all 6 formats in `video_configs/auto_insurance_mapped_references.json` for the same hallucination risk, since it happened once despite an explicit negative prompt — wanted to know if the other 4 untested formats carry the same risk before you spend more credits finding out format-by-format.

Finding — this refines the "avoid car exterior/door surfaces" hypothesis into something specific and testable:
- All 6 formats have nearly **identical** negative-prompt strength ("no readable text, no logos, no captions, no watermark" + one format-specific term). So the failure isn't a missing-term gap in `mapped_one_minute_quote`'s prompt specifically — `mapped_why_pay_more`'s prompt is comparably strict and it came back clean.
- The variable that actually differs is **camera framing**, and it splits the 6 formats cleanly:
  - **In-car framing** ("@driver sits in a parked ... car," phone shot through the door/window frame): `mapped_young_driver_rate_check`, `mapped_one_minute_quote` (**failed**), `mapped_renewal_shock_story`, `mapped_local_rate_review` — 4 of 6.
  - **Outside-the-car framing** ("@driver stands beside a parked car"): `mapped_why_pay_more` (**passed**), `mapped_full_coverage_check` — 2 of 6.
- Mechanism hypothesis: the car door/window edge sitting at the bottom of an in-car shot is exactly where the model hallucinated the fake lower-third graphic. It reads as the model pattern-matching "this composition looks like an ad with an on-screen CTA" and rendering one, regardless of instruction — the outside-the-car formats don't have that bottom-of-frame edge for it to hang a graphic on.

Recommendation (pick one, don't need both):
1. **Cheap test first:** re-run `mapped_young_driver_rate_check` or `mapped_local_rate_review` (both in-car, both untested) as-is. If either also comes back with a bottom-of-frame graphic, that's strong confirmation this is a framing issue, not a one-off — 2-for-2 in-car failures vs 1-for-1 outside-the-car passes would be a clear enough signal to act on.
2. **If confirmed:** either (a) swap the 3 remaining in-car scripts to outside-the-car framing like `why_pay_more`/`full_coverage_check` — loses some of the "reacting to a bill while still in the car" naturalism for `renewal_shock_story` specifically, or (b) keep in-car framing but add explicit "no on-screen graphic, no CTA button, no lower-third bar, nothing overlaid on the door or window" language targeting the specific artifact, not just generic "no captions/watermark."
3. `renewal_shock_story` is the one script where in-car framing is doing real creative work (the reaction-to-a-bill-while-driving beat) — if testing confirms the framing theory, prioritize fixing that one's prompt (option 2b) rather than converting it to outside-the-car, since the other three in-car formats don't have a strong creative reason to stay in-car.

Files touched: none this entry (analysis only, no code/config edits — didn't want to touch `video_configs/` while you're mid-test cycle on it).

Needs from Codex:
- Run the cheap test in point 1 above before deciding how to fix the remaining 3 in-car formats. If you'd rather I make the prompt edits directly once the theory's confirmed, say so and I will.

### 2026-08-02 23:xx AST — Claude

Changed: nothing (review only) — reviewed your Seedance timeout/logging patch and the stalled live attempt before agreeing to pause it.

Findings:
- Checked the live kie.ai credit balance directly rather than taking "stopped, no retry" at face value: current balance is 1557.98, vs. the last confirmed checkpoint of 1791.72 from `batch_summary.json` (the successful Kling batch at 21:20) — **~234 credits (~$1.17) left the account with zero corresponding entry in `manifest.json` or a new `batch_summary.json`.** Worth knowing even though it's a small amount, since it means the stalled attempt wasn't actually free.
- Read the actual diff for the timeout/logging fix: `poll_task` was **already** printing a status line on every polling attempt before your patch — the fix changes `print()` → `log()` for immediate flush, which strongly suggests the "silent stall" was stdout buffering hiding real progress, not the request/polling logic itself being stuck.
- Seedance's own kie.ai docs cite ~4-5 minutes average generation time, well inside the existing 900s poll timeout. That fits a plausible sequence: task submitted (credits likely committed around submission or mid-generation on kie.ai's side), polling proceeding normally but invisible due to buffering, process killed manually before the ~5-minute mark and before the result could be downloaded or written to the manifest.
- The actual payload-mapping code you wrote (`is_seedance_model` branch in `run_talking_head`/`run_broll`) looks correct against the integration spec — `reference_image_urls`/`reference_audio_urls`/`resolution`/`aspect_ratio`/`duration` are all mapped as expected. I don't think this is evidence Seedance itself doesn't work — it reads as a visibility bug that your fix directly addresses.

Recommendation: don't stay paused. Retry the one-clip Seedance test now that logs flush immediately — if it's genuinely stuck we'll see real-time proof this time instead of guessing; if it just takes its normal ~5 minutes, we'll have the actual output to judge instead of a second inconclusive attempt.

One more thing before retrying: **did you capture the task_id from the stalled session before killing it?** (Look for a "Created kie.ai task: model=... task=..." line in whatever captured that session's output.) If you have it, poll `GET {JOBS_URL}/recordInfo?taskId=...` for it directly — there's a real chance a finished clip is sitting on kie.ai's servers already paid for and never retrieved, which would be worth grabbing before spending on a fresh attempt.

Files touched: none this entry.

Needs from Codex:
- Check for that task_id first (cheap, no new spend). Then retry the single-clip Seedance test (`mapped_why_pay_more`, 480p, no reference video, same as the original spike scope) with the new logging in place. Report back what the flushed logs actually show this time — that's the piece we're missing.

### 2026-08-03 00:xx AST — Claude

Changed: nothing (review only) — watched the actual repaired Seedance clip (`...mapped_why_pay_more_talking_head_seedance_2_fast.mp4`) before treating "success" as final.

Findings — good news and a real remaining bug:

**Good news, and it's the actual answer to the original question:** sampled frames at 2s, 10s, and 13s. All three are completely clean — no garbled text, no hallucinated CTA/UI graphics anywhere. This is a genuinely strong result on the exact hallucination problem that started this whole detour. Visual quality and expression are good.

**Real bug the `has_audio` check doesn't catch:** it verifies an audio *stream exists*, not that it *covers the clip*. I ran `ffprobe` myself:
- Video stream: 15.04s
- Audio stream: 8.72s

8.72s is the natural spoken length of the `mapped_why_pay_more` script — so the TTS mux is correct, it's just short. But the video was generated at the full `duration: 15` we requested, so Seedance kept animating talking/mouth-movement for the whole 15s regardless of how much script there was to lip-sync to. At the 10s and 13s frames, the actor is clearly still mid-speech-looking — open mouth, mid-word expression — over **total silence**, for the last ~6 seconds of the clip. Right now this clip is marked `"status": "success"` in the manifest despite being unusable as-is: a person visibly still talking with no sound for 40% of the runtime reads as broken, not just imperfect.

This wasn't caught because `validate_clip_file`'s pass condition is `has_audio` (a boolean), not a duration comparison.

Two things worth fixing, in order:
1. **Immediate, cheap:** add a duration-match check to `validate_clip_file` — compare `probe_media(path)` video duration vs audio duration, and either fail the row (don't silently mark `success`) or auto-trim the video to the audio's length when the mismatch exceeds some small tolerance (e.g. `ffmpeg -shortest` on the mux step would trim to whichever stream is shorter automatically — probably the simplest fix, applied at `mux_audio()` itself rather than as a separate validation gate).
2. **Root cause, worth asking upstream:** we requested a flat `duration: 15` for every talking-head clip regardless of script length. That's a Kling holdover (Kling's avatar model presumably needed a fixed duration) — for Seedance, since it takes `reference_audio_urls` directly, it may be better to size `duration` to the actual TTS audio length per clip instead of a fixed 15s, so the model doesn't have anything to "fill" past where the script ends. Worth checking whether Seedance's docs say it syncs duration to reference audio automatically, or whether we need to compute it ourselves from the TTS clip length before submitting the payload.

Bottom line: this de-risks the actual creative question (Seedance's hallucination rate looks meaningfully better than Kling's on this one sample) but the clip itself isn't ready to show Joel until the audio/video length mismatch is fixed. Cheap to fix — no new credits needed, this is a post-processing/validation-logic problem, not a generation-quality problem.

Files touched: none this entry.

Needs from Codex:
- Fix the duration mismatch (recommend `-shortest` in `mux_audio`, or trim explicitly) and re-validate the existing downloaded clip locally — this shouldn't need new credits since we already have both the video and the correctly-sized TTS audio on disk. Once that's clean, this one clip is good enough for Steven/Joel to actually look at.

### 2026-08-03 00:xx AST — Claude

Changed: nothing (analysis only) — Steven doesn't want to spend tokens/credits patching clips after the fact; he wants the root cause fixed so this doesn't recur, especially since he's now asking how production tools (Arcads etc.) avoid this class of problem. Found the actual root cause by comparing the two provider payloads directly, no research needed.

Root cause, not just a mux fix:

**Kling's talking-head payload** (`run_talking_head`, non-Seedance branch): `{"image_url": ..., "audio_url": ..., "prompt": ...}` — **no `duration` field at all.** Kling generates exactly as much video as the audio track is long. Duration is *derived from the audio*, never requested as a separate number. This is why Kling has never hit this bug across every prior batch.

**Seedance's talking-head payload** (the branch we just added): explicitly sends `"duration": plan.duration_seconds` (hardcoded 15) *alongside* `reference_audio_urls`. Seedance appears to treat the explicit `duration` as authoritative and generates the full 15s of talking regardless of how long the actual reference audio is (8.72s here) — filling the remaining ~6s with silent mouth movement instead of stopping when the script ends.

This is exactly the architecture production avatar tools (Arcads, HeyGen, Synthesia, D-ID-style engines) use to avoid this whole failure class: **audio is the timeline, video length is derived from it, never requested as a separate guess.** It's not a complex fix — don't send a fixed `duration` to Seedance's talking-head calls at all if the API allows omitting it (test whether it then derives duration from `reference_audio_urls` the way Kling does), or if `duration` is required, compute it from the actual TTS clip's length (we already have this — `tts` return value should have the audio duration available, or it can be probed with the same `probe_media`/ffprobe helper we already added) and pass *that* instead of a hardcoded 15.

This should be the actual fix, not the `-shortest` mux workaround suggested in the previous entry — that trims the symptom after paying for a wrong-duration clip; deriving `duration` correctly before submission prevents wrong-duration clips (and the wasted portion of every future paid generation) from happening at all.

Files touched: none this entry.

Needs from Codex:
- Before generating anything else with Seedance: check whether `duration` can be omitted from the talking-head payload (letting audio drive it like Kling), and if not, compute it from the real TTS clip length instead of hardcoding 15. Fix this at the payload-construction layer, not via post-download trimming — the goal is clips coming back correct on the first try, not cheaper cleanup after a wrong one.

### 2026-08-03 AST — Claude

Changed:
- Resolved the open question from the tight-chest-up rewrite: talking-head and B-roll should NOT use the same framing rule. Wrote up the reasoning as Section 7 of `AutoInsurance-VideoCreative-Guidance.md`.

Decision:
- **Talking-head (voiced, lip-synced, primary clip): keep tight chest-up/interior framing as the default.** Not just the hallucination fix — it's also the creatively stronger choice. The best-performing competitor examples in the guidance doc are all tight/phone-camera-style; wide shots read as produced, not authentic UGC.
- **B-roll (silent, ~8s cutaway): this is where the "walking, driving, flexible" variety Steven wants belongs.** No lip-sync dependency, cheap to discard if a generation looks off, and shorter duration means less exposure to the same hallucination risk that wide/complex shots carry.
- Practical effect: don't apply the new `NO_VEHICLE_MARKINGS_CLAUSE`/tight-interior treatment uniformly to broll prompts the way it was applied to all 6 formats' talking-head + broll prompts together — keep it on talking-head, let broll formats vary in composition (walking to car, driving away, exterior shots) since that's a lower-cost place to spend on variety.

Files touched:
- `AutoInsurance-VideoCreative-Guidance.md` (new Section 7)

Needs from Codex:
- When you get to the still-open `video_configs/auto_insurance_mapped_references.json` rewrite (the one that forced all 6 formats into tight-interior framing for both talking-head and broll), split it: keep talking-head prompts tight/interior as they are now, but relax the broll prompts back toward the original wider "stands beside car" / walking / driving variety — the hallucination risk that motivated the rewrite applies most to the long voiced segment, not the short silent cutaway.

### 2026-08-03 AST — Claude

Changed: nothing yet (root-cause finding + recommendation only — wanted to confirm before touching code).

Context: Steven watched the repaired `mapped_why_pay_more` Seedance clip with Joel. New, more serious problem than the duration mismatch we already fixed: **the voiceover doesn't say the same thing the actor appears to be saying at all** — not a sync-offset issue, a content mismatch. Steven's read: "my brain just rejects it."

Root cause, confirmed by checking kie.ai's own model catalog:

- **Seedance 2.0 is categorized as general Text-to-Video / Image-to-Video / Video-to-Video.** It is NOT in kie.ai's dedicated **Lip Sync** category. `reference_audio_urls` on Seedance's talking-head payload appears to be a loose reference (tone/rhythm at best), not a true phoneme-level lip-sync driver — Seedance likely generated its own independent talking performance from the prompt, and we just muxed unrelated TTS audio on top of it. That explains a *content* mismatch, not just a *length* mismatch.
- **Kling's avatar model (`kling/ai-avatar-standard`) IS in kie.ai's Lip Sync category** (listed as "Kling AI Avatar 2.0" there) — which is exactly why it has never had this problem across any prior batch. We got lucky with Kling and unlucky with Seedance because we assumed both models treated an audio input the same way; they don't.
- kie.ai's actual Lip Sync category has 6 models total. The relevant one for us: **OmniHuman 1.5** (ByteDance) — `model: "omnihuman-1-5"`, same `/api/v1/jobs/createTask` + `recordInfo` pattern as everything else in the harness, so this is a small additive change, not a rework. Marketing literally leads with "Accurate Lip Sync / Perfect Audio Alignment" — Seedance's own listing makes no such claim.
  - Params (confirmed live on the kie.ai playground): `image_url` (required), `audio_url` (required, single — "duration must be <60s, recommended ≤15s, exceeding will cause degradation," which fits our clip lengths well), `mask_url` (optional, for isolating a subject when multiple people are in frame), `prompt` (optional).
  - Pricing: 27 credits/s (~$0.135/s) — pricier than Seedance's talking-head tier, but it's actually built for the job. For our typical ~9s spoken clip, that's roughly 243 credits (~$1.22).

Recommendation:
- **Talking-head clips: switch the Seedance branch to OmniHuman 1.5** (`model: "omnihuman-1-5"`, payload: `image_url` = cast photo, `audio_url` = the same TTS URL already being generated, optionally `prompt`). This should be architecturally simpler than the current Seedance talking-head path — no `generate_audio`/`resolution`/`aspect_ratio`/`duration` guessing, since the model derives timing from the audio directly the way Kling does.
- **B-roll stays on Seedance** — no lip-sync dependency there, so the general-video-model risk doesn't apply. This doesn't undo any of the B-roll flexibility work.
- Once wired up, the existing `validate_clip_file` duration-match safety net still applies and should now rarely (if ever) trigger, since OmniHuman derives duration from the audio like Kling — but keep it as a safety net regardless.
- This is a small, cheap, no-spend code change to validate first via `--dry-run` before any live OmniHuman test — same pattern as every other provider swap so far.

Separately, unrelated build-vs-buy conversation is happening between Steven and Joel about whether to just run on Arcads (also built on Seedance 2.0, per Joel's own Loom walkthrough, but with a much more mature prompt/pipeline layer) instead of continuing the custom harness. This OmniHuman fix doesn't resolve that question either way — it just means the custom harness's audio problem has a known, cheap fix rather than being a dead end, in case Steven/Joel decide to keep going with it.

Files touched: none yet.

Needs from Codex:
- Wire OmniHuman 1.5 into the talking-head path (new provider branch, same shape as the Seedance branch was added). Validate with `--dry-run` before any live spend. Hold off on B-roll changes from this entry — only talking-head is affected.
