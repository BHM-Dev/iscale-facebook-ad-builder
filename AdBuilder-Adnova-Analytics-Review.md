# Adnova Analytics Review

**Review date:** 2026-09-16  
**Workspace:** Bright Horizons Media / Get Business Coverage  
**Connected account:** RHO - Commercial Insurance  
**Scope:** Read-only walkthrough of Adnova Analytics after account sync. Reviewed the left rail, report navigation, charts, tables, filters, metric configuration, Compass, snapshots, comparative reports, and AI-report availability.

## 1. Executive summary

Adnova Analytics is strongest as a **creative decision workflow**, not as a general reporting dashboard.

The left rail gives the user three ways to work:

1. **Compass** — what deserves attention now.
2. **Saved report families** — where performance is concentrated by creative, copy, landing page, headline, or video.
3. **Custom reports / boards** — reusable analysis for a specific question.

That is a better mental model than placing every metric inside one Campaign Performance table. It answers the media buyer's actual sequence:

```text
What should I look at?  →  Why is it working?  →  What should I make next?
     Compass              report dimensions          Research / Remix
```

My recommendation is to borrow this structure for Ad Builder, but replace Adnova's purchase-first economics with BHM's actual operating metrics: spend, leads, CPL, revenue, ROAS, phone rate, agent acceptance/contact, and RPU.

The immediate opportunity is a **Creative Compass layer inside Campaign Performance**, followed by flexible report views. This is more valuable than building a broad analytics dashboard or gated AI taxonomy first.

## 2. Left-rail information architecture

### What Adnova shows

At the account level, the rail displayed:

```text
Bright Horizons Media / Get Business Coverage
└── Ad Account
    └── RHO - Commercial Insurance
        ├── Snapshots
        ├── Compass
        ├── Create Report
        │   ├── Top performing
        │   ├── Comparative analysis
        │   └── Compass
        └── Analytics Boards
            ├── Reports
            ├── Top creatives
            ├── Top copy
            ├── Top landing page
            ├── Top headlines
            ├── Top performing video hooks
            └── AI Reports
```

The AI Reports folder expands into tactic-specific analyses: Hook Tactic, Headline Tactic, Text Hook, Visual Hook, Theme, Asset Type, Offer, Seasonality, Persona, USP, Desire, Ad Angle, Funnel Breakdown, and Emotion.

### What works

- **Account context is always visible.** The user can tell which ad account is active without returning to a dashboard.
- **Compass is privileged.** It sits above the report library because it is an action surface, not a passive data view.
- **Report families use plain language.** “Top copy” and “Top landing page” are immediately understandable.
- **Create Report is a good escape hatch.** It offers three clear report intents instead of asking users to configure everything from scratch.
- **Boards are used as an organizing layer.** Reports can be treated as a working library rather than one-off analysis.
- **AI Reports are separated from deterministic reports.** This communicates that taxonomy/interpretation is an additional layer.

### What is weaker

- The rail is **long and flat** once all report types are visible. It becomes a report inventory rather than a prioritized workflow.
- “Reports” is ambiguous because it is both a board/folder label and a general category.
- There is no obvious **“Today” or “Needs attention” default landing state** after account sync. Compass is the closest equivalent.
- The active report is visually subtle; with many report names, it would be easy to lose the current context.
- “Snapshots” had no content in this account, so its purpose is not self-explanatory until a user has saved one.
- AI Reports appear prominent even though the account showed **“Unlock AI Tagging for your account.”** This creates an expectation gap during trial evaluation.
- Trial urgency (“05 days 19 hours”) is placed in the rail and competes with navigation. It is commercially useful but not product-navigation useful.

### Ad Builder recommendation

Use a two-tier rail or top-level switcher:

```text
Campaign Performance
├── Overview
├── Needs attention
├── Winners
├── Scaling
├── High-potential tests
└── Reports
    ├── By ad
    ├── By ad set
    ├── By campaign
    ├── By hook / angle
    └── Saved views
```

Keep Research separate as the **market/inspiration loop**. Analytics should hand a winning ad directly into Remix, Batch Generate, and Research—not make the user navigate back through a generic gallery.

## 3. Compass: Adnova's strongest product idea

Compass described itself as evaluating creative performance to uncover winning, scaled creatives and opportunities. It exposed five action-oriented tabs:

- **Launched Since Last 14 Days** — 35 creatives
- **Scaled Spend > $250** — 3 creatives
- **Winner: Scaled and ROAS > 1** — 0 creatives
- **High Potential Iteration Candidates** — 11 creatives
- **Custom Groups** — 35 creatives in 1 custom group

The high-potential list included creative, achievement, Click score, Hook score, Watch score, Convert score, Spend, and ROAS. For example, a commercial-insurance creative appeared as Scaling with $4,006.93 spend and 0.2 ROAS.

### Why this matters

Adnova does not force the user to infer action from a 143-row table. It creates a shortlist and labels the state of the creative. That is exactly the layer Joel needs when deciding what to pause, iterate, or scale.

### Important limitation

The scoring model is opaque. “Click score,” “Hook score,” “Watch score,” and “Convert score” are useful labels, but the user is not shown the thresholds, weighting, or minimum sample size. A score can look authoritative while hiding low-volume or attribution-quality issues.

### Ad Builder version

Build this with transparent BHM rules first:

| Surface | Initial rule | Primary action |
|---|---|---|
| Newly launched | Launched within 14 days | Monitor / open breakdown |
| Scaling | Spend above configurable threshold or budget growth | Inspect economics |
| Winner | Minimum spend + ROAS above 1, or CPL below target | Remix / duplicate |
| High potential | Strong CTR or early lead rate, insufficient spend | Give more budget / test |
| Needs attention | No leads, CPL above threshold, or RT ROAS below 1 | Pause / inspect |

Every label should expose the rule behind it. Use “High potential: CTR 2.1%, 4 leads, only $74 spend” rather than an unexplained score.

## 4. Report families

### Top creatives

The default report covered 2026-09-02 through 2026-09-15 and grouped by Ad Name. It showed a Spend + ROAS combo chart, followed by a table with 143 items and 20 rows per page.

The default table included:

```text
Ads | Spend | Purchase value | ROAS | CTR (all) | CPC (link click)
    | CPM | CPC (all) | AOV | Click to ATC ratio | Purchases
    | 1st frame retention | Thumbstop | CTR (outbound) | Click to purchase
```

This is a strong “find the concentration” view. It makes it easy to see which ads consumed spend and whether reported purchase value followed. It also includes useful creative diagnostics such as thumbstop and first-frame retention, even though this account's video fields showed 0% for the displayed rows.

The table had a Net Results row, sortable columns, pagination, expandable ad rows, and a custom-columns control.

### Top copy

Top copy grouped ads by the full copy text, with a letter identifier and an ad count. This is useful because one piece of copy may be reused across multiple creatives. The report surfaced both spend concentration and downstream purchase performance.

This is a good model for Ad Builder's Remix workflow: identify the copy pattern that is carrying spend, then generate creative variants around that copy rather than treating every ad as an isolated object.

### Top landing page

Top landing page grouped by destination URL. It exposed how many ads used each destination and paired the URL with spend, purchase value, ROAS, CTR, CPC, and purchase metrics.

This is valuable for diagnosing whether the creative is the problem or the handoff after the click. Ad Builder should eventually add destination-domain/landing-page grouping, but the BHM version must connect the URL to lead quality and revenue, not just purchase value.

### Top headlines

Top headlines grouped by headline and showed the number of ads using each headline. The account had 96 headline groups. This is especially relevant to the naming/copy work already done in Ad Builder: it gives a direct read on whether a repeated hook is actually associated with efficient acquisition.

### Top performing video hooks

This report correctly narrowed itself to “Ad type is Video,” but the connected account returned **No ads found for your search**. That is an important product behavior: the report explains the empty state instead of showing a meaningless chart.

For Ad Builder, the empty state should also explain what is missing: “No video ads with enough delivery in this date range. Try Last 30 days or remove the minimum-spend filter.”

## 5. Charts and data display

### Chart pattern

The primary chart is a compact combo chart: bars/values for Spend and a second scale for ROAS. It shows concentration well, but it is not a trend chart. It answers “which groups are large?” more than “when did performance change?”

The chart had three view tabs, but the accessible labels did not make their purpose clear. This is a discoverability issue: users can see that alternate views exist but cannot predict what they will show.

### Table pattern

The table is the more valuable surface for real optimization work because it supports:

- many simultaneous metrics;
- sorting;
- pagination;
- expandable ad rows;
- selection checkboxes;
- configurable visible columns;
- optional active status, tags, and launch date;
- a Net Results summary row.

The downside is density. Fifteen columns make the table powerful but difficult to scan on a normal laptop. The first screen is optimized for analysts, not for a media buyer who needs a quick decision.

### Ad Builder recommendation

Use two display modes:

1. **Decision mode:** 6–8 columns maximum, with status chips and action buttons.
2. **Analysis mode:** horizontally scrollable/customizable table with saved metric sets.

Recommended Decision mode columns:

```text
Ad / thumbnail | Status | Spend | Leads | CPL | RT Revenue | RT ROAS | Action
```

Recommended Analysis mode additions:

```text
CTR | CPC | CPM | outbound CTR | landing-page views | phone rate
agent acceptance | agent contact | RPU | launch date | ad set | campaign
```

## 6. Filters, dimensions, and metric configuration

Adnova's report controls are one of its strongest reusable patterns:

- explicit start/end dates;
- preset date ranges;
- group-by selector;
- metric chips that can be removed and reordered;
- Add Metrics picker;
- Dimension selector;
- custom columns;
- table settings;
- attribution-window control.

The available dimensions included Campaign Name, Ad Set Name, Ad Name, Ad Type, Distribution Format, Ad Status, Ad Launch Time, Ad ID, Tags, Delivery, and Naming Convention Properties.

This is the right abstraction. The user chooses the question's grain before reading the table.

### Ad Builder gap

Ad Builder currently has useful date controls and Meta/RedTrack performance columns, but it is still primarily a page-level operational table. It does not yet let Joel switch the same report between ad, ad set, campaign, headline, copy, destination, or angle.

### Highest-value MVP

Add a **View by** control to Campaign Performance:

```text
View by: Ad set | Ad | Campaign | Headline | Copy | Landing page | Angle
```

Only expose dimensions that are reliably available in our data. Headline/copy/landing-page grouping can start from the existing ad creative payload and local records; angle should remain optional until tagging quality is proven.

## 7. Metrics: what to borrow and what to reject

Adnova offers a broad metric picker, including Meta delivery metrics, video retention, click quality, ATC, purchases, CPA, leads, cost per lead, cost per contact, and its creative scores.

Borrow:

- user-selected metric chips;
- drag/reorder or sortable metric list;
- default metric sets by report type;
- attribution-window control shown next to the report;
- clear “No data” handling for unsupported creative types.

Do not adopt Adnova's purchase-first defaults for BHM. The connected report's key economics were Purchase value and ROAS, but those are not the business truth for our lead-gen operation.

BHM's primary analytics contract should be:

```text
Meta spend
→ leads
→ qualified/accepted leads
→ phone/contact outcomes
→ billable revenue
→ RPU and ROAS
```

Revenue should remain reconciled through `session_id` and the existing RedTrack/Switchboard/Everflow architecture. Adnova's purchase value is useful as a reference metric, but it should not replace BHM's revenue truth.

## 8. Snapshots, custom reports, and AI reports

### Snapshots

Snapshots had a clean empty state: “No snapshots found!” The feature is understandable once used, but the empty state does not explain what a snapshot preserves or why Joel would create one.

Ad Builder should defer snapshots until saved views have a concrete use case, such as preserving a pre-launch baseline or recording a weekly optimization review.

### Comparative analysis

The custom report builder was well structured. It exposed:

- report title and description;
- date range;
- metrics;
- dimension;
- two comparison-group rows;
- group name;
- filters;
- Add group.

This is a useful Phase 2 pattern for comparing angles, brands, ad sets, or landing pages. It should not be the first analytics build because it depends on reliable group definitions and stable attribution.

### AI Reports

The AI taxonomy is strategically interesting, especially Hook, Visual Hook, Theme, Offer, Persona, USP, Desire, Ad Angle, Funnel Breakdown, and Emotion. However, clicking an AI report in the connected account showed **Unlock AI Tagging for your account / Book a call**.

Recommendation: do not make AI tagging the first analytics investment. Start with deterministic fields and transparent rules. Add structured creative taxonomy after we have enough reliably labeled ads to validate whether the tags predict CPL, RPU, or ROAS.

## 9. Direct comparison to Ad Builder

| Need | Adnova | Ad Builder today | Recommendation |
|---|---|---|---|
| Account context | Persistent account in rail | Implicit in page/API context | Show selected Meta account prominently |
| “What should I do?” | Compass tabs | Needs Attention + Top Performers | Add Creative Compass tabs |
| Ad-level economics | Spend, purchase value, ROAS, many Meta metrics | Meta + RedTrack by ad set/ad | Make BHM revenue metrics first-class |
| Flexible grain | Ad, copy, headline, landing page, dimensions | Mostly operational ad set view | Add View by selector |
| Saved analysis | Reports, boards, snapshots | Not a central workflow | Add saved views after MVP |
| Creative diagnostics | Hook/watch/convert scores and video metrics | Basic performance + remix actions | Add transparent diagnostics, not opaque scores |
| AI taxonomy | Broad but gated | Angle tags and copy framework | Validate deterministic taxonomy first |
| Downstream action | Mostly analysis | Remix, Batch Generate, Push to Meta | Preserve Ad Builder's stronger action handoffs |

Our advantage is that Ad Builder already connects analysis to making and launching ads. Adnova's advantage is that it makes the analysis itself feel like a product rather than a table.

## 10. Recommended build sequence

### Ready for review: Phase 1

Build a read-only **Creative Compass** on Campaign Performance using existing data sources.

```text
Creative Compass
├── Launched recently
├── Scaling
├── Winners
├── High-potential tests
└── Needs attention
```

Each card/row should show the rule, the metric evidence, and a clear next action. Every item should link to the existing Remix, Batch Generate, campaign, or ad-level breakdown flow.

Minimum metrics:

- spend;
- leads;
- Meta CPL;
- RedTrack/Switchboard revenue;
- RT ROAS;
- CTR;
- launch date;
- ad set and campaign;
- ad status.

### Ready for review: Phase 1.5

Add report controls:

- date preset/custom date range;
- View by dimension;
- metric chips;
- saved metric presets for “Lead gen,” “Creative,” and “Video”;
- results-per-page control;
- active status / launch date display toggles.

### Phase 2 directional

- saved reports and snapshots;
- compare two or more groups;
- workspace-shared boards for reports;
- trend charts with period-over-period comparison;
- deterministic creative tags for angle, hook, offer, and format;
- AI-assisted labeling only after tag quality and outcome joins are proven;
- export/shareable weekly review.

## 11. Open questions and dependencies

1. Which revenue source is authoritative per Meta account: RedTrack, Switchboard, or Everflow?
2. Can each ad reliably be joined to lead, phone, acceptance, and revenue outcomes today, or is the first Compass version limited to ad-set-level downstream economics?
3. What minimum spend and minimum leads should qualify an ad for Winner or High Potential?
4. Should Joel's default home be Compass, or should Campaign Performance remain the home with Compass as the first tab?
5. Do we want workspace-shared saved views, or personal saved views plus a small set of team defaults?
6. What is the first decision we want to improve: reallocating spend, choosing Remix candidates, or identifying new creative angles?

## Final POV

Adnova's Analytics is worth borrowing for its **navigation and decision framing**, especially Compass and the report-family rail. It is not a model for BHM's final economics because its default view is purchase/ROAS oriented and its most interesting creative intelligence is gated.

The best next move is a narrow, transparent Creative Compass that turns our existing Meta + RedTrack data into prioritized actions and hands those actions directly into Remix and Batch Generate. That would improve Joel's daily loop without opening a new speculative analytics platform project.
