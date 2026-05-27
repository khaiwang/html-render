#!/usr/bin/env bash
# Idempotent start: only launch if not already bound to the port.
set -u

PORT="${HTML_RENDER_PORT:-7777}"
DIR="${HTML_RENDER_DIR:-$HOME/.html-render}"
PID_FILE="$DIR/.server.pid"
LOG_FILE="$DIR/.server.log"

mkdir -p "$DIR"

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

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
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
