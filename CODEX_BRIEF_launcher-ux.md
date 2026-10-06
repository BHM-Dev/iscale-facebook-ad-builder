# Codex follow-up — Launcher UX (after push 9631664)

`git pull origin develop` first. Frontend only. BulkAdCreation.jsx / AdCreativeStep.jsx are trigger files — edit locally, don't push; hand back to Claude Code.

Shipped in 9631664: keyboard Drive card selection, Selected badge, Clear selection, Feed+Stories review counts, status-accurate paused/live copy, shared constants in `adCreativeConstants.js`.

## Open items (from pre-push review)
1. **Blocked Drive cards unreachable by keyboard** (`AdCreativeStep.jsx`, `tabIndex={selectionBlocked ? -1 : 0}`): make focusable (keep `aria-disabled`); Enter/Space calls `toggleDriveAssetSelection` so the blocked-reason toast fires.
2. **Nested interactive**: Preview button inside `role="button"` card. Restructure (select control on thumbnail; Preview as sibling) and add `aria-label` e.g. "Select ad N, Feed + Stories pair".
3. **Selected badge** at `top-9 right-2` may overlap Preview / Already-added badges on narrow or pair cards — visual check, reposition.
4. **Clear selection**: show count ("Clear (N)"); consider undo toast; confirm it never removes already-added editor creatives.
5. **Review wording**: "pairs" → "creatives" when singles/video fallback present; Media line and intro both print `driveReviewInventory` — dedupe.
6. **Status badges on Review** for existing campaign/ad set (ACTIVE/PAUSED); amber callout instead of small blue text; launch button label should say live vs paused.
7. **Dead warning**: `reconciliationStorageUnavailable` is setter-only in BulkMatchImport (never rendered) — wire a banner or confirm intentional.
8. **Existing-campaign budget line** reads `campaignData.dailyBudget`; verify it's the real Meta budget, else hide.
9. **Partial-failure UX**: add retry-failed-rows guidance after "Stopped — X of Y created".

## Verify
`cd frontend && npm test && npm run build`. Keyboard: Tab to card → Space toggles; Tab to Preview → Enter opens preview, selection unchanged.
End with: "Edits done — ready for Claude Code 2-agent review + push."
