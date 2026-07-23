# Codex Brief — UX Walkthrough Fixes (2026-07-18 Chrome audit)

**Source:** Claude Code live walkthrough of adbuilder.velocitymx.io (post-E2E-fix deploy `89f48b4`).
**Classification:** All frontend-only. No trigger files, no backend, no migrations. Hand final push to Claude Code (light review — no ad-launch trigger files if you stay within the files below).

**Confirmed working (do not touch):** pages dropdown now lists DailyInsurance.news; PAUSED subtitle + button copy; variations default 1; "Main Text on Image" input with headline placeholder; character counters; learning UI empty states ("WAITING FOR DATA" / Untracked strips); Copy Library Use → Quick Generate copy import; vertical filter scoped to creative pages; zero console errors across the session.

---

## 1. P1 — Push modal cold start (Abel's first-push blocker)
**File:** `frontend/src/components/PushToMetaModal.jsx`
On a fresh browser profile the modal opens with Ad Account ID **empty** (placeholder `act_123456789`), Campaign disabled ("Enter Ad Account ID first"), and the Facebook Page field rendered as a bare text input (pages only fetch after an account ID exists + blur). Joel's localStorage hides this; Abel will hit a wall — he won't know `act_521142087204815`.

**Fix:**
- On modal open with no saved account ID, fetch ad accounts (`getAdAccounts` already exists in `lib/facebookApi.js` — used by campaign flows). If exactly one account, auto-fill it and immediately fetch campaigns + pages. If multiple, render an account dropdown.
- Keep the manual input as fallback only when the accounts fetch fails.
- While campaigns/pages load, show a small spinner/skeleton instead of the disabled placeholder text.

## 2. P1 — Copy Library → Quick Generate handoff is silent
**File:** `frontend/src/pages/ImageAds.jsx` (pendingQuickCopy effect + QuickGeneratePanel)
Clicking "Use" lands at the TOP of Quick Generate with no signal the copy was imported. The imported copy sits below the fold; the Angle Picker sits above it and a single angle click silently **overwrites** the imported copy. Brand/style also reset, and Generate is disabled with no explanation.

**Fix:**
- When `pendingQuickCopy` is consumed, show a dismissible banner at the top of the panel: `Copy imported from Copy Library: "<headline truncated>" — pick a brand and style, then generate.`
- While imported copy is present and untouched, add a confirm guard on Angle Picker apply: replace the copy only after an inline confirm (small "Replace imported copy?" on the card click, or collapse the Angle Picker section by default when copy was imported).
- Same banner pattern for the `pendingQuickCopy` arriving from Campaign Performance "Quick Variations" (`source: 'campaign_performance'`).

## 3. P2 — Disabled Generate button gives no reason
**File:** `ImageAds.jsx` QuickGeneratePanel
`canGenerate` requires brand + template + headline + body, but the disabled button is mute. Add a one-line hint under the button listing what's missing, e.g. `Missing: brand, style` (derive from the same booleans). No tooltip-only solutions — Joel won't hover.

## 4. P2 — Angle Picker shows Commercial Insurance angles under "All Verticals"
**File:** `ImageAds.jsx` AnglePicker
With filter=All and no brand, the fallback is `commercial_insurance`. Fine for Joel; confusing for Abel starting auto insurance/home services. Add a subdued line when the fallback fired: `Showing Commercial Insurance angles — pick a vertical above or select a brand to switch.` (Detect: no explicit vertical resolved from brand or filter.)

## 5. P2 — Style card selection state is easy to misread
**File:** `frontend/src/components/StyleSelector.jsx` (or wherever the card grid renders)
A check-mark circle appears on **hover**, which reads as "selected"; the real confirmation is a green banner *below* the 14-card grid (off-screen). Fix: persistent selected-state styling on the chosen card (border + check that stays), move/duplicate the "Selected: X" confirmation to the section header, and don't render a check affordance on hover. Also add `aria-pressed`/`aria-selected` to the card buttons (currently no selection state in the a11y tree).

## 6. P3 — Stale overlay subtitle
**File:** `ImageAds.jsx` — Text Overlay section subtitle still says "Bakes niche label + offer line into the image". Change to: "Bakes the main text, offer line + logo into the image."

## 7. P3 — Ad-copy quality guardrail note (no code unless cheap)
Observed in the existing library: "Barber Shop Insurance" creatives depict a **cocktail bar** (kie.ai misread "Barber"). With one-click Push now on the results grid, a wrong-scene image can reach Meta faster. Cheap mitigation if desired: on the results screen, show the niche + headline under each image so a mismatch is more noticeable before pushing. Do NOT build an AI image-QA step in this pass.

---

**Out of scope / known separately:** login takes ~8–10s (backend cold path, not frontend); headline 42/40 warning-only is intentional (Meta truncates); Copy Library spend/CPL columns are a separate pending spec; dead `ImageAdWizard.jsx` removal already queued as its own task.

**Verify before handing back:** `npm run build` passes; Use → banner shows; angle click doesn't silently clobber imported copy; fresh-profile (incognito) push modal auto-fills the single ad account and populates campaigns + pages without manual entry.
