# Winning Ads — Brief

**Date:** 2026-11-10 · **Owner:** Steve · **Builder:** Codex; Claude Code reviews and pushes
**Prototype:** `docs/briefs/AdBuilder-Winners-Prototype.html` (sample data, real RHO naming)
**Users:** Joel decides what creative to make next. Abel relaunches proven creative into new ad sets.

---

## 1. Executive summary

**Problem.** Everything we call a "winner" today is an **ad set**:

- Dashboard Top Performers: ≥$50 spend and RT ROAS > 0.
- Creative Compass: ≥$50 spend and ROAS ≥ 1.
- Campaign Performance's "Top performers" filter.

Nothing ranks individual **creatives**. Yet the buyers already move winning creatives by hand into "WINNERS" campaigns (`LEADS | AUTOBODY WINNERS`, `POP-LIMO | WINNERS NEW IMAGES`, `WW8-* | Winners Wave 8 Fleet And Crew`). Finding them means scrolling ad-set rows and expanding each one.

**Why now: the data is already clean.** Checked on production 2026-11-10:

- **Every RHO Commercial ad launched in the last 30 days (412 of 412)** went through the Ad Builder from Drive.
- **All 412 match their Drive file by name.** A Meta ad therefore traces back to the exact file Joel made.
- Since 11/8 the naming convention parses those names into wave, niche, sequence and concept (`WW8-FUN-02-HearseAndStaff-IMG-1x1`).

**Solution.** A **Winning ads** tab on Campaign Performance. It uses the same account and date range as the rest of the page. It ranks creatives by estimated profit, with a sample-size floor, and adds two things:

- **Group by concept.** One message across niches: "FleetMargin" ran in FUN, LOCK and PAINT. That tells Joel which ideas travel.
- **Relaunch.** Opens the launch flow with that exact Drive file preselected.

**Revenue attribution, honestly:**

- Meta gives spend and leads per ad.
- RedTrack gives revenue per ad for part of the traffic: 173 RHO ads, $12,456, over the last 7 days.
- Switchboard/Everflow, RHO's main revenue source, reports only per ad set (`sub3`).

So ranking uses **estimated profit = leads × the niche's revenue per lead − spend**. Revenue per lead is the same `rpl` that Max CPL already uses for that ad set. RedTrack revenue is shown beside it as a secondary, labelled "partial" column, and is never the ranking key.

**Economics.** This feature saves time and improves which creative gets reused. It doesn't produce revenue on its own.

The lever: relaunching proven creative into new niches and waves, without guessing which files those are. Success is measured as the share of new RHO ads that reuse a Winners-ranked file (§6).

---

## 2. Flow

```
Campaign Performance  [Ad sets] [Winning ads] [Creative Compass] [Intelligence]
                                   │  same account + date range as the page
                                   ▼
 Group by: (Creative) Concept  Headline       Min leads: 10     Niche: all ▾
 ┌───────────────────────────────────────────────────────────────────────────┐
 │ [img] WW8-FUN-01-FleetMargin   FUN · 2 ad sets   $1,240  41  $30  est +$430 │ [Relaunch] [Iterate]
 │ [img] VW-TREE-02-TreeTruckLabel TREE · 1         $410   9   —   not enough data (greyed)
 └───────────────────────────────────────────────────────────────────────────┘
 Relaunch → /facebook-campaigns with that Drive file preselected → pick target ad set → (names auto-fill)
```

---

## 3. Spec (Phase 1, ready for review)

### 3.1 Endpoint `GET /api/v1/winners`

**Params:** `ad_account_id`, `date_preset | date_from+date_to`, `group_by` (`creative` | `concept` | `headline`), `min_leads` (default 10).

**Data, with no new kind of Meta call:**

- Meta per-ad spend and leads: reuse `get_account_ads_insights_bulk`, the same call and cache that `/auto-pause/ads-bulk` uses.
- `FacebookAd` rows: `fb_ad_id`, `creative_name`, `image_url`, `thumbnail_url`, `headlines`, `bodies`, `source_type`, `source_category`, joined to ad set and campaign.
- `DriveAsset` matched by `file_name == creative_name`, giving `drive_file_id`. This is what Relaunch needs.
- Max CPL entry per ad set, giving `{max_cpl, rpl, niche}`.
- RedTrack `get_report_by_sub(..., "sub1")` for revenue per ad.

Cache the response per (account, range, group_by) for 15 min.

**Row shape:**

```
{ key, label, group_by, image_url, drive_file_id, drive_file_name,
  niches: [..], niche_codes: [..], adset_count, ad_ids: [..], active_ad_count,
  spend, leads, cpl, max_cpl (spend-weighted), est_revenue, est_profit,
  rt_revenue, rt_coverage ("full" | "partial" | "none"),
  first_seen, enough_data: bool }
```

**Grouping rules:**

- **creative:** one row per Drive file (`creative_name`). The same file in 3 ad sets is one row with `adset_count` 3.
- **concept:** the concept is `parseName(creative_name)`, or `conceptFromFilename`. Implement the backend equivalent in `services/naming_presets.py`. `HearseAndStaff` from FUN and from LOCK is one row, and `niches` lists both.
- **headline:** grouped by normalized first headline.

**Ranking:**

- Sort by `est_profit` descending among rows with `enough_data` (leads ≥ `min_leads`). Rows under the floor sort after, greyed.
- `est_revenue` = Σ over the row's ads of `leads × rpl(adset)`.
- Ads whose ad set has no `rpl` count toward spend and leads but not toward `est_revenue`, and the row gets `est_partial: true`.

### 3.2 Tab UI (`CampaignPerformance.jsx` gets a new tab; the component goes in its own file `components/WinningAds.jsx`)

- **Controls:** group-by segmented control; min-leads input (default 10); niche filter; "Active only" toggle.
- **Columns:**
  - thumbnail
  - name: the convention name, with the concept in bold
  - niches as chips
  - ad sets
  - spend
  - leads
  - CPL, coloured against Max CPL exactly like the Ad sets tab
  - est. profit, with an info tooltip: "leads × this niche's revenue per lead − spend"
  - RT revenue, with a "partial" badge when `rt_coverage != full`
  - status ("2 active")
  - actions
- **Floor:** rows under the floor are greyed, with "not enough data (9 leads)". They are never hidden; a toggle can hide them.
- **Actions:**
  - **Relaunch** writes `pendingDriveRelaunch = {account_id, drive_file_ids:[...], source:'winners'}` and opens `/facebook-campaigns` in a new tab. The launch flow reads it on mount, selects those Drive assets in the Creative step, and deletes the key.
  - **Iterate** is the existing `/batch-generate?adId=…`, using the row's top-spend ad.
- **Concept view:** expanding a row lists its ads by niche with each one's CPL, so Joel can see where the concept works and where it doesn't.
- **Empty and error states** follow the Ad sets tab. If Max CPL is unavailable, est. profit shows "—", rows sort by leads, and a banner explains why.

### 3.3 Launch-flow handoff

`FacebookCampaigns.jsx` / `AdCreativeStep.jsx` (**trigger file**) consume `pendingDriveRelaunch`:

- They preselect the assets in the Drive picker state.
- If an asset is missing from the picker (sync drift), they show a warning listing the missing file names. Nothing fails silently.

Ad names come from the naming setup. Convention-named files are used verbatim.

## 4. Decision table

| Condition | Shown as |
|---|---|
| leads ≥ floor, rpl known | ranked by est. profit |
| leads ≥ floor, some ads lack rpl | ranked, est. profit marked "partial" |
| leads < floor | greyed "not enough data (n leads)", sorted after |
| 0 leads, spend ≥ one Max CPL | greyed red "no leads yet", never ranked as a winner |
| no Drive match (non-Drive ad) | row shown, Relaunch disabled ("not from Drive"), Iterate still works |
| RT revenue for every ad | `rt_coverage: full` |

## 5. Constraints

- **No Meta writes.** Relaunch only opens the launch flow, and the buyer launches as usual.
- **Rate limits:** reuse the ads-bulk cache. The Winners tab must not add a second per-ad Meta read when the Ad sets tab has already loaded the same range.
- `session_id`: N/A (internal tool).
- **Trigger file:** `AdCreativeStep.jsx`, possibly. That means the 2-agent review.

## 6. Tracking

**Events** (add to the allowlist): `winners_viewed {group_by}`, `winners_relaunch {count, group_by}`, `winners_iterate`.

**Success at 2 weeks:** at least 25% of new RHO ads reuse a Drive file that was in the Winners top 20 on its launch day. That is measurable from `FacebookAd.creative_name` against cached rankings.

## 7. Build priority

**Phase 1 (one Codex PR):** endpoint, tab with the 3 group-bys and the floor, Relaunch handoff, Iterate.

**Phase 2 (directional):**

- **Fatigue:** last-7-day vs prior-7-day CPL per creative.
- **"Untested niches" per concept:** a one-click relaunch into niches where the concept hasn't run.
- **Winners filter inside the Drive picker.**
- **Pinning to Copy Library.**
- **Reuse-vs-fresh dial** at generation time (synthesis #6).

## 8. Open questions

1. **Min-leads floor.** Default 10. RHO's niche CPLs run around $30–60, so 10 leads is roughly $300–600 of spend per creative. Lower it if too few rows qualify in a 7-day window. Default the tab to the last 14 days?
2. **Placement.** A tab on Campaign Performance uses the page's account and date range. A separate `/winners` page would be easier to find from the launch flow. My recommendation is the tab, plus a Phase 2 "From winners" filter in the Drive picker.

**Verified on production 2026-11-10:**

- 412/412 last-30-day RHO ads are Drive-sourced with exact filename matches.
- RedTrack `sub1` returns per-ad revenue for 173 RHO ads, $12,456 over 7 days.

**Not verified:** how many creatives clear the 10-lead floor in a typical 7- or 14-day window. Check this once the endpoint exists, and tune the default.
