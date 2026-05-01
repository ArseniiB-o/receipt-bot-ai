#!/usr/bin/env bash
# Claude Logger — PostToolUse hook
# Reads hook payload from stdin, appends TOOL_USE + TOOL_RESULT to session JSONL

set -euo pipefail

LOG_DIR=".claude/logs"
SESSION_ID_FILE="${LOG_DIR}/.current_session_id"

[[ -d "$LOG_DIR" ]] || mkdir -p "$LOG_DIR"

# Read hook payload from stdin
PAYLOAD=$(cat)

TOOL_NAME=$(echo "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name','unknown'))" 2>/dev/null || echo "unknown")
TOOL_INPUT=$(echo "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('tool_input',{})))" 2>/dev/null || echo "{}")
TOOL_OUTPUT=$(echo "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('tool_response',''); s=str(r)[:2000]; print(s)" 2>/dev/null || echo "")
TOOL_SUCCESS=$(echo "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print('true' if not d.get('is_error') else 'false')" 2>/dev/null || echo "true")

SESSION_ID="unknown"
[[ -f "$SESSION_ID_FILE" ]] && SESSION_ID=$(cat "$SESSION_ID_FILE")

LOG_FILE=$(ls -t "${LOG_DIR}"/session-*.jsonl 2>/dev/null | head -1 || echo "")
[[ -z "$LOG_FILE" ]] && exit 0

TS=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
MACHINE=$(hostname)

# Escape strings for JSON
escape_json() {
  python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" <<< "$1" 2>/dev/null || echo '""'
}

TOOL_OUTPUT_ESC=$(escape_json "$TOOL_OUTPUT")
TOOL_INPUT_SAFE=$(echo "$TOOL_INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d))" 2>/dev/null || echo '{}')

TOOL_USE_EVENT="{\"ts\":\"${TS}\",\"session\":\"${SESSION_ID}\",\"machine\":\"${MACHINE}\",\"type\":\"TOOL_USE\",\"data\":{\"tool\":\"${TOOL_NAME}\",\"input\":${TOOL_INPUT_SAFE}}}"
TOOL_RESULT_EVENT="{\"ts\":\"${TS}\",\"session\":\"${SESSION_ID}\",\"machine\":\"${MACHINE}\",\"type\":\"TOOL_RESULT\",\"data\":{\"tool\":\"${TOOL_NAME}\",\"output\":${TOOL_OUTPUT_ESC},\"success\":${TOOL_SUCCESS}}}"

echo "$TOOL_USE_EVENT" >> "$LOG_FILE"
echo "$TOOL_RESULT_EVENT" >> "$LOG_FILE"
