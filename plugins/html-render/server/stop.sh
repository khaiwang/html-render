#!/usr/bin/env bash
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib/session-path.sh
. "$SCRIPT_DIR/../lib/session-path.sh"
PID_FILE="$(hr_state_dir)/.server.pid"
if [ ! -f "$PID_FILE" ]; then
  echo "[html-render] no pid file at $PID_FILE; nothing to stop"
  exit 0
fi
pid=$(cat "$PID_FILE")
if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
  echo "[html-render] pid $pid not running; clearing pid file"
  rm -f "$PID_FILE"
  exit 0
fi
kill "$pid"
sleep 0.3
if kill -0 "$pid" 2>/dev/null; then
  kill -9 "$pid"
fi
rm -f "$PID_FILE"
echo "[html-render] stopped (was pid $pid)"
