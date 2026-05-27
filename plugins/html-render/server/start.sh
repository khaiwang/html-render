#!/usr/bin/env bash
# Idempotent start: only launch if not already bound to the port.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib/session-path.sh
. "$SCRIPT_DIR/../lib/session-path.sh"

PORT="${HTML_RENDER_PORT:-7777}"
DATA_DIR="$(hr_data_dir)"
STATE_DIR="$(hr_state_dir)"
PID_FILE="$STATE_DIR/.server.pid"
LOG_FILE="$STATE_DIR/.server.log"

mkdir -p "$DATA_DIR" "$STATE_DIR"

# One-time migration: sweep any flat pages from the old default location
# (~/.html-render) into a _legacy group so existing history isn't orphaned.
LEGACY_OLD="$HOME/.html-render"
if [ "$LEGACY_OLD" != "$DATA_DIR" ] && [ -d "$LEGACY_OLD" ]; then
  shopt -s nullglob
  old_pages=("$LEGACY_OLD"/*.html)
  shopt -u nullglob
  if [ "${#old_pages[@]}" -gt 0 ]; then
    mkdir -p "$DATA_DIR/_legacy"
    mv "${old_pages[@]}" "$DATA_DIR/_legacy/" 2>/dev/null || true
    echo "[html-render] migrated ${#old_pages[@]} legacy page(s) to $DATA_DIR/_legacy"
  fi
fi

if [ -f "$PID_FILE" ]; then
  pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "[html-render] already running (pid $pid) on port $PORT"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[html-render] port $PORT already in use by another process" >&2
  exit 1
fi

nohup python3 "$SCRIPT_DIR/server.py" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
disown 2>/dev/null || true
sleep 0.3
if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "[html-render] started (pid $(cat "$PID_FILE")) on port $PORT"
else
  echo "[html-render] failed to start — check $LOG_FILE" >&2
  exit 1
fi
