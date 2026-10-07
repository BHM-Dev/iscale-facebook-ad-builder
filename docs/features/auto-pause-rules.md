# Auto-Pause Rules (`/auto-pause-rules`)

Rules evaluated every 30 minutes (APScheduler, `main.py`) against live Meta insights (`last_7d`, which excludes today).
Actions: pause (ad set or ad), notify (Slack), increase/decrease budget, increase/decrease bid, duplicate ad set.
Code: `frontend/src/pages/AutoPauseRules.jsx`, `backend/app/api/v1/auto_pause.py` (`_run_check`).

## Money safeguards (server-side — the ones that count)
- **Rule numbers validated on create/bulk/patch:** threshold > 0 and <= cap (CPL/CPA 10000, CTR 100, ROAS 20); `min_spend >= 1` for **every non-notify action** (was pause/decrease only — an increase with `min_spend 0` could scale on one lead). Runtime guard also enforces a $1 floor for legacy rows saved with 0.
- **One-shot rules are claimed before the Meta write** (`_claim_rule`: atomic `UPDATE … WHERE is_active`), so the scheduler and a manual `/check` can't both apply a +20% (would compound to +44%). Transient failure re-arms; permanent failure disables + Slack alert. If the process dies between claim and write the rule shows "Claimed for firing — write not confirmed".
- **Increase budget/bid only on a live ACTIVE ad set** (reads `effective_status` from Meta right before writing; skips otherwise — local status can be stale).
- **$5,000/day ceiling on rule-driven increases** (`MAX_DAILY_BUDGET_CENTS`, applied in `adjust_adset_budget_by_percent`); hitting it disables the rule and alerts.
- **Zero-lead spend counts as a CPL breach** for `cpl greater_than` once spend ≥ min_spend (previously "no data", so the worst case never paused). Only when Meta reports `leads == 0`, no ROAS value exists, and spend ≥ 2× the threshold (guards purchase-optimized ad sets and attribution lag). Repeat-duplicate rules are not claimed (cooldown only).
- **Failed duplicate:** one-shot rule stays disabled (a partial copy may exist on Meta; retrying would create another); repeat rule starts its cooldown; Slack alert.
- **Visibility:** a failed Meta insights fetch for an account is now listed in the check's `errors`; a crashed scheduler run posts a Slack summary error.
- Rule auto-disables only when the target is confirmed DELETED/ARCHIVED in Meta (2026-10-06).

## Verified vs not
- **Unit-tested:** rule-number validation (incl. increase/duplicate/bid with min_spend 0).
- **Verified in production 2026-10-07** (script in the backend container, paused ad set, no Meta write): live status read returns `PAUSED`/`PAUSED` (so the increase skip would trigger); a +10000% adjust on the $50 ad set was refused at the $5,000 ceiling and the budget stayed $50; `_claim_rule` run from two sessions returned True then False, and the claimed row showed the "Claimed for firing — write not yet confirmed" reason. Temp rule deleted.
- **Not verified live:** full `_run_check` path (re-arm on transient failure, zero-lead breach, failure alerts) — a check evaluates every active rule, so it wasn't run.
- **UI (shipped 2026-10-07, unit-tested only, not browser-verified):** no preselected ad set; confirms on bulk pause, percent/duplicate rules, enable, edit (action/percent/condition changes) and "Run all rules now"; readable API errors; numbers validated as whole numbers and sent as integers.
- **Browser-verified in production 2026-10-07 (`0270c2f`; nothing created, nothing run):** Add Rule opens with no ad set selected ("Applies to 0 ad sets"); a single pause rule goes through a "Confirm pause rule" step; Esc steps back from that confirm to the form, and Esc again closes the modal; "Run all rules now" opens a dialog naming the account (RHO - Commercial Insurance), "Active rules: 0" and that it only runs an early check, and Esc cancels it. A first attempt showed Esc closing the whole modal (handler race), fixed with a capture-phase listener.
- **UI round 2 shipped** (Codex `70b58a1` + Claude Esc/focus fixes): pause always confirms (red alert if loaded data already meets the condition, no autofocus on Confirm when a warning shows), run-check names the account and says it only runs rules early, Esc steps back from confirm and is ignored while saving/typing, load-failed state with Retry, 90%+ decrease warning, corrected copy.
- **UI still open:** the already-breaching check only sees data on the loaded ad set rows (usually none), so silence is not safety; Enter-to-confirm pattern, `aria-pressed`/label ids, focus return; run-check doesn't list which ad sets would act; 'How it works' omits bid/duplicate.

## Open items
- `last_7d` window: a same-day blowup is invisible until tomorrow, and a brand-new rule sees pre-existing spend. Needs an explicit window field (migration).
- ROAS rules use Meta purchase ROAS, not Switchboard/RedTrack revenue — mostly dead on lead-gen accounts.
- Skipped increases (ad set not ACTIVE) are only in the check response, not Slack.
- Lifetime budgets and bid increases have no ceiling; ceiling is global, not per account.
- Local `daily_budget` isn't updated after a rule write until the next sync.
- Retry-forever on token/permission errors (no failure counter); ad-scoped rules can't detect a deleted ad.
- Decimal thresholds (ROAS 1.5, CTR 0.5) need a DB migration (threshold is Integer).
- Unscoped users can create increase/duplicate rules; consider a permission.

## Changelog
- 2026-10-07 UI hardening round 2 (Codex `70b58a1` + Esc/focus/warning fixes).
- 2026-10-07 UI hardening round 1 (Codex `00109f4` + Claude integer/payload and edit-confirm fixes).
- 2026-10-07 enforcement hardening (claim-before-write, live-ACTIVE check, ceiling, zero-lead CPL, min_spend floor, failure alerts); frontend brief for Codex.
