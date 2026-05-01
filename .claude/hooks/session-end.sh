#!/usr/bin/env bash
# Claude Logger — PostSessionEnd hook
# Writes SESSION_END event and triggers Obsidian note generation

set -euo pipefail

LOG_DIR=".claude/logs"
SESSION_ID_FILE="${LOG_DIR}/.current_session_id"

[[ -d "$LOG_DIR" ]] || exit 0

SESSION_ID="unknown"
[[ -f "$SESSION_ID_FILE" ]] && SESSION_ID=$(cat "$SESSION_ID_FILE")

LOG_FILE=$(ls -t "${LOG_DIR}"/session-*.jsonl 2>/dev/null | head -1 || echo "")
[[ -z "$LOG_FILE" ]] && exit 0

TS=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
MACHINE=$(hostname)

SESSION_END="{\"ts\":\"${TS}\",\"session\":\"${SESSION_ID}\",\"machine\":\"${MACHINE}\",\"type\":\"SESSION_END\",\"data\":{\"duration\":0,\"messagesCount\":0,\"filesTouched\":0,\"commandsRun\":0,\"errorsCount\":0}}"
echo "$SESSION_END" >> "$LOG_FILE"

# Generate Obsidian note
if command -v claude-logger &>/dev/null; then
  claude-logger export --latest 2>/dev/null || echo "[claude-logger] Note generation failed (non-fatal)" >&2
elif [[ -f "$(dirname "$0")/../dist/index.js" ]]; then
  node "$(dirname "$0")/../dist/index.js" export --latest 2>/dev/null || true
fi
