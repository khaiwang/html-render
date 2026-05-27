#!/usr/bin/env bash
# Stop hook: classifies the last assistant turn and dispatches the
# html-renderer in the background if it's worth rendering. Exits in
# well under a second so the main session never feels blocked.
set -u

INPUT="$(cat)"
DIR="${HTML_RENDER_DIR:-$HOME/.html-render}"
LOG="$DIR/.stop-hook.log"
mkdir -p "$DIR"

log() {
  echo "[$(date -Iseconds)] $*" >>"$LOG"
}

# Resolve plugin dir (parent of this script).
PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"

TRANSCRIPT="$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('transcript_path', ''))
except Exception:
    pass
")"

log "fired transcript=${TRANSCRIPT:-<none>}"

if [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
  log "  → no readable transcript, skip"
  exit 0
fi

MODE="$(python3 - "$TRANSCRIPT" <<'PY'
import json, sys, re

path = sys.argv[1]
try:
    with open(path) as f:
        events = [json.loads(line) for line in f if line.strip()]
except Exception:
    print('skip'); sys.exit(0)

def role_of(e):
    return e.get('role') or (e.get('message') or {}).get('role')

# Find last user-message boundary.
last_user = -1
for i in range(len(events) - 1, -1, -1):
    e = events[i]
    if role_of(e) == 'user' and not e.get('isMeta'):
        last_user = i
        break
since = events[last_user + 1:] if last_user >= 0 else events

text_chunks = []
tool_calls = []
for e in since:
    if role_of(e) != 'assistant':
        continue
    msg = e.get('message') or e
    content = msg.get('content')
    if isinstance(content, str):
        text_chunks.append(content)
    elif isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get('type') == 'text':
                text_chunks.append(c.get('text', ''))
            elif c.get('type') == 'tool_use':
                tool_calls.append(c.get('name', ''))

text = '\n'.join(text_chunks).strip()

if len(text) < 200:
    print('skip'); sys.exit(0)

if any(t in ('Edit', 'Write', 'NotebookEdit', 'MultiEdit') for t in tool_calls):
    print('diff'); sys.exit(0)

headers = re.findall(
    r'^\s*#{1,3}\s+(plan|summary|review|recap|architecture|design|implementation|analysis)',
    text, re.IGNORECASE | re.MULTILINE)
numbered = len(re.findall(r'^\s*\d+\.\s', text, re.MULTILINE))
fences = text.count('```') // 2

if headers or numbered >= 5 or fences >= 3:
    print('narrative'); sys.exit(0)

print('skip')
PY
)"

log "  → mode=$MODE"

if [ "$MODE" = "skip" ] || [ -z "$MODE" ]; then
  exit 0
fi

if ! command -v claude >/dev/null 2>&1; then
  log "  → 'claude' CLI not on PATH; cannot dispatch"
  exit 0
fi

# Ensure server is up (idempotent).
bash "$PLUGIN_DIR/server/start.sh" >>"$DIR/.server.log" 2>&1 || true

SLUG="$(date -u +%Y%m%dT%H%M%SZ)-$MODE"
OUT="$DIR/$SLUG.html"
PORT="${HTML_RENDER_PORT:-7777}"

# Compose the prompt for the background renderer. The agent file
# location is read from this plugin so users don't need any extra wiring.
PROMPT="You are the html-renderer subagent. Read the instructions at $PLUGIN_DIR/agents/html-renderer.md.

Source: transcript at $TRANSCRIPT
Mode: $MODE
Output: $OUT
Server port: $PORT
Plugin dir: $PLUGIN_DIR

For mode 'diff': run git diff against the working tree to capture what changed in this session.
For mode 'narrative': read the last assistant turn from the transcript.

Print exactly one line on success: rendered: http://localhost:$PORT/$(basename "$OUT")"

# Detach fully — never block the session.
nohup claude -p "$PROMPT" >>"$DIR/.renderer.log" 2>&1 &
RENDERER_PID=$!
disown 2>/dev/null || true

log "  → dispatched renderer pid=$RENDERER_PID out=$SLUG.html"
exit 0
