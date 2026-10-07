# Dashboard (`/`)

Performance overview: Needs Attention, Top Performers, Performance by Niche, CAPI Match Quality, and one-click
actions that touch Meta (pause, +20% scale, budget edit). Code: `frontend/src/pages/Dashboard.jsx`.
This file covers the **money-moving actions**; other cards are documented in the repo `CLAUDE.md` history.

## Money safeguards (budget + pause actions)
- **One shared confirm** (`components/BudgetConfirmModal.jsx`) for all three budget actions — campaign budget popover,
  ad set inline edit, **"+20% Scale"**. It reads the **live Meta budget** first (`lib/liveBudget.js` →
  `GET /facebook/{campaigns|adsets}/{id}`, 4 s timeout) and shows "from $X (live in Meta) to $Y (+N%)". If the live read
  fails it falls back to the cached value, labelled amber "last synced — could not verify live", and the Scale button
  says "Scale +20% (unverified)".
- **Scale is computed from the LIVE budget**, not the locally cached one (a stale cache used to be able to turn "+20%"
  into a silent cut). CBO campaigns scale the **campaign** budget — the modal says it applies to every ad set.
- **Large changes:** the server (same guard as Campaign Performance) refuses >3× up / <⅓ of live until a second red
  "Yes, apply N× increase / N% cut" confirm. Hard ceiling $5,000/day. ABO switch shows a red warning.
- **Keyboard:** the confirm button is autofocused (Enter confirms), Esc cancels. The clicked Scale button shows a
  spinner while the live read runs; Save buttons show "Checking live budget…". Double-clicks are ignored (ref guard).
- Success toast keeps the audit trail: `Ad set "name" budget scaled: $50 → $60/day (+20%)`.
- Errors never print "[object Object]" (shared `lib/budgetErrors.js`), including the Dashboard **Pause** button.

## Verified vs not
- **Unit-tested:** `liveBudget.test.js` (percent math, live read null/undefined/cents), `budgetErrors.test.js`.
- **Server guard** verified live 2026-10-07 (see campaign-performance.md).
- **Not yet browser-verified:** the Dashboard confirm modal and the live-read → scale flow (no click-through of an
  actual scale done — deferred with Pause/Resume until close to real use).

## Open items
- Dashboard **Pause** is still a one-click action (it is the safe direction); consider the same confirm as Campaign Performance.
- Bulk scale (select several ad sets → one confirm) if Joel's one-confirm-per-row proves slow.
- Campaign Performance still has its own inline copy of the confirm modal; fold it onto `BudgetConfirmModal`.

## Changelog
- 2026-10-07 shared live-budget confirm for all Dashboard budget actions; scale from live budget; keyboard + feedback.
