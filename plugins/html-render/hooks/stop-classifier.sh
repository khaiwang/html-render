#!/usr/bin/env bash
# Stop hook: classifies the last assistant turn and dispatches the
# html-renderer in the background if it's worth rendering. Waits briefly
# (only when needed) for the transcript file to finish flushing, since the
# Stop event can fire a few ms before the final assistant message is written.
set -u

INPUT="$(cat)"

# Resolve plugin dir (parent of this script) and load shared path helpers.
PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=../lib/session-path.sh
. "$PLUGIN_DIR/lib/session-path.sh"

STATE_DIR="$(hr_state_dir)"
LOG="$STATE_DIR/.stop-hook.log"
mkdir -p "$STATE_DIR"

log() {
  echo "[$(date -Iseconds)] $*" >>"$LOG"
}

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
import json, sys, re, time

path = sys.argv[1]

def role_of(e):
    return e.get('role') or (e.get('message') or {}).get('role')

def is_human(e):
    # A genuine human turn. Claude Code records tool results as role
    # 'user' too, so we must exclude those — otherwise the "last user
    # message" boundary lands on the final tool result and we only see
    # the assistant text after the last tool call, not the whole turn.
    if role_of(e) != 'user' or e.get('isMeta'):
        return False
    content = (e.get('message') or e).get('content')
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        types = {c.get('type') for c in content if isinstance(c, dict)}
        return 'tool_result' not in types
    return False

def load_turn():
    # Read the transcript and return (assistant_text, tool_calls) for the
    # turn following the last genuine human message.
    try:
        with open(path) as f:
            events = [json.loads(line) for line in f if line.strip()]
    except Exception:
        return '', []
    last_user = -1
    for i in range(len(events) - 1, -1, -1):
        if is_human(events[i]):
            last_user = i
            break
    since = events[last_user + 1:] if last_user >= 0 else events
    text_chunks, tool_calls = [], []
    for e in since:
        if role_of(e) != 'assistant':
            continue
        content = (e.get('message') or e).get('content')
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
    return '\n'.join(text_chunks).strip(), tool_calls

# The Stop event can fire a few ms before the final assistant message is
# flushed to the transcript. Poll until the turn's assistant text is present
# AND stable between two reads (so we classify the whole turn, not a partial
# one). Returns fast when already complete; caps the wait at ~3s for the rare
# turn that ends without any assistant text.
text, tool_calls = '', []
prev_len = -1
for _ in range(15):
    text, tool_calls = load_turn()
    if text and len(text) == prev_len:
        break
    prev_len = len(text)
    time.sleep(0.2)

if len(text) < 200:
    print('skip'); sys.exit(0)

if any(t in ('Edit', 'Write', 'NotebookEdit', 'MultiEdit') for t in tool_calls):
    print('diff'); sys.exit(0)

# Structural signals that a turn is substantial enough to render.
headings = len(re.findall(r'^\s*#{1,3}\s+\S', text, re.MULTILINE))
list_items = len(re.findall(r'^\s*(?:\d+\.|[-*])\s', text, re.MULTILINE))
fences = text.count('```') // 2

if len(text) >= 1500 or headings >= 2 or list_items >= 5 or fences >= 3:
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
bash "$PLUGIN_DIR/server/start.sh" >>"$STATE_DIR/.server.log" 2>&1 || true

PORT="${HTML_RENDER_PORT:-7777}"
# Output lands in this session's directory; URL carries the project/session path.
IFS=$'\t' read -r OUT URL < <(hr_new_output "$TRANSCRIPT" "$MODE" "$PORT")

# For diff mode, pre-compute the diff HERE so the renderer never needs a
# shell. The renderer runs confined to read/write tools (see --allowedTools
# below), so it cannot run git — or anything else — itself.
SOURCE_LINE="Source: the Claude Code transcript at $TRANSCRIPT (read the last assistant turn)."
if [ "$MODE" = "diff" ]; then
  DIFF_FILE="${OUT%.html}.diff"
  {
    echo "=== git diff --stat HEAD ==="
    git diff --stat HEAD
    echo "=== git diff (unstaged working tree) ==="
    git diff
    echo "=== git diff --cached (staged) ==="
    git diff --cached
  } >"$DIFF_FILE" 2>/dev/null || true
  SOURCE_LINE="Source: a pre-computed git diff at $DIFF_FILE — just Read it. Do NOT run git or any shell command."
fi

# Compose the prompt for the background renderer. The agent file
# location is read from this plugin so users don't need any extra wiring.
PROMPT="You are the html-renderer subagent. Read the instructions at $PLUGIN_DIR/agents/html-renderer.md.

$SOURCE_LINE
Mode: $MODE
Output: $OUT
Server port: $PORT
Plugin dir: $PLUGIN_DIR

The server is already running; you do not need to start it.
You have ONLY Read and Write tools — generate the HTML, write it to the output path, and print the URL.

Print exactly one line on success: rendered: $URL"

# Detach fully — never block the session. Confine the renderer to read/write
# tools in default permission mode, so even if the parent session runs in
# bypass mode this unattended background agent cannot execute shell commands
# or reach the network, regardless of what untrusted text the transcript holds.
# Prompt goes via stdin: --allowedTools is variadic and would otherwise
# swallow a trailing positional prompt as a tool name.
printf '%s' "$PROMPT" | nohup claude -p \
  --permission-mode default \
  --allowedTools "Read Write Edit Glob Grep" \
  >>"$STATE_DIR/.renderer.log" 2>&1 &
RENDERER_PID=$!
disown 2>/dev/null || true

log "  → dispatched renderer pid=$RENDERER_PID out=$OUT"
exit 0
