# Profit / Loss (`/pnl`)

Per-account (gross) and all-accounts (net) profit from Meta spend, Switchboard/Everflow revenue (RedTrack for non-Switchboard accounts) and hand-entered cost entries. Code: `backend/app/api/v1/pnl.py`, `frontend/src/pages/Pnl.jsx`. Revenue sources and gotchas are in the team's memory notes; this file records the **rules decided by Steve** so they are not re-litigated.

## Revenue rules
- **Per-account revenue = Everflow conversions whose sub3 is one of that account's own ad set ids** (2026-09-09). The same offer can run on several accounts, so an offer-wide total is never credited to one account.
- **All-accounts total adds one extra bucket:** revenue whose sub3 is a **Meta campaign id of a scoped account** (broken tracking macro / not-yet-synced ad set) — it ties to our Meta campaigns.
- **Ignored (2026-10-24, Steve):** revenue whose sub3 is **missing, blank, a literal unexpanded macro like `{{adset.id}}`, or otherwise not a Meta id**. It is third-party traffic sent through BHM's network and is separate from the internal media buying. Returned as `network_revenue`, shown on the All-accounts view as "Not included in revenue or profit", and **excluded from revenue, profit and the base for percent-of-profit costs** (Abel's 5%). Previously this bucket was added to the total ("unknown revenue"), which also conflicted with Steve's 2026-10-20 note.
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

## Changelog
- 2026-10-25 closed months frozen (extras segment), per-scope rows, 3-day grace, resync surfaces incomplete extras.
- 2026-10-24 non-Meta-id revenue moved from "unknown" (added) to `network_revenue` (excluded, reported); UI line added.
