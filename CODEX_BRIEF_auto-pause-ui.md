# Codex brief — Auto-Pause Rules page hardening (frontend)

`git pull origin develop` first. Frontend only: `frontend/src/pages/AutoPauseRules.jsx` (+ small shared helpers in `frontend/src/lib/`). Not a trigger file; commit locally, hand back to Claude Code for review + push. Never create/edit real rules against Meta while testing, never click "Run Check Now" on production.

Backend is already hardened (server validation: threshold > 0 and <= cap per metric, min_spend >= 1 for every non-notify action; one-shot rules are disabled before the Meta write; increases need a live ACTIVE ad set and stay under the $5,000/day ceiling). Don't change `backend/`.

Reuse: `components/BudgetConfirmModal.jsx` (Enter confirms / Esc cancels / autofocus pattern), `lib/budgetErrors.js`, and the rule validation + 2-step confirm in `CampaignPerformance.jsx` `AddRuleModal` (`RULE_DEFAULTS`, `RULE_WARN_ABOVE`).

## High (fix first)
1. **AddRuleModal pre-selects `adsets[0]`** (~line 74). Start with an empty selection; require an explicit pick (validation already errors on empty).
2. **Pause rules bulk-create with no confirm** (~145-152, 218-220). Route pause through the confirm step too (at least when N > 1) and list the target names.
3. **Ad-scope confirm count bug** (~129-132, 227-229, 242): count/button use `selectedAdsets` (always empty for ads). Derive from `targets.filter(selected)`.
4. **EditRuleModal has no confirm and no re-validation** (~535-563). Re-run the same number validation; if action or % changed, or action is increase/decrease/duplicate, show the confirm + amber warning. If `rule.triggered_at` is set (rule already fired and is disabled), say that saving does not re-arm it.
5. **Enable toggle has no confirm** (~1128-1134, 858-869). Confirm on enable (not disable): state action, %, target, and "may fire on the next check (every 30 min)".
6. **"Run Check Now" has no confirm** (~871-894). It evaluates every active rule and performs real Meta changes. Add a confirm listing the count of active rules by action type; rename "Run all rules now". Show the server's `detail` on failure (line 878 discards it).
7. **Scope unclear**: the check/rules list use an `ad_account_id` from localStorage or none. Show the account scope in the confirm and in the page header.

## Medium
8. Errors show `[object Object]` / generic text (~564, 215, 856, 855, 878, 892). Extract the create-time formatter (~195-209) into a shared `parseApiError` and use it for edit, toggle, delete, run check, logs. Guard `res.json()`.
9. Number inputs use `Number(e.target.value)` → empty becomes 0 (~385, 471, 483, 603, 682, 690). Keep raw strings, parse on submit, reject NaN/empty/out-of-range: threshold > 0 and <= cap (cpl/cpa 10000, ctr 100, roas 20), min_spend >= 1 unless notify.
10. `step="1"` blocks decimal CTR/CPL/CPA (~471, 682). Use `step="any"` (server threshold column is an integer today, so for now validate whole numbers and say so; decimals need a backend migration — don't attempt).
11. Percent not bounded in JS (~130-133, 385, 602): validate 1-100, whole numbers; add an amber "large change" confirm line over 50%.
12. Modal a11y: Add/Edit/Delete modals need `role="dialog"`, `aria-modal`, `aria-labelledby`, Escape to close, autofocus (Cancel for delete), focus return. Icon-only buttons (history/edit/toggle/delete) need `aria-label`; scope toggles `aria-pressed`; labels need `htmlFor`/ids.
13. Stale state: `ads` loaded once (~846 gate `ads.length === 0`) — reset on modal open, add refresh. `loadAdsets`/`loadAds` swallow errors (~813, 829) and show "No tracked ad sets… Sync them first" — show a load-failed state with Retry.
14. Copy: "None of them run more than once" is wrong for Notify and repeat-Duplicate (~285, 374, 1178) — condition on `form.action`. "How it works" (~1159) omits bid, duplicate and ad scope.

## Low
15. Rule summary formatting by metric (~1102: CTR `%`, ROAS `x`), fire-history value hard-codes `$` (~774), "Active Rules" counts disabled/fired rules (~1075), budget preview label should show the sync timestamp if available (~266).

## Verify
`cd frontend && npm run test:unit && npm run build && npx eslint src/pages/AutoPauseRules.jsx`. Add unit tests for any new pure helper (parse/validate). Browser-check on a dev session only: open the modals, keyboard through them, cancel everything.
End with: "Edits done — ready for Claude Code 2-agent review + push."

---

## Round 2 — state as of `00109f4` + Claude's follow-up fixes (supersedes the list above)

Done and reviewed: items 1 (no preselected ad set), 2 (bulk pause confirm), 3, 4, 5, 6, 7, 8 (create/edit/toggle/run-check), 9, 11. Claude then fixed: decimals now rejected client-side (server columns are integers), payload sends numbers via `ruleNumbersForPayload` (empty notify min_spend → 0), edit confirm also fires when metric/operator/threshold/min_spend change, pause/notify edits no longer always confirm. Tests added in `lib/autoPauseRules.test.js`.

Still to do (frontend only, same constraints — commit locally, hand back):
1. **Single pause rule confirm** (Joel P1): a pause rule on ONE ad set still creates with no confirm. Confirm always for pause; wire `RULE_WARN_ABOVE` (imported, unused) as an amber "implausible threshold" warning; if live data is already on the page, say how many selected targets already breach the rule.
2. **Run-check confirm**: show the account NAME (not the raw `act_…` id / "server default account"); say it only runs rules early (the scheduler already runs every 30 min); list which ad sets/ads would act if cheap to derive.
3. **Keyboard/a11y (item 12)**: Esc closes, Enter confirms, on Add/Edit/Delete/Enable/Run dialogs (pattern: `components/BudgetConfirmModal.jsx`); `role="dialog"`/`aria-modal`/`aria-labelledby` on the Add and Edit form modals; `aria-label` on icon-only buttons; `aria-pressed` on scope toggles; `htmlFor`/ids on labels; focus returns on close; Delete defaults focus to Cancel.
4. **Item 13**: reset `ads` when the Add modal opens + a refresh; show a load-failed state with Retry instead of "No tracked ad sets… Sync them first" when `loadAdsets`/`loadAds` fail.
5. **Item 14 copy**: "None of them run more than once" (~line 288) is wrong for Notify and repeat-Duplicate — condition on action; update "How it works" (omits bid, duplicate, ad scope). Remove the duplicated "creates N independent rules" line in the pause confirm.
6. **Enable confirm**: if the rule already fired (`triggered_at`), say enabling does not re-arm it / how to re-arm; say whether it is currently breaching if known.
7. **Delete/logs/loadRules errors** still generic — use `parseApiError`.
8. Decrease budget/bid at 100% can zero a budget: hard-warn above ~90%.
9. Low: format summary by metric (CTR %, ROAS x), fire-history `$` only for CPL/CPA, "Active Rules" count excludes disabled/fired, ROAS spinner `step` 0.1 is pointless while thresholds are integers — leave at 1 and say whole numbers only in the helper text.

Verify: `cd frontend && npm run test:unit && npm run build && npx eslint src/pages/AutoPauseRules.jsx src/lib/autoPauseRules.js`.
End with: "Edits done — ready for Claude Code 2-agent review + push."
