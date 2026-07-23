# Codex Brief: Move Ask AI to Campaign Performance

## Goal
Move the Ask AI feature from the bottom of the Dashboard to Campaign Performance as a persistent floating toggle. Keep a secondary placement on Dashboard but move it to the top.

## Current state
- Ask AI lives at the bottom of `frontend/src/pages/Dashboard.jsx`
- Joel never sees it — he lives in Campaign Performance

## What to build

### 1. Campaign Performance — floating Ask AI button + panel
In `frontend/src/pages/CampaignPerformance.jsx`:

- Add a floating button fixed to the bottom-right corner:
  - Dark pill button: `💬 Ask AI` 
  - Position: `fixed bottom-6 right-6 z-50`
  - Clicking it toggles a chat panel open/closed

- The chat panel:
  - Slides up from bottom-right (or opens as a fixed right-side drawer, ~380px wide)
  - Header: "Ask AI" + subtitle "powered by Claude + live Meta data" + close X
  - Same chat input + response UI as the current Dashboard Ask AI
  - Suggested prompts relevant to what Joel actually asks:
    - "What are my worst ad sets today?"
    - "Which niches are underperforming this week?"
    - "What should I pause right now?"
  - Reuse whatever API call/component the Dashboard version uses

### 2. Dashboard — move Ask AI to top
In `frontend/src/pages/Dashboard.jsx`:
- Remove Ask AI from the bottom
- Add it near the top, below the page header but above the metrics cards
- Keep it compact — collapsed by default with an "Ask AI" expand button, or a single input bar

## Files to touch
- `frontend/src/pages/CampaignPerformance.jsx` — add floating button + panel
- `frontend/src/pages/Dashboard.jsx` — move Ask AI from bottom to top

## Do NOT touch
- The Ask AI API call/backend logic — just move/reuse the UI
- Any trigger files (BulkAdCreation.jsx, AdCreativeStep.jsx, facebookApi.js, facebook_service.py)

## Notes
- The floating button should not interfere with the Remix drawer (which also opens from the right). If the Remix drawer is open, the Ask AI button can stay visible — they serve different purposes.
- Mobile: floating button is fine, panel should be full-width on small screens
- No agent review needed for this — pure UI move, no API changes

## Done when
- Ask AI floating button visible on Campaign Performance, opens/closes panel cleanly
- Dashboard Ask AI moved to top (collapsed by default)
- Commit locally, hand off to Claude Code for push
