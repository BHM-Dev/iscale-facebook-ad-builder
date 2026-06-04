# Codex Brief: Research Scraper Live Diagnosis

## Goal
Diagnose why the Research page returns 0 or near-0 ads for commercial insurance queries. Fix the root cause. No need to involve Steve — run tests yourself and commit the fix.

## What to check (in order)

### 1. Check VPS logs for token status
SSH to VPS and run:
```
docker logs <backend_container> 2>&1 | grep -E "\[scraper\]" | tail -30
```
Look for `token=MISSING`. If missing, the Meta Ads Library API is unavailable and all queries fall through to Chromium fallback.

### 2. Check if Meta API token env var exists on VPS
```
docker exec <backend_container> printenv | grep -i facebook
```
If `FACEBOOK_ADS_LIBRARY_TOKEN` or `META_ADS_TOKEN` (check `backend/app/core/config.py` for the exact var name) is not set, that's the root cause. Note it and include in brief back to Steve — he needs to DM Golden with the var name.

### 3. Check what keywords are being searched
In `backend/app/core/vertical_config.py`, find the `commercial_insurance` entry. List all `search_keywords`. Are there too many? Each keyword = one scraper run = one API call or one Chromium session.

### 4. Check the Chromium fallback output
In `backend/app/services/scraper.py`, find `_fallback_search`. Look at:
- Does it extract ads correctly from the current Meta Ads Library HTML structure?
- What CSS selectors or parsing logic is used? The Ads Library UI changes frequently — selectors may be stale.
- Check if Playwright/Chromium is actually installed on the VPS: `docker exec <container> python -c "from playwright.sync_api import sync_playwright; print('ok')"`

### 5. Check the relevance gate threshold
In `backend/app/services/research_service.py`, `_filter_ads_by_vertical_relevance`:
- `min_score = 3`
- If Chromium returns ads but they score < 3, they get silently dropped.
- Add a temporary log: for each rejected ad, print the full text and score so we can see what's being dropped.

### 6. Check `limit_per_keyword` 
In `backend/app/api/v1/research.py`, the `browse-ads` endpoint — what is `limit_per_keyword` set to? Should be 20 (was reduced from 50 to reduce timeout risk).

## What to fix
Based on findings:
- If token missing: document the env var name in this file, do NOT add the token value — Steve will DM Golden
- If Chromium selectors stale: update selectors to match current Ads Library HTML
- If relevance gate is too aggressive: lower `min_score` to 2 or add a bypass when < 3 ads would be returned (return what we have rather than nothing)
- If too many keywords causing timeouts: reduce `search_keywords` list in vertical_config.py to the 5-6 most productive ones

## Files
- `backend/app/core/vertical_config.py` — keyword lists
- `backend/app/services/scraper.py` — `_api_search`, `_fallback_search`
- `backend/app/services/research_service.py` — relevance gate
- `backend/app/api/v1/research.py` — `browse-ads` endpoint, timeout, limit_per_keyword
- `backend/app/core/config.py` — env var names for Meta token

## Output expected
1. Commit any code fixes to develop branch
2. Add a `## Findings` section to the bottom of this file with: root cause, what was fixed, any env vars Steve needs to add via Golden

## Findings

### Root Cause
- Could not complete the live VPS Docker log/env checks from this machine: the repo documents Golden's Docker workflow and container name (`ad-builder-api`), but no VPS SSH host/alias is available in `~/.ssh/config` or project docs.
- Code inspection found a concrete app-side failure mode: the Commercial Insurance relevance gate used a hard `min_score = 3`. If the Meta API returns 0 and Chromium fallback extracts sparse ad text, otherwise acceptable ads can score below 3 and get dropped before saving, leaving the Research page with 0-2 cards.
- The fallback scraper already includes `brand_name` in request negative keyword filtering, and now also includes persistent `KeywordBlacklist` terms from the prior scraper fix.
- The frontend refresh does pass `limit_per_keyword=20`. The backend endpoint default was still `200`, so direct/API refreshes could accidentally run very large sequential scrapes.
- Commercial Insurance had 10 searches. Because each keyword is one API call or one Chromium session, this can be slow/fragile when the API token is missing or returning zero.

### What Was Fixed
- Lowered the Commercial Insurance relevance threshold from `3` to `2`.
- Added full rejected-ad text previews to relevance logs so the next VPS log read shows exactly what text was scored and why it was dropped.
- Added a low-volume safety floor: if the gate would return fewer than 3 ads, it recovers the best borderline candidates instead of returning an empty/near-empty Research view.
- Strong negative matches still stay out: recovered candidates must either score at least `1`, or, when the scraper only found 1-3 ads total, have score `0` with no negative penalty terms.
- Changed the backend `search-and-save-vertical` default `limit_per_keyword` from `200` to `20`, matching the frontend refresh behavior.
- Reduced Commercial Insurance searches from 10 to 6 high-intent terms: `small business insurance`, `contractor insurance`, `business insurance quote`, `trucking insurance`, `restaurant insurance`, `general liability insurance for small business`.

### Env Vars For Golden To Check
- Preferred env var for the Ads Library API token: `FACEBOOK_ADS_LIBRARY_TOKEN`.
- Existing fallback env vars accepted by `backend/app/services/scraper.py`: `VITE_FACEBOOK_ACCESS_TOKEN` and `FACEBOOK_ACCESS_TOKEN`.
- `backend/app/core/config.py` currently formalizes `FACEBOOK_ACCESS_TOKEN`; it does not define `FACEBOOK_ADS_LIBRARY_TOKEN`, but the scraper reads it directly from `os.getenv()`.
- Ask Golden to run: `docker exec ad-builder-api printenv | grep -i facebook`.
- If no token appears, add `FACEBOOK_ADS_LIBRARY_TOKEN` on the VPS and restart with `docker compose restart backend`.
