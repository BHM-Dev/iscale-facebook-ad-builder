# Approvals Queue (proposals on Campaign Performance)

Spec: [`docs/briefs/AdBuilder-Approvals-Queue-Brief.md`](../briefs/AdBuilder-Approvals-Queue-Brief.md).

## What it does
- Every hour, a job evaluates each ad set's real profit: Switchboard billable revenue minus Meta spend.
- When a trigger fires, it writes a **proposal**, either to pause the ad set or to raise its daily budget by 20%. The proposal carries a snapshot of the numbers behind it.
- Joel or Abel approves or dismisses each proposal. **Nothing reaches Meta without a click.**
- Existing auto-pause rules are untouched.

## Triggers
Thresholds come from a replay of RHO's real 30 days (see the brief §1), and live in `app/services/proposal_service.py`.

| Key | Condition | Action |
|---|---|---|
| `no_revenue_spend` | Spent ≥ $50 today and $0 revenue over the last 3 days | Pause |
| `loss_3d` | 3-day spend ≥ $150 and 3-day profit ≤ −$150 | Pause |
| `scale_winner` | 7-day spend ≥ $200, ROI ≥ 50%, profitable on ≥ 4 of 7 days, has a daily budget | +20% daily budget, capped by `MAX_DAILY_BUDGET_CENTS` |

- There is **no CPL trigger**. In the replay, ad sets with a CPL spike went on to make +$11.3k over the next 3 days.
- Only live ACTIVE ad sets are evaluated. A pause trigger beats a raise.
- Each ad set has at most one open proposal, and isn't re-proposed for 3 days after a decision.

**Expiry.** An open proposal expires when:
- the condition clears;
- the ad set is no longer active;
- it has been open for 24 hours.

## Money safeguards (server-side)
- **Approve re-checks the ad set live in Meta.** If its status or budget no longer matches the proposal, the proposal becomes `stale` and nothing is sent.
- **Approve executes exactly once.** It does an atomic `open|failed → executing` update, so a double click or a second tab gets a 409.
- **Budget raises use the budget editor's guards:** `_enforce_budget_sanity`, which includes the ceiling and the large-change check.
- **Revenue unavailable:** no proposals are created and none expire. Missing revenue is never treated as $0.
- **Permissions:** approve and dismiss need `campaigns:write` and access to the account.
- **"Today" is the ad account's own day,** read from Meta's `timezone_name`, not the server's UTC date. A day with no spend yet can't fire `no_revenue_spend` on yesterday's numbers.
- **Empty revenue counts as unavailable.** If the account has ≥ $500 spend in the window and zero revenue rows, the run is treated as "revenue unavailable" rather than as $0 everywhere.
- **Expiry can't overwrite a decision.** Expiry is a status-guarded UPDATE, so if someone clicked Approve between the evaluator's read and its write, the click wins.
- **Interrupted approves:** a proposal stuck in `executing` for more than 15 minutes is released as `failed`. Retry re-checks the ad set live first.
- **Failed proposals** stay on the panel, with Retry, for 24 hours.
- **Transient Meta states:** `IN_PROCESS` and `WITH_ISSUES` count as still running when re-checking a pause, so they don't produce a false `stale`.

## Shadow week
- `PROPOSALS_SHADOW` defaults to true. Only the emails in `PROPOSALS_SHADOW_VIEWERS` see proposals; everyone else gets `visible: false`.
- `GET /proposals/shadow-report` compares proposals with what people actually did, using Meta's activity log (`/act_{id}/activities`):
  - an ad set is `object_type: CAMPAIGN` in that log (legacy naming);
  - people are identified by `actor_name`;
  - actions that match an auto-pause rule log entry within 10 minutes are excluded.

## Endpoints (`/api/v1/proposals`)
- `GET ""`: open proposals and the last-run state.
- `GET /history`
- `GET /stats`
- `POST /{id}/approve`
- `POST /{id}/dismiss`
- `POST /events`
- `GET /shadow-report`
- `POST /evaluate`: admin only. Runs the evaluator now; never writes to Meta.

## Config
| Env var | Default | Meaning |
|---|---|---|
| `PROPOSALS_ENABLED` | true | Turns the hourly job on or off |
| `PROPOSALS_SHADOW` | true | Shadow week on |
| `PROPOSALS_SHADOW_VIEWERS` | none | Comma-separated emails who can see proposals during the shadow week |
| `PROPOSALS_ACCOUNT_IDS` | Every Switchboard-revenue account | Accounts the evaluator covers. Only accounts with a Switchboard revenue source are kept. **Production (set 2026-11-02, Steve):** `act_521142087204815,act_737291135429748` — RHO and RHO 4, the accounts actively running commercial insurance |

## Status
- **Unit-tested:** triggers, dedupe and expiry, approve (executed, stale, failed then retry, double click), dismiss validation, activity-log parsing, and shadow matching (`tests/unit/test_proposals.py`).
- **Verified in production 2026-11-02** (`c8ec09d`, run from Steve's Chrome):
  - Migration `ad5e6f708192` applied, and both tables exist.
  - First evaluation: 4 Switchboard accounts in 12.3s, revenue available on all. RHO got 7 `scale_winner` proposals, for example ROI 82–105% on $441–$3,349 of 7-day spend, with raises such as $350 → $420/day. No pause proposals (the run was mid-morning in the account's timezone). The other 3 accounts got none.
  - Shadow report on RHO's live activity log (8.4s): Joel made 57 ad-set pauses and 47 budget increases over 7 days. 17 actions by the token owner were counted as people. 0 were excluded as rule actions, because no rule fired.
- **Not verified:** a real Approve or Dismiss (nothing has been clicked yet), the hourly job firing unattended, and the panel UI (with Codex: `CODEX_BRIEF_approvals-queue-panel.md`).

## Open items
- Phase 1.5: an outcome job that fills `outcome_3d`.
- Revenue days are bucketed in Eastern time, while Meta spend days use the account's timezone.
- Phase 2: editable thresholds, ad-level proposals, the BHM Everflow accounts, and a Slack summary per vertical channel.

## Changelog
- 2026-11-02: Phase 1 backend (models, migration `ad5e6f708192`, evaluator, endpoints, shadow report).

## Panel (2026-11-02)
- `ProposalsPanel.jsx` sits on Campaign Performance, above Creative Compass. The open count shows as a badge on the Facebook nav item. Both are hidden for anyone outside `PROPOSALS_SHADOW_VIEWERS` during the shadow week.
- Approve shows a success toast. A 409 shows "Already handled". Stale and failed results stay on the card (failed ones get a Retry). A gateway or non-JSON error reloads the list, because the Meta write may have landed.
- Only one approve can be in flight at a time.
- *Unit-tested only* (8 vitest cases); not yet clicked in production.
