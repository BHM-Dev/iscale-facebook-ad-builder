# Codex Brief: split the Profit/Loss page into per-account gross and an all-accounts net

**Steve's decision, 2026-07-29.** Monthly costs are business-level, not account-level. Showing them on every account's view means the same $350 appears in several places and gets mentally added up more than once.

> "Because we are showing revenue and spend by ad account, we'll need an overall view to calculate net profit. If we're looking at specific ad accounts, we can just display gross profit for that ad account."

So:

| Scope | Shows |
|---|---|
| **A specific ad account** | Ad Spend · Billable Revenue · **Gross Profit** · Margin on gross. **No costs. No net profit.** |
| **All accounts** | Combined Ad Spend · combined Billable Revenue · Gross Profit · **Monthly Costs** · **Net Profit** |

Costs and net profit exist in exactly one place — the All accounts view. That is what makes double counting impossible.

---

## Money math — get these exactly right

**Gross profit** = `revenue − spend`. Per account in account scope; the sum of every account's revenue minus the sum of every account's spend in all-accounts scope. Both give the same number for the combined case; compute it from the summed totals.

**Which accounts are "all"?** The accounts the requesting user is permitted to see, intersected with accounts that actually have ad sets. Reuse `_active_account_ids(db)` and the existing scoping in `_resolve_scoped_default_account` / `User.allowed_account_ids()`. A scoped user must never see an aggregate that includes an account they can't access.

**Costs in all-accounts scope:**
- an all-account cost entry (`ad_account_id IS NULL`) counts **once, at its full amount**. `allocation_method` is irrelevant here — do not divide it. A cost stored as `even` or `by_spend` still counts once in full in this view, because the whole point is that the business paid it once.
- an account-specific cost counts once, for its own account.
- `pct_of_*` types resolve against the **combined** bases: `pct_of_spend` on combined spend, `pct_of_revenue` on combined revenue, `pct_of_gross_profit` on combined gross, `pct_of_profit` on combined gross minus all non-`pct_of_profit` costs. The existing ordering rules in `_resolve_costs` still apply — a `pct_of_profit` cost never sees another `pct_of_profit` cost, and floors at $0 on a loss.
- `recurring_monthly` still multiplies by overlapping months via `_overlap_months`.

**Net profit** = combined gross − total costs. Only in all-accounts scope. **Never** compute a net profit in single-account scope — that is the misleading number this change exists to remove.

**Margin:** in account scope it is gross ÷ revenue. In all-accounts scope it is net ÷ revenue. Label them so they can't be confused — "gross margin" vs "net margin".

---

## Backend

`GET /pnl/summary` and `GET /pnl/months` take `ad_account_id`. Add an aggregate mode — `ad_account_id=all` is fine, or a separate `scope=all` param, your call, but be consistent across both endpoints.

In aggregate mode:
1. resolve the permitted account list
2. get spend and revenue per account (reuse `_spend_for_account` and `_revenue_for_account` — the per-account revenue provider still applies, so one account can be on Switchboard while another is on RedTrack)
3. sum them, then resolve costs once against the combined figures
4. `data_incomplete` is true if **any** account's fetch failed, and say which in `errors`. A partial aggregate presented as a total is exactly the class of bug we keep finding.

For `/pnl/months` in aggregate mode, reuse `pnl_month_snapshots` per account and sum the snapshots — that is what keeps it fast. A month is only servable from cache if **every** account in scope has a snapshot for it; otherwise fetch that month.

Response should carry `gross_profit` explicitly rather than leaving the frontend to subtract, and a `scope` field (`account` | `all`) so the UI knows which shape it is rendering.

---

## Frontend — `frontend/src/pages/Pnl.jsx`

Add a scope control near the period controls: **All accounts** / the active account. Default to **All accounts**, since that is the view with the bottom line on it.

- **All accounts scope:** five tiles — Ad Spend, Billable Revenue, Gross Profit, Monthly Costs, Net Profit. The cost ledger section stays, as does month-over-month.
- **Account scope:** Ad Spend, Billable Revenue, Gross Profit, Gross Margin. **Hide the cost ledger and any net profit.** Put one quiet line where the costs section was: *"Monthly costs and net profit are on the All accounts view — they're business-wide, not per account."*
- Month-over-month follows the same rule: in account scope its Costs and Net columns are hidden, not zeroed.
- Adding or editing a cost stays available from the All accounts view only.

Keep the existing behaviour otherwise: the `Gross`/`Incomplete` badges, the `stored`/`live` badges and Re-fetch button, the collapsible event breakdown, the unattributed-revenue line, CSV export.

---

## Constraints

- **Do not** show a net profit for a single account under any circumstance.
- **Do not** divide an all-account cost in the aggregate view. Counted once, in full.
- No new tiles beyond the five per scope. No CPL. The scope guard in `CODEX_BRIEF_pnl_everflow_revenue.md` still holds.
- Don't touch `models.py`, `main.py`, `backend/alembic/versions/`, or the four trigger files.
- No migration should be needed — `allocation_method` stays as it is, it simply stops mattering in the aggregate view.
- **Don't push.** Hand back to Claude Code for review.

## Done means

State, from a live check against `act_521142087204815` and the all-accounts view:
- gross profit for RHO alone, and combined gross across accounts
- total monthly costs, and that the $350 RedTrack entry appears **once** at $350
- net profit in the all-accounts view, and that no net profit renders in account scope
