# Campaign Intelligence MVP — Claude Code Handoff

## Decision

Build the first Campaign Intelligence release as a **hardcoded analysis type with flexible date presets**.

Do **not** wait for Joel's full question-set mapping before shipping this MVP. Also do **not** make question sets user-definable yet.

## MVP Scope

### Analysis type

Ship one enum-backed question set:

```js
question_set = "niche_profitability"
```

This answers:

- Which niches are profitable for the selected period?
- Which niches should Joel scale, watch, or pause?
- Is the problem Meta-side cost, RedTrack revenue, or both?

### Date presets

Support these presets:

```js
today
yesterday
last_7d
this_month
last_30d
weekdays_mtd
weekends_mtd
custom
```

Important: `weekdays_mtd` and `weekends_mtd` are **month-to-date filters**.

- `weekdays_mtd`: current month through today, Monday-Friday only
- `weekends_mtd`: current month through today, Saturday-Sunday only
- `custom`: date_from/date_to, all days for MVP

The backend should resolve presets into concrete date ranges plus an optional day filter:

```json
{
  "date_from": "2026-06-01",
  "date_to": "2026-06-14",
  "day_filter": "weekend"
}
```

Allowed `day_filter` values:

```js
all
weekday
weekend
```

## Recommended API Shape

Create a dedicated intelligence route instead of putting the Claude call inside copy generation.

Suggested endpoint:

```http
GET /api/v1/intelligence/niche-profitability?preset=last_7d
GET /api/v1/intelligence/niche-profitability?preset=custom&date_from=2026-06-01&date_to=2026-06-14
```

Response shape:

```json
{
  "question_set": "niche_profitability",
  "preset": "weekends_mtd",
  "date_from": "2026-06-01",
  "date_to": "2026-06-14",
  "day_filter": "weekend",
  "summary": "Plain-English AI summary here.",
  "rows": [
    {
      "niche": "AutoBody",
      "spend": 312.0,
      "revenue": 462.0,
      "profit": 150.0,
      "roi": 0.48,
      "leads": 15,
      "cpl": 20.8,
      "redtrack_conversions": 8,
      "verdict": "scale",
      "reason": "Profitable with positive ROI and stable CPL.",
      "join_status": "matched"
    }
  ]
}
```

## Backend Logic

1. Pull Meta spend/leads/CPL by ad set for the resolved date range.
2. Extract niche using the existing niche extraction logic.
3. Pull RedTrack revenue/conversions by campaign/date for the same resolved date range.
4. Apply `day_filter` before aggregation:
   - `all`: include every date
   - `weekday`: Monday-Friday only
   - `weekend`: Saturday-Sunday only
5. Join Meta and RedTrack by campaign/date, then aggregate by niche.
6. Calculate:
   - spend
   - revenue
   - profit = revenue - spend
   - roi = profit / spend
   - leads
   - cpl
   - RedTrack conversions
   - join_status
7. Generate deterministic verdicts before the AI summary.

Suggested verdict logic:

| Condition | Verdict |
|---|---|
| spend >= 50 and roi >= 0.25 | `scale` |
| spend >= 50 and roi >= 0 | `run` |
| spend >= 50 and roi < 0 and roi > -0.25 | `watch` |
| spend >= 50 and roi <= -0.25 | `pause` |
| spend < 50 | `insufficient_data` |
| Meta spend exists but no RedTrack match | `tracking_check` |

## RedTrack Join Fallback

If Meta has spend but RedTrack has no matching revenue row:

```json
{
  "revenue": 0,
  "redtrack_conversions": 0,
  "join_status": "missing_redtrack"
}
```

The AI summary must distinguish this from confirmed poor performance:

> "Some niches have spend but no matched RedTrack revenue. Treat those as tracking/revenue checks before pausing solely on ROI."

## Claude Prompt Design

Use one prompt for this analysis type:

```js
prompt_template = "niche_profitability"
```

The AI should summarize the already-calculated table. It should not invent metrics or override deterministic verdicts.

Prompt should receive:

- selected preset label
- date_from/date_to
- day_filter
- aggregated rows
- verdict definitions
- join-status notes

Prompt output should include:

- 3-5 sentence executive summary
- scale/run/watch/pause highlights
- warning if `missing_redtrack` rows exist
- one concrete next action for Joel

## Frontend Placement

Put the MVP on Dashboard as a collapsible **Campaign Intelligence** card.

Controls:

- Preset segmented control:
  - Today
  - Yesterday
  - Last 7d
  - This Month
  - Last 30d
  - Weekdays MTD
  - Weekends MTD
  - Custom
- Refresh button
- Custom date inputs only when `custom` is selected

Display:

- AI summary card
- Niche table:
  - Niche
  - Spend
  - Revenue
  - Profit
  - ROI
  - CPL
  - Verdict
  - Join status

## Architecture Position

This is still an MVP because it limits the **question type**, not the date window.

Correct:

```js
question_set = "niche_profitability"
preset = "weekends_mtd"
```

Incorrect for MVP:

```js
freeform_question = "what should I do with plumbers this weekend?"
```

Joel can define more recurring questions later. Each one should become a new enum-backed analysis type, for example:

```js
cpl_trend
budget_opportunity
yesterday_delta
adset_outliers
weekend_vs_weekday
```

## Files Likely Touched

Expected:

- `backend/app/api/v1/intelligence.py` — new route
- `backend/app/main.py` — include router
- `frontend/src/pages/Dashboard.jsx` — Dashboard card

Possible:

- `backend/app/services/facebook_service.py` — if reusing Meta/RedTrack join helpers requires service changes

Reminder: `backend/app/services/facebook_service.py` is a trigger file. If touched, run the required two-agent pre-push review before any push.

## Validation Checklist

- `today`, `yesterday`, `last_7d`, `this_month`, `last_30d` return concrete date ranges.
- `weekdays_mtd` excludes Saturdays and Sundays.
- `weekends_mtd` includes only Saturdays and Sundays.
- Custom date range works for all days.
- Niches aggregate multiple ad sets correctly.
- Meta spend with missing RedTrack appears as `missing_redtrack`, not silently profitable/unprofitable.
- AI summary references the selected range and does not invent numbers.
- Dashboard card loads without blocking the rest of Dashboard.
