# Codex Brief: Research Live Debug — Why Are 0 Ads Returning?

## Problem
Hitting "Pull Ads" in Research spins for a while then returns nothing. Token is confirmed set on VPS. Need to find out exactly what the Meta Ads Library API is returning.

## Step 1: Add raw response logging to scraper.py

In `backend/app/services/scraper.py`, in `_api_search`, after `response.raise_for_status()`, add:

```python
data = response.json()
print(f"[scraper] API raw response: status={response.status_code} data_count={len(data.get('data', []))} paging={data.get('paging')} error={data.get('error')}")
```

This must print before any filtering happens. We need to see:
- How many ads Meta is returning raw
- Whether Meta is returning an error object
- Whether paging is present

Also add after the negative keyword filter loop:
```python
print(f"[scraper] after negative filter: {len(ads)} ads kept from {len(raw_ads_before_filter)} raw")
```
(You'll need to capture the pre-filter count — add `raw_count = len(data.get('data', []))` before the filter loop.)

## Step 2: Check the actual API call being made

In the same function, the log line `[scraper] API URL sample` is already there for batch 0. After deploying Step 1, trigger a Research pull and check VPS logs:

```bash
docker logs ad-builder-api --tail=100 2>&1 | grep -E "\[scraper\]|Calling API|API raw"
```

Paste the output into ## Findings below.

## Step 3: Check for silent exception swallowing

In `_api_search`, is there a broad `except` that silently returns `[]`? Check `backend/app/services/scraper.py` around lines 80-100. If there's a `except Exception: return []` or similar, add logging before the return:

```python
except Exception as e:
    print(f"[scraper] API search failed: {type(e).__name__}: {e}")
    return []
```

## Step 4: Check the browse-ads endpoint

In `backend/app/api/v1/research.py`, find the `browse-ads` or `search-and-save-vertical` endpoint. 

Check:
- Does it call `search_and_save` or `_api_search` directly?
- Is there a try/except around the scraper call that swallows errors?
- What does it return when 0 ads come back — does it return `{"ads": []}` or does it raise a 500?

Add a log at the top of the endpoint handler:
```python
print(f"[research] browse-ads called: vertical_id={vertical_id} query={...} limit={...}")
```
And after the scraper returns:
```python
print(f"[research] scraper returned {len(ads)} ads")
```

## Step 5: Check what the frontend is actually receiving

In `frontend/src/pages/Research.jsx`, find the fetch call for pulling ads. Check:
- What endpoint is it calling?
- What does it do when the response has 0 ads — does it show a message or just silently render nothing?
- Is there an error catch that's eating a non-200 response?

## What to fix
Once root cause is clear from logs:
- If Meta API is returning 0 results: the query terms may be too specific or the account token may not have Ads Library access. Try calling the API manually with `curl` using the token from `printenv` to confirm.
- If Meta API is returning results but filter is dropping them all: lower thresholds or log which ads are being dropped and why.
- If there's a silent exception: fix the exception handler to surface the real error.
- If the frontend isn't rendering results that ARE coming back: fix the render logic.

## Curl test (run on VPS to confirm API works at all)
```bash
TOKEN=$(docker exec ad-builder-api printenv FACEBOOK_ACCESS_TOKEN)
curl -s "https://graph.facebook.com/v21.0/ads_archive?access_token=$TOKEN&ad_reached_countries=US&search_terms=commercial+insurance&ad_active_status=ALL&limit=5&fields=id,page_name,ad_creative_bodies" | python3 -m json.tool | head -60
```
Paste the output into ## Findings. This tells us immediately if the token works with the Ads Library endpoint.

## Findings
- Local code instrumentation added; live VPS Docker commands could not be run from this machine because no VPS SSH host/alias is available in `~/.ssh/config` or project docs.
- Token is reported confirmed on VPS by Steve, but this session could not independently verify `docker exec ad-builder-api printenv | grep -i facebook`.
- `_api_search` now logs raw Meta response details immediately after `response.raise_for_status()` and before filtering:
  - HTTP status
  - raw `data_count`
  - `paging`
  - `error`
- `_api_search` now logs per-batch post-filter results:
  - `[scraper] after negative filter: X ads kept from Y raw`
- API exception logging now includes exception class:
  - `[scraper] API search failed: <Type>: <message>, falling back to scraper`
- `search-and-save-vertical` now logs the refresh call inputs:
  - `vertical_id`
  - `sub_vertical`
  - `limit_per_keyword`
- After each keyword search, `search-and-save-vertical` now logs:
  - vertical label
  - keyword
  - number of ads returned by `ResearchService.search_and_save()`
- Frontend check:
  - `Research.jsx` calls `POST /research/search-and-save-vertical?vertical_id=...&limit_per_keyword=20`
  - On non-200 response it surfaces `err.detail || 'Refresh failed'`
  - On `total_new === 0`, it shows `Already up to date — N keywords checked, no new ads`, then reloads browse/saved ads
  - It is not silently swallowing non-200 refresh errors

### Commands To Run After Deploy
```bash
docker logs ad-builder-api --tail=100 2>&1 | grep -E "\[scraper\]|\[research\]|Calling API|API raw"
```

```bash
TOKEN=$(docker exec ad-builder-api printenv FACEBOOK_ACCESS_TOKEN)
curl -s "https://graph.facebook.com/v21.0/ads_archive?access_token=$TOKEN&ad_reached_countries=US&search_terms=commercial+insurance&ad_active_status=ALL&limit=5&fields=id,page_name,ad_creative_bodies" | python3 -m json.tool | head -60
```

### Expected Interpretation
- If `API raw response` shows `data_count=0`, Meta is returning no raw ads for the query before our filters.
- If `data_count>0` but `after negative filter: 0 ads kept`, the negative/page/relevance filters are the cause.
- If the API log is absent and fallback logs appear, `_api_search` is failing before/inside the API call.
- If curl returns an OAuth/permission error, the token exists but does not have usable Ads Library API access.
