# Ad Builder — Competitor Synthesis Redesign Brief

Source material: `Birch-Design-Reference-Capture.md`, `AdEspresso-Design-Reference-Capture.md`,
`AdBuilder-BulkRules-Feature-Brief.md`. Grounded against the current code: `BulkAdCreation.jsx`,
`AdCreativeStep.jsx`, `AutoPauseRules.jsx`, `CampaignPerformance.jsx`, `Dashboard.jsx`,
`FacebookCampaigns.jsx`. This is a POV, not a menu — where the two reference tools disagree, a
call is made and the reasoning is given.

---

## 1. Executive summary

**The problem:** the Ad Builder's bulk-launch flow (`BulkAdCreation.jsx`) computes every
permutation correctly and safely (rate-limit awareness, partial-failure recovery, dual-placement
targeting — all more sophisticated than what's visible in either competitor's UI), but it shows
its work worse than either competitor. Joel finds out what he's about to launch by reading a text
summary line and a flat list of unstyled rows with a thumbnail — not by seeing what the ad will
actually look like on Facebook. Two other real gaps: there is no live-counting feedback *while
building* the creative (only after hitting Review), and there is exactly one axis of testing
(creative) — no targeting-variant testing, no rules beyond pause.

**The solution — three moves, not a rebuild:**
1. Bring the "N variations" counter forward into `AdCreativeStep.jsx` (AdEspresso's pattern) so
   Joel sees the multiplication happen live, before he ever reaches Review.
2. Replace the flat review list in `BulkAdCreation.jsx` with a native Facebook-style preview card
   per ad (AdEspresso's "Show All" grid) — this is the single highest-leverage change since it
   directly reduces the "did I just approve a bad combo" risk that a real Meta launch carries.
3. Generalize `auto_pause.py`/`AutoPauseRules.jsx` per the existing bulk-rules brief, borrowing
   Birch's live match-count preview and AdEspresso's plain-English sentence summary — already
   scoped, just re-affirmed here as the third leg.

**The economics:** every launch is real Meta spend the moment it goes live. Right now the only
guardrail between "reviewed" and "launched" is Joel reading headline/body text in a small input
box next to a thumbnail. A wrong image/headline pairing that ships costs actual ad spend before
anyone notices — a rendered preview catches that before Meta does.

---

## 2. Sections impacted

| Ad Builder surface | File(s) | What changes |
|---|---|---|
| Ad creative step (headline/body/media entry) | `frontend/src/components/AdCreativeStep.jsx` | Add live combinatorial counter |
| Bulk launch review screen | `frontend/src/components/BulkAdCreation.jsx` | Replace flat list with native ad-preview grid; add per-ad exclude-before-launch |
| Ad Remix wizard | `frontend/src/pages/AdRemix.jsx` | Add persistent right-rail running summary (currently summary only appears at the end) |
| Auto-pause rules | `frontend/src/pages/AutoPauseRules.jsx`, `backend/app/api/v1/auto_pause.py` | Generalize action set + add live match-count preview — already scoped in `AdBuilder-BulkRules-Feature-Brief.md`, unchanged here |
| Campaign Performance / Facebook Campaigns | `frontend/src/pages/CampaignPerformance.jsx`, `frontend/src/pages/FacebookCampaigns.jsx` | Add period-over-period comparison cells; expand filter surface |
| Dashboard | `frontend/src/pages/Dashboard.jsx` | No structural change recommended (already decluttered 2026-09; P&L moved out, Ask AI is a widget) — one small addition only (see §4.6) |

Nothing here touches `facebook_service.py`'s Meta API calls except the rules-engine work already
scoped in the bulk-rules brief (new action types = new Meta API calls). The preview-grid and
live-counter changes are pure frontend — they render data BulkAdCreation/AdCreativeStep already
compute, they don't change what gets sent to Meta.

---

## 3. Layout changes, screen by screen

### 3.1 `AdCreativeStep.jsx` — bring the counter forward

Today: headlines, bodies, and media are entered across this step with no running total; the
"N media × N headlines × N bodies" math only appears once, computed inside
`BulkAdCreation.jsx`'s Summary box, after the user has already moved past creative entry.

**Change:** add a small sticky counter — literally AdEspresso's format —
`{media} MEDIA × {headlines} HEADLINES × {bodies} BODIES = {total} ads` — pinned to the top or
side of the creative step, recalculating on every keystroke/upload. This is copy-paste-simple
(the math already exists in `BulkAdCreation.jsx`'s `useEffect` that builds `permutations`; it just
needs to run one step earlier, live). No new state model — same three arrays already being built.

Include AdEspresso's real rough edge as a QA note, not a reason to skip it: a field that's typed
via a race-condition-prone flow can silently not register into the count. Whatever we build here
must recompute the count from the actual current input value, not from a stale array snapshot.

### 3.2 `BulkAdCreation.jsx` Review screen — the real change

Today's review row (per `BulkAdCreation.jsx:603-668`): a 48px thumbnail, a rename input, a trash
icon, and (post-launch only) an outcome pill. No headline/body text is shown per row at all — you
have to trust the permutation math, or trace back to `AdCreativeStep.jsx` to see what a given
headline/body pairing actually says.

**Change:** replace the flat row list with a responsive card grid (3-4 columns desktop, 1 mobile),
each card styled as a compact native Facebook feed-preview: Page name placeholder, the actual
image/video, the actual headline + body text for that combination, format badge (1:1 / 9:16) kept
as-is, and the existing rename input + trash icon moved into the card footer instead of an inline
row. This is directly AdEspresso's "Show All" pattern (§3 of the capture doc) — the thing Birch
doesn't have and the single most-praised detail in that walkthrough.

- Keep the existing Summary box above the grid unchanged — it's already doing the job Birch's
  "Creates N ads in M ad sets" line does, just needs no rework.
- Keep the amber "Not attempted" / red "Failed" outcome treatment — just move it to a card badge
  instead of a row badge.
- The trash icon becomes the literal "exclude this combination before it ever gets created" action
  AdEspresso's "✕" performs — same behavior as today's `removeAd`, just relocated onto a richer
  card.

**What NOT to copy from either tool:** neither tool's two-placement-preview-per-card complexity is
worth it here — Ad Builder already knows the exact placement (1:1 feed vs 9:16 stories) per ad from
`ad.format`; show one preview matching that ad's actual format, not a generic feed+story pair like
AdEspresso does for every combination regardless of relevance.

### 3.3 `AdRemix.jsx` — persistent right-rail summary

AdEspresso's strongest single pattern (their own words, and mine after reading four screens of
wizard steps): the right rail accumulates a running summary across every step, not just at the
end. `AdRemix.jsx` is BHM's closest equivalent wizard shape (6 steps, `Wizard.jsx` component) but
currently only shows a summary at the results step.

**Change:** add a persistent right-rail card, visible from Step 2 onward, that accumulates:
brand/product/profile selection → hook/angle → generated copy preview, growing as each step
completes rather than appearing only at the end. This is a layout addition, not new data — every
field already exists in `wizardData`.

### 3.4 Campaign Performance / Facebook Campaigns — comparison cells + filter surface

Two independent, smaller changes, both directly named in the capture docs:

- **Comparison cells** (Birch Explorer, §4 of that capture): each metric cell shows current-period
  value, previous-period value, and a colored delta — instead of today's single flat number. This
  is the single biggest "why is this number good or bad" gap in `CampaignPerformance.jsx` today —
  Joel currently has to remember last week's CPL from memory or a separate tab.
- **Filter surface** (AdEspresso's Campaigns list, §4): status checklist (Active/Paused/etc.),
  date-range filter, metric-threshold filter (`Filter by... < = > value`). `FacebookCampaigns.jsx`
  is only 196 lines today — this is a real gap, not a nice-to-have polish item, if the account list
  grows past what fits on one screen.

### 3.5 Dashboard — no structural change, one addition

The dashboard was just decluttered (P&L moved to its own page, Ask AI turned into a floating
widget) — don't re-clutter it. The one addition worth taking from AdEspresso's Overview page: the
**KPI-tile-to-chart-line color linking** (§5 of that capture) — if `Dashboard.jsx`'s performance
chart doesn't already color-match its tiles to its chart series, that's a one-line CSS-variable fix
worth doing since it's free and both competitors independently converged on it (Birch's Explorer
does the identical thing on its table-row-to-chart-line checkboxes, §4 of that capture — two
unrelated products landing on the same trick independently is a strong signal it's just correct).

### 3.6 Birch-sourced patterns — chrome-level, apply across the whole app

Birch's capture is lighter on single big mechanics (it doesn't have AdEspresso's rendered preview
grid) but heavier on disciplined, repeatable chrome-level rules that would tighten every screen in
the Ad Builder at once, not just one wizard:

- **One primary button per screen** (Birch §6.2): a screen gets exactly one solid/dark button —
  the single most important action — everything else (secondary actions, cancel, back) is a
  lighter gray or plain text link. Worth a pass across `BulkAdCreation.jsx`, `AdRemix.jsx`, and
  `AutoPauseRules.jsx` specifically, since bulk-launch and rule-creation screens are exactly where
  an accidental click on the wrong button is costliest.
- **"Ghost of the real thing" empty states** (Birch §6.1): every empty/locked state in Birch shows
  a low-opacity, real-shaped preview of what the feature produces, instead of a blank box or a
  generic icon. Directly applicable to `GeneratedAds.jsx`'s empty gallery, `CopyLibrary`'s
  pre-first-sync state, and `Research.jsx` before a first search — right now these presumably show
  a plain empty message; a blurred/ghosted preview of what a populated gallery/table looks like
  answers "what do I get" before the user does anything, at near-zero build cost (it's the same
  component with opacity + a real-looking placeholder dataset).
- **Compact pill summaries that expand into full editors** (Birch §6.3): filters/date-ranges
  default to a one-line pill ("Campaign status is active + 1 other filter") and only expand into
  the full editor on click. This is the right implementation detail for §3.4's expanded filter
  surface on `FacebookCampaigns.jsx` — build the full filter editor, but collapse it to a pill by
  default once a filter is saved, rather than leaving the full form always open and eating screen
  space.
- **Redundant, layered status communication** (Birch §6.4): anything that takes time is signaled
  in at least two places at once (subtitle + button state + content-area message). `BulkAdCreation.jsx`
  already does a version of this for the launch progress bar (`progress.status` + the
  rate-limit banner) — worth explicitly checking kie.ai image-generation polling in
  `BatchGenerate.jsx`/`ImageAds.jsx` against this same bar, since long-running async jobs are
  exactly where "is this stuck?" ambiguity costs the most trust.
- **Icon rail with tooltips, no persistent labels** (Birch §6.5) — a genuine layout alternative for
  `Layout.jsx`'s sidebar if it ever gets crowded (it's currently a labeled list per the file map in
  `CLAUDE.md`); not an urgent change today, noted for when the nav list grows past what fits
  comfortably.

None of §3.6 requires a product decision — these are systemic polish, cheap individually, and worth
batching into whichever phase below happens to touch each screen anyway rather than a standalone
pass.

---

## 4. Functionality improvements — ranked

### 4.1 Native ad-preview grid on Review (highest priority)
Covered in §3.2. This is the change with the most direct dollar-risk reduction — it's the last
screen before real Meta spend.

### 4.2 Live combinatorial counter during creative entry
Covered in §3.1. Cheap, and removes the "how many ads am I actually about to make" ambiguity a
step earlier than today.

### 4.3 Targeting-variant testing axis (genuinely new capability, not a UI tweak)
AdEspresso's "What do you want to test?" modal (its capture doc §9) is the one mechanic neither
Birch nor BHM's current tool has: a *second* combinatorial axis (Gender / Relationship Status /
Placement) that multiplies against creative variants, with a hard cap shown before commit
(`1 creatives × 1 targets = 1 Ads, Max 250 Ads`). Today, `BulkAdCreation.jsx` only varies creative
— targeting is fixed per ad set. This is a real feature gap, not a layout issue, and it's the one
item on this list that needs a product decision before scoping: does Joel actually want to
split-test targeting variants inside one ad set, or is per-audience testing already handled some
other way in his workflow today? Flag for Joel, don't build speculatively.

### 4.4 Three ad-set creation modes (Birch Stage — real functional gap, not styling)
Birch's Stage build card (capture doc §5b) names three distinct ways bulk-created ads land in ad
sets: **Duplicate ad set** (clone one ad set, all N ads inside it), **Duplicate ad set for each
media** (clone a separate ad set per file — one ad each), **Add to ad set** (append into an ad set
that already exists, no cloning). `BulkAdCreation.jsx` today only does the equivalent of the first
mode, and only within a single ad set already selected upstream — it can't append to an existing
ad set without cloning, and it can't spin up one ad set per creative automatically. Birch's own
**live plain-English summary line** under the mode picker ("Creates 2 ads in 1 new ad set",
recalculated from the actual file count + mode before commit) is the cheap, portable detail to
copy alongside it — same spirit as §3.1's live counter, just for ad-set fan-out instead of ad
count. This is a real Meta API surface change (new ad-set creation/lookup logic in
`facebook_service.py`), not a rendering change like §3.1-3.3 — scope and review it accordingly.

### 4.5 Bulk rules — already scoped, re-affirmed here
`AdBuilder-BulkRules-Feature-Brief.md` already covers this in full (MVP: Pause/Notify/Increase
budget/Decrease budget, live match-count preview, reuse existing 30-min scheduler). No changes to
that brief from this pass — just confirming it's still the right next build after the two items
above, not competing with them.

### 4.6 Comparison-cell metrics + expanded filters
Covered in §3.4 and §3.6. Lower priority than 4.1-4.4 because it's additive polish to an existing
working screen, not closing a real gap.

### 4.7 Skip, don't build
- **Report Generator / white-label client reports** (AdEspresso) — agency-shaped, BHM is internal
  only. Explicitly out of scope.
- **Asset Manager folder hierarchy** (AdEspresso) — real gap (Copy Library/Generated Ads are flat
  galleries) but low urgency; revisit only if the flat gallery becomes a real search problem.
- **Approval-gate workflow** (AdEspresso Collaboration Hub) — conceptually resonant with BHM's own
  pre-push review discipline, but BHM is internal, not agency/client. The existing 2-agent pre-push
  review already is BHM's approval gate, just for code, not for Joel's ad launches. Not recommending
  a new in-product approval screen for Joel's own launches unless he asks for one.
- **AI assistant as slide-out panel vs. floating widget** (Birch) — the Dashboard declutter just
  shipped `AskAiWidget.jsx` as a floating widget 2026-09. Don't re-litigate that decision from this
  pass; if it needs revisiting, that's a separate conversation, not a byproduct of this brief.

---

## 5. Build priority / phased rollout

**Phase 1 (do first, smallest surface area, no backend changes):**
- [x] 3.1 Live counter in `AdCreativeStep.jsx` — shipped, see commit
- ~~3.5 Dashboard tile/chart color linking~~ — dropped, no chart exists on Dashboard today (§6.3)
- 3.6 Birch chrome-level patterns (one-primary-button pass, ghosted empty states) — batch into
  whichever screen each phase below already touches; no standalone pass needed

**Phase 2 (frontend-only, moderate surface area):**
- 3.2 Native preview grid in `BulkAdCreation.jsx` Review screen
- 3.3 Persistent right-rail summary in `AdRemix.jsx`

**Phase 3 (already scoped elsewhere, proceed per that brief):**
- Bulk rules engine generalization (`AdBuilder-BulkRules-Feature-Brief.md`) — Birch is the primary
  reference for this brief already (action catalog, live match-count preview)

**Phase 4 (real Meta API surface change — needs its own scoping pass, not a quick add):**
- Three ad-set creation modes from Birch's Stage (§4.4) — touches `facebook_service.py`

**Phase 5 (needs a product decision before scoping):**
- Targeting-variant testing axis (§4.3) — confirm with Joel first
- Comparison-cell metrics + filter surface (§3.4) — real but lower urgency

---

## 6. Open questions & dependencies

1. Does Joel want targeting-variant split-testing (§4.3) at all, or is per-audience testing already
   handled another way today? This determines whether Phase 4's first item is scoped or dropped.
2. Phase 2's preview grid needs a real Page name/avatar to render an authentic-looking Facebook
   card — is that already available from the connected ad account via the Meta API, or does it need
   a new field/config?
3. ~~Confirm whether `Dashboard.jsx`'s existing chart already color-links tiles to chart series~~ —
   checked directly (2026-09-12): `Dashboard.jsx` has no chart at all today, just KPI cards + tables
   (Needs Attention, Performance by Niche, CAPI Match Quality). §3.5's tile/chart color-linking item
   is dropped — there's nothing to link, and building a new chart wasn't asked for and would be
   scope creep on this brief.
4. None of Phase 1-2 touches a trigger file (`BulkAdCreation.jsx` and `AdCreativeStep.jsx` ARE
   trigger files per `CLAUDE.md`, so both phases still require the 2-agent pre-push review before
   push, even though the changes are frontend-rendering-only and don't touch `facebook_service.py`
   or add new Meta API calls).
