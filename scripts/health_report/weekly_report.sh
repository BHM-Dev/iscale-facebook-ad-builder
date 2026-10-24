#!/bin/bash
# Weekly Ad Builder health report. Plain script, zero model tokens, read-only.
# Runs Monday morning via launchd (com.bhm.adbuilder-weekly-health-report) and DMs Steve ONLY
# (never #media-buys or any team channel). If the DM doesn't arrive Monday morning, this job is the thing that broke.
#
#   weekly_report.sh            # gather + DM
#   weekly_report.sh --dry-run  # gather + print, no DM
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

REPO="/Users/Steve1/Claude/AdBuilder"
BASE="https://adbuilder-api.velocitymx.io/api/v1"
SSH="ssh -i $HOME/.ssh/id_ed25519 -o ConnectTimeout=10 -o BatchMode=yes ubuntu@adbuilder.velocitymx.io"
STEVE_DM="U6M6033G9"
OUT=""; WARN=0; BAD=0
ok()   { OUT+=":white_check_mark: $1"$'\n'; }
warn() { OUT+=":warning: $1"$'\n'; WARN=$((WARN+1)); }
bad()  { OUT+=":red_circle: $1"$'\n'; BAD=$((BAD+1)); }
hdr()  { OUT+=$'\n'"*$1*"$'\n'; }

# ---- 1. Production + deploys ----------------------------------------------------------------------------
hdr "Production & deploys"
CODE=$(curl -s -o /dev/null -m 15 -w "%{http_code} %{time_total}" "$BASE/docs" || echo "000 0")
VER=$(curl -s -m 15 "$BASE/version" | jq -r '.commit // empty' 2>/dev/null | cut -c1-7)
HEAD=$(cd "$REPO" && git fetch -q origin 2>/dev/null; git rev-parse --short=7 origin/develop 2>/dev/null)
[ "${CODE%% *}" = "200" ] && ok "API up (${CODE%% *}, ${CODE##* }s)" || bad "API check returned ${CODE%% *}"
if [ -n "$VER" ] && [ "$VER" = "$HEAD" ]; then ok "Serving latest commit \`$VER\`"
else bad "Prod serves \`${VER:-?}\` but develop is \`${HEAD:-?}\` — a deploy may have failed silently"; fi
SINCE=$(date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)
for W in "Build & Push Frontend" "Test Suite" "CI - Pre-Deploy Checks"; do
  R=$(gh run list --repo BHM-Dev/iscale-facebook-ad-builder --workflow "$W" --limit 40 --json conclusion,createdAt \
      -q "[.[] | select(.createdAt > \"$SINCE\")] | map(.conclusion) | group_by(.) | map(\"\(.[0]):\(length)\") | join(\" \")" 2>/dev/null)
  case "$R" in *failure*) warn "$W (7d): $R";; "") ok "$W: no runs in 7d";; *) ok "$W (7d): $R";; esac
done

# ---- 2. Backups (the gap found 2026-10-24) -----------------------------------------------------------------
hdr "Backups"
NEWEST=$($SSH "ls -1t /home/ubuntu/backups/*.sql* 2>/dev/null | head -1" 2>/dev/null)
if [ -z "$NEWEST" ]; then bad "No database backup files found on the VPS"
else
  AGE_D=$($SSH "echo \$(( (\$(date +%s) - \$(stat -c %Y '$NEWEST')) / 86400 ))" 2>/dev/null)
  if [ "${AGE_D:-99}" -le 8 ]; then ok "Newest backup is ${AGE_D}d old ($(basename "$NEWEST"))"
  else bad "Newest backup is ${AGE_D}d old ($(basename "$NEWEST")) — backups are not running"; fi
fi
CRON=$($SSH "crontab -l 2>/dev/null | grep -c pg_dump" 2>/dev/null)
[ "${CRON:-0}" -ge 1 ] && ok "Backup cron present" || warn "No pg_dump cron on the VPS"

# ---- 3. VPS health -----------------------------------------------------------------------------------------
hdr "Server"
DISK=$($SSH "df --output=pcent / | tail -1 | tr -dc 0-9" 2>/dev/null)
[ "${DISK:-100}" -lt 80 ] && ok "Disk ${DISK}% used" || { [ "${DISK:-100}" -lt 90 ] && warn "Disk ${DISK}% used" || bad "Disk ${DISK}% used"; }
CACHE=$($SSH "docker system df --format '{{.Type}} {{.Reclaimable}}' 2>/dev/null | grep 'Build Cache' | sed 's/Build Cache //'" 2>/dev/null)
[ -n "$CACHE" ] && OUT+=":information_source: Docker build cache reclaimable: $CACHE"$'\n'
NORESTART=$($SSH 'for c in $(docker ps --format "{{.Names}}"); do [ "$(docker inspect -f "{{.HostConfig.RestartPolicy.Name}}" $c)" = "no" ] && echo $c; done | tr "\n" " "' 2>/dev/null)
[ -z "${NORESTART// }" ] && ok "All containers restart automatically" || warn "No restart policy: ${NORESTART}"
ENVBAK=$($SSH "ls /home/ubuntu/iscale-facebook-ad-builder/.env.bak* 2>/dev/null | wc -l" 2>/dev/null)
[ "${ENVBAK:-0}" -eq 0 ] && ok "No leftover .env backups" || warn "${ENVBAK} leftover .env.bak file(s) hold plaintext secrets"
N5XX=$($SSH "docker logs ad-builder-api --since 168h 2>&1 | grep -cE 'HTTP/1.1\" 5[0-9][0-9] '; true" 2>/dev/null)
[ "${N5XX:-0}" -lt 25 ] && ok "HTTP 5xx in 7d: ${N5XX:-?}" || warn "HTTP 5xx in 7d: ${N5XX}"

# ---- 4. Data freshness & Meta -----------------------------------------------------------------------------
hdr "Data & Meta"
SYNC=$($SSH "docker exec ad-builder-db psql -U postgres -d facebook_ad_builder -t -A -c \"select extract(epoch from (now()-max(synced_at)))/3600 from facebook_adsets\"" 2>/dev/null | cut -d. -f1)
if [ -z "$SYNC" ]; then warn "Could not read last Meta ad-set sync time"
elif [ "$SYNC" -le 2 ]; then ok "Meta ad-set sync fresh (${SYNC}h ago)"
else bad "Meta ad-set sync is ${SYNC}h old — scheduled sync may be failing (stale data drives auto-pause)"; fi
USAGE=$($SSH "docker exec ad-builder-db psql -U postgres -d facebook_ad_builder -t -A -F, -c \"select coalesce(max(app_usage_max),0), coalesce(max(account_usage_max),0), coalesce(sum(throttles),0) from meta_call_stats where hour_start > now() - interval '7 days'\"" 2>/dev/null)
if [ -n "$USAGE" ]; then
  A=${USAGE%%,*}; REST=${USAGE#*,}; B=${REST%%,*}; T=${REST##*,}
  [ "${T:-0}" -lt 5 ] 2>/dev/null && ok "Meta usage peak 7d: app ${A}%, account ${B}%, throttles ${T}" || warn "Meta usage peak 7d: app ${A}%, account ${B}%, throttles ${T}"
fi
W=$(stat -f %m "$HOME/Library/Logs/adbuilder-health-watcher.log" 2>/dev/null || echo 0)
HRS=$(( ($(date +%s) - W) / 3600 ))
[ "$HRS" -le 3 ] && ok "Health watcher ran ${HRS}h ago" || bad "Health watcher last ran ${HRS}h ago — the 2-hourly watcher has stopped"

# ---- 5. Code health ----------------------------------------------------------------------------------------
hdr "Code"
if (cd "$REPO" && python3 scripts/check_alembic_heads.py >/dev/null 2>&1); then ok "Alembic: single migration head"
else warn "Alembic check failed — multiple heads or a broken chain"; fi
AUD=$(cd "$REPO/frontend" && npm audit --omit=dev --json 2>/dev/null | jq -r '.metadata.vulnerabilities | "critical \(.critical), high \(.high), moderate \(.moderate)"' 2>/dev/null)
CRIT=$(echo "$AUD" | sed -n 's/critical \([0-9]*\).*/\1/p')
[ "${CRIT:-0}" -gt 0 ] && warn "npm audit (prod deps): $AUD" || ok "npm audit (prod deps): ${AUD:-unavailable}"

# ---- send --------------------------------------------------------------------------------------------------
if [ $BAD -gt 0 ]; then HEAD_ICON=":red_circle:"; STATE="$BAD red, $WARN amber"
elif [ $WARN -gt 0 ]; then HEAD_ICON=":large_yellow_circle:"; STATE="$WARN amber"
else HEAD_ICON=":large_green_circle:"; STATE="all clear"; fi
TEXT="$HEAD_ICON *Ad Builder weekly health — $STATE* ($(date '+%a %b %d'))"$'\n'"$OUT"$'\n'"_Plain script, no AI. If this DM is missing on Monday morning, the job itself is down: \`launchctl list | grep weekly-health\`._"

if [ $DRY -eq 1 ]; then echo "$TEXT"; exit 0; fi
TOKEN=$(security find-generic-password -a "$USER" -s bhm-slack-bot-token -w 2>/dev/null) || { echo "no slack token in keychain" >&2; exit 1; }
python3 -c 'import json,sys;print(json.dumps({"channel":sys.argv[1],"text":sys.argv[2],"mrkdwn":True}))' "$STEVE_DM" "$TEXT" \
  | curl -fsS -m 20 -X POST https://slack.com/api/chat.postMessage -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json; charset=utf-8" -d @- \
  | jq -r 'if .ok then "posted" else "slack error: \(.error)" end'
