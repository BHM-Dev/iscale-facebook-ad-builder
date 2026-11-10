# Codex brief: Winning ads, Phase 1

**Spec:** `docs/briefs/AdBuilder-Winners-Brief.md`. Sections 3 and 4 are the contract.
**Visual reference:** `docs/briefs/AdBuilder-Winners-Prototype.html`. Its grouping, ranking and floor logic are a working reference.

## Preflight

```bash
git pull origin develop
```

## Build

1. **Backend `GET /api/v1/winners`** in a new `backend/app/api/v1/winners.py`, registered in `main.py`, with logic in `backend/app/services/winners_service.py`.
   - **Sources:**
     - `get_account_ads_insights_bulk`. Reuse the ads-bulk cache; add no new Meta call type.
     - `FacebookAd`, joined to ad set and campaign.
     - `DriveAsset`, matched on `file_name == creative_name`.
     - The Max CPL entry per ad set, which gives `rpl` and `max_cpl`.
     - RedTrack `get_report_by_sub(..., "sub1")`.
   - **Grouping:** `creative`, `concept` or `headline`. Backend concept parse lives in `services/naming_presets.py` (mirror the frontend `conceptFromFilename`).
   - **Ranking:** `est_profit = Σ leads × rpl − spend`, sorted descending among rows with leads ≥ `min_leads` (default 10). Rows under the floor sort after.
   - **Partial data:** rows where some ads lack `rpl` get `est_partial`. `rt_coverage` is one of `full`, `partial` or `none`.
   - **Response:** row shape per brief §3.1. Cache 15 minutes per (account, range, group_by).
   - **Tests:** unit tests for the grouping and ranking function.
2. **Frontend** `frontend/src/components/WinningAds.jsx`, plus a **Winning ads** tab in `CampaignPerformance.jsx` placed second after Ad sets (`?tab=winners`).
   - It uses the page's account and date range. Default to Last 14 days when the page is on Today or Yesterday.
   - Columns, colours, the greyed floor, the concept expand and the Max CPL fallback all follow the brief.
3. **Relaunch:**
   - **Write:** `pendingDriveRelaunch = {account_id, drive_file_ids, source:'winners'}`, then open `/facebook-campaigns` in a new tab.
   - **Read:** the launch flow (`FacebookCampaigns.jsx` / `AdCreativeStep.jsx`) reads it on mount and preselects those Drive assets in the Creative step.
   - **Missing files:** if an asset isn't in the picker, show a warning that lists the missing files. Nothing fails silently.
   - **Cleanup:** delete the key after reading.
4. **Iterate** uses the existing `/batch-generate?adId=…` with the row's top-spend ad.
5. **Events:** add `winners_viewed`, `winners_relaunch` and `winners_iterate` to the allowlist.

## Hard rules

- No Meta writes. Relaunch only opens the launch flow.
- Don't add a second per-ad Meta read when the Ad sets tab already loaded the same range.
- Est. profit is labelled as an estimate. RedTrack revenue is shown as "partial" and never sets the rank.
- Use `authFetch`, toasts and custom modals.
- `AdCreativeStep.jsx` is a trigger file. End with: "Edits done — ready for Claude Code 2-agent review + push." Do not push.
- Run `npm run build`, `npx vitest run`, and the backend unit tests for the new service.

## Done means

On RHO Commercial, last 14 days, the tab lists creatives ranked by est. profit. It shows `FleetMargin`-style concepts across niches, and Relaunch lands in Launch Ads with those exact Drive files selected.

Report how many creatives cleared the 10-lead floor, so the default can be tuned.
