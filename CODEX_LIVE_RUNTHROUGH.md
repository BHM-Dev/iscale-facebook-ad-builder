# Codex Task: Live Run-through of the Deployed App

Drive the real app in a signed-in browser and find anything glitchy. This is a QA pass, not a code review — click things, watch what breaks.

**URL:** https://adbuilder.velocitymx.io
**Account to use:** `RHO - Commercial Insurance` (`act_521142087204815`) — the active, primary account
**Just deployed:** commits `892017a..704ad96` — new `/pnl` page, Dashboard MTD strip, P&L nav entry, page title/favicon change

---

## ⚠️ This is production

Joel uses this daily. The database is live.

- **Do not push anything to Meta.** No ad creation, no launches, no status changes, no budget edits. If a flow ends in "Push to Meta" or "Launch," stop at the confirmation and back out.
- **Cost-ledger writes are real.** You need to exercise the Add/Edit/Delete cost flow, so create entries labelled exactly `ZZ TEST — delete me` and **delete every one before you finish.** Report the count you created and the count you deleted.
- **Do not delete or edit anything you did not create.** If you find pre-existing cost entries, leave them alone.
- **Stay on `act_521142087204815`** except for the one account-switch test below. Ignore United Debt Help, The Better Normal, and ResourceHelpOnline entirely.
- **Do not push code.** If you find a bug, write it up; don't fix and ship.

---

## Known and expected — do NOT report these as bugs

These are all correct behaviour. Reporting them wastes a round trip.

1. **February 2026 shows ~$20,420 spend, $0 revenue, and a large loss. March looks bad too.** RedTrack wasn't live until March. Steve explicitly decided not to flag or suppress these.
2. **Margin can read as a wild negative** (e.g. −300.9% for March). Deliberate — Steve wants lifetime performance visible, unsmoothed.
3. **Net Profit shows a grey `GROSS` badge and an amber banner** while no cost entries exist. That's the point: it isn't real net until the ledger has entries.
4. **Billable Revenue caption reads `RedTrack · live`.** The Switchboard/Everflow switch is code-complete but waiting on env vars. If it reads `Switchboard`, Golden has landed them — note it, that's not a bug either.
5. **An amber banner about ~112 ad sets having no RedTrack rows.** Expected — mostly old paused ad sets.
6. **No CPL anywhere on the P&L page.** Deliberate scope decision.

---

## Walk this

### 1. P&L page — the new surface, test it hardest

- Nav: is there a **P&L** entry directly under Dashboard? Does it route to `/pnl`?
- Header: title reads **Profit & Loss**, two lines not three, account name + id visible, not cramped or overlapping at normal desktop width. Also check ~1280px and a narrow window — does the meta line wrap sanely or collide with the period controls?
- Period controls: switch **MTD → Month → Custom range** and back. Pick several months with the month picker. Does each load, and do the tiles and both tables all update together?
- **Custom range with the dates left empty** — you should get a clear prompt to choose dates, not a blank/broken-looking page.
- **Custom range with end before start** — expect a clean error, not a crash.
- **Refresh** button: spinner behaves, data reloads, no duplicate rows.
- **Add cost** modal, one entry per type: `one_off`, `recurring_monthly`, `pct_of_spend`, `pct_of_revenue`, `pct_of_gross_profit`, `pct_of_profit`. For each percent type, confirm the live preview line shows a resolved dollar figure that matches the percentage of the stated base. Enter `5` and check the maths.
- Validation: blank label; percent **over 100**; `effective_to` before `effective_from`. Each should give a readable toast, not a 422 dump or a silent no-op.
- **Applies to → All ad accounts**: the Allocation dropdown should appear. Save one, confirm the row shows an `All accounts` pill and a "this account" share smaller than the full amount.
- **Edit** an entry — does the modal pre-fill correctly, including the Applies-to and Allocation values?
- **Delete**: custom modal with backdrop blur and a red button (never a native `confirm()`). For an all-accounts entry, the copy must warn it affects **every** account's ledger.
- With entries logged, confirm Other Costs is non-zero, the `GROSS` badge disappears, and Net Profit picks up green/red colour.
- **Export CSV** — open it. Do the numbers match what's on screen for the selected period?
- **Account switch while sitting on `/pnl`**: switch to `DIN Auto Insurance`, then back. Does everything refetch, or do stale numbers from the previous account linger in the tiles, cost ledger, or month table? Watch closely for a mixed state mid-load.

### 2. Dashboard

- Is there a **Running P&L** strip near the top? Five tiles, MTD, correct account?
- Does clicking it land on `/pnl`?
- Do its numbers agree with the P&L page's MTD figures? **A mismatch here is a real finding — report it.**
- Does the rest of the Dashboard still work — date filter, Performance by Niche, Needs Attention click-through?

### 3. Branding change

- Browser tab title should read **Ad Builder**. It must not say "BreadWinner - Fresh Campaigns" anywhere.
- Favicon should be the BHM logo, not a bread emoji. Check it actually loads and isn't a broken-image icon.

### 4. Smoke-test Joel's daily path

`Layout.jsx` changed, so re-confirm nothing regressed in normal use. Load each and check it renders without a blank page or console error — no need to complete the flows:

Campaign Performance · Build New Ad (`/ad-remix`) · Batch Generate · Image Ads · Copy Library · Research · Generated Ads · Brands · Products · Customer Profiles · Facebook Campaigns · Winning Ads · Auto-Pause Rules

Open the **Remix drawer** on a Campaign Performance row and confirm it opens and closes cleanly. Don't generate.

### 5. While you work

Keep the browser console and network tab open. Note any red console errors, any 4xx/5xx that isn't an expected 401, and anything that takes more than ~10 seconds. `/pnl/months` is the most likely slow one — time it and say how long.

---

## Output

Group findings as:

- **Broken** — errors, blank pages, wrong numbers, data loss
- **Glitchy** — flicker, stale data, layout collisions, bad wrapping, slow loads
- **Cosmetic** — copy, spacing, alignment

For each: where you were, what you clicked, what you expected, what happened. A screenshot for anything visual.

Then state plainly: **test cost entries created, and deleted.** They must match.

If you find nothing wrong, say so — don't manufacture findings. "Clean" is a legitimate result and more useful than padding.

**Do not fix anything and do not push.** Report back, and Claude Code will triage.
