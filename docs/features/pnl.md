# Profit / Loss (`/pnl`)

Per-account (gross) and all-accounts (net) profit from Meta spend, Switchboard/Everflow revenue (RedTrack for non-Switchboard accounts) and hand-entered cost entries. Code: `backend/app/api/v1/pnl.py`, `frontend/src/pages/Pnl.jsx`. Revenue sources and gotchas are in the team's memory notes; this file records the **rules decided by Steve** so they are not re-litigated.

## Revenue rules
- **Per-account revenue = Everflow conversions whose sub3 is one of that account's own ad set ids** (2026-09-09). The same offer can run on several accounts, so an offer-wide total is never credited to one account.
- **All-accounts total adds one extra bucket:** revenue whose sub3 is a **Meta campaign id of a scoped account** (broken tracking macro / not-yet-synced ad set) — it ties to our Meta campaigns.
- **Counted (2026-10-26, Steve; verified against RedTrack):** revenue whose sub3 is the literal unexpanded macro `{{adset.id}}`. All 147 October rows carried RedTrack click ids of our own "Commercial Insurance - RHO v1 / RHO 4 | ABO…" campaigns — our Meta clicks, macro not expanded. All-accounts total only (can't be placed on an ad set). Closed months already frozen (Jul–Sep) are not restated; the explicit Re-fetch on a closed month recomputes it under the current rules, so it WOULD pick this up. Only the exact literal `{{adset.id}}` is matched (October raw rows showed no encoded/variant forms); `{{campaign.id}}` alone or a variant would still land in `network_revenue`. Scope guard is the offer filter only (the macro rows can't be tied to an account).
- **Ignored (2026-10-24, Steve):** revenue whose sub3 is **missing, blank, or otherwise not a Meta id** (e.g. `ThankYouPage`, `Email`). It is third-party traffic sent through BHM's network and is separate from the internal media buying. Returned as `network_revenue`, shown on the All-accounts view as "Not included in revenue or profit", and **excluded from revenue, profit and the base for percent-of-profit costs** (Abel's 5%). Previously this bucket was added to the total ("unknown revenue"), which also conflicted with Steve's 2026-10-20 note.
- Revenue tied to a Meta id outside the scoped accounts is reported as `foreign_revenue`, never added.

## Closed months are frozen (2026-10-25, Steve: "already paid months can be frozen, no need to keep repulling them")
- **Per-account figures** of a closed month were already frozen (`pnl_month_snapshots`). The **all-accounts extras** (campaign-id-tied revenue + reported network/foreign buckets) were re-pulled from Everflow on every load; they are now frozen too, as one extra snapshot row per closed month **per account scope** (pseudo account id `__all_scope_extras__:<scope hash>`, no schema change).
- **When it freezes:** the pull succeeded, the month ended **3+ days ago** (late conversions/clawbacks), it is exactly one whole calendar month, and **every account's own snapshot for that month already exists** (so an unsynced ad-set table can't lock in a misclassification). The current month and custom ranges stay live. A frozen row is only trusted for the same scope and revenue rule.
- **Escape hatch:** `POST /pnl/months/{month}/resync` (needs `pnl:write`) re-fetches and overwrites both the per-account rows and the extras; if the extras pull fails it returns 502 instead of half-succeeding.
- **Still live for a closed month:** Abel's commission is computed at read time, so editing/adding cost entries (amounts, dates, `profit_threshold`) still changes it; only revenue/spend are frozen. A month also stays live if any account lacks a snapshot.

## Verified vs not
- **Unit-tested:** the classification (ad set → per-account, scoped campaign → counted, non-Meta sub3 → network, out-of-scope campaign → foreign) and that `network_revenue` is not added to revenue/gross profit (`backend/tests/test_pnl_network_revenue.py`).
- **Not verified live / reviewed only:** how much each past month moves (see Changelog).

## Open items (2026-10-24 review)
- ~~Closed months restate~~ — resolved 2026-10-25 by freezing (above). Note the values frozen are the ones under the current rule (network revenue excluded), i.e. what the screen already showed after 2026-10-24.
- An ad set id that Meta knows but the local table does not (stale sync — the scheduled sync only covers RHO Commercial + RHO 4) falls into `foreign` and is excluded; nothing flags it.
- Closed months can freeze low when ad sets are missing locally; legacy one-off costs aren't migrated to single dates (1 row); restricted users see all-account costs; failures can render as `$0`. See `Ad-Builder-Full-Review-2026-10-24.md` (kept local).

## Reconciliation check (2026-10-26, Joel: "P&L is not fully accurate again")
Checked live against Meta and Everflow for today, yesterday and MTD (*verified in production*, read-only):
- **Spend ties to Meta.** Sum of ad-set rows = Meta account-level spend to the cent for all five scoped accounts today (\$1,364.31 both); MTD differs by \$1.95 (calls seconds apart).
- **Revenue ties to Everflow row by row.** Every conversion in the period lands in exactly one bucket (ad set / campaign / network / unknown id).
- **Gap 1 — ad sets missing from the local table.** The 30-min `meta_sync` only covered RHO Commercial + RHO 4, so two DIN Auto Insurance ad sets created Oct 22 were unknown: their \$89.58 of revenue was dropped while the account's spend was counted. Fixed: the scheduled sync now defaults to every account with an Everflow mapping (`META_SYNC_ACCOUNT_IDS` still overrides).
- **Gap 2 — literal-macro revenue is our Meta traffic (fixed 2026-10-26, Steve's call; RedTrack click-id lookup matched 147 of 149 to our own campaigns, 0 to anyone else's).** MTD \$2,769.89 of the \$3,125.68 `network_revenue` has sub3 `{{adset.id}}`. All 147 rows carry a RedTrack click id; 133 have a Meta fbclid; referrers are facebook.com / instagram.com. 72 rows (\$1,221.15) have sub4 = the exact name of one of our own ads on RHO Commercial. That contradicts the "third-party traffic" premise of the 2026-10-24 rule for at least that slice.

## Changelog
- 2026-10-26 unexpanded `{{adset.id}}` revenue now counted in the All-accounts total.
- 2026-10-26 scheduled Meta sync defaults to all Everflow-mapped accounts.
- 2026-10-25 closed months frozen (extras segment), per-scope rows, 3-day grace, resync surfaces incomplete extras.
- 2026-10-24 non-Meta-id revenue moved from "unknown" (added) to `network_revenue` (excluded, reported); UI line added.
