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

## Known open items (from the 2026-10-24 review)
No container restart policy (all four `restart=no`; host up 25 weeks); Postgres uses the default `postgres` password (not reachable from the internet — ufw allows only 22/80/443/25); a leftover `.env.bak-*` file with plaintext secrets; 45 GB reclaimable Docker build cache; deploy-failure notifier disabled (`if: ${{ false }}`); CI doesn't gate deploy. Restart policy + password rotation need a short maintenance window.
