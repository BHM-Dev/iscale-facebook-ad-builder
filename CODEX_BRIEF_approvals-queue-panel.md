# Codex brief: Approvals Queue panel (frontend only)

**Spec:** `docs/briefs/AdBuilder-Approvals-Queue-Brief.md` §3.
**Visual and interaction reference:** `docs/briefs/AdBuilder-Approvals-Queue-Prototype.html`. Match it. Leave out the dev toolbar and telemetry drawer; those are prototype-only.

**Backend:** already built and deployed. Do not change backend files. If the API seems wrong, stop and say so.

**When done:** commit locally and end with "Edits done — ready for Claude Code 2-agent review + push."

## Scope

1. **New component** `frontend/src/components/ProposalsPanel.jsx`.
   - Render it on `frontend/src/pages/CampaignPerformance.jsx`, above the ad set table.
2. **Sidebar badge** in `frontend/src/components/Layout.jsx`.
   - Show the open count next to the Campaign Performance nav item.
   - Fetch `GET /proposals` on mount and every 5 minutes, only while `document.visibilityState === 'visible'`.
   - Hide the badge when the count is 0 or `visible` is false.
3. **Do not touch:**
   - the four trigger files: `BulkAdCreation.jsx`, `AdCreativeStep.jsx`, `facebookApi.js`, `facebook_service.py`;
   - any backend file.

## Rules (from CLAUDE.md)

- Call the API with `import { authFetch } from '../lib/facebookApi'`, prefixed with `import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'`, as `CampaignContext.jsx` does.
- Use `useToast()` for notifications. Never `alert()` or `confirm()`.
- Tailwind only, matching the restrained look of the existing page.

## API (prefix `/api/v1/proposals`)

### `GET /proposals`

Returns:

```json
{
  "visible": true,
  "shadow": true,
  "proposals": [Proposal],
  "accounts": {"act_…": {"at": "...", "revenue_available": true, "created": 1, "expired": 0, "open": 3}},
  "dismiss_reasons": ["Revenue is lagging", "Still testing", "Handled it myself", "Wrong call", "Other"]
}
```

- When `visible` is false, **render nothing**. That is the shadow week for everyone except Steve.
- When `shadow` is true and `visible` is true, show the note: *"Shadow week: only you can see these. Joel and Abel don't see this panel yet."*
- If any account has `revenue_available === false`, show the amber note: *"Revenue source unavailable — no new proposals until Switchboard responds. Missing revenue is never treated as $0."*
- Otherwise show: *"Nothing changes in Meta until someone approves. Existing auto-pause rules are unchanged."*

**`Proposal`** has these fields:
- `id`, `fb_account_id`, `fb_adset_id`, `adset_name`
- `trigger_keys`, `trigger_labels` (array), `action` (`pause` | `budget_increase`), `action_params`
- `evidence` (below)
- `status`: `open` | `executing` | `failed` | `executed` | `dismissed` | `expired` | `stale`
- `status_reason`, `execution_result`, `created_at`, `decided_by`, `decided_at`, `dismiss_reason`

**`evidence`** looks like this:

```json
{
  "why": "Spent $64 today with no revenue in 3 days",
  "days": [{"day": "2026-10-31", "spend": 58.1, "leads": 4, "revenue": 0, "profit": -58.1}],
  "totals_7d": {"spend": 402.55, "leads": 29, "revenue": 120, "profit": -282.55},
  "current": {"status": "ACTIVE", "daily_budget_cents": 7500},
  "as_of": "2026-11-02"
}
```

- `days` has 3 entries, oldest first. Show the last one as **Today**; for the others, show the weekday name of `day`.
- For `budget_increase`, `action_params` is `{from_cents, to_cents}`.

### `POST /proposals/{id}/approve`

- Returns the updated Proposal.
- A `status` of `stale` means the ad set changed in Meta and **nothing was sent**. Show `status_reason` in an amber box on the card, then drop the card from the open list after a refresh.
- `failed` means Meta rejected the change. Show `execution_result.error` in red, with a **Retry** button that calls approve again.
- A 409 means it was already decided elsewhere. Refresh the list.
- While the request is in flight, disable both buttons and show *"Checking the ad set in Meta…"*.

### `POST /proposals/{id}/dismiss`

- Body: `{"reason": "...", "note": "..."}`.
- The reason must be one of `dismiss_reasons`. `Other` requires a note.
- 400 returns a message. Show it as a toast.

### History and stats tabs

- `GET /proposals/history?limit=100` returns `[Proposal]`. Render it as the **History** tab table.
  - Columns: When, Ad set, Trigger, Decision, By, Result.
  - Leave out "After 3 days" for now; outcomes are Phase 1.5.
- `GET /proposals/stats` returns `{trigger_key: {label, proposed, approved, dismissed, expired, dismiss_reasons}}`. Render it as the **How each trigger is doing** tab.
  - Columns: Trigger, Proposed, Approved, Dismissed, Expired, Approval rate (approved ÷ (approved + dismissed)).

### `POST /proposals/events`

- Body: `{"event", "proposal_id", "props"}`. Fire and forget; ignore failures.
- Send:
  - `proposal_viewed` once per card per page load;
  - `proposal_evidence_expanded`;
  - `ads_manager_opened`;
  - `proposal_tab_viewed` with `{tab}`.

## Card (prototype `.card`)

**Header:**
- A pill: red **PAUSE** or green **RAISE BUDGET**.
- `adset_name`.
- Right-aligned meta: account label, then `trigger_labels.join(' + ')`, then relative age from `created_at`.
- For the account label, use the name from `useCampaign().adAccounts` matching `fb_account_id`. Fall back to the id.

**Body:**
- `evidence.why` as the line under the header.
- A **Show / Hide the numbers** toggle, expanded by default.
- The table: Day | Spend | Leads | Revenue | Profit. Add a bold 7-day totals row. Negative profit is red.
- A state line:
  - `Current: <current.status> · $<daily_budget_cents/100>/day`
  - `Proposed: PAUSE`, or `Proposed: $<to>/day (+20%)` for a budget raise.

**Buttons:**
- Primary: **Approve — pause ad set** (red) or **Approve — raise to $X/day** (blue).
- **Dismiss ▾** opens the reason pills, a textarea that appears only for Other, and a **Dismiss proposal** button. That button is disabled until a reason is picked.
- **Open in Ads Manager ↗** opens `https://adsmanager.facebook.com/adsmanager/manage/adsets?act=<id without act_>&selected_adset_ids=<fb_adset_id>` in a new tab.

**Panel:**
- Header "Proposals (n)" with tabs: Open | History | How each trigger is doing.
- Empty state: *"No proposals right now. The next check runs within the hour."*

## Mobile

- The card stacks.
- The table hides the Leads column under 760px.
- Buttons go full width.

## Done when

- `npm run build` and `npx vitest run` pass.
- There is a vitest for ProposalsPanel. With mocked `authFetch` it covers:
  - hidden when `visible: false`;
  - renders the cards;
  - approve → `stale` shows the amber message;
  - approve → `failed` shows Retry;
  - dismiss is disabled until a reason is picked, and Other requires a note.
- No change to any trigger file or backend file.
