#!/bin/bash
# Polls Ad Builder for unhandled launch incidents; runs one headless Claude Code
# investigation for the batch; DMs Steve the result. Plain script, zero tokens when idle.
set -uo pipefail
BASE="https://adbuilder-api.velocitymx.io/api/v1"
REPO="/Users/Steve1/Claude/AdBuilder"
DIR="$(cd "$(dirname "$0")" && pwd)"
LOCK="/tmp/adbuilder-incident-investigator.lock"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

mkdir "$LOCK" 2>/dev/null || { echo "$(date -u +%FT%TZ) already running"; exit 0; }
trap 'rmdir "$LOCK"' EXIT

TOKEN=$(security find-generic-password -a "$USER" -s adbuilder-incident-token -w 2>/dev/null) || { echo "no incident token in keychain"; exit 1; }
SLACK=$(security find-generic-password -a "$USER" -s bhm-slack-bot-token -w 2>/dev/null) || { echo "no slack token in keychain"; exit 1; }

dm() {
  python3 -c '
import json, sys
print(json.dumps({"channel": "U6M6033G9", "text": ":mag: *[Ad Builder incident]*\n" + sys.argv[1][:3500], "unfurl_links": False}))
' "$1" | curl -fsS -X POST https://slack.com/api/chat.postMessage \
      -H "Authorization: Bearer $SLACK" -H "Content-Type: application/json; charset=utf-8" -d @- >/dev/null
}

PENDING=$(curl -fsS -m 20 -H "X-Incident-Token: $TOKEN" "$BASE/launch-outcomes/pending") || { echo "$(date -u +%FT%TZ) poll failed"; exit 0; }
[ "$PENDING" = "[]" ] && exit 0

IDS=$(python3 -c "import json,sys;print(json.dumps({'ids':[r['id'] for r in json.loads(sys.argv[1])]}))" "$PENDING")
# Claim first: one incident, one run. A crashed run DMs the raw incident instead of re-looping.
curl -fsS -m 20 -X POST -H "X-Incident-Token: $TOKEN" -H "Content-Type: application/json" -d "$IDS" "$BASE/launch-outcomes/mark-investigated" >/dev/null || { echo "claim failed"; exit 0; }

cd "$REPO" && git pull --ff-only origin develop >/dev/null 2>&1
OUT=$(mktemp)
perl -e 'alarm shift; exec @ARGV' 2400 claude -p "$(cat "$DIR/prompt.md")
$PENDING" \
  --permission-mode acceptEdits --max-turns 80 \
  --allowedTools "Read" "Edit" "Write" "Grep" "Glob" "Agent" \
    "Bash(git:*)" "Bash(gh:*)" "Bash(ssh:*)" "Bash(curl:*)" "Bash(npx esbuild:*)" "Bash(python3:*)" "Bash(grep:*)" "Bash(ls:*)" \
  > "$OUT" 2>&1
RC=$?
if [ $RC -eq 0 ] && [ -s "$OUT" ]; then
  dm "$(cat "$OUT")"
else
  dm "Investigator run failed (exit $RC). Raw incidents: $(echo "$PENDING" | head -c 1500)"
fi
rm -f "$OUT"
