#!/bin/bash
# Read-only health watcher for Ad Builder. Runs every ~2h via launchd. Plain script, zero tokens.
# Findings are filed as incidents (same queue the investigator polls). Same finding type is
# not re-filed within 6h.
set -uo pipefail
BASE="https://adbuilder-api.velocitymx.io/api/v1"
SSH="ssh -i $HOME/.ssh/id_ed25519 -o ConnectTimeout=10 ubuntu@adbuilder.velocitymx.io"
STATE="$HOME/.adbuilder-watcher-state"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
touch "$STATE"

TOKEN=$(security find-generic-password -a "$USER" -s adbuilder-incident-token -w 2>/dev/null) || { echo "no incident token"; exit 1; }
SLACK=$(security find-generic-password -a "$USER" -s bhm-slack-bot-token -w 2>/dev/null) || SLACK=""

N409=$($SSH "docker logs ad-builder-api --since 130m 2>&1 | grep -c 'ads/save HTTP/1.1\" 409'; true") || N409=-1
N5XX=$($SSH "docker logs ad-builder-api --since 130m 2>&1 | grep -cE 'HTTP/1.1\" 5[0-9][0-9] '; true") || N5XX=-1
NCREATE=$($SSH "docker logs ad-builder-api --since 130m 2>&1 | grep -c 'Create creative failed'; true") || NCREATE=-1
USAGE=$($SSH "docker exec ad-builder-db psql -U postgres -d facebook_ad_builder -t -A -F, -c \"select coalesce(max(app_usage_max),0), coalesce(max(account_usage_max),0), coalesce(sum(throttles),0) from meta_call_stats where hour_start > now() - interval '3 hours'\"") || USAGE=""
HEALTH=$(curl -s -o /dev/null -m 15 -w "%{http_code}" "$BASE/docs")

APP_USE=$(echo "$USAGE" | cut -d, -f1); ACCT_USE=$(echo "$USAGE" | cut -d, -f2); THROTTLES=$(echo "$USAGE" | cut -d, -f3)
APP_USE=${APP_USE:-0}; ACCT_USE=${ACCT_USE:-0}; THROTTLES=${THROTTLES:-0}

FINDINGS=()
[ "$N409" -ge 1 ] 2>/dev/null && FINDINGS+=("ads_save_409|$N409 ads/save 409 conflicts in the last ~2h")
[ "$N5XX" -ge 10 ] 2>/dev/null && FINDINGS+=("http_5xx|$N5XX HTTP 5xx responses in the last ~2h")
[ "$NCREATE" -ge 2 ] 2>/dev/null && FINDINGS+=("create_creative_failed|$NCREATE Meta creative-creation failures in the last ~2h")
[ "$THROTTLES" -ge 3 ] 2>/dev/null && FINDINGS+=("meta_throttle|$THROTTLES Meta throttle responses in the last 3h")
{ [ "$APP_USE" -ge 75 ] || [ "$ACCT_USE" -ge 75 ]; } 2>/dev/null && FINDINGS+=("meta_usage_high|Meta usage high: app ${APP_USE}%, account ${ACCT_USE}% (3h max)")
[ "$HEALTH" != "200" ] && FINDINGS+=("api_down|API docs endpoint returned $HEALTH")
[ "$N409" = "-1" ] && FINDINGS+=("watcher_ssh_failed|Watcher could not read VPS logs over SSH")

NOW=$(date +%s)
for f in "${FINDINGS[@]:-}"; do
  [ -z "$f" ] && continue
  KEY="${f%%|*}"; MSG="${f#*|}"
  LAST=$(grep "^$KEY " "$STATE" | tail -1 | cut -d' ' -f2)
  if [ -n "${LAST:-}" ] && [ $((NOW - LAST)) -lt 21600 ]; then continue; fi
  BODY=$(python3 -c 'import json,sys;print(json.dumps({"summary":"Watcher: "+sys.argv[2],"meta":{"finding":sys.argv[1],"window":"last ~2-3h (UTC now: "+sys.argv[3]+")"}}))' "$KEY" "$MSG" "$(date -u +%FT%TZ)")
  if curl -fsS -m 20 -X POST -H "X-Incident-Token: $TOKEN" -H "Content-Type: application/json" -d "$BODY" "$BASE/launch-outcomes/incident" >/dev/null; then
    echo "$KEY $NOW" >> "$STATE"
  elif [ -n "$SLACK" ]; then
    python3 -c 'import json,sys;print(json.dumps({"channel":"U6M6033G9","text":":warning: *[Ad Builder watcher]* "+sys.argv[1]+" (could not file incident)"}))' "$MSG" \
      | curl -fsS -X POST https://slack.com/api/chat.postMessage -H "Authorization: Bearer $SLACK" -H "Content-Type: application/json; charset=utf-8" -d @- >/dev/null \
      && echo "$KEY $NOW" >> "$STATE"
  fi
done
tail -200 "$STATE" > "$STATE.tmp" && mv "$STATE.tmp" "$STATE"
echo "$(date -u +%FT%TZ) watcher ok: 409=$N409 5xx=$N5XX createfail=$NCREATE usage=$APP_USE/$ACCT_USE throttles=$THROTTLES health=$HEALTH findings=${#FINDINGS[@]}"
