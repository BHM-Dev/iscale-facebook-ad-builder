# Codex Brief — Fix: scoped users get false 403s on their OWN accounts

**Repo:** `BHM-Dev/iscale-facebook-ad-builder`, branch `develop`. Local: `/Users/Steve1/Claude/AdBuilder`
**Priority:** HIGH — a live media buyer (Abel) currently can't use the app.
**Type:** Backend enforcement tweak (facebook.py, auto_pause.py, dashboard.py) + small frontend gating (CampaignContext.jsx, Dashboard.jsx). NOT the four trigger files (BulkAdCreation/AdCreativeStep/facebookApi/facebook_service) — but it DOES touch security-enforcement code, so run a self-review before pushing (see bottom).

## What's wrong
Hard per-account enforcement shipped in `a739606`. It works for blocking *other* accounts, but it's now **falsely blocking scoped users from their OWN assigned accounts.**

Abel (assigned: Trusted Home Service `act_287925406489877` + DIN Auto `act_949433761196746`) reports:
- Error toast top-right on login
- Dashboard: no data
- Campaign Performance: sees Auto campaign + ad set **names** but **no metrics**
- Clicking **Sync**: error

## Root cause
The guard `_assert_account_allowed(user, ad_account_id)` (in `backend/app/api/v1/facebook.py`) does:
```python
if ad_account_id is None:
    raise HTTPException(403, "Select one of your assigned ad accounts.")
```
For a SCOPED user, any request that arrives with **no** `ad_account_id` 403s with that exact message.

The frontend omits the param when the active account is empty/unresolved:
- `Dashboard.jsx` load(): `if (activeAccountId) insightsParams.set('ad_account_id', activeAccountId);` — omitted when empty.
- Same pattern on the Dashboard sync call and elsewhere.

So on login (before/without a resolved account) the metrics calls (`/auto-pause/insights-bulk`, `/auto-pause/ads-bulk`, `/dashboard/niche-summary`) and `/facebook/sync` all fire account-less → 403 → the top-right error + blank metrics + failed sync. `read_saved_adsets` still returns ad set **names** because for a scoped user with no account param it filters to `fb_account_id IN allowed` (no 403) — which is exactly why Abel sees names but no metrics.

(Note: the CampaignContext default-resolution at `frontend/src/context/CampaignContext.jsx` lines ~143-153 is actually correct — it falls back to the first *allowed* account. The problem is calls firing account-less during/around resolution, plus the backend being unforgiving about a missing account for a user who only HAS allowed accounts anyway.)

## The fix — two layers

### Layer 1 (primary, backend): default a missing account to the scoped user's first allowed account, on READ + sync endpoints
For a scoped user (`allowed_account_ids()` is not None), when an endpoint's `ad_account_id` is **None/empty**, resolve it to the user's **first allowed account** instead of 403'ing. Rationale: a scoped user has no legitimate "all accounts" view, so "no account specified" should mean "my (first) account," not an error. Keep the hard 403 only when a NON-EMPTY account OUTSIDE the allow-list is explicitly requested.

Add a helper in `facebook.py` next to `_assert_account_allowed`:
```python
def _resolve_scoped_default_account(current_user, ad_account_id):
    """For a scoped user, coerce a missing/empty ad_account_id to their first
    allowed account and return it; raise 403 only if a non-empty account outside
    the allow-list is explicitly requested. No-op (returns input) for unrestricted."""
    allowed = current_user.allowed_account_ids()
    if allowed is None:
        return ad_account_id
    if ad_account_id:
        if normalize_account_id(ad_account_id) not in allowed:
            raise HTTPException(status_code=403, detail="You don't have access to this ad account.")
        return ad_account_id
    # scoped + no account specified → default to their first allowed account
    return next(iter(allowed), None)
```
Apply it (replace the bare `_assert_account_allowed(...)` guard) and USE the returned value on these READ/sync endpoints so the downstream Meta call is scoped to the resolved account:
- `facebook.py`: `read_pixels`, `sync_from_meta` (use returned account for the sync), `read_saved_adsets` (when scoped + no param, it already filters to `in_(allowed)` — leave that; just don't 403).
- `auto_pause.py`: `get_insights_bulk`, `get_ads_bulk` — set `ad_account_id = _resolve_scoped_default_account(current_user, ad_account_id)` before the `svc.get_account_*` call.
- `dashboard.py`: `get_niche_summary` — same.

Leave the strict `_assert_adset_allowed / _assert_ad_allowed / _assert_campaign_allowed` (object-id-anchored, mutation) guards **fail-closed as-is** — those are correct. Only the account-level READ/sync guards get the forgiving default.

### Layer 2 (defense-in-depth, frontend): don't fire account-scoped calls with an empty account
In `Dashboard.jsx` `load()` (and the sync handler): after `if (activeAccountLoading) return;`, also skip when there is genuinely no account resolvable. Simplest: if `!activeAccountId && adAccounts.length > 0`, wait (return) — the effect re-fires when `activeAccountId` settles. Do NOT hard-block forever (unrestricted admins may legitimately have an empty active account meaning "default"). Keep it minimal; Layer 1 is the real fix.

## Verify / reproduce
1. Backend logs on the VPS will show the 403s. SSH: `ubuntu@adbuilder.velocitymx.io`, then `docker compose logs backend | grep -i "assigned ad account\|403"` (adjust container name via `docker compose ps`).
2. After the fix, a scoped user hitting the Dashboard/Campaign Performance with no/empty account must get **their first allowed account's data**, never the "Select one of your assigned ad accounts" toast.
3. Confirm an admin (unrestricted) is unchanged.
4. `npm run build` passes.

## Files
- `backend/app/api/v1/facebook.py` (add helper; swap guards on read_pixels/sync_from_meta)
- `backend/app/api/v1/auto_pause.py` (insights-bulk, ads-bulk)
- `backend/app/api/v1/dashboard.py` (niche-summary)
- `frontend/src/pages/Dashboard.jsx` (load gating)
No migration. No new env var.

## Review + push
This edits security-enforcement code. Before pushing to develop, run a self-review focused on: does the forgiving default ever let a scoped user reach a NON-allowed account? (It must not — the default is `next(iter(allowed))`, always in-list; an explicit out-of-list account still 403s.) If usage allows, hand back to Claude Code for the Haiku+Sonnet pre-push review; otherwise push to `develop` (auto-deploys) and Steve/Claude Code validate against Abel's login after.
