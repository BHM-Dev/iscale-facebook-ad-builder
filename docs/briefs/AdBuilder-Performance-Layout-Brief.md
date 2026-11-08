# Campaign Performance Layout — Brief

**Date:** 2026-11-07 · **Owner:** Steve · **Builder:** Codex (Phase 1), Claude Code reviews and pushes
**Prototype:** `docs/briefs/AdBuilder-Performance-Layout-Prototype.html` (open in a browser; sample data)
**Inputs:** `AdBuilder-GetHookd-Layout-Addendum.md`, `AdBuilder-AdStellar-Layout-Addendum.md` §4

---

## 1. Executive summary

**Problem.** `/campaign-performance` stacks four full-width sections:

1. Daily Close card
2. Proposals panel
3. Creative Compass
4. Performance table

On a laptop, the table Joel works in starts roughly two screens down. Filters sit in the table's header and scroll away. Everything is visible at once, so nothing stands out.

**Solution: the table owns the first screen.**

- The close shrinks to a single strip.
- Proposals move to a collapsible rail on the right, beside the table, so a proposal and its ad-set row are visible together.
- Creative Compass and Intelligence become tabs.
- One sticky toolbar holds every filter.
- A goal line answers Joel's first question before he reads a single row: how many ad sets are over Max CPL right now?

**Economics.** This is a time and attention fix, not a revenue feature:

- Joel opens this page several times a day.
- The test is time to first action on an over-goal ad set.
- Today that means scrolling, then an unsorted visual hunt. After the change it is one click on "9 over Max CPL".
- No new Meta reads in Phase 1, so no rate-limit exposure on RHO.

**What it does not do:** no new Meta writes, no inline budget editing beyond what exists today, and no chat UI.

---

## 2. Layout

### Today
```
Header: title · +Add Rule · Intelligence ▸ · Sync · freshness · date
[deep-link banner]
┌ Yesterday's close (≈260px tall) ───────────────────────┐
┌ Proposals (≈300–600px, grows with count) ──────────────┐
┌ Creative Compass (≈200px) ─────────────────────────────┐
┌ Performance  [collapse][rotation][search][metric][status][sort][↻]
│ campaign rows → expand → ad-set table → expand → ads  │
```

### Proposed
```
┌ Campaign Performance   [RHO Commercial ▾] [Last 7 days ▾]   Synced 4m ago  [Sync] [⋯] ┐
├ Thu Nov 6 closed +$615 · $6.7k spend · 1.09x · 167 leads · MTD +$12.3k (pace +$30.4k)  Details ▸  Copy ┤
├ [ Ad sets ]  [ Creative Compass ]  [ Intelligence ]                                      ┤
├─ sticky ───────────────────────────────────────────────────────────────────────────────┤
│ 38 spending · ● 29 under Max CPL · ● 9 over · ○ 4 no Max CPL   │ 🔍 │ Filters(2) │ Sort ▾ │ ☰ Group │ Proposals 4 │
│ [Niche: Towing ×] [Status: Active ×] [Clear all]                                       │
├──────────────────────────────────────────────────────────┬─────────────────────────────┤
│ TOTAL  $6,187  180  $34.37  —  1.09x  +$615              │ Proposals (4)          [×]  │
│ ▸ RHO v1 | ABO | LIMO | 10.06      $1,840 …              │ ┌ PAUSE  Funeral — CBO 2  ┐ │
│     ▸ WW3-LIMO-SUV-02  Active  $1,212 31 $39 $45 …       │ │ CPL $71 vs Max $45, 3d  │ │
│     ▸ WW3-LIMO-SED-01  Paused (campaign) …               │ │ ▁▂▃▅▇  data thru Nov 6  │ │
│ ▸ TOWING …                                               │ │ [Approve] [Dismiss]     │ │
│                                                          │ └─────────────────────────┘ │
└──────────────────────────────────────────────────────────┴─────────────────────────────┘
```

**Rules:**

- The rail is **320px** at ≥1280px wide. Below that it becomes an overlay drawer opened from the "Proposals 4" button.
- Open/closed state persists in localStorage (`perfProposalsRail`).
- **Default open when there are pending proposals.** Closed otherwise, so the table gets the full width.
- Clicking a proposal card scrolls to its ad-set row and highlights it; the parent campaign expands if collapsed. The existing `highlightedAdsetId` path already does this.
- The sticky region is the toolbar plus the chip row. It pins under the app header once scrolled.
- The table header row pins directly beneath it.

### Deliberate departures from the addenda

| Addendum said | This brief says | Why |
|---|---|---|
| Ad-set click opens a right drawer (GetHookd) | **Keep inline expansion** | The rail already owns the right side, and two right-side panels fight each other. `AdsBreakdown` (Remix, Quick Ad, ad pause) is tested and is Joel's muscle memory. Revisit only if inline expansion becomes the complaint. |
| Proposals as a tab (GetHookd) vs docked panel (AdStellar pass 1) | **Docked rail** | A proposal is about one row. Side-by-side is the whole point. A tab hides the row you are approving against. |
| 7-day sparkline column | **Phase 2 compare chart** | Per AdStellar §4.5. A sparkline column needs daily data for every row, which means a new Meta read. Select-to-compare loads only 2–5 ad sets. |

---

## 3. Detailed spec (Phase 1 — ready for review)

### 3.1 Header (one row)

- **Left:** "Campaign Performance" as h1, text-xl, with no subtitle line. The "Live Meta insights · RedTrack…" subtitle is removed.
- **Right, in order:**
  1. Account selector (existing)
  2. Date preset plus custom range (existing)
  3. Freshness pill (existing `summarizeSyncFreshness`)
  4. Sync button
  5. A `⋯` menu containing **Add auto-pause rule** (opens the existing `AddRuleModal`)
- `CampaignIntelligencePanel` moves out of the header into the **Intelligence** tab (§3.3).
- The weekend hint ("Weekend — switch to Last 7 Days") stays. It renders as a tooltip on the date select, not a line of text.

### 3.2 Close strip

`DailyCloseCard` gets a `variant` prop: `'strip' | 'full'`, default `'full'`, so any other caller is unchanged.

The strip is one line, `text-sm`:

```
{Day Mon D} closed {±$profit} · {$spend} spend · {roas}x · {leads} leads · MTD {±$mtd} (pace {±$pace})   Details ▸   Copy
```

- Profit is green or red. The rest is gray-700.
- Below ~900px it wraps to two lines. Never truncate a number.
- **Details ▸** opens a right drawer (480px, backdrop) that renders the existing full card unchanged:
  - per-account split
  - top/bottom 3 movers (full names, per `1023f1a`)
  - partial-data warnings
- **Copy** uses the existing `formatCloseForSlack`.
- **State lines are kept verbatim:** pending, error, Everflow-unavailable, and partial. For partial, the strip appends an amber "· partial: missing {account}" segment. Never hide it in the drawer.
- Events:
  - existing `close_card_viewed` keeps firing on strip render;
  - add `close_details_opened` (check the `/daily-close/event` allowlist and extend it).

### 3.3 Tabs

`Ad sets` (default) · `Creative Compass` · `Intelligence`.

- **URL:** the `tab` param (`?tab=compass`). Back and forward work, and a reload restores the tab.
- **Compass tab:** the existing `CreativeCompass` component, unchanged in Phase 1. `openCompassAdset` must also switch `tab` back to `adsets` before highlighting. Today it sets `view=compass` and scrolls, so verify the deep link still lands on the row.
- **Intelligence tab:** renders `CampaignIntelligencePanel` with `initialOpen` true. It keeps its own preset selector, which already inherits the page date.
- The tab bar shows **no** counts on Compass or Intelligence. Counts are for things that need action.

### 3.4 Goal line (left side of the sticky toolbar)

Computed client-side from data the page already loads: `bulkInsights` and `maxCplData`. No new endpoint.

```
{n} spending · ● {a} under Max CPL · ● {b} over · ○ {c} no Max CPL
```

**Counts:**

- **spending:** visible-scope ad sets (current account, current date range, before toolbar filters) with spend > 0.
- **under:** has a Max CPL and `cpl <= max_cpl`.
- **over:** has a Max CPL and either:
  - `cpl > max_cpl`, or
  - zero leads with spend ≥ max_cpl. **Zero-lead spend counts as over** once it exceeds one Max CPL. That is the case Joel most needs flagged, and a null CPL must not hide it.
- **no Max CPL:** spending, but `maxCplData` has no entry or is unavailable.

**Display:**

- Dots use the same green, red and gray as the Max CPL cell.
- Each count is a button that applies the filter. Clicking an active chip again clears it. These are two new `statusFilter` values, `over_max` and `under_max`, plus `no_max`.
- If `maxCplData.available === false`, render `{n} spending · Max CPL unavailable`. Never show zeros.
- While `bulkInsightsLoading`, render `Loading…`. Never show zeros.

Event: `goal_chip_clicked {chip}`.

### 3.5 Sticky toolbar (right side) and the chip row

- **Search:** the existing name search, always visible.
- **Filters (n):** a popover containing:
  - status select (existing options minus `top_performers` and `refresh_soon`, which become presets in the same popover)
  - niche
  - metric threshold (existing CPL/Spend/RT ROAS `<`/`>` value)

  `n` is the count of active filters.
- **Sort ▾:** existing options, plus `Over Max CPL first`, which sorts by `cpl / max_cpl` descending, nulls last.
- **Group by campaign** toggle, default **on** (today's view).
  - **Off** gives a flat ad-set list: campaign name as a gray second line under the ad-set name, and sort applies across all campaigns. This is the Ads Manager "Ad sets" tab view.
  - Persist it in localStorage `perfGroupByCampaign`.
- **Rotation queue** moves into the Filters popover as a preset with its count. The amber explainer banner stays when the preset is active.
- **Proposals {n}** toggles the rail and shows its badge count.
  - The nav badge deep link (`e604af6`) must open the rail and close any open drawer.
  - The Facebook hub tile count (`df171d6`) is unchanged.
- **Refresh ↻** (existing handler).

**Chip row** (only rendered when at least one filter is active): one removable chip per active filter, plus "Clear all".

The **dashboard deep-link banner is replaced by chips**:

- `view=attention` → chip `Needs attention ×`
- `niche` → `Niche: X ×`
- `adsetId` → `Viewing: {name} ×`
- `view=top-performers` → `Top performers ×`

Removing a chip clears exactly that piece of state and its URL param. The current banner's × resets everything, which loses the date range. That is the bug AdStellar's Top Ads has, so don't copy it.

### 3.6 Campaign drill

- Clicking a **campaign name** (not its chevron) applies a `Campaign: {name} ×` chip and shows only that campaign's ad sets, expanded. The date range is untouched. This is Ads Manager's campaign → ad sets drill.
- Chevron behavior is unchanged.
- Implement it as a new `campaignFilter` state plus a `campaign` URL param.

### 3.7 Table

- **Total row** pinned at the top of the table body, for the current filtered scope: spend, leads, blended CPL, blended ROAS, profit. It reads "Total · {n} ad sets". It uses the same columns as the rows, and no Max CPL total.
- **Effective status column** (ad-set rows):
  - `Active`
  - `Paused`
  - `Paused (campaign)`: the ad set is ACTIVE but its campaign is not. Campaign status is already on the grouped campaign object.
  - `Off (budget 0)`, if applicable
  - `Archived`

  This uses only the data the page already has. **"Learning" is Phase 2** because it needs a new field from Meta.
- **Frozen first column:** the ad-set name column is `sticky left-0` with a white background when the table scrolls horizontally (narrow screens).
- **Highlight:** the row targeted by a proposal click or deep link gets a 2px indigo left border and an indigo-50 background for 4s, then fades.
- Column order is unchanged: Ad set · Status · Spend · Leads · CPL · Max CPL · ROAS · Profit · Brand · Actions.

### 3.8 Proposals rail

This **reuses `ProposalsPanel`** with a new `layout="rail"` prop. The default `'panel'` is unchanged, for the tests and any other caller.

**Rail card (compact):**

- action chip (PAUSE / RAISE BUDGET)
- ad-set name, which is the button that scrolls to its row
- the existing `evidence.why` sentence, clamped to 2 lines with expand
- `Current → Proposed` on one line
- **data line:** `Data through {last evidence day} · proposed {relativeAge(created_at)}`, using existing fields only
- Approve / Dismiss, which use **the existing handlers, confirmations and stale/failed states, unchanged**
- "Open in Ads Manager" stays, as a small link

**Rail header:** "Proposals (n)", a close ×, and a link to the existing history table, which opens in the rail.

**Empty state:** "No proposals. Rules ran {time}." Closed by default when empty.

**Not changed:** proposal generation, trigger logic, execution, dismissal reasons. This is layout only.

### 3.9 Mobile (<768px)

- The header wraps to two rows.
- The close strip wraps.
- Tabs scroll horizontally.
- The toolbar collapses to: goal line on its own row, then Search · Filters · Proposals.
- The rail is a full-screen overlay.
- The table scrolls horizontally with the frozen name column.

---

## 4. Decision logic

| Condition | Goal-line bucket | Max CPL cell |
|---|---|---|
| spend = 0 in range | not counted | — |
| no Max CPL entry / unavailable | no Max CPL | — |
| leads > 0, CPL ≤ 0.85 × max | under | green |
| leads > 0, 0.85 × max < CPL ≤ max | under | amber (existing) |
| leads > 0, CPL > max | **over** | red |
| leads = 0, spend ≥ max | **over** | red, "0 leads" |
| leads = 0, spend < max | under (too early) | gray, "0 leads" |

| Rail default | Condition |
|---|---|
| open | pending proposals > 0 and no saved preference, or deep link from the nav badge |
| closed | 0 pending, or the user closed it (persisted) |

---

## 5. Integration notes

- **No new backend endpoints in Phase 1.** Two small backend changes:
  - Extend `_CLIENT_EVENTS` in `proposals.py` with `proposal_rail_toggled` and `proposal_row_jumped`.
  - Extend the daily-close event allowlist with `close_details_opened`.
- Page-level events go through the same daily-close event endpoint if it is generic enough. Otherwise use console-free no-ops: **don't add an analytics vendor.** Phase 1 events:
  - `perf_tab_viewed {tab}`
  - `goal_chip_clicked {chip}`
  - `group_by_toggled {on}`
  - `campaign_drilled`
- **URL contract**, all optional and composable:
  - `tab`, `campaign`, `niche`, `adsetId`, `view`, `date_preset`, `date_from`, `date_to`, `search`, `proposals=open`
  - Existing Dashboard deep links (`view=attention|top-performers|refresh-soon|compass`, `niche`, `adsetId`) must keep working. Add a test per link.
- `session_id` passthrough: N/A. This is an internal tool with no revenue path.

## 6. Tracking: what "worked" means

The baseline comes from the existing proposal events plus the new ones, over 2 weeks before and after:

1. **Proposal decision latency:** median `created_at` → approve/dismiss. Expect a drop, because proposals now sit beside the table.
2. **Goal-chip usage:** share of Joel's sessions with ≥1 `goal_chip_clicked`. Below 20% after 2 weeks means the line isn't earning its space, so revisit it.
3. **Close details opens.** If they're near zero, the strip alone is enough. Confirms the shrink.
4. Ask Joel directly after a week: "What do you still scroll for?"

---

## 7. Build priority

**Phase 1 (Codex, ~1 PR, frontend plus two allowlist lines).** Ready for review:

1. Header compaction plus `⋯` menu
2. Close strip plus Details drawer
3. Tabs (Compass and Intelligence move)
4. Sticky toolbar plus Filters popover plus chip row (replaces the deep-link banner)
5. Goal line plus `over_max`/`under_max`/`no_max` filters plus the "Over Max CPL first" sort
6. Proposals rail (`layout="rail"`) plus row jump
7. Total row, effective status, frozen name column
8. Group-by-campaign toggle plus campaign drill chip

**Phase 2 (directional; each needs backend work and a Meta-read decision):**

- **Compare chart.** Check 2–5 ad sets to get a daily CPL/spend line chart above the table. This needs `GET /facebook/adsets/daily?ids=&date_preset=`, reusing the ad-set-level `time_increment=1` fetch already in `proposal_service.py`. Cache it per (ids, range) for 15 min. Rate-limit caution on `act_521142087204815`.
- **Learning status.** Add `learning_stage_info` to the ad-set sync fetch.
- **Creative freshness stat** in the close strip: the share of yesterday's spend on ads under 14 days old. Needs ad `created_time` × yesterday's ad-level spend.
- **Compass as a group-by table** (creative / headline / body / niche):
  - merged duplicate names
  - leads shown beside every CPL
  - ranks greyed out below a lead floor (start at 10)
- **Ad-set drawer**, only if inline expansion becomes the complaint.

## 8. Open questions

1. **Group-by default.** I've kept grouped-by-campaign as the default so Joel's view doesn't change under him. The flat list matches Ads Manager's Ad sets tab and allows cross-campaign sorting. Is that worth asking Joel to switch defaults? *Recommend: ship grouped by default, mention the toggle to him.*
2. **The zero-lead "over" rule** (spend ≥ one Max CPL with 0 leads counts as over) is a display rule, not an auto-pause trigger. It changes no rule behavior, so it doesn't need Joel and Abel's trigger sign-off, but tell Joel what the red count means.
3. **Phase 2 compare chart** adds an on-demand Meta read (2–5 ad sets per click). Acceptable, or should it stay DB-only (wait for a daily ad-set snapshot table)?

**Not verified:** pixel heights in the "Today" diagram are estimates from the code structure, not measured in a browser.
