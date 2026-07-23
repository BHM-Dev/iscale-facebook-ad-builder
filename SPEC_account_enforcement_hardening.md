# Spec — Hard Account Enforcement (follow-up to declutter scoping)

**Owner:** Claude Code (touches `facebook_service.py` trigger file + auto_pause + push-to-meta + frontend → mandatory 2-agent review).
**Status:** ✅ SHIPPED `a739606` (2026-07-23). Every BLOCKING/HIGH/MEDIUM item below is guarded. Reviewed by Haiku (logic) + Sonnet (adversarial bypass) — no confirmed bypass. Admin (superuser) flows verified unaffected live. Resolution uses `fb_account_id` (local) + Meta fallback; unrestricted users short-circuit.

**Residual / follow-ups:**
- **Scoped-user 403 not yet verified live** — needs an Abel (or scoped test account) login to confirm a 403 end-to-end in the browser. Logic verified by review + admin-unaffected confirmed; the live scoped test is the last gap.
- **Brand endpoints** (`assign_campaign_brand`/`assign_brand_to_adset`) check the loaded row's `fb_account_id` directly with **no Meta fallback** — a not-yet-tagged (NULL) row 403s a scoped user until the scheduler tags it (≤30 min). Acceptable/fail-closed.
- **Bonus fixes found during build:** `/dashboard/stats` + `/dashboard/niche-summary` were fully **unauthenticated** — added auth + account scoping. `list_rules` was an unguarded enumeration leak — now scoped.

---
_Original spec below (all items now implemented)._

## The core problem
`_assert_account_allowed(user, ad_account_id)` only guards endpoints that take an `ad_account_id`. Most write/read endpoints are keyed by `adset_id` / `ad_id` / `campaign_id` with **no server-side link back to an account**. So there's no account-ownership model to check against. Everything below flows from that.

## Prerequisite: account-ownership resolution
Add a way to resolve an adset/ad/campaign id → its `ad_account_id`, then reuse `_assert_account_allowed`. Options:
- **Preferred:** persist `fb_account_id` on `FacebookCampaign` / `FacebookAdSet` during `/sync` (and on `GeneratedAd` at push), so resolution is a local lookup.
- Fallback: query Meta for the object's account (adds latency; use only when not in local DB).
Add a helper `assert_adset_allowed(user, fb_adset_id, db)` / `assert_campaign_allowed(...)` that resolves then calls `_assert_account_allowed`.

## BLOCKING (money-touching — fix before relying on this as a boundary)
1. `PATCH /facebook/adsets/{fb_adset_id}/status` (`update_adset_status`) — resolve→check. Also currently only `get_current_active_user`; keep or add `campaigns:write`.
2. `PATCH /facebook/ads/{fb_ad_id}/status` (`update_ad_status`) — resolve ad→adset→account→check.
3. `PATCH /facebook/adsets/{fb_adset_id}/budget` (`update_adset_budget`) — resolve→check.
4. `PATCH /facebook/campaigns/{fb_campaign_id}/budget` (`update_campaign_budget`) — resolve→check.
5. `POST /facebook/push-to-meta` — add an `ad_account_id` field to the request (frontend AdRemix must send it; the push modal already knows the account), then `_assert_account_allowed`. Highest consequence (creates live ad).
6. `auto_pause.py` — entire router unscoped:
   - `POST /auto-pause/check` (`_run_check`) pauses ad sets **system-wide** for any caller. It's also called by the scheduler (no user). Fix: when called by a user, scope to their allowed accounts; the scheduler path stays global. Simplest interim: restrict the HTTP `/check` to superusers (scheduler unaffected).
   - `GET /auto-pause/insights/{fb_adset_id}`, `/insights-bulk`, `/ads-bulk` — resolve→check (data leak of spend/CPL/revenue).
   - `POST/PATCH/DELETE /auto-pause/rules` — a scoped user can plant/modify rules on other accounts' adsets. Resolve→check on the adset the rule targets.

## HIGH (data leaks — fast-follow acceptable, but close soon)
7. `GET /facebook/ads?adset_id=` (`read_ads`) — resolve→check.
8. `GET /facebook/adsets/saved` (`read_saved_adsets`) — no account param; queries whole local table. Filter to the user's allowed accounts (needs the `fb_account_id` column from the prerequisite). This is Campaign Performance's main data source, so it's the broadest leak.
9. `GET /facebook/ads/{fb_ad_id}/creative` (`get_ad_creative`) — resolve→check (feeds Remix/Iterate pre-fill).
10. `POST /facebook/sync` (`sync_from_meta`) — guard `ad_account_id`; it's the root cause that persists other accounts' data into the shared DB (feeds #8).

## MEDIUM
11. `GET /facebook/pixels` — guard `ad_account_id`.
12. `PATCH /facebook/campaigns/{id}/brand`, `/adsets/{id}/brand` — resolve→check (corrupts shared bookkeeping otherwise).
13. `dashboard.py` — not audited yet; aggregates adset/niche performance. Audit for `ad_account_id`-optional reads and scope.

## Out of scope
`generated_ads.py` CRUD has no account concept (local bookkeeping, no `ad_account_id` column). Scoping it would need an account column + backfill — defer.

## Done =
A scoped user (non-superuser with assignments) gets 403 on every endpoint above for a non-allowed account/adset/ad/campaign, verified by a bypass re-test (attempt each with another account's id). Unrestricted users + scheduler unaffected.
