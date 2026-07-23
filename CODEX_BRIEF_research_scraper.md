# Codex Brief: Fix Research Scraper — Commercial Insurance

## Problem
Research section returns 0–2 ads after refresh. Root cause: Meta Ads Library API
returns 0 results for every keyword, so all 10 fall back to Chromium. Chromium
returns almost nothing and has a bug: brand_name is excluded from negative keyword
filtering (Saltwater Coaching LLC showed up despite "coaching" being a negative).

## Files to touch
- `backend/app/services/scraper.py`

## Fix 1 — Diagnose API vs fallback path (add one log line)

In `search_ads()`, before the try/except, add:
```python
print(f"[scraper] token={'SET' if self.access_token else 'MISSING'}, using={'API' if self.access_token else 'fallback'}")
```
This tells us immediately in VPS logs whether the token is even present.

## Fix 2 — Brand name in fallback negative keyword filter

In `_fallback_search`, find where `text_to_check` is built for negative keyword
filtering. It currently only checks ad copy fields. Add brand_name to it.

Find this pattern (around line 509):
```python
# Check all text fields for negative keywords
```
The `text_to_check` must include the `brand_name` / page name field, same as
`_api_search` does:
```python
text_to_check = (
    f"{ad_data.get('brand_name', '')} "
    f"{ad_data.get('headline', '')} "
    f"{ad_data.get('ad_copy', '')} "
    f"{ad_data.get('cta_text', '')}"
).lower()
```
Exact field names may differ — check what the fallback's ad_data dict contains and
include the page/advertiser name field alongside the body copy.

## Fix 3 — API base URL check

In `_api_search`, `self.base_url` is used to hit the Ads Library API. Confirm:
- URL should be `https://graph.facebook.com/v21.0/ads_archive` (or current version)
- The `ad_reached_countries` param spells out correctly
- Print the full URL on the first call so we can see it in VPS logs

## Fix 4 — Fallback: raise the per-page ad limit

In `_fallback_search`, look for where the browser navigates and how many results
it collects. If there's a `limit` or scroll count, increase it — current results
suggest it's stopping at 1–2 per keyword.

## What NOT to change
- `vertical_config.py` — keywords and negatives are set; don't touch
- `research.py` — API endpoint logic is fine
- Frontend — no changes needed

## Done condition
After your fix, push locally. Claude Code will review and push to develop.
