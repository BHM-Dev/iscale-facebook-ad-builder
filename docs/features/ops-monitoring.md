# Ops & monitoring

What watches the Ad Builder, where it lives, and how to tell if it has stopped. All of it alerts **Steve's Slack DM only** — never `#media-buys` or any team channel.

| What | Where it runs | Cadence | Source | Notes |
|---|---|---|---|---|
| **Database backup** | VPS crontab (ubuntu) | nightly 09:15 UTC | `scripts/ops/backup_db.sh` (installed at `/home/ubuntu/bin/backup_db.sh`, outside the git checkout) | `pg_dump` → gzip → verified complete → copied to R2 `db-backups/` (size-checked) → local prune (14 days daily, 60 days Sundays). Failure or unexpected exit DMs Steve. Log: `/home/ubuntu/backups/backup.log`. |
| **Health watcher** | Steve's Mac, launchd `com.bhm.adbuilder-health-watcher` | every 2 h | `scripts/incident_investigator/watcher.sh` | Read-only: 409s, 5xx, creative failures, Meta throttle/usage, API up. Plain script. |
| **Incident investigator** | Steve's Mac, launchd | every 10 min | `scripts/incident_investigator/investigator.sh` | Polls the incident queue; empty log = nothing to investigate. |
| **Weekly health report** | Steve's Mac, launchd `com.bhm.adbuilder-weekly-health-report` | Mon 08:30 local | `scripts/health_report/weekly_report.sh` | Plain script, zero AI tokens: prod/deploy/CI, backups (local + R2), disk, restart policy, leftover `.env.bak`, 5xx, Meta sync freshness + usage, watcher alive, Alembic head, `npm audit`. If the Monday DM is missing, the job is down (`launchctl list | grep weekly-health`). |
| **Monthly full review** | Claude scheduled task `adbuilder-monthly-full-review` | 1st of month 09:00 | task prompt in `~/claude-config/scheduled-tasks/` | Six read-only reviewers + read-only VPS checks; writes `Ad-Builder-Full-Review-<YYYY-MM>.md` locally (untracked — it lists unpatched gaps) and DMs a ≤150-word summary. Needs the Claude app open (runs on next launch if closed). |
| **Slack monitor** | Claude scheduled task `adbuilder-slack-monitor` | 07:30 + 16:30 | — | Joel/Abel/Steve group chat. |

## Verified
- **2026-10-25:** first backup ran by hand (1.8 MB, uploaded to R2 and size-checked); **restore drill passed** — loaded into a throwaway Postgres container: 0 errors, identical row counts across 10 tables (users, ad sets, campaigns, ads, generated ads, cost entries, month snapshots, rules, scraped ads, drive assets) and the same Alembic version. The weekly report job was kickstarted via launchd and posted to Steve's DM.
- **Not yet verified:** the cron firing at 09:15 UTC unattended (check `backup.log` on 2026-10-26); the failure-alert path (never triggered); the Monday 08:30 schedule itself.

## Maintenance window 2026-10-25 (Steve: "run it whenever, it won't impact Meta")
- **Restart policy:** all four containers now `restart: unless-stopped` — set live with `docker update` (no downtime) and persisted in `docker-compose.prod.yml` (so a redeploy keeps it) and `/home/ubuntu/traefik/docker-compose.yml` (on the VPS, outside the repo).
- **Postgres password rotated** off the default (`ALTER USER` in the live DB, then `POSTGRES_PASSWORD` in the VPS `.env`, API recreated with `--no-deps`; verified the API connects with the new password, 0 auth failures; auto-rollback was armed but not needed). The password lives only in the VPS `.env`.
- **Log rotation:** json-file, 10 MB x 5 per container (API logs run ~0.4 MB/day, so ~months of history).
- **Traefik dashboard** (port 8080, insecure API mode) now bound to `127.0.0.1` only. It was already unreachable from the internet (provider firewall), but Docker publishes past ufw, so this removes the reliance on a single layer. Use an SSH tunnel to reach it.
- **Not changed (deliberately):** DB still shares the `traefik-proxy` network with the API/web/traefik containers (only our four containers are on it; isolating it means a compose network redesign with outage risk and little gain).

## Known open items (from the 2026-10-24 review)
a leftover `.env.bak-*` file with plaintext secrets and 45 GB reclaimable Docker build cache (cleanup below); deploy-failure notifier disabled (`if: ${{ false }}`); CI doesn't gate deploy. Restart policy + password rotation need a short maintenance window.

## Speed pass, batch 1 (2026-10-30)
Measured first in Steve's Chrome: every page's data finished in under 4s warm. The lag was elsewhere. Full review: `docs/briefs/AdBuilder-Speed-Review-2026-10-30.md` (local).

**Changes:**
- **Frontend:**
  - Each page is now its own lazy chunk (`lib/lazyPage.js`). The main bundle went from 1.55 MB to 283 KB, or 90 KB gzipped.
  - If a tab is still open from before a deploy and requests an old chunk, the page reloads once. `PageErrorBoundary` keeps the sidebar visible if a page still fails to load.
  - nginx now has `gzip on`. It was off, so the bundle was sent raw.
- **API:**
  - Added `GZipMiddleware`. `drive-assets` was 4 MB raw and `adsets/saved` was 0.5 MB.
  - Auth dependencies are now plain `def`, so their DB lookups no longer run on the single event loop.
  - Pool settings: 10 + 20, with `pre_ping` and `recycle` (Postgres `max_connections` is 100).
- **Meta insights cap:** the 20s and 60s caps on Meta insights now actually return. A `with ThreadPoolExecutor` block used to wait for the hung call.
  - Verified with a stubbed 26s Meta call: the old code took 26s and the new code raises at 20s.
  - The cap still covers the first page only. Later pages load outside it.
- **Ad Remix:** the source-image download runs in the threadpool, not on the event loop.
- **Scheduler:** jobs are staggered by start time after boot: auto-pause +2 min (it used to wait 30 min after every deploy), Drive +7, RedTrack +10, Meta sync +20. All four have `max_instances=1` and `coalesce`.
- **Research:** browse-ads is fetched once per visit instead of twice.
- **Library grids:** images use `loading="lazy"`.

- **Shared chunks** (`3d6474d`): React and the router sit in one `vendor` chunk (73 KB gz). It changes only when those packages are upgraded, so it stays cached across deploys. Lucide icons sit in one `icons` chunk; they used to be a dozen tiny files fetched in a chain.

**Status:**
- **Verified in production 2026-10-30** (Steve's Chrome):
  - The main JS is now served gzipped. The API returns `content-encoding: gzip`.
  - Opening a page now loads 4–7 JS files with no page errors. All 28 page chunks were import-tested against the built bundle.
  - Every measured page has its data in 0.75–1.45s, including Campaign Performance at 0.87s. That number is a warm-cache figure, not a fixed one.
  - Research calls browse-ads once.
- **Unit-tested only:** the auth dependencies (`/auth/me`) and the Meta cap.
- **Not verified:** the auto-pause run at boot+2 in production, because it logs nothing when no rule fires.

## Speed pass, batch 2 (2026-10-30)

**Changes:**
- **Campaign Performance and Dashboard start from the saved ad account.**
  - They no longer wait for `/facebook/accounts`.
  - The account list still loads in the background. If the saved account isn't in it, the page switches accounts.
  - If the user switches accounts while the list is loading, the user's choice wins: the list handler re-reads storage.
  - Dashboard's load depends on a `noActiveAccount` boolean instead of `adAccounts.length`, so the list arriving no longer reloads the page.
- **niche-profitability** (Campaign Performance's slowest call, 3.1s):
  - Meta and RedTrack are fetched in parallel.
  - Requests for the same range share one fetch.
  - Its own 30s Meta cap now actually caps.
  - RedTrack has a 45s backstop.
- **`get_account_insights_bulk` has one shared 60s cache.**
  - It is single-flight and returns deep copies. Before, each page kept its own cache or had none.
  - The Refresh buttons pass `refresh` through and skip it.
  - The auto-pause job always reads Meta directly (`refresh=True`), so pause and budget decisions never use cached numbers.
- **`/facebook/pages` and `/facebook/pixels` are cached for 5 minutes per account**, with `?refresh=true` to skip.
  - Pages measured 1.95s live.
  - Empty lists are never cached.
  - Page access tokens are stripped before caching.
  - `/pixels` now runs the same account check as `/pages`.
- **API gzip level is now 6** (was 9). That saves about 20ms on the 4 MB Drive list for almost the same size.

**Deliberately not done:**
- **Paging the Drive list.** It takes about 170ms on the server and sends 449 KB gzipped. Paging would mean reworking the launcher's picker.
- **Caching live ad sets (5.4s) and campaigns.** A launch modal must show an ad set the moment it's created, and many write paths would need to clear the cache.

- **Meta insights page size is now 500 rows** (`1f7bb9b`). Meta's default page is 25 rows, so the account ad-set pulls made up to 10 round trips one after another.
  - Measured live on RHO. The rows and spend are identical to the cent:

    | Range | Before | After |
    |---|---|---|
    | 14 days | 11.4s | 1.6s |
    | 30 days | 23.0s | 3.6s |
    | 90 days | 28.8s | 3.4s |

**Status:**
- **Unit-tested:**
  - The new tests fail on the old code: the fetches ran serially, and 3 concurrent requests made 3 Meta pulls.
  - Cache tests cover hits, refresh, expiry, deep copies, and single-flight.
- **Verified in production 2026-10-30** (Steve's Chrome):
  - Cold 30-day niche-profitability: 14.7s → 3.5s.
  - Cold 30-day insights-bulk: 3.8s. A repeat call returns in 0.09s from cache.
  - Pages: 1.2s cold, 0.07s cached. The response contains no tokens.
  - Dashboard's niche summary reused the shared cache.
  - Campaign Performance starts its insights call before `/facebook/accounts` returns. A full reload has all data in 2.5s.
- **Not verified:** the switch when the saved account is no longer in the list, and a manual switch made while the list is loading. Neither was exercised in a browser.

## Speed pass, batch 3 (2026-10-30)

**Changes:**
- **Research scraping no longer runs on the server's only event loop.**
  - The search, search-and-save, capture-advertiser, vertical-refresh and run-scheduled-searches routes are now plain `def`. They run the async scraper with `asyncio.run` in the threadpool.
  - The brand-scrape background task works the same way.
  - Before, their sync DB writes (a commit per ad) and the blocking boto3 R2 uploads stalled every request for the length of a refresh or scrape.
- **Chromium cap:** the `asyncio.Semaphore(2)` became `_ChromiumSlots`, a threading semaphore polled without blocking.
  - An asyncio semaphore binds to one loop. A test showed it raising "bound to a different event loop" six times once two loops contended, which they now do.
  - The cap of 2 holds across loops (test).
- **`CampaignContext` value is memoised.**

**Deliberately not done:**
- **#13 budget-typing re-render:** testing it in production means typing into a live budget field. Revisit if Joel reports lag.
- **#14 releasing DB connections in background jobs:** batch 1 raised the pool from 15 to 30, and there have been zero pool waits in the logs.
- **Memoising `BrandContext`:** its functions aren't stable, so memoising would do nothing without a riskier refactor.

**Behaviour change:** a Research refresh started from a tab that is then closed now runs to completion. The old async route was cancelled when the tab closed. The Meta budget was already charged up front, so the accounting stays correct.

**Status:**
- **Unit-tested:** route shape, the async service running from a worker thread, and the cross-loop cap.
- **Verified in production 2026-10-30:** a live `POST /research/search` returned 200 with 10 ads in 0.7s. The logs show no event-loop errors.
- **Not verified:** a Playwright-fallback search, a brand scrape, and a vertical refresh. None of these was run, to avoid spending Meta budget and creating research rows.
