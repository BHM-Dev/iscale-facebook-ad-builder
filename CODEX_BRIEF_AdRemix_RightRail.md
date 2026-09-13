# Codex Brief — Persistent Right-Rail Summary in AdRemix.jsx

Ref: `AdBuilder-Competitor-Synthesis-Redesign-Brief.md` §3.3 / §4 Phase 2, second item (the
preview-grid item in `BulkAdCreation.jsx` is Claude Code's, already shipped separately — this is
the other Phase 2 item, and it's NOT a trigger file, so it's yours end-to-end).

## The problem

`frontend/src/pages/AdRemix.jsx` is a 7-step wizard (Template → Brand → Product → Profile →
Campaign → Generate → Results). Right now every selection the user makes (brand, product,
audience profile, offer/urgency/messaging) just disappears into `wizardData` state with no
visible trace until Step 7's Results screen. There's no way to glance back at what's already been
locked in without clicking Back through prior steps.

AdEspresso's wizard (a real competitor tool, captured in `AdEspresso-Design-Reference-Capture.md`
§9) solves this with a right-rail summary panel that accumulates every commitment as the user
moves forward — visible continuously, not just at the end. That's the pattern to bring here.

## The change

From Step 2 onward (once `wizardData.brand` starts getting set), add a persistent right-rail
card, visible alongside the step content, that shows:

- **Brand** — `wizardData.brand.name` once set
- **Product** — `wizardData.product.name` once set (Step 3)
- **Audience Profile** — `wizardData.profile.name` once set (Step 4)
- **Campaign details** — `wizardData.campaignDetails.offer` / `.urgency` / `.messaging`, each
  appearing as soon as that field is filled in (Step 5), not gated on the whole step being
  "complete"

Each row should be visually "not yet set" (grayed placeholder text, e.g. "—") before that step is
reached, and switch to the real value the moment it's set — this is meant to *feel* like it's
accumulating, the same way AdEspresso's reach/budget numbers grow as you fill in each field, not
like a static summary that pops in fully-formed at Step 7.

## Layout

Current structure (`AdRemix.jsx:748`) is a single centered column: `<div className="max-w-5xl
mx-auto">` wrapping the header, progress-step bar, banners, and then each `currentStep === N`
block in sequence.

Change to a two-column grid **only for the step-content region** (leave the header and the
top progress-step bar exactly as they are — don't touch those):

```jsx
<div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6 items-start">
  <div>{/* existing currentStep === N blocks, unchanged */}</div>
  {currentStep >= 2 && (
    <aside className="sticky top-6 bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-3 hidden lg:block">
      {/* summary rows */}
    </aside>
  )}
</div>
```

- `hidden lg:block` — don't try to cram this into mobile widths; it's a nice-to-have on desktop,
  not a requirement on a phone screen doing a 5-step wizard.
- `sticky top-6` so it stays visible while the step content scrolls (mirrors the same sticky
  pattern already used for the live counter in `AdCreativeStep.jsx`, shipped this same week —
  keep the two visually consistent if you can, same amber/purple restraint, no new color intro).
- Step 7 (Results) already has its own full-width results layout — do NOT force the rail into
  that step; gate it to `currentStep >= 2 && currentStep <= 6`, or just `currentStep < 7` if that
  reads cleaner in context.

## What NOT to build

- No new state. Every field this rail displays already exists in `wizardData` — this is a pure
  rendering addition.
- Don't touch the top progress-step bar (`AdRemix.jsx:758-786`) — it's a different, already-good
  pattern (icons + labels + connecting line) and isn't in scope here.
- Don't add this to Step 1 (Template) — there's nothing to summarize yet at that point, and
  `wizardData.brand` etc. are all still null.

## Push protocol

This is a UI-only change to a non-trigger file (`AdRemix.jsx` is not in the trigger-file list in
`CLAUDE.md`) — per the project's Codex rules, you can commit locally. Final push still goes
through Claude Code so the diff gets logged, but this specific change does not require the
2-agent pre-push review team (that's reserved for the trigger files:
`BulkAdCreation.jsx`/`AdCreativeStep.jsx`/`facebookApi.js`/`facebook_service.py` — none of which
this touches).

End your session with the standard handoff line: "Edits done — ready for Claude Code review +
push."
