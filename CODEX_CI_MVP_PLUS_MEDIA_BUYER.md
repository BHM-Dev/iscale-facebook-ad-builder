# Campaign Intelligence MVP+ — Media Buyer Enhancements

## Goal

Improve the existing Campaign Intelligence MVP so it feels more like a media-buying action tool and less like a passive report.

Do **not** add new question sets yet. Keep the current hardcoded analysis type:

```js
question_set = "niche_profitability"
```

Enhance the existing Dashboard card with:

1. Action queue
2. Confidence
3. Suggested budget action
4. Active budget/ad set context
5. Top/worst ad set note where available
6. Tracking warning summary

## Why

Joel does not just need to know whether a niche is profitable. He needs to know:

- What should I do next?
- How much should I scale/cut?
- Is the recommendation based on enough data?
- Is this a niche problem or one bad ad set?
- Can I trust the RedTrack join?

The current MVP answers profitability. This pass should answer actionability.

---

## UX Mockup

Inside the existing Campaign Intelligence card, after the AI summary and before the table:

```text
Campaign Intelligence

[Today] [Yesterday] [Last 7d] [This Month] [Last 30d] [Weekdays MTD] [Weekends MTD] [Custom]

Last 7 days

AI summary...

Action Queue
┌─────────────────────────────────────────────────────────────────────┐
│ Scale: Base (+20%), Image (+15%), Car Dealership (+15%)              │
│ Pause / cut: Water Tour & Ferry (pause), Masonry (pause)             │
│ Watch: Barber Shop, Laundromat, Plumbing                             │
│ Tracking check: Image, Plumbing, Masonry                             │
└─────────────────────────────────────────────────────────────────────┘

Tracking Warning
3 niches have partial RedTrack match. Treat ROI as directional until verified.

Niche table:
┌──────────────┬───────┬─────────┬────────┬─────┬─────┬──────────┬────────────┬────────────┬──────────────┬────────────┐
│ Niche        │ Spend │ Revenue │ Profit │ ROI │ CPL │ Verdict  │ Confidence │ Budget     │ Action       │ Join       │
├──────────────┼───────┼─────────┼────────┼─────┼─────┼──────────┼────────────┼────────────┼──────────────┼────────────┤
│ Base         │ $2.5k │ $4.9k   │ +$2.4k │ 97% │ $7  │ Scale    │ High       │ $595/day   │ Scale +20%   │ Matched    │
│ Water Tour   │ $606  │ $359    │ -$247  │-41% │ $20 │ Pause    │ High       │ $118/day   │ Pause        │ Matched    │
│ Plumbing     │ $957  │ $861    │ -$96   │-10% │ $21 │ Watch    │ Medium     │ $450/day   │ Cut 25%      │ Partial RT │
└──────────────┴───────┴─────────┴────────┴─────┴─────┴──────────┴────────────┴────────────┴──────────────┴────────────┘
```

Keep the table dense and operational. Avoid adding decorative cards.

---

## Backend Changes

File:

```text
backend/app/api/v1/intelligence.py
```

### Add per-niche fields

Each row should include:

```json
{
  "confidence": "high",
  "confidence_reason": "Spend >= $300 and leads >= 10",
  "suggested_action": "scale_20",
  "suggested_action_label": "Scale +20%",
  "current_daily_budget": 59500,
  "active_adset_count": 3,
  "avg_spend_per_adset": 837.54,
  "top_adset": {
    "name": "June 8 - Autobody",
    "spend": 404.12,
    "revenue": 912.34,
    "roi": 1.26
  },
  "worst_adset": {
    "name": "June 3 - Autobody Broad",
    "spend": 188.22,
    "revenue": 0,
    "roi": -1.0
  }
}
```

If daily budget or ad set details are not available from the current Meta insight fetch, implement the fields that are available and return `null` for the rest. Do not add a slow new Meta call just for budget/adset detail unless existing saved ad set data is already available in this endpoint.

### Confidence logic

Add deterministic confidence:

```python
if spend >= 300 and leads >= 10:
    confidence = "high"
elif spend >= 100 or leads >= 5:
    confidence = "medium"
else:
    confidence = "low"
```

Recommended reasons:

```text
High: Spend >= $300 and leads >= 10
Medium: Spend >= $100 or leads >= 5
Low: Limited spend/leads
```

### Suggested action logic

Keep this deterministic. Suggested action should be based on verdict + confidence + join status.

For confirmed all-day views:

| Condition | suggested_action | Label |
|---|---|---|
| `scale` + high confidence | `scale_20` | `Scale +20%` |
| `scale` + medium confidence | `scale_10` | `Scale +10%` |
| `scale` + low confidence | `watch` | `Watch` |
| `run` | `hold` | `Hold` |
| `watch` + negative ROI below -10% | `cut_25` | `Cut 25%` |
| `watch` otherwise | `watch` | `Watch` |
| `pause` + high/medium confidence | `pause` | `Pause` |
| `pause` + low confidence | `cut_50` | `Cut 50%` |
| `tracking_check` | `audit_tracking` | `Audit tracking` |
| `insufficient_data` | `collect_data` | `Collect data` |

For day-filtered/directional views:

- Do **not** suggest hard pauses.
- Prefix scale/cut actions as directional:

| Directional verdict | suggested_action | Label |
|---|---|---|
| `directional_scale` | `directional_scale` | `Directional scale` |
| `directional_run` | `directional_hold` | `Directional hold` |
| `directional_watch` | `directional_watch` | `Directional watch` |
| `directional_pause` | `directional_cut` | `Directional cut` |

### Action queue

Return an `action_queue` object at response top level:

```json
{
  "action_queue": {
    "scale": ["Base (+20%)", "Image (+10%)"],
    "cut_or_pause": ["Water Tour & Ferry (Pause)", "Masonry (Pause)"],
    "watch": ["Barber Shop", "Laundromat"],
    "tracking_check": ["Image", "Plumbing", "Masonry"]
  }
}
```

Rules:

- `scale`: rows with suggested action `scale_20`, `scale_10`, or `directional_scale`
- `cut_or_pause`: rows with `pause`, `cut_50`, `cut_25`, or `directional_cut`
- `watch`: rows with `watch`, `hold`, `directional_watch`, `directional_hold`
- `tracking_check`: rows where `join_status` is `partial_redtrack`, `missing_redtrack`, or verdict is `tracking_check`
- Cap each list at 5 names

### Tracking warning

Return a top-level object:

```json
{
  "tracking_warning": {
    "has_warning": true,
    "partial_count": 3,
    "missing_count": 1,
    "message": "3 niches have partial RedTrack match and 1 is missing RedTrack revenue. Treat ROI as directional until verified."
  }
}
```

No warning if both counts are zero.

### AI prompt update

Pass the new fields to the AI summary:

- confidence
- suggested_action_label
- join_status
- tracking warning

Prompt guard:

```text
Do not recommend a harder action than suggested_action_label.
For directional rows, use cautious language and say "directional."
If tracking_warning.has_warning is true, include it in the summary.
Output plain text only.
```

---

## Frontend Changes

File:

```text
frontend/src/pages/Dashboard.jsx
```

### Add Action Queue block

Place after AI summary and before table.

Suggested layout:

```jsx
{ciData.action_queue && (
  <div className="mb-4 rounded-xl border border-gray-100 bg-gray-50 p-4">
    <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Action Queue</div>
    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
      <div><span className="font-semibold text-green-700">Scale:</span> ...</div>
      <div><span className="font-semibold text-red-700">Cut/Pause:</span> ...</div>
      <div><span className="font-semibold text-orange-700">Watch:</span> ...</div>
      <div><span className="font-semibold text-yellow-700">Tracking:</span> ...</div>
    </div>
  </div>
)}
```

Hide empty categories or show `None`.

### Add Tracking Warning block

If `ciData.tracking_warning?.has_warning`, show a compact warning:

```jsx
<div className="mb-4 rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
  {ciData.tracking_warning.message}
</div>
```

### Add table columns

Add columns after `Verdict`:

```text
Confidence
Action
```

Keep `Join` as the final column.

New table order:

```text
Niche | Spend | Revenue | Profit | ROI | CPL | Verdict | Confidence | Action | Join
```

### Confidence labels

Map:

```js
high: green "High"
medium: orange "Med"
low: gray "Low"
```

Show tooltip/title with `confidence_reason`.

### Suggested action labels

Use `row.suggested_action_label`.

Suggested styles:

```js
scale_20 / scale_10 / directional_scale: green
hold / watch / directional_hold / directional_watch: gray/orange
cut_25 / cut_50 / directional_cut: orange
pause: red
audit_tracking: yellow
collect_data: gray
```

### Optional row subtext

Under niche name, add a tiny line:

```text
3 active ad sets · $595/day budget
```

Only show values that exist.

Do not make the row tall if both values are missing.

---

## Do Not Add

- Do not add a new `/intelligence` page.
- Do not add new question sets yet.
- Do not add automated pause/scale actions from this card.
- Do not add charts.
- Do not add another AI call.

---

## Validation Checklist

- Dashboard still loads with Campaign Intelligence collapsed.
- Opening CI still lazy-loads `last_7d`.
- Action Queue appears above table when data exists.
- Tracking warning appears when partial/missing RedTrack exists.
- Rows show Confidence and Action columns.
- Day-filtered presets still show directional verdicts and directional actions.
- Custom preset still clears old results before Apply.
- No raw Markdown appears in summary.
- `npm run build` passes.
- `npx eslint src/pages/Dashboard.jsx` passes.
- `python3 -m py_compile backend/app/api/v1/intelligence.py backend/app/main.py` passes.

## Product Acceptance

Joel should be able to scan the card and answer in under 10 seconds:

1. What should I scale?
2. What should I cut or pause?
3. What needs tracking verification?
4. Which recommendations are high-confidence?
