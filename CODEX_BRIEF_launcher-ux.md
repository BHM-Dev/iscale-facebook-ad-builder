# Codex follow-up — Launcher UX (state as of `fac96bf`)

`git pull origin develop` first. Frontend + one small backend endpoint. `BulkAdCreation.jsx` and `AdCreativeStep.jsx` are trigger files — edit locally, don't push; hand back to Claude Code for the 2-agent review + push.

## Already shipped (don't redo)
Keyboard/whole-card Drive selection, hover reasons, `Clear (N)`, visible No-copy/Blocked pills, Feed+Stories review counts, status-accurate paused/live copy, existing-target status + budget lines, live Meta status check on Review (gates launch; 15s timeout; Retry check + "I checked Ads Manager" acknowledgement; "unverified" labels after an acknowledged failure), red LIVE banner / gray "will not spend yet" banner, partial-failure retry note.

## 1. Browser verification (not yet done by anyone — all findings so far are from reading code)
Dev session, test ad account, **never click the final Launch / create any Meta ad**.
- Drive picker: hover a blocked card and a "No copy" pill → tooltip shows the reason. Tab to a blocked card, Enter → warning toast fires. Tab to Preview, Enter → preview opens, selection unchanged. Space on a card toggles it.
- Selected badge (`bottom-10 right-2`) vs status pills (`bottom-10 left-2`): check a narrow 5-column card and a Feed+Stories pair card for overlap; reposition if they collide.
- `Clear (N)` clears only the pending picker selection; already-added creatives remain.
- Review with existing campaign + existing ad set: block `/campaigns` in devtools → red banner, Launch disabled, reason line under the button, Retry check works, acknowledge checkbox releases the hold and labels switch to "unverified". Throttle to >15s → timeout error path.
- Pause the ad set in Ads Manager after picking it → Review shows PAUSED after the check.
- Existing campaign + **new** ad set (Drive separate-ad-sets mode) → status check runs, LIVE banner appears when campaign is ACTIVE.
- Sticky footer: the reason `<p>` stacks under the Launch button (right-aligned) without disturbing Back/Launch layout, incl. mobile width.
- Force a failure on ad 2 of 3 (invalid URL or mocked 500) with existing campaign + ad set: confirm which retry UI shows vs the reconciliation lock.

## 2. Status check: fetch by id (backend + frontend)
`getCampaigns(accountId)` lists every ACTIVE/PAUSED campaign (limit 500) and `getAdSets(campaignId)` pulls targeting/schedule fields just to read one status — slow, and trips Meta rate limits (code 17 hit on `act_521142087204815` before). Also drops WITH_ISSUES / IN_PROCESS campaigns → false "not found".
- Add `GET /facebook/campaigns/{id}` and `GET /facebook/adsets/{id}` returning only `id,name,status,effective_status,daily_budget,lifetime_budget`. Lightweight, single Meta `api_get`.
- Use them in the Review effect (`BulkAdCreation.jsx`, live-status `useEffect`). Distinguish error types: 404/archived/deleted vs rate-limit (code 17)/timeout vs network, with distinct copy. Rate-limit/timeout = acknowledge allowed; deleted/archived = hard block with only "Go back".
- Also read `effective_status` and show it when it differs from `status` (e.g. campaign ACTIVE but effectively PAUSED/WITH_ISSUES).

## 3. Review step
- Re-check status at click time for existing-campaign launches (or at least when the tab regains focus); show "checked HH:MM" aging ("checked 3 min ago") with a Refresh link.
- Show the existing campaign budget on Review for CBO ("Campaign budget $X/day (CBO)") — it's fetched but not displayed.
- After an acknowledged failure, show a "status unverified" banner (currently no LIVE/paused banner at all in that state).
- Consolidate the three overlapping status boxes (live-check banner, summary, ad-set status) into one "Delivery" block: Campaign [status] · Ad set [status] · Ads will be [ACTIVE/PAUSED] · Budget.
- Product decision for Steve before building: a "create ads paused" toggle (Ads Manager default) when parents are ACTIVE. Do not build without sign-off.
- Add spinner to the pending state; Ads Manager deep links beside "verify in Ads Manager".
- Ad-set budget mirror: when the live ad set has a lifetime budget, also set `adsetData.budgetScheduleType = 'LIFETIME'` (local DB mirror currently saves lifetime>0 with `DAILY`).

## 4. Partial failure / retry
- Unlocked-errors branch for Drive launches says "not safe to replay" right beside a green "Retry remaining ads" — make the Drive text conditional on the same condition that locks (`createdAdIds` / uncertain rows exist).
- List created ad names (Created / Failed / Unknown) in the amber box; label the button "Retry N remaining ads".
- "No Meta objects were created" (non-Drive text) is slightly overstated — image/creative objects may exist as orphans.

## 5. Drive card polish
- aria-label includes only "Select ad {file}" — add blocked reason via `aria-describedby`.
- Pill `title` attributes are dead code under the overlay (card-level `cardTitle` owns hover) — remove.
- A selection that becomes blocked after a Drive refresh still shows "Selected" — prune or show the blocked state.
- "No copy" pill: amber outline so it's visible across a 20-tile grid; truncate the long red pill. Rename `Clear (N)` → `Clear selection (N)`.
- `ProductForm.jsx:179` says "Drive manifest URL" — reword for users. (`DrivePackageHealth.jsx` mentions match the real `HANDOFF-MANIFEST.txt` filename; leave.)

## Verify
`cd frontend && npm run test:unit && npm run build && npx eslint src/components/AdCreativeStep.jsx src/components/BulkAdCreation.jsx src/components/BulkMatchImport.jsx src/lib/launchPlan.js src/lib/launchDraft.js src/lib/driveCreativeSelection.js`
Space out live-verification calls against one ad account (Meta rate limit).
End with: "Edits done — ready for Claude Code 2-agent review + push."
