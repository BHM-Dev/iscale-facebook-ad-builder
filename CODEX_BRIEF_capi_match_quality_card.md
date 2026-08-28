# Codex Brief — CAPI Match Quality Dashboard Card

## Context
Steve's team is running two live tests: RHO 4 uses an advertiser-run CAPI integration, the
other RHO accounts use Everflow's CAPI. Theory: RHO 4's own CAPI should produce a higher
Event Match Quality (EMQ) score and thus lower costs. This brief is the frontend half of
answering that — the backend is already built and pushed to `develop`:

- New table `capi_quality_snapshots` (one row per pixel + account + **event** + day — Meta
  returns EMQ per event_name with no aggregate row) — see `models.CapiQualitySnapshot`
- New service `backend/app/services/capi_quality_service.py` — pulls Meta's Dataset Quality
  API once a day per pixel (`FacebookAdSet.pixel_id`), stores EMQ score, ACR, event coverage,
  match-key coverage breakdown per event
- New endpoints (all under `/api/v1/capi-quality`, existing auth, no new permission, already
  account-scoped server-side to match this app's usual per-user account restrictions):
  - `GET /latest` → `{"accounts": [{pixel_id, pixel_name, fb_account_id, account_name, snapshot_date,
    fetch_error?, events: [{event_name, event_match_quality, acr, event_coverage,
    data_freshness, match_key_feedback, fetch_error}, ...]}, ...]}` — **one entry per tracked
    ad account, each carrying a list of events** (an account can have EMQ data for more than
    one event_name, e.g. "Lead" and "CompleteRegistration"). There is no single "the" score per
    account — pick one to headline (see below) and show the rest in expanded detail. Looks back
    up to 3 days if today's job hasn't run yet. `fetch_error` at the account level (not inside
    an event) means the whole pixel failed to fetch that day — render as an account-level error,
    not a metrics table.
  - `GET /history?pixel_id=<id>&fb_account_id=<id>&event_name=<name>&days=30` →
    `{"pixel_id", "fb_account_id", "event_name", "history": [{snapshot_date, event_match_quality,
    acr, event_coverage, data_freshness, match_key_feedback, fetch_error}, ...]}` — trend for
    ONE specific event on ONE account (all three params required — there's no cross-event trend).
  - `POST /sync` → `{"synced": N, "failed": N, "tracked_pixels": N}` — manual "Sync now",
    same code path as the daily 14:00 UTC scheduled job

`event_match_quality` is Meta's 0–10 EMQ composite score. `match_key_feedback` is a dict of
per-identifier coverage %, e.g. `{"email": 82.1, "phone": 61.4, "external_id": 90.0, ...}` (exact
key names come straight from Meta — render generically, don't hardcode which identifiers exist).
`event_coverage` is a **trailing 7-day average**, not a same-day number — label it as such, don't
let day-over-day deltas in it read as real single-day movement. `acr`/`event_coverage`/
`data_freshness`'s exact field shape isn't 100% first-party-confirmed by Meta's docs (parsed
defensively on the backend) — treat them as best-effort secondary stats, EMQ is the number that
matters most here.

**Picking which event to headline on the card:** with no aggregate row, use the event in the
`events` list with the highest `event_match_quality` as the account's headline number (show its
`event_name` next to it, e.g. "7.2 · Lead", so it's clear which event that score is for) — and
list every other event underneath in the expanded detail. If `events` is empty but there's no
account-level `fetch_error`, treat it the same as the empty-state case below.

## Scope — this brief is frontend only
No backend changes. No trigger files touched (`AdCreativeStep.jsx`, `BulkAdCreation.jsx`,
`facebookApi.js`, `facebook_service.py` are untouched by this work).

## What to build

A compact card on `frontend/src/pages/Dashboard.jsx` — NOT a new page, NOT a new nav entry.
Steve was explicit about this: Meta's own Events Manager already shows this per-pixel, so a
whole new destination in our app just adds a click. The value we add is the side-by-side
comparison across RHO accounts, so keep it a glanceable card with expand-on-demand detail.

**Card layout (collapsed / default state):**
- Title: "CAPI Match Quality" with a small info icon/tooltip explaining what EMQ is in one
  sentence (something like: "Meta's 0–10 score for how well your server-sent conversion data
  matches to real Meta accounts. Higher usually means lower costs.")
- One row per tracked ad account (from `GET /latest`'s `accounts` list), sorted by `account_name`:
  - Account name, with the pixel name/id shown as a small secondary label (e.g. "RHO 4 · pixel
    1529618242272114"). This matters here specifically: confirmed live 2026-08-28 that a few ad
    sets inside "RHO - Commercial Insurance" already point at the *same* pixel as RHO 4 — when
    two accounts share a pixel, Meta reports the identical EMQ for both, which looks like a bug
    if you can't see why. Showing the pixel id makes that self-evident instead of confusing.
  - Headline EMQ score (the highest-`event_match_quality` entry in that account's `events`
    list — see "Picking which event to headline" above), big and color-coded (e.g. red <5,
    yellow 5–7, green >7 — use whatever thresholds read well against real data, these are a
    starting point not a hard requirement), with its `event_name` shown as a small label next
    to the score
  - That same event's ACR (%) as a secondary stat, if present
  - "as of {snapshot_date}" — if `snapshot_date` is more than 1 day old, show a small stale-data
    indicator (a pending/greyed dot, not an error) since it looks back 3 days
  - If the account has an account-level `fetch_error` (whole pixel failed that day — `events`
    will be empty in this case): show a compact error row for that account
    ("Couldn't fetch — {short error}") instead of trying to render an empty events list as zero
- A manual "Sync now" button (small, top-right of the card) that calls `POST /sync`, shows a
  spinner while in flight, then reloads `GET /latest`. Use the existing `useToast()` pattern
  (`showSuccess`/`showError`) for the result — never `alert()`.
- Empty state: if `accounts` is empty (no pixels tracked yet, or DB just migrated), show a
  neutral message + the Sync now button, not a broken-looking empty table.

**Expanded detail (click a row, or a chevron per row):**
- List every event in that account's `events` array (not just the headlined one) — each with its
  own EMQ, ACR, and:
  - Match-key coverage breakdown as a small bar list or simple table: identifier name → %
    coverage (from that event's `match_key_feedback`, render whatever keys are present — don't
    assume a fixed set)
  - Data freshness (`data_freshness` field — just show it as a small badge/label, whatever
    string comes back)
  - Per-event `fetch_error`, if set, shown inline for that one event row (distinct from the
    account-level `fetch_error` above)
- If you have time/budget: a simple sparkline or small line chart of EMQ over the last 30 days
  for the headlined event, using
  `GET /history?pixel_id=...&fb_account_id=...&event_name=...&days=30` (all three params
  required) — nice to have, not required for v1. If you skip it, leave a clear
  `{/* TODO: trend sparkline via GET /history */}` comment so it's easy to pick up later, don't
  silently drop it.

## Patterns to follow (this repo's conventions — see CLAUDE.md)
- `import { authFetch } from '../lib/facebookApi'` for all calls — never raw `fetch()`
- `useToast()` → `showSuccess/showError/showWarning/showInfo` — never `alert()`
- No `confirm()` — this feature has no destructive actions so this shouldn't come up, but if you
  add anything destructive later, use the existing custom-modal pattern instead
- Match the existing Dashboard card visual style (spacing, border, header treatment) — look at
  how the existing "Performance by Niche" or Needs Attention sections are built and mirror that,
  don't introduce a new card chrome style
- Numbers: EMQ to 1 decimal (e.g. "7.2"), ACR as a percentage with 1 decimal (e.g. "12.4%")

## Do NOT do
- Do not create a new route/page or a new sidebar nav entry
- Do not touch any backend file — this is 100% frontend
- Do not touch `AdCreativeStep.jsx`, `BulkAdCreation.jsx`, `facebookApi.js`, or
  `facebook_service.py`
- Do not add a new permission gate — the endpoints are already open to any authenticated user
  (server-side, already scoped to each user's assigned ad accounts)

## Heads up — data may be sparse or missing on first real load
This hasn't been live-verified against real Meta accounts yet. Two real possibilities when you
build against it:
1. **An account's `fetch_error` is set and `events` is empty.** This can mean Meta genuinely
   rejected the request (e.g. the pixel's owning Business Manager hasn't granted our token
   dataset-level access) — not a bug in your UI. Render it as the error state described above,
   don't treat it as "no data yet."
2. **RHO 4 and another RHO account show identical scores.** EMQ is a property of the Meta pixel,
   not the ad account — if two accounts happen to share one pixel, Meta reports the same number
   for both. If you notice this while testing against real data, flag it, don't silently pick a
   different metric to differentiate them — it means the comparison this card exists for may not
   be answerable the way it's currently modeled, and that's a product conversation, not a UI fix.

## Push protocol
Per CLAUDE.md: this is a pure frontend change touching only `Dashboard.jsx` (and a new small
component file if you split the card out, e.g. `frontend/src/components/CapiMatchQualityCard.jsx`
— your call whether it's worth splitting out or inline). No trigger file, no migration, no new
dependency. Commit locally; hand off to Claude Code for the final push per the standard protocol
(Codex doesn't push feature code).
