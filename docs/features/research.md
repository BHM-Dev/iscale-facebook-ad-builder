# Research (`/research`)

Competitor-ad catalog (Meta Ad Library captures + external imports) per vertical, used to find angles and send an
inspiration payload to Build New Ad (`/ad-remix`). Grown a lot via Codex (evidence review, taxonomy filters, watchlist,
research tests linked to launched ads, Ask Research, capture receipts). Code: `frontend/src/pages/Research.jsx` (~3,000 lines),
`backend/app/api/v1/research.py` (~3,000 lines, 57 routes), `services/{scraper,brand_scraper,research_service}.py`,
`core/vertical_config.py`. This entry comes from a three-lens audit on 2026-10-07 (backend cost/authz, frontend honesty/handoff,
product workflow). **Read-only audit — nothing below is fixed unless it says so.**

## What protects money / trust today
- Claims about spend and winners are blocked server-side in the Ask Research prompt; vendor "winning" signals are stored as context only.
- Research tests: server-side idempotency, one-link-per-test claim, cross-vertical source rejection, paused Meta handoff.
- Ad Remix labels competitor copy "study, not copy" and runs a similarity check with one retry (`ad_remix.py`).
- Meta API token is masked in the one logged URL sample; no server-side fetch of user-supplied URLs found (imports store URLs, never fetch).
- All 57 routes require a logged-in user.
- Shipped 2026-10-07: stored `'unknown'` CTA/page type is treated as unknown in the API filter and UI (`11a4fdc`).

## Audit findings — OPEN
### High (cost / abuse / authorization) — backend
1. **Unbounded `limit`** on `/search` and `/search-and-save` (`schemas/research.py:8`, `scraper.py` loops 300 ads per Meta call, falls back to Chromium). One request can run hundreds of Meta calls; the rate limiter checks the *logged* total before the call. *(Verified: no upper bound.)* `search_and_save_vertical` `limit_per_keyword` is also unbounded.
2. **Rate limit is global, not per user** and has no in-flight lock — one user (or a double-click) can burn the whole 200-calls/59-min budget and block Joel and Saule. Vertical fan-out runs every keyword concurrently on a double-click.
3. **`POST /run-scheduled-searches` is open to any logged-in user**, runs synchronously in the request at limit 100, skips the rate limiter, and nothing in the repo calls it (no cron). *(Verified.)*
4. **`POST /brand-scrapes`** — unlimited, no dedupe on `page_id`, each launches a background scrape + image downloads to R2.
5. **Destructive routes with no role/ownership check:** `DELETE /boards/{id}`, `DELETE /config-verticals/{id}/ads` (bulk-deletes all non-saved ads in a vertical, no log), saved-search delete, blacklist add/delete (global — changes filtering for everyone), brand-scrape delete (also removes R2 media).
6. **Handoff payload (`Research.jsx:2223`)**: full ad object written to localStorage with no try/catch (quota error = button silently does nothing), no timestamp/TTL — AdRemix consumes whatever is there however old.
7. **Brand switch mid-wizard keeps the competitor context + auto-filled offer** (`AdRemix.jsx:149/199/412`) — can generate for brand B using brand A's research.
8. **`deconstruct_template` fetches a client-supplied `source_image_url`** (`ad_remix.py:463`) with no host allow-list (SSRF surface) and silently falls back to a generic blueprint when the Meta CDN URL has expired; UI says the source image is "never used" but it is analyzed.
9. **Guessed taxonomy shown like evidence:** keyword rules tag `%` → "statistic", "honestly" → "ugc" as `rules_v1`; `running_days` keeps counting after an ad stops delivering.

### Medium
- Ask Research (`/copilot/query`) calls Claude per request with no per-user limit or cache; `capture-advertiser` has no cooldown; Chromium fallback has no concurrency semaphore on a single uvicorn worker.
- Meta access token appears in exception text (`raise_for_status` URL) that is **printed to server logs** (`scraper.py:83`, `brand_scraper.py:213`) and may be stored in `brand_scrape.error_message` (`str(e)[:500]`). Not found returned to clients; redact anyway.
- NULL vs `'unknown'` sentinels differ by writer (scraper writes NULL/'image'; taxonomy writes 'unknown'); Ask Research sends `cta: "unknown"` for NULLs.
- Browse list vs client filter mismatch: `ads_per_advertiser` and the 500 cap apply server-side *before* the client review filter; no "showing first 500" notice; search-mode "new" treats missing `first_seen` as new while browse mode doesn't.
- "N new this week" is really *newly cataloged*; saved-ads load failures look like an empty library (stars show unsaved); save/unsave have no in-flight guard and unsave doesn't roll back; "Block advertiser" is team-wide with no confirm or unblock UI; `setBrowseAds([])` on every refetch.
- `_is_due` in `scheduler_service` mixes local and UTC time; blacklist adds accept unbounded/duplicate values; a new Vertical is created for any `vertical` string on ad-library-import; no `role="dialog"`/focus trap on import modals.
- ESLint: the 10 errors in `Research.jsx` are unused catch bindings / benign — none is a real bug.

## Product perspective (fresh read)
- The page is a **research-ops console** (12+ panels), not a buyer's tool. Daily job = browse watched advertisers' new creatives → one click into Build test. Everything else competes with that.
- **Loop is only weakly closed:** the linked test shows revenue/profit after a sync, but not spend, CPL, leads or ROAS (Joel's decision metrics), outcome is free text, and nothing aggregates across tests.
- **Highest-value next steps (in order):** (1) read spend/CPL/leads onto the linked test row + "result ready" prompt; (2) learnings-by-attribute table (profit/CPL by hook, promise, angle across completed tests) and feed top results into Remix copy as few-shot; (3) one-click "Build test" from any card; (4) collapse the screen to Feed + Queue (merge Saved/Boards/Research Brief; merge Next Actions/Watchlist/Test Backlog; demote Compare and Ask Research); (5) scheduled watchlist refresh with a failure alert (today it is manual — fails "runs without Steve").
- **Do not build next:** more taxonomy filters, evidence-coverage scores, receipts/provenance UI, smarter Ask Research, more compare/boards, further Research test-suite expansion.
- **Trust labels to fix:** "SOURCE REVIEWED" (green, reads as a quality stamp; means an import was reviewed), "reviewed" has three meanings, "N recent" reads as running now, capture date should be on the card not only in a tooltip.

## Verified vs not
- **Verified (code read + spot-checked):** unbounded `limit`; `/run-scheduled-searches` open to any user with no caller; token exposure is log-only.
- **Not verified:** everything else above is code-reading only; nothing was run or tried against production. Screen order is inferred, not seen.

## Changelog
- 2026-10-07 first feature-log entry (audit); Unknown CTA/page-type fix `11a4fdc`.
