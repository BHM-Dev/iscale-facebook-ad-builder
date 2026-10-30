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

**Status:**
- Unit-tested: auth via `/auth/me`, the Meta cap, and frontend vitest.
- Not verified in production until after the deploy.
