#!/usr/bin/env bash
# Claude Logger — PreSessionStart hook
# Creates new session JSONL log and injects prior vault context

set -euo pipefail

LOG_DIR=".claude/logs"
CONFIG_PATH="C:\Users\mole1\.claude\logger\config.json"
SESSION_ID_FILE="${LOG_DIR}/.current_session_id"

[[ -d "$LOG_DIR" ]] || mkdir -p "$LOG_DIR"

# Generate session ID
SESSION_ID=$(python3 -c "import random,string; print(''.join(random.choices(string.ascii_lowercase+string.digits, k=6)))" 2>/dev/null || date +%s | tail -c 7)
echo "$SESSION_ID" > "$SESSION_ID_FILE"

DATE=$(date -u +"%Y-%m-%d")
TS=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
MACHINE=$(hostname)
WORKING_DIR=$(pwd)

# Detect git branch
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

# Detect project name
PROJECT_NAME=""
REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
if [[ -n "$REMOTE" ]]; then
  PROJECT_NAME=$(basename "$REMOTE" .git 2>/dev/null || echo "")
fi
if [[ -z "$PROJECT_NAME" ]] && [[ -f "package.json" ]]; then
  PROJECT_NAME=$(python3 -c "import json; d=json.load(open('package.json')); print(d.get('name',''))" 2>/dev/null || echo "")
fi
if [[ -z "$PROJECT_NAME" ]]; then
  PROJECT_NAME=$(basename "$WORKING_DIR")
fi

LOG_FILE="${LOG_DIR}/session-${DATE}-${SESSION_ID}.jsonl"

# Write SESSION_START event
SESSION_START="{\"ts\":\"${TS}\",\"session\":\"${SESSION_ID}\",\"machine\":\"${MACHINE}\",\"type\":\"SESSION_START\",\"data\":{\"workingDir\":\"${WORKING_DIR}\",\"gitBranch\":\"${GIT_BRANCH}\",\"projectName\":\"${PROJECT_NAME}\"}}"
echo "$SESSION_START" > "$LOG_FILE"

# Try to read vault context
if command -v claude-logger &>/dev/null; then
  echo ""
  claude-logger vault last "$PROJECT_NAME" 2>/dev/null || true
  claude-logger vault pending "$PROJECT_NAME" --limit 5 2>/dev/null || true
elif [[ -n "$CONFIG_PATH" ]]; then
  # Fallback: try node directly
  node "$(dirname "$0")/../dist/index.js" vault last "$PROJECT_NAME" 2>/dev/null || true
fi
