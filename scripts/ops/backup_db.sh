#!/bin/bash
# Nightly Ad Builder database backup. Runs ON THE VPS from the ubuntu user's crontab.
#   pg_dump -> gzip -> verify the dump is complete -> copy off-box to R2 -> prune old local copies.
# Any failure (including an unexpected exit) DMs Steve via the app's Slack service (same path as the Drive alerts)
# and exits non-zero. Installed at /home/ubuntu/bin/backup_db.sh, deliberately OUTSIDE the git checkout so a deploy
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

# One run at a time.
exec 9>"$DIR/.backup.lock"
flock -n 9 || { log "another backup run is active; skipping"; DONE=1; exit 0; }

fail() {
  DONE=1   # stop the EXIT trap from alerting a second time
  log "FAILED: $1"
  rm -f "$FILE.partial"
  docker exec "$API_CONTAINER" rm -f "/tmp/$NAME" >/dev/null 2>&1 || true
  docker exec "$API_CONTAINER" python -c '
import sys
from app.services.slack_service import send_drive_sync_alert
ok = send_drive_sync_alert(summary=sys.argv[1], detail="Nightly pg_dump backup on the VPS. See /home/ubuntu/backups/backup.log", headline="Ad Builder DB backup failed")
print("failure alert sent:", ok)
' "$1" 2>&1 | tail -n 3 || log "could not send failure alert"
  exit 1
}
# Any unexpected death (a bug, a signal, an unset variable) must not be silent.
trap 'if [ "$DONE" != 1 ]; then fail "backup script exited unexpectedly"; fi' EXIT

# Old aborted runs leave .partial files that no other rule would ever delete.
find "$DIR" -maxdepth 1 -name 'db-*.sql.gz.partial' -mtime +1 -delete 2>/dev/null || true

# 1. dump + compress (pipefail makes either side failing fail the whole pipeline)
docker exec "$DB_CONTAINER" pg_dump -U postgres -d "$DB" --no-owner | gzip -9 > "$FILE.partial" || fail "pg_dump or gzip returned an error"

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
