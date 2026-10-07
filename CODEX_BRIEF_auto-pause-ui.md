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
