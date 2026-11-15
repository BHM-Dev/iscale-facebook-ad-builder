#!/bin/bash
# Nightly Ad Builder database backup. Runs ON THE VPS from the ubuntu user's crontab.
#   pg_dump -> gzip -> verify the dump is complete -> copy off-box to R2 -> prune old local copies.
# Any failure (including an unexpected exit) DMs Steve via the app's Slack service (same path as the Drive alerts),
# falling back to a direct Slack post from the host when the app container can't send, and exits non-zero. Installed at /home/ubuntu/bin/backup_db.sh, deliberately OUTSIDE the git checkout so a deploy
# can't clash with it. The crontab line must redirect output: `>> /home/ubuntu/backups/backup.log 2>&1`.
# Retention: local daily dumps 14 days; Sunday dumps 60 days. R2 copies are not pruned (a dump is a few MB).
set -uo pipefail
DIR=/home/ubuntu/backups
DB_CONTAINER=ad-builder-db
API_CONTAINER=ad-builder-api
DB=facebook_ad_builder
STAMP=$(date -u +%Y%m%d-%H%M%S)
NAME="db-$STAMP.sql.gz"
FILE="$DIR/$NAME"
MIN_BYTES=200000
DONE=0
mkdir -p "$DIR"
log() { echo "$(date -u +%FT%TZ) $*"; }

APP_ENV=/home/ubuntu/iscale-facebook-ad-builder/.env
STEVE_DM=U6M6033G9
DUMP_TIMEOUT=1800   # seconds; a hung pg_dump must fail loudly, not hold the lock forever

# Direct Slack post from the host, used when the app container can't send —
# which is exactly when the API is down, i.e. when a backup alert matters most
# (2026-11-01 review, N7). The token is read from the app's .env and never echoed.
alert_direct() {
  local token
  token=$(grep -m1 '^SLACK_BOT_TOKEN=' "$APP_ENV" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"'\r')
  [ -n "$token" ] || { log "no SLACK_BOT_TOKEN in $APP_ENV; alert not sent"; return 1; }
  python3 -c 'import json,sys; print(json.dumps({"channel": sys.argv[1], "text": ":rotating_light: *Ad Builder DB backup failed* — " + sys.argv[2] + " (sent from the VPS host; the app container could not send it). See /home/ubuntu/backups/backup.log"}))' "$STEVE_DM" "$1" \
    > "$DIR/.alert.json"
  # Header via a file descriptor, not argv, so the token never shows in `ps`.
  curl -sS --max-time 15 -H @<(printf 'Authorization: Bearer %s\n' "$token") \
       -H 'Content-type: application/json; charset=utf-8' \
       --data @"$DIR/.alert.json" https://slack.com/api/chat.postMessage | grep '"ok":true' >/dev/null \
    && { rm -f "$DIR/.alert.json"; log "failure alert sent directly"; } \
    || { rm -f "$DIR/.alert.json"; log "direct failure alert failed"; return 1; }
}

alert() {
  timeout 60 docker exec "$API_CONTAINER" python -c '
import sys
from app.services.slack_service import send_drive_sync_alert
ok = send_drive_sync_alert(summary=sys.argv[1], detail="Nightly pg_dump backup on the VPS. See /home/ubuntu/backups/backup.log", headline="Ad Builder DB backup failed")
print("failure alert sent:", ok)
sys.exit(0 if ok else 1)
' "$1" 2>&1 | tail -n 3
  [ "${PIPESTATUS[0]}" = 0 ] || alert_direct "$1"
}

fail() {
  DONE=1   # stop the EXIT trap from alerting a second time
  log "FAILED: $1"
  rm -f "$FILE.partial"
  docker exec "$API_CONTAINER" rm -f "/tmp/$NAME" >/dev/null 2>&1 || true
  alert "$1" || log "could not send failure alert"
  exit 1
}

# One run at a time. A run still holding the lock is now bounded by
# DUMP_TIMEOUT, so finding it held means something is badly stuck — say so.
exec 9>"$DIR/.backup.lock"
flock -n 9 || { DONE=1; log "another backup run is active; skipping"; alert "skipped: a previous backup run still holds the lock" || true; exit 1; }
# Any unexpected death (a bug, a signal, an unset variable) must not be silent.
trap 'if [ "$DONE" != 1 ]; then fail "backup script exited unexpectedly"; fi' EXIT

# Old aborted runs leave .partial files that no other rule would ever delete.
find "$DIR" -maxdepth 1 -name 'db-*.sql.gz.partial' -mtime +1 -delete 2>/dev/null || true

# 1. dump + compress (pipefail makes either side failing fail the whole pipeline)
# timeout runs INSIDE the container so it kills pg_dump itself, not just the docker client.
docker exec "$DB_CONTAINER" timeout "$DUMP_TIMEOUT" pg_dump -U postgres -d "$DB" --no-owner | gzip -9 > "$FILE.partial" || fail "pg_dump or gzip returned an error (or ran past ${DUMP_TIMEOUT}s)"

# 2. verify: valid gzip, not tiny, and the dump ran to completion
gzip -t "$FILE.partial" 2>/dev/null || fail "dump is not a valid gzip file"
SIZE=$(stat -c %s "$FILE.partial")
[ "$SIZE" -gt "$MIN_BYTES" ] || fail "dump is suspiciously small (${SIZE} bytes)"
gunzip -c "$FILE.partial" | tail -n 5 | grep -q "PostgreSQL database dump complete" || fail "dump is truncated (no completion marker)"
mv "$FILE.partial" "$FILE" || fail "could not finalize the dump file"

# 3. off-box copy to R2, verified by size
docker cp "$FILE" "$API_CONTAINER:/tmp/$NAME" >/dev/null || fail "could not copy the dump into the app container"
docker exec "$API_CONTAINER" python -c '
import os, sys, boto3
from botocore.config import Config
name = sys.argv[1]; path = "/tmp/" + name
s3 = boto3.client("s3", endpoint_url="https://%s.r2.cloudflarestorage.com" % os.environ["R2_ACCOUNT_ID"],
                  aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                  region_name="auto",
                  config=Config(request_checksum_calculation="when_required", response_checksum_validation="when_required"))
key = "db-backups/" + name
s3.upload_file(path, os.environ["R2_BUCKET_NAME"], key)
head = s3.head_object(Bucket=os.environ["R2_BUCKET_NAME"], Key=key)
assert head["ContentLength"] == os.path.getsize(path), "uploaded size mismatch"
os.remove(path)
' "$NAME" || fail "upload to R2 failed (the local copy is kept)"

# 4. prune local copies: 14 days for daily dumps, 60 days for Sundays. Only ever touches db-*.sql.gz.
for f in "$DIR"/db-*.sql.gz; do
  [ -e "$f" ] || continue
  day=$(basename "$f" | sed -E 's/^db-([0-9]{8}).*/\1/')
  age=$(( ( $(date -u +%s) - $(stat -c %Y "$f") ) / 86400 ))
  dow=$(date -u -d "$day" +%u 2>/dev/null || echo 0)
  if [ "$age" -gt 60 ] || { [ "$age" -gt 14 ] && [ "$dow" != "7" ]; }; then rm -f "$f"; log "pruned $(basename "$f")"; fi
done

DONE=1
log "ok $NAME $((SIZE/1024)) KB (local + R2 db-backups/$NAME)"
