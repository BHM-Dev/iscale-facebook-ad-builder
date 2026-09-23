# Best Times / Dayparting — Abel Feedback Scope

## 1. Executive summary

### Problem

Best Times currently makes the buyer inspect a selector, a large timing-context warning, and four broad pooled daypart cards before answering the practical question: “When should I run this campaign?” The backend already provides hourly Meta delivery data, but the UI collapses it into `12a–6a`, `6a–2p`, `2p–6p`, and `6p–12a` windows. The current recommendation logic is also mostly a pooled ROI threshold, so it does not clearly distinguish profitable performance from repeatable performance.

### Recommended solution

Ship a focused MVP that makes the answer visible immediately:

1. Put a prominent **Recommended Meta Schedule** summary at the top.
2. Show the selected date range and timezone beside the Best Times title.
3. Add Profit to timing metrics.
4. Replace the four broad cards with configurable 1-hour or 2-hour blocks; default to 2-hour blocks for scanability.
5. Add High / Medium / Low confidence with a short explanation.
6. Add a compact expandable Timing Context / Coverage box.
7. Explain “profitable but inconsistent” directly on the recommendation.
8. Include explicit **Run** and **Avoid** windows in Meta-ready format.

### Economics / decision rule

The output should optimize for repeatable profit, not the highest observed ROI. A block is only recommended when it has enough spend/revenue evidence and is positive across a sufficient share of the underlying weekday/date buckets. This reduces the risk of shifting budget into a lucky but unstable hour.

The backend already returns hourly spend, leads, revenue, ROI, confidence, and confidence reason. MVP can calculate Profit and stability from those cells in the API or frontend; recommendation logic should live in the backend once the rule is agreed so the UI cannot drift from the decision model.

## 2. Flow diagrams

### Current

```text
Open Best Times
  → choose campaign/ad set
  → read Timing Context / Coverage
  → inspect four broad pooled cards
  → infer a schedule manually
```

### MVP target

```text
Open Best Times
  → Recommended Meta Schedule
      Mon–Fri · 7 AM–2 PM PT
      Run: 7 AM–2 PM     Avoid: 12 AM–6 AM
      High confidence · +$X profit · +Y% ROI
  → inspect 2-hour blocks by weekday/weekend
  → expand “Why this recommendation?”
  → optionally copy/enter the Run and Avoid windows in Meta
```

### Recommendation decision flow

```text
Hourly cells
  → calculate profit + ROI per cell
  → pool into 1-hour/2-hour blocks
  → measure evidence + positive-bucket consistency
  → classify confidence
  → recommend / hold / avoid
  → render Meta-ready schedule
```

## 3. Detailed spec with wireframe + copy

### Ready for review — MVP

#### A. Top-of-panel context

Replace the current low-contrast metadata line with a visible context row:

```text
Best Times                                      Refresh
Last 30 Days · Aug 23–Sep 21 · PT              Exact / Directional attribution
Campaign or ad set selector
```

Use the API’s existing `date_from`, `date_to`, `preset_label`, and `timezone` fields. Format dates for people (`Aug 23–Sep 21`) while retaining the exact ISO dates in a tooltip or accessible label.

#### B. Prominent recommendation card

Place this before the campaign/ad set selector’s detailed grid:

```text
RECOMMENDED META SCHEDULE                         High confidence
Mon–Fri · 7 AM–2 PM PT                            Based on 5 of 5 weekday buckets

RUN                                                AVOID
Mon–Fri · 7 AM–2 PM                               Mon–Fri · 12 AM–6 AM
+$1,240 profit · +38% ROI                         -$410 profit · -22% ROI

Why: positive in 5/5 weekday buckets with sufficient spend.
```

If no schedule qualifies:

```text
NO REPEATABLE SCHEDULE YET
There is profitable activity, but no time block is consistently positive
enough to recommend changing Meta delivery. Keep the current schedule and
collect more evidence.
```

The card must never imply certainty when attribution is incomplete or revenue is allocated directionally. In those cases label the recommendation **Directional test schedule** and retain the existing “do not change budgets” guardrail.

#### C. Granular timing breakdown

Default to 2-hour blocks for MVP, with a small toggle for 1-hour detail when needed:

```text
Weekday schedule · Mon–Fri                         2-hour blocks

7–9 AM       Run       +$320 profit   +42% ROI   High
9–11 AM      Run       +$510 profit   +51% ROI   High
11 AM–1 PM   Hold      +$40 profit    +4% ROI    Medium
1–3 PM       Run       +$210 profit   +18% ROI   Medium
3–5 PM       Inconsistent — profitable, but positive in only 2/5 buckets
```

Show Spend, Revenue, Profit, ROI, confidence, and evidence count. Leads remain available as a secondary detail or tooltip; do not add another dense primary column if it harms scanability.

#### D. Confidence indicator

Display `High`, `Medium`, or `Low` as a badge, plus a plain-language reason. Keep the existing evidence count, but make it supporting detail rather than the only confidence signal.

Suggested MVP rubric:

| Confidence | Minimum evidence | Interpretation |
|---|---|---|
| High | At least 4 positive weekday buckets or 2 positive weekend buckets, adequate spend, and ≥75% positive buckets | Safe enough for a schedule recommendation |
| Medium | Adequate spend and ≥60% positive buckets, but fewer observations or smaller sample | Testable recommendation; do not over-scale |
| Low | Insufficient spend/revenue, or less than 60% positive buckets | Do not use for a schedule change |

The exact dollar thresholds should reuse or replace the current `$100 spend / $25 revenue` gate deliberately; do not create a second undocumented threshold system.

#### E. Inconsistency explanation

For any profitable block omitted from Run, show the reason inline:

> Profitable overall, but inconsistent: positive in 2 of 5 weekday buckets. The average is lifted by one strong day, so this is not recommended as a standing Meta schedule.

This should be generated from the underlying weekday/day bucket results, not from a generic string in the UI.

#### F. Timing Context / Coverage

Collapse the current large yellow section into a compact disclosure:

```text
ⓘ Timing context & coverage                                      Expand
```

When expanded, retain attribution method, allocation warning, excluded/dropped revenue, ad-set caveat, and the existing “keep budgets unchanged” warning. The section should be open automatically only when attribution is incomplete or directional.

### Phase 2 directional

- One-hour default for accounts with enough data; preserve 2-hour mode for smaller samples.
- Hourly heatmap by day of week.
- Copy schedule button or structured handoff into the Meta launch flow.
- Schedule comparison against the campaign’s current Meta schedule.

## 4. Routing / decision-logic tables

### Recommendation outcomes

| Outcome | Rule | UI treatment |
|---|---|---|
| Recommend Run | Positive profit/ROI, sufficient evidence, stable across weekday/date buckets | Green Run window in top card and detail grid |
| Recommend Avoid | Negative profit/ROI, sufficient evidence, stable negative signal | Red Avoid window; explain evidence |
| Hold | Near break-even or mixed evidence | Amber Hold; no schedule change |
| Profitable but inconsistent | Positive aggregate profit, but consistency below recommendation threshold | Neutral/Inconsistent; explicit explanation |
| Unavailable | Attribution incomplete, revenue untracked, or insufficient evidence | Keep budgets unchanged; show coverage explanation |

### Evidence model

The current `sampleDays` is a count of weekday buckets with spend and revenue, but it does not fully communicate stability. Add or derive these fields:

| Field | Meaning |
|---|---|
| `block_profit` | Revenue minus spend |
| `block_roi` | Profit divided by spend |
| `positive_bucket_count` | Number of underlying weekday/date buckets with positive profit |
| `evidence_bucket_count` | Number of buckets with usable spend and revenue |
| `consistency_rate` | Positive bucket count divided by evidence bucket count |
| `recommendation_status` | `run`, `avoid`, `hold`, `inconsistent`, or `unavailable` |
| `recommendation_reason` | Human-readable reason shown in the UI |

Important: define whether a “bucket” means weekday (`Mon`) or each calendar date-hour observation. For the first MVP, use weekday pooling because it matches the current UI language; add calendar-date variance in Phase 2 if the data supports it.

## 5. Integration specs

### Backend

- Keep `GET /api/v1/intelligence/best-times` as the endpoint.
- Preserve existing hourly Meta breakdown and attribution safeguards.
- Add a response-level `recommended_schedule` object and block-level derived fields.
- Keep `dayparts` for backward compatibility during rollout, but stop using it as the primary UI representation.
- Return `timezone` and ISO date fields as today; no new upstream integration is required.
- If recommendation computation moves server-side, add unit tests for stable positive, stable negative, inconsistent positive, low evidence, and incomplete attribution cases.

Suggested shape:

```json
{
  "recommended_schedule": {
    "status": "run",
    "label": "Mon–Fri · 7 AM–2 PM PT",
    "run_windows": [{"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "start_hour": 7, "end_hour": 14}],
    "avoid_windows": [],
    "confidence": "high",
    "profit": 1240.0,
    "roi": 0.38,
    "positive_bucket_count": 5,
    "evidence_bucket_count": 5,
    "reason": "Positive in 5 of 5 weekday buckets with sufficient spend."
  }
}
```

### Meta handoff

MVP should render exact days/hours in Meta terminology but not mutate Meta schedules automatically. Any future “Apply schedule” action must be separately authorized and should show the exact payload before submission.

## 6. Tracking & analytics spec

Track:

- Best Times opened.
- Campaign/ad set selected.
- Recommendation status viewed.
- Run/Avoid schedule expanded.
- 1-hour vs 2-hour toggle changed.
- Timing Context expanded.
- Confidence/reason explanation expanded.
- Refresh clicked.
- Future: Copy schedule / Apply schedule clicked.

Include `ad_account_id`, selected campaign/ad set, date range, timezone, attribution method, recommendation status, confidence, and schedule label in event properties. Do not log raw revenue payloads if the existing analytics policy does not permit it.

## 7. Build priority / phased rollout

### Ready for review — 1–2 day MVP

1. Add visible date range/timezone context.
2. Add Profit to timing cards.
3. Add 2-hour block display from existing hourly cells.
4. Add High/Medium/Low badge and evidence copy.
5. Collapse Timing Context / Coverage.
6. Add server-backed recommendation status and top-level Recommended Meta Schedule.
7. Add inconsistent-profitable explanation.
8. Add frontend/backend tests for recommendation cases and verify mobile layout.

### Phase 2 — after MVP usage/data review

1. Hourly heatmap by day of week.
2. Date-level variance and stronger confidence calibration.
3. 1-hour view as the default for sufficiently mature data.
4. Copy/export schedule and compare against current Meta schedule.
5. Optional reviewed “Apply to Meta” workflow with a confirmation step and audit event.

## 8. Open questions & dependencies

1. Should the MVP default to 2-hour blocks, with 1-hour detail behind a toggle? Recommendation: yes.
2. Should “avoid” mean negative profit only, or negative ROI below a threshold? Recommendation: use profit/ROI plus evidence; do not avoid on a tiny negative sample.
3. Should recommendations be campaign-level only, or also available at ad-set level? Recommendation: keep both, but label ad-set recommendations as lower-sample investigative guidance.
4. What is the minimum evidence for Abel’s team to act? The current thresholds are a starting point, not yet validated as a business rule.
5. Are Meta schedule changes expected to be manual for this release? Recommendation: yes; render exact instructions first and defer mutation.
6. Do we want “Run” to mean a standing schedule or a controlled test schedule when revenue is allocated? Recommendation: call it **Directional test schedule** whenever attribution is allocated.

## Recommendation

Approve the MVP above. It directly answers “When should I run this campaign?” within seconds, reuses the existing hourly data and timezone/date fields, and adds the missing stability explanation without committing to the more expensive heatmap or Meta write-back work.
