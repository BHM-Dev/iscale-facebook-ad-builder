# Ad Builder — Performance Brief

## 1. Executive summary

**Problem.** Joel needs a fast way to distinguish a real economic deterioration from normal delivery volatility without adding a Slack feed, hard-coding a CPL target, or forcing him out of his existing Campaign Performance workflow.

**MVP.** Add a quiet Dashboard entry point and a dedicated Performance Brief page. The page reviews a completed date range against the immediately preceding equal-length range, identifies only material problem days, and links directly to the existing ad-set view for inspection.

**Economics.** The account-level view uses exact Switchboard billable revenue only when the existing P&L mapping is available: configured offer plus exact Meta ad-set ID in Everflow `sub3`. A day can be weak with a low CPL if revenue per lead is lower; a high CPL is not automatically bad when revenue per lead supports it. Ad-set rows remain Meta delivery diagnostics and do not pretend to allocate account revenue.

## 2. Flow diagram

```text
Dashboard date/account context
        |
        +--> Quiet “Performance Brief” card
                   |
                   v
Completed-day Performance Brief
        |
        +--> Account economics: Meta + exact Switchboard revenue
        +--> Material problem days: spend-weighted RPL exception
        +--> Delivery contributors: Meta ad sets, current vs matched prior period
                   |
                   v
Campaign Performance filtered to exact ad set and date range
```

## 3. Detailed specification, wireframe, and copy

### Dashboard card

```
[ Performance Brief                                      Open review → ]
  Completed-day review combines Meta delivery with exact Switchboard billable
  revenue. Problem days and contributors appear only when material.
```

The Dashboard card does not post to Slack, send notifications, or change ads.

### Full page

1. Date picker defaults to the last seven completed days; today is excluded.
2. Five account-level metrics: spend, leads, CPL, billable revenue, revenue per lead. Each compares with the preceding equal-length completed period.
3. “Problem days worth inspecting” only includes a day with at least 10% of period spend when either:
   - revenue per lead is at least 25% below the period’s observed average; or
   - material spend produced no readable Meta leads.
4. “Ad sets to inspect” only includes current Meta delivery evidence:
   - spend without leads, or
   - spend increased at least 25%, CPL increased at least 25%, and both periods have readable CPL.
5. Every ad-set row links into Campaign Performance with the current date range.

Copy is intentionally diagnostic: “inspect,” “watch,” and “delivery context,” never “pause” or “scale.”

## 4. Routing and decision logic

There is no static CPL target. The core comparison is economics observed inside the selected period:

```text
if exact account revenue is available:
  compare daily revenue per lead with selected-period revenue per lead
else:
  limit the brief to Meta delivery signals and disclose the gap
```

This makes `$15 CPL / $20 RPL` different from `$11 CPL / $9 RPL` without pretending all commercial-insurance niches have the same economics.

## 5. Integration and passthrough specifications

`GET /api/v1/dashboard/performance-brief?ad_account_id=&date_from=&date_to=` returns:

- current and prior equal-length daily Meta delivery;
- exact current/prior daily Switchboard revenue only with existing P&L permission and exact mapping;
- account totals and material-day flags;
- current/prior Meta ad-set delivery joined to local campaign names.

The endpoint is read-only and uses the Dashboard’s scoped-account resolver and bounded, deep-copy cache. It does not make a Meta write, create an ad, alter budgets, or invoke Slack.

## 6. Tracking and analytics

MVP records no new external events. The decision artifact is the page itself, and source provenance is visible in the UI. Phase 2 may add local-only `performance_brief_opened`, `problem_day_opened`, and `adset_drilldown_opened` events if we need to prove use before adding recurring briefs.

## 7. Phased rollout and priorities

### Ready for review

- Dashboard entry card
- Completed-day Performance Brief route
- Exact account economics with source status
- Material daily exception logic
- Meta-only delivery contributors and drill-through
- Unit tests for unknown revenue, real zero revenue, exception threshold, and ad-set join behavior

### Phase 2 / directional

- Weekly saved snapshot and a compact historical comparison
- Optional local usage telemetry after the team has used the page
- Creative/package rollups only after a reliable creative-to-delivery join exists
- Narrative AI only if the deterministic brief demonstrates that it improves decisions

## 8. Open questions and dependencies

- Billable account revenue remains unavailable until the existing Switchboard account/offer configuration and exact ad-set mapping are present.
- Revenue and spend are conversion-date/delivery-date views, not cohort-matched lead revenue. The page discloses this rather than presenting it as settled profit.
- The page is designed for review, not automatic action. Any future automated pause/scale recommendation requires separate, approved guardrails.
