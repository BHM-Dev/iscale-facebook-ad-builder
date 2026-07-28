# Phase 2 Review — P&L Tracker. NOT PUSHED.

Two review agents (backend correctness + media-buyer perspective) plus a manual read. Findings below are confirmed against the code, not speculative. **Do not push until the BLOCKING items are fixed.**

The through-line: the page renders authoritative-looking money numbers that are systematically wrong, and it looks *most* confident exactly when the data is broken. For a P&L, that is worse than an error page.

---

## BLOCKING — fix before push

### B1. Revenue is cache-only, and the cache query can never match a month

`_redtrack_revenue()` never imports or calls `RedTrackService`. It reads `redtrack_cache` exclusively. The brief specified live `get_report_by_adset(date_from, date_to)` as primary, cache as fallback.

That alone would be a spec deviation. The killer is how the cache is shaped: rows are written by `/redtrack/sync` from `preset_to_dates(date_preset)`, default `last_7d`. There is **no scheduler entry** writing them on any cadence. So:

- The exact-match arm (`date_from == start AND date_to == end`) never matches a monthly query.
- The fallback arm requires **full containment** (`date_from >= start AND date_to <= end`). A `last_7d` row spanning `06-28..07-04` is excluded from a July query entirely, despite 4 of its days being in range.
- **July full-month query:** returns whatever fragment of 7-day cache happens to sit wholly inside July, against a *full month* of Meta spend. Revenue massively understated → fabricated loss.
- **MTD query on July 3rd:** today's cache row spans `06-27..07-03`, `date_from < start`, excluded → **revenue = $0**, net profit = −spend. The page shows a pure loss for a converting account.

**Fix:** call `RedTrackService().get_report_by_adset(start.isoformat(), end.isoformat())` live for the period. Fall back to cache only on exception, and when you do, use an **overlap** test (`date_from <= end AND date_to >= start`), not containment. Set `revenue_source` from the branch actually taken.

### B2. Meta API failure silently becomes "$0 spend"

`_spend_for_account()` catches every exception and returns `Decimal("0")`. During a Meta outage or rate-limit: spend = 0, `net_profit = revenue − 0 − costs` (inflated), margin becomes a great-looking percentage, and every `pct_of_spend` cost resolves to 0 — inflating profit further. Nothing in the payload says the number is missing.

The page looks *better* precisely when it's broken. That is the single worst failure mode for this feature.

**Fix:** don't catch-and-zero. Return `spend=None` with a `data_incomplete: true` flag and have the UI render "Meta data unavailable" instead of a figure.

### B3. `get_months()` is an N+1 Meta fan-out

Each of the 6 `_summary()` calls hits `_spend_for_account` once, and because any `ad_account_id=NULL` cost entry sets `needs_allocation`, also calls `_spend_map()` which loops **every** active account. With 4 accounts and Abel's retainer present (exactly the specced shape): `(1 + 4) × 6 = 30` synchronous Graph API calls in one request. It will time out or trip rate limits — which per B2 degrade silently to zeros, producing a wrong 6-month trend with no error.

**Fix:** compute `_spend_map` once per request and reuse it across all months, including for the primary account.

The month-stepping arithmetic itself is correct for i=0..5 (verified by hand) — just convoluted. Leave it or simplify, your call.

### B4. `recurring_monthly` is charged once regardless of period length

The branch chain special-cases only the four `pct_*` types; `one_off` **and** `recurring_monthly` both fall through to `resolved_amount = amount * share`. A $3,000/mo retainer over a custom 3-month range resolves to $3,000, not $9,000. Costs understated 3×, net profit overstated by the same. Correct by coincidence for single-month views, which is why it survived testing.

**Fix:** multiply by the number of months the entry's effective window overlaps with `[start, end]`.

### B5. Superuser with no `ad_account_id` gets incoherent output

`_resolve_scoped_default_account` returns `None` unchanged for unrestricted users. `normalize_account_id(None)` → `None`. Then `FacebookAdSet.fb_account_id == None` renders `IS NULL` and matches nothing → **revenue always 0** — while `_spend_for_account(None, ...)` passes `None` to the Meta SDK and reports on some undefined default. Revenue and spend describe different things, and the response still renders a complete P&L card that reads as "all accounts."

The frontend always passes `activeAccountId`, so this is API-level only — but it's a trivially reachable wrong answer.

**Fix:** require an explicit account, or aggregate properly. Don't pass `None` through as if it were an account id.

### B6 (P0, UI). Failed refresh keeps stale numbers on screen

In `Pnl.jsx` `load()`, a non-ok response throws before `setSummary`/`setMonths`. Neither is cleared. The tiles and both tables keep rendering the **previous** account's or period's numbers, visually identical to a fresh load. The only signal is an auto-dismissing toast.

**Fix:** clear state or set an explicit stale flag on failure, and render an error state in place of the figures.

### B7 (P0, UI). "Gross" profit styled identically to real net profit

When `has_costs` is false — the default for any new account — the Net Profit tile still renders bold and color-coded, distinguished only by a 12px gray caption reading "Gross". Joel skims a green number and scales spend on a figure that is pre-retainer, pre-commission, pre-tooling.

**Fix:** hard banner or badge on the tile, not a caption. The number should not look final when it isn't.

---

## HIGH

### H1. No authorization on all-accounts cost entries

`update_cost` and `delete_cost` only check scope when `entry.ad_account_id` is truthy. For `ad_account_id=NULL` entries — Abel's retainer, exactly the specced shape — the check is skipped for **every** user. A user scoped to one account can edit or delete a cost affecting every account's P&L.

Low real-world blast radius today (only Joel and Steve hold `pnl:write`), but it's an unguarded write path on the most sensitive row in the table.

**Fix:** require `current_user.allowed_account_ids() is None` (unrestricted) to mutate a null-account entry.

### H2. Percent amounts are unbounded

`amount: Decimal = Field(..., ge=0)` with no upper bound and no cross-field check. Entering `500` for a `pct_of_*` type computes 5× spend as one cost line, no error. A typo of 50 instead of 5 for Abel's commission silently corrupts the P&L.

`pct_of_profit` is otherwise **correct** — verified non-circular (base computed once before any profit-based entry applies, so multiple entries don't compound) and correctly floored at 0 on negative profit.

**Fix:** validate `amount <= 100` when `cost_type` starts with `pct_of_` in `_validate_cost_fields`.

### H3. RedTrack outage indistinguishable from genuine zero revenue

A degraded revenue path returns `0`, the tile shows `$0`, and Net Profit shows a large red loss driven purely by Meta spend. Joel could pause a working campaign over a data outage. `unmapped_adsets` only covers ad sets with no rows at all, not an API failure.

**Fix:** falls out of B1 + B2 — surface a real `revenue_source` and a data-incomplete state.

### H4. Delete modal doesn't warn that all-accounts entries affect every account

Rows carry an "All accounts" badge, but the delete modal always shows the same generic copy. Deleting what looks like a stray entry while viewing one account silently removes it from every account's P&L.

**Fix:** conditional copy in the modal for null-account entries.

### H5. CSV export ignores the selected period

`exportCsv()` always dumps the fixed trailing-6-months `months` array regardless of the `mtd`/`month`/`custom` selection, while the filename bakes in the currently-selected month — implying it matches what's on screen. Joel filters to a custom range, exports for Steve, and hands over different numbers than he was looking at.

---

## MEDIUM / LOW

- **M1.** `revenue_source` is a hardcoded `"cached"` literal. Accidentally true today only because no live path exists. Derive it: `live` / `cache_exact` / `cache_fallback` / `none`.
- **M2.** Custom range with empty dates early-returns with no toast and no guidance. Tiles show "—" and the ledger says "No costs logged for this period" — misleading, nothing was queried. Prompt for the dates.
- **M3.** Dashboard strip says "Incomplete" for the same state the full page calls "Gross". Pick one word.
- **M4.** Cost ledger and MoM tables aren't gated on `loading`, so during an account switch the blanked KPI tiles sit above the previous account's rows.
- **L1.** Percent input has no `max` attribute (pairs with H2).
- **L2.** No as-of timestamp on Ad Spend. Ads Manager conditions buyers to expect delay language.
- **L3.** `create_cost` / `update_cost` return `resolved_amount = 0`, which the UI may briefly render as $0.

---

## Verified correct — don't change

- `pct_of_profit` non-circularity and the negative-profit floor at $0.
- `_cost_query` effective-window overlap logic.
- Month-stepping arithmetic in `get_months` (i=0..5).
- `authFetch` and `useToast` used throughout; delete is a proper custom modal with a red button — no `alert()` or `confirm()`.
- Permission gates present on all six endpoints (`pnl:read` / `pnl:write`).
- Nav item and Dashboard strip correctly gated on `hasPermission('pnl:read')`, which mirrors the backend's superuser bypass.
- No trigger files, `models.py`, migration, or `init_db.py` touched. Scope was respected.

---

## Note on scope

`Layout.jsx` also deleted an unrelated `showUserMenu` state line. Harmless (it was unused, ESLint clean) but out of scope — mention it or revert it.

`main.py` router registration is deliberately NOT done yet. Registering it would expose these endpoints. It happens after the blocking fixes land.
