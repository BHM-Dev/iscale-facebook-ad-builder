# Ad Builder Dashboard — Declutter Brief

Route: **Codex** (layout-only change, no hooks/migrations/trigger files touched).

## Problem
Dashboard feels too busy. Two contributors, both confirmed with Steve:

1. The "Running Profit/Loss" card on `/` duplicates the dedicated `/pnl` page — same numbers, second location.
2. "Ask AI" is a full inline card in the page flow instead of a persistent, out-of-the-way widget.

## Change 1 — Remove the Running P&L card from Dashboard

**File:** `frontend/src/pages/Dashboard.jsx`

Delete the block at **lines 1202–1253** (the `{hasPermission('pnl:read') && (pnlSummary || pnlLoading) && (...)}` card — starts with `<Link to="/pnl" ...>`, ends at the closing `)}` right before the `{/* Insights error banner */}` comment).

Also remove now-dead state/logic that only fed this card, if nothing else on the page reads it:
- `pnlSummary`, `pnlLoading` state (~lines 552–553)
- `loadPnl` effect (~lines 858–876)
- `pnlRevenueSourceLabel` helper (~line 11) — confirm no other usage first

Keep the `/pnl` nav item in `Layout.jsx` (line 53) — P&L still needs a home, just not duplicated on the Dashboard.

## Change 2 — Ask AI becomes a floating widget, bottom-right

**Why bottom-right, not top-right:** top-right is already account/nav territory in this app; bottom-right is the standard placement users expect for an assistant/chat affordance (Intercom/Drift-style) and stays clear of primary content.

**Current location:** `frontend/src/pages/Dashboard.jsx`, inline card at lines **1255–1345** (`{/* Ask AI */}` through its closing `</div>`), backed by state/handler defined earlier in the same file: `aiQuery`, `aiAnswer`, `aiLoading`, `aiDatePreset`, `showAiExamples`, and the `askAI` function (~line 828).

**Target:** extract into a new standalone component, e.g. `frontend/src/components/AskAiWidget.jsx`, carrying its own state (don't leave it dependent on Dashboard's local state — it needs to work from any page).

Mount it in `frontend/src/components/Layout.jsx`, inside the outer wrapper that already renders `<Outlet />` (bottom of the file), so it persists across every route instead of only appearing on `/`.

**Widget behavior:**
- Collapsed state: small circular button, fixed position, bottom-right (`fixed bottom-6 right-6 z-50` or equivalent), violet accent to match current styling (`bg-violet-600`), sparkle icon (already imported as `Sparkles` in Dashboard.jsx).
- Expanded state: opens the existing input + date-preset chips + examples + answer panel as a floating card anchored above the button (not a full-page modal — keep it dismissable by clicking the button again or an explicit close).
- Preserve all existing functionality as-is: date preset chips, example queries, markdown-rendered answer (`MarkdownAnswer`), clear button. This is a relocation + collapse/expand wrapper, not a rebuild.
- Keep the "powered by Claude + live Meta data" caption somewhere in the expanded view.

## Out of scope
- No change to the `/pnl` page itself.
- No change to the Ask AI backend/API call logic — same `askAI` request, just called from the new component.
- No change to KPI row, Top Performers, or any other Dashboard section.

## Verification
- Dashboard no longer shows a P&L card; `/pnl` still works and is still reachable from nav.
- Ask AI button appears bottom-right on every page (not just Dashboard), expands/collapses correctly, and existing query flow still works end to end (date preset → query → answer → clear).
- No console errors from now-unused state left behind in Dashboard.jsx.
