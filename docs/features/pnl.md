# Profit / Loss (`/pnl`)

Per-account (gross) and all-accounts (net) profit from Meta spend, Switchboard/Everflow revenue (RedTrack for non-Switchboard accounts) and hand-entered cost entries. Code: `backend/app/api/v1/pnl.py`, `frontend/src/pages/Pnl.jsx`. Revenue sources and gotchas are in the team's memory notes; this file records the **rules decided by Steve** so they are not re-litigated.

## Revenue rules
- **Per-account revenue = Everflow conversions whose sub3 is one of that account's own ad set ids** (2026-09-09). The same offer can run on several accounts, so an offer-wide total is never credited to one account.
- **All-accounts total adds one extra bucket:** revenue whose sub3 is a **Meta campaign id of a scoped account** (broken tracking macro / not-yet-synced ad set) — it ties to our Meta campaigns.
- **Ignored (2026-10-24, Steve):** revenue whose sub3 is **missing, blank, a literal unexpanded macro like `{{adset.id}}`, or otherwise not a Meta id**. It is third-party traffic sent through BHM's network and is separate from the internal media buying. Returned as `network_revenue`, shown on the All-accounts view as "Not included in revenue or profit", and **excluded from revenue, profit and the base for percent-of-profit costs** (Abel's 5%). Previously this bucket was added to the total ("unknown revenue"), which also conflicted with Steve's 2026-10-20 note.
- Revenue tied to a Meta id outside the scoped accounts is reported as `foreign_revenue`, never added.

## Verified vs not
- **Unit-tested:** the classification (ad set → per-account, scoped campaign → counted, non-Meta sub3 → network, out-of-scope campaign → foreign) and that `network_revenue` is not added to revenue/gross profit (`backend/tests/test_pnl_network_revenue.py`).
- **Not verified live / reviewed only:** how much each past month moves (see Changelog).

## Open items (2026-10-24 review)
- **Closed months restate.** All-scope revenue is computed live (never snapshotted), so removing the network bucket lowers past months and any percent-of-profit commission computed from them — including months already paid. Decide whether to freeze paid months.
- An ad set id that Meta knows but the local table does not (stale sync — the scheduled sync only covers RHO Commercial + RHO 4) falls into `foreign` and is excluded; nothing flags it.
- Closed months can freeze low when ad sets are missing locally; legacy one-off costs aren't migrated to single dates (1 row); restricted users see all-account costs; failures can render as `$0`. See `Ad-Builder-Full-Review-2026-10-24.md` (kept local).

## Changelog
- 2026-10-24 non-Meta-id revenue moved from "unknown" (added) to `network_revenue` (excluded, reported); UI line added.
