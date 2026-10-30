# Ad Builder — Speed Review (2026-10-30)

> **Status: complete** (items 13 and 14 deferred). All three batches shipped and deployed on 2026-10-30. The final results come first; the original review follows below them, unchanged, for the record.

## Final results (measured in production, Steve's Chrome)

| What | Before | After |
|---|---|---|
| First load after a deploy | 1.55 MB JS, uncompressed | ~125 KB gzipped (90 KB shell + page chunk). The 73 KB React vendor chunk stays cached across deploys |
| API JSON | Uncompressed (Drive list 4.0 MB) | Gzipped (Drive list 449 KB on the wire) |
| Meta ad-set insights, RHO, 14 days | 11.4s | 1.6s |
| Meta ad-set insights, RHO, 30 days | 23.0s | 3.6s |
| Meta ad-set insights, RHO, 90 days | 28.8s | 3.4s |
| niche-profitability, 30 days, first load | 14.7s | 3.5s |
| Repeat Meta insights pull within 60s, any page | Full re-pull | 0.09s (shared cache) |
| Facebook Pages list in launch modals | 1.2–1.95s every open | 0.07s cached |
| Campaign Performance, full reload | Waited for the account list before loading | Insights request starts before the list returns; all data in 2.5s |
| Every page measured (10), warm cache | Up to 3.7s | 0.75–1.45s |
| Research browse-ads | Fetched twice per visit | Once |

Notes on the table:
- The Meta rows are identical before and after, with spend matching to the cent ($116,211.73 for 30 days, $174,398.49 for 90 days). The gain comes from requesting 500-row pages instead of Meta's 25-row default. This was the largest single win, and the original review below missed it. It turned up while profiling batch 2.
- After a normal deploy, a returning user re-downloads about 15 KB of app shell plus the page they open.

**Freeze risks removed.** Each of these could stall the single server process for every user:
- The auth check on every request ran its DB lookup on the event loop.
- The Meta 20s, 30s and 60s timeouts didn't actually stop the call. The 20s one was verified with a stubbed 26s call, which now raises at 20s.
- Ad Remix downloaded the source image on the event loop.
- Research searches, captures, vertical refreshes and brand scrapes ran on the event loop.
- The three 30-minute jobs fired in the same second. They are now staggered, and auto-pause first runs at boot+2 min instead of boot+30.

**Commits:**

| Batch | Commits |
|---|---|
| 1 | `dfd0e2b`, `3d6474d` |
| 2 | `e9006ce`, `1f7bb9b` |
| 3 | `8266787` |
| Docs | `ee88ce4`, `82640d5`, `c5bc550` |

Change-level detail lives in `docs/features/ops-monitoring.md`.

### Item status

| # | Item | Outcome |
|---|---|---|
| 1 | gzip on the frontend nginx | Done, verified in production |
| 2 | Route code-splitting | Done. All 28 page chunks import-tested; pages load with no errors in production |
| 3 | Auth dependencies to `def`, pool settings | Done. Unit-tested via `/auth/me`; pool is now 10+20 |
| 4 | Meta insights cap | Done. Fixed in 3 places; the cap still covers only the first page so big accounts aren't cut off |
| 5 | Campaign Performance starts from the saved account | Done. The saved-account start is verified in production. Code now makes a manual switch during the list load win, but that path wasn't tested in a browser (see Not verified) |
| 6 | niche-profitability: fetch in parallel, single-flight | Done. 14.7s → 3.5s (that figure includes the page-size fix) |
| 7 | Ad Remix image download off the event loop | Done |
| 8 | Brand scrape off the event loop | Done, along with all Research search routes. The Chromium cap was rebuilt to work across event loops |
| 9 | Drive assets payload | Partly done. gzip took it from 4.0 MB to 449 KB, and the server spends about 170ms on it. Paging was not done because it would mean reworking the launcher picker |
| 10 | Stagger the scheduler jobs | Done. Every job now has `max_instances=1` and `coalesce` |
| 11 | Shared Meta insights cache | Done. 60s, single-flight, deep copies; Refresh buttons skip it; auto-pause always reads fresh |
| 12 | Cache Meta reads | Partly done. Pages and Pixels are cached for 5 min. Live ad sets (5.4s) and campaigns are not, because a launch modal must show a newly created ad set immediately |
| 13 | Budget-typing re-render | Deferred. Testing it means typing into a live budget field; revisit if Joel reports lag |
| 14 | Release DB sessions during background jobs | Deferred. The pool doubled and logs show zero pool waits |
| 15 | Research double fetch | Done, verified in production |
| 16 | Lazy-loaded library images | Done |
| 17 | Memoised context values | Partly done. CampaignContext is done; BrandContext's functions aren't stable, so memoising it would do nothing |
| — | Meta insights 500-row pages *(new)* | Done, verified live. The largest win of the pass |
| — | API gzip level 9 → 6 *(new)* | Done. Saves about 20ms on the largest payload |

### Not verified

- **Auto-pause at boot+2 min.** It logs nothing when no rule fires, so the earlier first run could not be confirmed in production.
- **Account edge cases.** Two cases were never exercised in a browser: the saved account dropping off the account list, and a manual account switch made while the list is still loading.
- **Research jobs that cost budget or create data.** No brand scrape, vertical refresh or Playwright-fallback search was run. The first real one from Joel or Abel is the live check.
- **Stale-tab reload after a deploy.** The code was reviewed, but the reload path was never exercised.
- **Warm vs cold timings.** The per-page timings are warm-cache. The cold figures in the results table are for the Meta-backed calls only.

### Process notes

- Every batch had a pre-push review. Each review caught at least one real issue, and all were fixed before pushing:
  - the insights cap moving paging under the 20s limit;
  - the stale-chunk blank screen;
  - the account-switch race;
  - `/pixels` missing the account permission check that `/pages` has.
- New tests were proven to fail on the old code wherever behaviour changed.
- 139 backend tests error both before and after, because they need a live Postgres. That is pre-existing and unrelated.

---

# Original review (2026-10-30, before any changes)

## Executive summary

Measured in Steve's signed-in Chrome against production. Every page's data calls finish in under 4s, and most in under 1s. Day-to-day lag is not coming from slow data.

There are three real problems:

1. **The first load after every deploy is heavy.**
   - The whole app is one 1.5 MB JavaScript file, sent uncompressed. It has no gzip and no per-page splitting.
   - Every push changes the file name, so Joel re-downloads all 1.5 MB on his next load. That can happen several times a day.
2. **A few code paths can freeze the server for everyone.** Some request handlers are written as async but do blocking work, and the server runs as a single process, so one stuck call stalls every user.
   - The login/permission check runs on every request and uses the database the blocking way.
   - Ad Remix's image download blocks.
   - Brand scrapes upload files to R2 the blocking way.
   - The 20-second safety cap on Meta insights calls doesn't actually cap them.
   - None of this is firing today: the logs show no connection-pool exhaustion in the last 72h, and the server sits at 0.1% CPU. It is cheap insurance against "everything hangs while Meta is slow."
3. **Joel's home page (Campaign Performance) waits in line.**
   - Its slowest call was **niche-profitability at 3.1s**.
   - It doesn't start loading until the ad-account list comes back, even though the account ID is already saved in the browser.

The recommended fix order is in the Build priority section. The first batch is about half a day of work and touches no Meta write paths.

## Measured (production, 2026-10-30, warm server caches)

| Page | Data calls | All data in | Slowest call |
|---|---|---|---|
| Dashboard `/` | 10 | 1.2s | ads/status-bulk 0.5s |
| Campaign Performance | 8 | **3.7s** | intelligence/niche-profitability **3.1s** |
| P&L | 6 | 2.8s | pnl/months 2.2s |
| Creative Library | 5 | 1.5s | drive-assets 0.9s (**4.0 MB response**) |
| Auto-pause rules | 6 | 1.4s | adsets/saved 0.4s |
| Research | 9 | 1.2s | browse-ads 0.6s (**fetched twice**) |
| Every other page | 4–6 | 0.4–1.0s | — |

Other measurements:

- **App shell:** one JS file, 1,548,999 bytes. Production nginx sends it without `Content-Encoding`, confirmed with curl. Cache headers are already correct: hashed assets are cached for a year as `immutable`, and `index.html` is `no-store`.
- **Single calls:**

  | Call | Time | Size |
  |---|---|---|
  | `facebook/campaigns` (no cache, live Meta) | 0.98s | |
  | `adsets/saved` | | 492 KB |
  | `generated-ads` | | 163 KB |
  | `insights-bulk` (14-day range, first request) | 0.25s | |

- **Server:**
  - 2 vCPU and 3.8 GB RAM. The API uses 766 MB.
  - One uvicorn process.
  - The SQLAlchemy pool is the default 5+10, with no `pool_pre_ping`.
  - The database is small: 835 ad sets, 529 ads, 2,695 Drive assets.

## Findings, ranked by what Steve and Joel feel

Status labels:
- *Confirmed*: I read the code or measured it.
- *Agent*: reported by a review agent; I didn't re-check it line by line.

| # | Problem | Where | Felt as | Fix | Effort | Status |
|---|---|---|---|---|---|---|
| 1 | No gzip on the frontend nginx | `frontend/Dockerfile` (inline nginx conf) | Slow first load after every deploy | `gzip on` plus types for JS, CSS and JSON. Takes 1.5 MB down to about 400 KB | 10 min | Confirmed |
| 2 | No route code-splitting: all ~28 pages in one bundle | `frontend/src/App.jsx:18-46` (0 `React.lazy`) | Same as #1, plus parse time on every full load | `React.lazy` per route plus one `Suspense`. `manualChunks` for react and lucide | 1 hr | Confirmed |
| 3 | Auth dependencies are `async def` but use sync DB queries | `core/deps.py:12,38,92,105` | Normally nothing. If the DB pool is busy, the whole server freezes for up to 30s, including logins | Make them plain `def`. Engine: `pool_pre_ping=True`, `pool_recycle=1800`, `pool_size=10, max_overflow=20` | 30 min | Confirmed. No freeze seen in 72h of logs |
| 4 | The 20s/60s cap on Meta insights doesn't cap | `facebook_service.py:1993, :3390` (`with ThreadPoolExecutor`, which waits on exit) | When Meta is slow, Dashboard and Campaign Performance hang instead of erroring at 20s | Same pattern already used at `:2239`: no `with`, `shutdown(wait=False)` | 20 min | Confirmed |
| 5 | Campaign Performance waits for `/facebook/accounts` before loading anything | `CampaignPerformance.jsx:2121-2150`, `CampaignContext.jsx:307-355` | Blank table for an extra round trip on every full load, worse when the Meta accounts cache is cold | Start with the account ID saved in `localStorage` and reconcile when the list arrives | 1 hr | Agent. Code path matches |
| 6 | niche-profitability: Meta, then RedTrack, in series, with no single-flight | `intelligence.py:1716-1730` | 3.1s, the slowest call on Joel's home page | Fetch both in parallel and add a per-key lock | 45 min | Measured. Agent for the cause |
| 7 | Ad Remix downloads the source image with a blocking call inside an async handler | `ad_remix_service.py:89` (`fetch_bytes`) | Each remix stalls every other user for the download time, up to 30s on a bad Meta CDN URL | `await run_in_threadpool(fetch_bytes, …)` | 15 min | Confirmed |
| 8 | Brand scrape: blocking boto3 R2 upload and DB commits inside an async background task, for up to 500 ads | `research.py:1229`, `brand_scraper.py:939-978` | During a brand scrape the whole app gets choppy for minutes | Run the scrape as a plain-`def` task, or thread-offload the upload and commits. Reuse one S3 client | 45 min | Confirmed |
| 9 | Drive assets endpoint returns everything: 4.0 MB | `drive_assets.py:103-165` | Creative Library and the launcher media picker take about 1s and get worse as Drive grows | Return only the fields the grid needs and paginate. Cache the `_table_exists` check | 1 hr | Measured |
| 10 | The three 30-minute jobs (auto-pause, RedTrack, Meta sync) fire in the same second. Three jobs have no `max_instances` or `coalesce` | `main.py:562-622` | A periodic blip every 30 min, and Meta rate-limit pressure on RHO's account | Give them staggered `start_date`s (+0, +7, +14 min) and set `max_instances=1, coalesce=True` on all of them | 15 min | Agent. Matches code |
| 11 | Each endpoint keeps its own cache of the same Meta insights pull | `auto_pause.py:643`, `dashboard.py:309,555`, `ai_insights.py:111` | Opening Campaign Performance then Dashboard makes Meta pull the same data again. It also raises rate-limit risk | One shared 60–90s cache with in-flight dedupe inside `get_account_insights_bulk` | 1.5 hr | Agent |
| 12 | Meta reads with no cache | `facebook.py` `/campaigns` (0.98s), `/pixels`, `/pages`, `/adsets`, `/ads`, `/lead-forms` | Launch wizard dropdowns wait on Meta every time | A 60–120s TTL cache, the same as `/accounts` already has | 1 hr | Measured for `/campaigns` only |
| 13 | Whole-page re-render while typing a budget | `CampaignPerformance.jsx` (30+ top-level states, no row `React.memo`) | Typing lag in budget editors | Pull the budget editor and row out as memoised components | 2 hr | Agent. Not felt-tested |
| 14 | Auto-pause job and Drive sync keep a DB connection checked out across slow external calls | `main.py:135-159`, `drive_sync_service.py:293` | Pool pressure, which feeds into #3 | Release the session before Meta and Drive calls | 1–2 hr | Agent |
| 15 | Research loads browse-ads twice per visit | `Research.jsx:1682` | About 0.6s of wasted work | Dedupe the effect | 15 min | Measured |
| 16 | Library grids load full-size images, with no `loading="lazy"` | `GeneratedAds.jsx:723,885,1025,1068`, `CreativeLibrary.jsx:286` | Slow scroll and paint on the library pages | `loading="lazy" decoding="async"` | 10 min | Agent |
| 17 | Context `value` objects aren't memoised | `CampaignContext.jsx:~365`, `BrandContext.jsx:282` | Extra re-renders | `useMemo` | 15 min | Agent |

**Deliberately not recommended now:**

- **Database indexes.** The agent rated missing indexes on `fb_adset_id` and `fb_ad_id` as high. At 835 ad sets and 529 ads, Postgres scans those tables in microseconds, so an index migration buys nothing measurable today. Revisit if the tables pass about 50k rows.
- **Paginating `generated-ads`.** 163 KB is fine for now.
- **Multiple uvicorn workers.** With 2 vCPU it is possible, but the APScheduler jobs would run once per worker and double the Meta calls. Fixes #3, #7 and #8 solve the freeze risk without that.
- **The P&L 4-minute warm job.** One agent flagged it as constant load. The server measured at 0.14% CPU between runs, so there's no evidence it hurts. Leave it.

## Build priority

**Batch 1: half a day, low risk, no Meta write paths. Do first.**
- #1 gzip
- #2 code-splitting
- #3 auth dependencies and pool settings
- #4 insights timeout cap
- #7 Ad Remix thread-offload
- #10 staggered jobs
- #15 Research double fetch
- #16 lazy images

Then re-measure the first load after deploy and the Campaign Performance load.

**Batch 2: Joel's home page and the launcher.**
- #5 load from the saved account ID
- #6 niche-profitability in parallel
- #9 slim the Drive assets payload
- #11 shared insights cache
- #12 cache Meta reads

**Batch 3: as needed.**
- #8 brand scrape, when scrapes are used more
- #13 budget-typing re-render, if Joel reports lag
- #14 DB session release
- #17 memoised context values

## Tracking and verification

After each batch, repeat today's method in Steve's Chrome: load each page, record when its last data call finishes, and note the slowest call. Also check:
- `curl -sI -H 'Accept-Encoding: gzip' …/assets/<file>.js` shows `content-encoding: gzip`;
- bundle chunk sizes from `npm run build`;
- `docker logs ad-builder-api | grep "QueuePool limit"` stays at 0.

## Not verified

- **Cold loads.** Every page timing was taken with warm server caches. A cold Meta or RedTrack fetch, such as the first load after a deploy or after a cache expires, will be slower. Only `insights-bulk` (0.25s) and `/campaigns` (0.98s) were measured cold.
- **Frontend render and paint time.** I measured network/data completion, not render time. I didn't test typing lag (#13) by hand.
- **Agent-reported items.** Items marked *Agent* came from code reading by review agents. I spot-checked #3, #4, #7, #8, #9 and the gzip and bundle findings myself.
