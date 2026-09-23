# Ad Builder — Dashboard Overview Redesign Brief

## 1. Executive summary

The current Dashboard is functionally rich but visually reads as a vertically stacked report: KPI cards, CAPI diagnostics, Top Performers, Needs Attention, and Performance by Niche all compete for attention.

The MVP should turn it into an operational command center for Joel:

1. Is the account healthy?
2. What needs intervention now?
3. What should be scaled or remixed?
4. Which niches are working?

The first release should primarily reorganize existing data and actions. It should not require a new analytics warehouse, new Meta fields, or a new attribution model.

## 2. Proposed flow

```text
Dashboard / Overview
        |
        +--> Date range + account context
        |
        +--> KPI strip with period-over-period deltas
        |
        +--> Needs Attention       +--> Performance Trend
        |       |                  |
        |       +--> Pause         +--> Spend / Leads / CPL / ROAS
        |                          |
        +--> Top Performers: scale, quick-generate, inspect
        |
        +--> Performance by Niche
        |
        +--> Account Health: CAPI quality and sync diagnostics
```

## 3. MVP scope — ready for review

### A. Reorder the existing information hierarchy

- Keep the header, account context, date range, Sync, and Refresh controls.
- Keep the five existing KPI cards: Spend, Leads, CPL, Revenue, ROAS.
- Move Needs Attention immediately below the KPI row.
- Place a new compact trend chart beside Needs Attention on desktop; stack it below on mobile.
- Move Top Performers below the action row.
- Keep Performance by Niche below Top Performers.
- Move CAPI Match Quality into a collapsed Account Health section at the bottom.

### B. Improve the KPI strip

Keep the existing values and warning thresholds. Add, where the API already supports the comparison:

- period-over-period delta;
- directional color only when the direction is unambiguous;
- a short comparison label, such as `vs previous 7 days`.

Do not add new attribution calculations in this phase. If a comparison value is unavailable, omit the delta rather than showing a misleading zero.

### C. Make Needs Attention the primary action area

The first actionable block should show the highest-priority issues first. Each row keeps the existing behavior:

- issue reason;
- spend and CPL;
- budget control;
- Pause action;
- link to Campaign Performance.

MVP presentation changes:

- limit the initial view to the three most important issues;
- show a clear `See all N` action;
- use a stronger severity treatment for red versus orange issues;
- preserve the existing pause confirmation and error handling.

### D. Add a lightweight Performance Trend chart

The chart should use data already returned or cheaply available from the existing dashboard endpoint. MVP options, in order of preference:

1. daily Spend and Leads with a selectable secondary metric;
2. daily CPL and ROAS if both series are reliable;
3. a simple sparkline summary if a full daily series is not currently available.

The chart needs:

- the active date range;
- one primary metric at a time;
- hover or accessible labels for dates and values;
- no fabricated interpolation for missing days;
- a clear empty state when the range has insufficient data.

If the current endpoint cannot provide a daily series without a broad backend change, ship the layout first with a compact trend placeholder and make the chart Phase 1B.

### E. Preserve the strongest existing actions

Do not remove or relocate these actions out of context:

- `+20%` scaling;
- `Quick Generate`;
- `Pause`;
- `View all in Performance`.

For CBO rows, retain the existing warning that scaling affects the campaign, not only the displayed ad set.

## 4. Wireframe and copy

```text
Overview                                      [Last 7 Days v] [Sync] [Refresh]
DIN Auto Insurance · 18 active ad sets

Spend          Leads          Blended CPL      RT Revenue      RT ROAS
$12,420        183            $67.87           $18,900         1.52x
↑ 8%           ↑ 14%          ↓ 5%             ↑ 11%           ↑ 7%
vs prev. period

NEEDS ATTENTION                         PERFORMANCE TREND
3 items require action                 [Spend] [Leads] [CPL] [ROAS]
🔴 High CPL · Commercial · $94.20      chart
🟠 Frequency rising · Auto · 3.1       Last 7 Days
🟠 No recent leads · Mortgage           [View performance]
[See all 3]

TOP PERFORMERS                           PERFORMANCE BY NICHE
Ad set | Spend | CPL | ROAS | Actions   Niche | Spend | Revenue | ROAS | CPL

ACCOUNT HEALTH                            [collapsed by default]
CAPI quality · last sync · data warnings
```

Recommended copy changes:

- Page title: `Overview` rather than `Dashboard`.
- `Needs Attention`: `What needs action` may be clearer, but retain the existing label if Joel already recognizes it.
- CAPI section title: `Account Health`, with `CAPI Match Quality` as the internal subsection label.
- Empty attention state: `All clear — no ad sets currently need action.`
- Trend empty state: `Not enough daily data for this range.`

## 5. Routing and decision logic

| Condition | Dashboard behavior |
|---|---|
| Red issue exists | Show first in Needs Attention with red severity and pause action |
| Orange issue exists | Show after red issues with orange severity |
| More than 3 attention items | Show 3, then `See all N` |
| No attention items | Show green all-clear state |
| ROAS unavailable | Show `—`; do not infer zero |
| Revenue unavailable | Keep RT cards visible with an awaiting-sync explanation |
| Daily trend unavailable | Show compact empty state; do not block the rest of the dashboard |
| CAPI fetch error | Keep Account Health expandable and show its existing recovery copy |
| Mobile viewport | Stack trend below Needs Attention; tables remain horizontally scrollable |

## 6. Integration and data impact

### No new database schema in MVP

The first pass should consume the existing Dashboard payload and existing CAPI endpoints. No Alembic migration is justified for the layout change.

### Possible backend addition for Phase 1B

If the current dashboard endpoint does not expose daily points, add a narrowly scoped read-only field such as:

```json
{
  "trend": {
    "granularity": "day",
    "points": [
      {"date": "2026-09-12", "spend": 120, "leads": 4, "cpl": 30, "roas": 1.2}
    ]
  }
}
```

The backend should calculate from the same source and date range as the headline cards. Do not mix Meta and RedTrack windows silently.

## 7. Tracking and analytics

Add frontend interaction events only if the project’s existing event path supports them:

- `dashboard_viewed` with date preset and account;
- `dashboard_attention_item_opened`;
- `dashboard_pause_clicked`;
- `dashboard_scale_clicked`;
- `dashboard_quick_generate_clicked`;
- `dashboard_trend_metric_changed`;
- `dashboard_account_health_expanded`.

The redesign should also log which dashboard block Joel opens first, which is the most useful validation of whether the new hierarchy works.

## 8. Build priority

### Phase 1 — MVP layout, low risk

- Reorder sections.
- Add responsive two-column action/trend shell.
- Improve KPI hierarchy and labels.
- Collapse Account Health by default.
- Keep all existing actions and API calls.
- Add loading, empty, error, and mobile states.

### Phase 1B — trend data

- Add daily series only if the existing payload cannot support it.
- Validate that the trend uses the same period and attribution source as the cards.
- Add one chart, not a dashboard builder.

### Phase 2 — optional refinement

- Saved dashboard view or default date preset.
- Comparison against previous period with explicit methodology.
- Alert history or recurring issue tracking.

## 9. Acceptance checks

- Joel can identify the highest-priority issue without scrolling past CAPI diagnostics.
- The first viewport shows KPIs plus at least one actionable block on desktop.
- Needs Attention still pauses the intended ad set and handles errors correctly.
- Top Performer scaling preserves the existing CBO warning.
- Quick Generate continues to open with the correct ad set context.
- CAPI is still available but no longer dominates the primary workflow.
- Mobile layout does not clip controls or hide action buttons.
- No new migration is required for the MVP.
- Existing Dashboard loading and error states remain understandable.

## 10. Open questions and dependencies

- Does the current dashboard API already return daily points, or should the trend chart be Phase 1B?
- Should the default date range remain the current preset or change to Last 7 Days?
- Does Joel prefer the term `Needs Attention` or `What needs action`?
- Should Account Health remain on Overview or eventually become its own diagnostics page?

## Recommendation

Approve Phase 1 as a frontend-first information-hierarchy redesign. The biggest improvement comes from moving action-oriented content above diagnostics and giving the page one visual trend anchor. Do not begin with a new reporting backend or a customizable dashboard system.
