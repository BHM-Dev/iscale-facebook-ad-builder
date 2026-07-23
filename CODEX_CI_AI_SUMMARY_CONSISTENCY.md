# Campaign Intelligence — AI Summary Consistency Fix

## Problem

The deterministic table/action queue is now correct, but the AI summary can still name tracking-check niches that are not actually in the deterministic tracking queue.

Live example from Chrome:

- Table / Action Queue tracking list:
  - `Car Dealership`
  - `Laundromat`
  - `Water Tour & Ferry`
- AI summary said to audit:
  - `Plumbing`
  - `Water Tour & Ferry`
  - `Masonry`

That is a trust problem. Joel should be able to trust that the prose summary never contradicts the table.

## Goal

Make the AI summary strictly subordinate to deterministic backend output.

The AI can explain and prioritize. It must not invent tracking checks, harder actions, or different niche lists than the backend calculated.

## File

```text
backend/app/api/v1/intelligence.py
```

## Required Fix

### 1. Pass deterministic action queue into the prompt

`_generate_summary(...)` should receive:

```python
action_queue: dict
tracking_warning: dict
```

Update the call site after `action_queue` and `tracking_warning` are built.

### 2. Add a deterministic queue block to the prompt

Add a compact prompt section like:

```text
DETERMINISTIC ACTION QUEUE:
Scale: Base (Scale +20%), Image (Scale +20%)
Cut/Pause: Water Tour & Ferry (Pause), Masonry (Pause)
Watch: Plumbing, Religious
Tracking check: Car Dealership, Laundromat, Water Tour & Ferry
```

If a category is empty, pass `None`.

### 3. Add strict prompt guardrails

Add these exact instructions or equivalent:

```text
You must not contradict the deterministic action queue.
Only name tracking-check niches from DETERMINISTIC ACTION QUEUE > Tracking check.
Do not infer tracking issues from ROI, CPL, spend, or join status unless the niche is listed in Tracking check.
Do not recommend a harder action than suggested_action_label.
For directional rows, use cautious language and say "directional."
If tracking_warning.has_warning is true, mention the warning, but only name the niches in Tracking check.
Output plain text only — no markdown, no bullet points, no headers, no bold.
```

### 4. Optional stronger version

If the AI still drifts, remove tracking-check names from the AI's responsibility entirely:

- Render a deterministic tracking warning/list in the frontend.
- Tell AI:

```text
Do not list tracking-check niche names. The UI renders that list separately.
```

But first try the stricter prompt using `action_queue.tracking_check`.

## Expected Behavior

If `action_queue.tracking_check` is:

```json
["Car Dealership", "Laundromat", "Water Tour & Ferry"]
```

Then the AI summary may say:

```text
Verify tracking for Car Dealership, Laundromat, and Water Tour & Ferry.
```

It must not say:

```text
Verify tracking for Plumbing and Masonry.
```

unless those names are actually in `action_queue.tracking_check`.

## Validation

Run:

```bash
python3 -m py_compile backend/app/api/v1/intelligence.py backend/app/main.py
npx eslint src/pages/Dashboard.jsx
```

Then Chrome test:

1. Open Dashboard.
2. Expand Campaign Intelligence.
3. Load `Last 7d`.
4. Compare AI summary tracking names to Action Queue > Tracking.
5. Load `Weekends MTD`.
6. Compare AI summary tracking names to Action Queue > Tracking.

Pass condition:

- Every tracking-check niche named in the AI summary appears in Action Queue > Tracking.
- AI summary does not recommend harder actions than the table's `Action` column.
- Directional views still use cautious/directional language.

