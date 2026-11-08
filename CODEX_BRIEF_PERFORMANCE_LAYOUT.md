# Codex brief: Campaign Performance layout, Phase 1

**Spec:** `docs/briefs/AdBuilder-Performance-Layout-Brief.md`. Read §2–§5 in full; they are the contract.
**Visual reference:** `docs/briefs/AdBuilder-Performance-Layout-Prototype.html`. Open it in a browser. The data in it is sample data.
**Scope:** Phase 1 only (brief §7). Do not build anything marked Phase 2.

## Preflight

```bash
git pull origin develop
```

## Files you will touch

- `frontend/src/pages/CampaignPerformance.jsx` (3.7k lines; most of the work)
- `frontend/src/components/DailyCloseCard.jsx`: add `variant: 'strip' | 'full'`. The default stays `'full'`.
- `frontend/src/components/ProposalsPanel.jsx`: add `layout: 'panel' | 'rail'`. The default stays `'panel'`.
- `backend/app/api/v1/daily_close.py:88`: add `close_details_opened` to the event allowlist.
- `backend/app/api/v1/proposals.py:120`: add `proposal_rail_toggled` and `proposal_row_jumped` to `_CLIENT_EVENTS`.
- Tests: `DailyCloseCard.test.jsx` and `ProposalsPanel.test.jsx` must keep passing unchanged. Add tests for:
  - the strip variant
  - the rail layout
  - the goal-line bucket function (every row of brief §4, including zero-lead spend ≥ Max CPL counting as **over**)
  - the deep links listed below

## Build order (one commit per step)

1. **Header compaction.** One row. `CampaignIntelligencePanel` leaves the header. "+ Add Rule" moves into a `⋯` menu. The subtitle line is removed.
2. **Close strip and Details drawer.** Use `DailyCloseCard variant="strip"`. The drawer renders the unchanged full card. Keep every pending/error/partial state, and show "partial" *in the strip*.
3. **Tabs.** Ad sets / Creative Compass / Intelligence, driven by the `?tab=` URL param. `openCompassAdset` must switch to `tab=adsets` before it highlights.
4. **Sticky toolbar and chip row:**
   - Search stays visible.
   - Status, niche and the metric threshold go into a Filters popover, along with Rotation queue and Needs attention as presets.
   - Sort, the Group-by-campaign toggle and the Proposals button complete the toolbar.
   - **Delete the dashboard deep-link banner.** Its states become removable chips. Removing one chip clears only that state and its URL param, never the date range.
5. **Goal line.** Compute it client-side from `bulkInsights` and `maxCplData`. Add `statusFilter` values `over_max`, `under_max` and `no_max`, plus a sort option "Over Max CPL first". Show "Loading…" or "Max CPL unavailable" when there's no data; never show zeros.
6. **Proposals rail.** Render `ProposalsPanel layout="rail"`:
   - 320px wide, sticky, at ≥1280px; an overlay drawer below that.
   - Default open when there are pending proposals. Persist the user's choice in localStorage `perfProposalsRail`.
   - Clicking the ad-set name on a card scrolls to that row, expands its campaign, highlights the row for 4s, and clears any filter hiding it.
   - Approve, dismiss, confirm, stale and failed handling must stay **byte-for-byte the same behavior**.
   - The nav badge deep link (`e604af6`) opens the rail.
7. **Table:**
   - Pinned Total row.
   - Effective-status pill: Active / Paused / Paused (campaign) / Archived. Build it from data the page already holds. No "Learning".
   - Sticky first column.
   - Group-by toggle: off gives a flat list with the campaign name as a second line. Persist in `perfGroupByCampaign`. Default is on.
   - A click on a campaign name adds a `Campaign: X` chip (new `campaign` URL param). The chevron still collapses.

## Hard rules

- No new Meta API calls, no new endpoints, and no change to any Meta write path (budget, pause, proposals execution).
- Keep inline ad-set expansion (`AdsBreakdown`). **Do not** build an ad-set drawer.
- Do not edit the four trigger files (`BulkAdCreation.jsx`, `AdCreativeStep.jsx`, `facebookApi.js`, `facebook_service.py`).
- `authFetch` only. Toasts, not `alert()`. Custom modals, not `confirm()`.
- Brand and highlight state stays keyed by `adset.id`.
- **These deep links must still land correctly:**
  - `view=attention`
  - `view=top-performers`
  - `view=refresh-soon`
  - `view=compass&adsetId=`
  - `niche=`
  - `adsetId=`
  - the date params
  - the nav proposals badge
- Mobile (<768px): no horizontal page scroll. Only the table scrolls horizontally.
- Run `npm run build`, `npm test`, and the backend tests for the two touched API files.

## Done means

End with: "Edits done — ready for Claude Code 2-agent review + push." Do not push.
Include a list of anything in brief §3 you could not do with existing data, with the reason.
