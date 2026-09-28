# Research Release Review — Commercial & Auto Insurance

## Scope

This local batch evolves Research from a broad captured-ad gallery into a
source-backed operating flow for commercial insurance and auto insurance:

`targeted Meta capture → advertiser evidence → watchlist → original BHM test → guarded Meta handoff`

It intentionally does **not** claim competitor spend, conversion, delivery,
or ROAS. Retained catalog observations and BHM performance remain separate.

## Reviewer paths

### 1. Targeted advertiser capture

1. Open Research → Commercial Insurance or Auto Insurance → Advertisers.
2. Capture an advertiser with depth 10, 30, or 50.
3. Confirm the resulting Ad Library is scoped to the retained Meta page name
   when it differs from the typed shorthand.
4. Confirm the receipt shows source, requested/filtered/retained counts, new
   versus deduplicated records, page names, evidence coverage, and limits.
5. Open a retained creative and confirm the source badge, query tooltip, last
   capture timestamp, Meta source link, and (when present) live destination.

### 2. Advertiser watchlist

1. Add a commercial or auto advertiser from Advertisers.
2. In Watchlist, use **Refresh advertiser** and confirm it stays in Watchlist
   while a bounded 30-ad capture updates retained evidence.
3. Confirm freshness/change labels refer to catalog captures only—not delivery
   or performance.
4. Confirm the broad vertical refresh remains manual and clearly labeled.

### 3. Evidence → test → Meta handoff

1. From a creative or Watchlist brief, add a test decision.
2. Confirm the selected source is from the active vertical. A source retained
   under the other insurance vertical must be rejected server-side.
3. Use **Build test**, then complete the existing original-copy flow.
4. On a successful Meta create, confirm the BHM GeneratedAd is linked to the
   test item and is shown as such in Test Backlog.
5. Retry the same Meta request ID: it must replay safely.
6. Attempt another new launch with the same linked test: it must fail before
   the Meta write, preserving one durable test-to-ad attribution link.
7. Attempt simultaneous new request IDs for one unlinked test: exactly one
   may claim the test before Meta; the other must fail closed. A request that
   fails while still preparing may safely release its claim on retry.

## Required safety assertions

- Only `commercial_insurance` and `auto_insurance` can create Watchlist or
  Test Backlog records.
- Live captures persist `capture_source`, `capture_query`, and
  `capture_country` on retained records.
- `Open live destination` is an external visit, not an asserted landing-page
  capture or verification.
- A Direct Meta launch validates the buyer owns the supplied test decision.
- Completed idempotent launch requests replay before checking whether a local
  test record still exists.
- A durable `launch_claim_id` prevents cross-browser double launches for the
  same test decision and remains in place for reconciliation if Meta was
  already reached but local bookkeeping later failed.

## Local validation completed

- `npm --prefix frontend run build`
- `python3 -m py_compile` for changed backend routes/services
- `python3 scripts/check_alembic_heads.py`
- Focused Research unit suite: 20 passing tests

## Environment limitation

The local machine has no PostgreSQL service or Docker runtime. The TestClient
acceptance suites—including the new Watchlist/Test Backlog route coverage and
the Meta handoff route coverage—must run in CI or a PostgreSQL-backed review
environment. No production capture or Meta write has been attempted from this
local batch.
