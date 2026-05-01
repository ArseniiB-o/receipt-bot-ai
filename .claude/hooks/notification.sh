#!/usr/bin/env bash
# Claude Logger — Notification hook

set -euo pipefail

LOG_DIR=".claude/logs"
SESSION_ID_FILE="${LOG_DIR}/.current_session_id"

SESSION_ID="unknown"
[[ -f "$SESSION_ID_FILE" ]] && SESSION_ID=$(cat "$SESSION_ID_FILE")

LOG_FILE=$(ls -t "${LOG_DIR}"/session-*.jsonl 2>/dev/null | head -1 || echo "")
[[ -z "$LOG_FILE" ]] && exit 0

PAYLOAD=$(cat)
MESSAGE=$(echo "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message',''))" 2>/dev/null || echo "")
LEVEL=$(echo "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('level','info'))" 2>/dev/null || echo "info")

TS=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
MACHINE=$(hostname)

MSG_ESCAPED=$(python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" <<< "$MESSAGE" 2>/dev/null || echo '""')
EVENT="{\"ts\":\"${TS}\",\"session\":\"${SESSION_ID}\",\"machine\":\"${MACHINE}\",\"type\":\"NOTIFICATION\",\"data\":{\"message\":${MSG_ESCAPED},\"level\":\"${LEVEL}\"}}"
echo "$EVENT" >> "$LOG_FILE"
