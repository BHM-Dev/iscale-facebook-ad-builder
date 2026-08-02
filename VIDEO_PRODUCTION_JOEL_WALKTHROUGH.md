# Auto Insurance Video Production Walkthrough

## Goal

Use Ad Builder's video harness to test Arcads-style auto-insurance UGC concepts without spending full-production money on every idea.

The workflow is:

```text
Ad Library research -> script/pattern guidance -> cheap draft videos -> Joel review -> final contender videos
```

## What Joel Reviews

Joel is reviewing whether the system is worth using for paid-social creative production.

Review for:

- first 3 seconds: does the hook stop the scroll?
- actor believability: does this look like a real driver?
- voice/face match: does the voice fit the person?
- clarity: can the viewer understand the point instantly?
- compliance: no fake savings guarantee, no "owed money", no fake urgency
- AI artifacts: no garbled text, bad hands, warped steering wheel, fake phone UI, or lip-sync drift

## Cost Modes

Use these modes instead of generating everything every time.

| Mode | What it generates | Use when | Approx cost before cache |
|---|---|---|---|
| `draft` | 2 talking-head tests per cast, no B-roll | first pass on scripts/cast | lowest |
| `contender` | 4 talking-head tests per cast, no B-roll | scripts/cast look promising | medium |
| `final` | 4 talking-head + 4 B-roll clips per cast | only after Joel likes draft/contender | highest |

Live generation has a default planned-spend cap of `350` credits. `draft` fits under that cap. `contender` and `final` require an intentional higher cap or override.

The harness reuses:

- existing cast images
- cached TTS for the same script and voice
- existing local video clips with the same cast, prompt, format, and script

That means rerunning the same batch can be close to free unless `--force-video` or `--force-tts` is used.

## Recommended Testing Sequence

### 1. Preview the cheap draft plan

```bash
python3 backend/scripts/video_finetuning_harness.py --dry-run --mode draft --cast-count 1 --tts-provider gemini
```

Expected shape:

- 1 cast
- 2 scripts
- talking-head only
- no B-roll

### 2. Generate the draft batch

```bash
python3 backend/scripts/video_finetuning_harness.py --yes --mode draft --cast-count 1 --tts-provider gemini
```

Gemini TTS is recommended until Kie/ElevenLabs stops failing reliably.

### 3. Open the review page

```text
backend/scripts/finetuning_output/review.html
```

Joel should pick:

- best actor
- best script/hook
- obvious rejects
- any artifact patterns to fix

### 4. Expand promising scripts

This tests all four current script formats without paying for B-roll yet.

Contender is above the default safety cap, so use an intentional cap:

```bash
python3 backend/scripts/video_finetuning_harness.py --yes --mode contender --cast-count 1 --tts-provider gemini --max-planned-credits 550
```

### 5. Generate final candidates only after approval

Final mode is the expensive mode, so use an intentional cap:

```bash
python3 backend/scripts/video_finetuning_harness.py --yes --mode final --cast-count 1 --tts-provider gemini --max-planned-credits 1000
```

Then assemble:

```bash
python3 backend/scripts/video_assembly_harness.py --yes
```

To check whether complete talking-head + B-roll pairs exist before rendering:

```bash
python3 backend/scripts/video_assembly_harness.py --plan-only
```

Review:

```text
backend/scripts/assembly_output/review.html
```

## Current Script Formats

- `driving`: renewal-check angle
- `phone_check`: quick phone rate-check angle
- `loyalty_check`: same-insurer-for-years angle
- `quick_psa`: fast overpay callout

To test a specific format:

```bash
python3 backend/scripts/video_finetuning_harness.py --yes --mode draft --formats quick_psa --cast-count 1 --tts-provider gemini
```

## Hard Reject Rules

Reject and regenerate if any of these appear:

- garbled, fake, or cloaked on-screen text
- readable fake phone quote UI
- warped steering wheel or wrong-side driving context
- bad hands or extra fingers
- voice does not fit actor
- lip sync drifts
- actor changes identity between cuts
- fixed savings guarantee without substantiation
- "you are owed money" framing
- fake scarcity or countdown urgency

## Joel Feedback Format

Use this quick format when sending feedback:

```text
Winner:
Rejects:
Best hook:
Worst artifact:
Would I test this in Meta? yes/no
What would make it launchable:
```
