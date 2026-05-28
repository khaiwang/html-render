#!/usr/bin/env bash
# Stop hook: classifies the last assistant turn and dispatches the
# html-renderer in the background if it's worth rendering. Waits briefly
# (only when needed) for the transcript file to finish flushing, since the
# Stop event can fire a few ms before the final assistant message is written.
set -u

# Never recurse. The html-renderer worker is itself a `claude -p` process, so
# when it finishes its OWN Stop event re-enters this hook — which would render
# the renderer's session (titled with the subagent prompt) and loop. The
# dispatcher sets HTML_RENDER_CHILD=1 on the worker so we bail here.
if [ -n "${HTML_RENDER_CHILD:-}" ]; then
  exit 0
fi

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

def msg_text(e):
    content = (e.get('message') or e).get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(c.get('text', '') for c in content
                       if isinstance(c, dict) and c.get('type') == 'text')
    return ''

def load_turn():
    # Read the transcript and return (assistant_text, tool_calls, user_prompt)
    # for the turn following the last genuine human message.
    try:
        with open(path) as f:
            events = [json.loads(line) for line in f if line.strip()]
    except Exception:
        return '', [], ''
    last_user = -1
    for i in range(len(events) - 1, -1, -1):
        if is_human(events[i]):
            last_user = i
            break
    prompt = msg_text(events[last_user]) if last_user >= 0 else ''
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
    return '\n'.join(text_chunks).strip(), tool_calls, prompt

# The Stop event can fire a few ms before the final assistant message is
# flushed to the transcript. Poll until the turn's assistant text is present
# AND stable between two reads (so we classify the whole turn, not a partial
# one). Returns fast when already complete; caps the wait at ~3s for the rare
# turn that ends without any assistant text.
text, tool_calls, prompt = '', [], ''
prev_len = -1
for _ in range(15):
    text, tool_calls, prompt = load_turn()
    if text and len(text) == prev_len:
        break
    prev_len = len(text)
    time.sleep(0.2)

if len(text) < 200:
    print('skip'); sys.exit(0)

# Walkthrough: the user asked to be walked through code. Detected from the
# eliciting prompt; a manual /walkthrough command exists if this misses.
if re.search(r'\bwalk\s+(?:me\s+|us\s+)?through\b|\bwalk-?through\b', prompt, re.IGNORECASE):
    print('walkthrough'); sys.exit(0)

# Structural signals that a turn carries a substantial explanation.
headings = len(re.findall(r'^\s*#{1,3}\s+\S', text, re.MULTILINE))
list_items = len(re.findall(r'^\s*(?:\d+\.|[-*])\s', text, re.MULTILINE))
fences = text.count('```') // 2
narrative_worthy = (len(text) >= 1500 or headings >= 2 or list_items >= 5 or fences >= 3)

# Edits → diff. If the same turn ALSO carries a real explanation, emit
# 'diff+narr' so the hook renders BOTH (a diff page and a normal narrative
# page, cross-linked) instead of discarding the prose.
if any(t in ('Edit', 'Write', 'NotebookEdit', 'MultiEdit') for t in tool_calls):
    print('diff+narr' if narrative_worthy else 'diff'); sys.exit(0)

if narrative_worthy:
    print('narrative'); sys.exit(0)

print('skip')
PY
)"

log "  → mode=$MODE"

if [ "$MODE" = "skip" ] || [ -z "$MODE" ]; then
  exit 0
fi

# Ensure server is up (idempotent).
bash "$PLUGIN_DIR/server/start.sh" >>"$STATE_DIR/.server.log" 2>&1 || true

PORT="${HTML_RENDER_PORT:-7777}"
HAS_CLAUDE=0; command -v claude >/dev/null 2>&1 && HAS_CLAUDE=1

# render_diff_page <out> <url> [related_url] [related_label]
render_diff_page() {
  local out="$1" url="$2" diff_file="${1%.html}.diff"
  {
    echo "=== git diff --stat HEAD ==="; git diff --stat HEAD
    echo "=== git diff (unstaged working tree) ==="; git diff
    echo "=== git diff --cached (staged) ==="; git diff --cached
  } >"$diff_file" 2>/dev/null || true
  bash "$PLUGIN_DIR/lib/diff-explain.sh" \
    "$PLUGIN_DIR" "$diff_file" "$out" "$url" "$TRANSCRIPT" "${3:-}" "${4:-}" \
    >>"$STATE_DIR/.renderer.log" 2>&1
}

if [ "$MODE" = "walkthrough" ]; then
  # Two-column code walkthrough: placeholder now, then a capable agent
  # segments the walkthrough against the real files and Python renders it.
  IFS=$'\t' read -r OUT URL _T < <(hr_new_output "$TRANSCRIPT" "walkthrough" "$PORT")
  bash "$PLUGIN_DIR/lib/walkthrough-render.sh" \
    "$PLUGIN_DIR" "$OUT" "$URL" "$TRANSCRIPT" >>"$STATE_DIR/.renderer.log" 2>&1
  log "  → walkthrough placeholder rendered; segments generating out=$OUT"
  exit 0
fi

if [ "$MODE" = "diff+narr" ] && [ "$HAS_CLAUDE" = "1" ]; then
  # Turn had BOTH edits and a real explanation → two cross-linked pages: a
  # deterministic diff page and a normal (rich, LLM-templated) narrative page.
  # Compute both URLs FIRST so each page can link the other.
  IFS=$'\t' read -r D_OUT D_URL _T < <(hr_new_output "$TRANSCRIPT" "diff" "$PORT")
  IFS=$'\t' read -r N_OUT N_URL _T < <(hr_new_output "$TRANSCRIPT" "narrative" "$PORT")
  render_diff_page "$D_OUT" "$D_URL" "$N_URL" "Session summary →"
  bash "$PLUGIN_DIR/lib/narrative-render.sh" \
    "$PLUGIN_DIR" "$N_OUT" "$N_URL" "$TRANSCRIPT" "$D_URL" "← Code diff" \
    >>"$STATE_DIR/.renderer.log" 2>&1
  log "  → diff+narrative rendered: diff=$D_URL narrative=$N_URL"
  exit 0
fi

if [ "$MODE" = "diff" ] || [ "$MODE" = "diff+narr" ]; then
  # Plain diff (or diff+narr with no claude available for the narrative page).
  IFS=$'\t' read -r OUT URL _T < <(hr_new_output "$TRANSCRIPT" "diff" "$PORT")
  render_diff_page "$OUT" "$URL"
  log "  → rendered diff (deterministic; explanations in background) out=$OUT"
  exit 0
fi

# Narrative mode: dispatch the confined LLM renderer in the background.
if [ "$HAS_CLAUDE" != "1" ]; then
  log "  → 'claude' CLI not on PATH; cannot dispatch narrative renderer"
  exit 0
fi
IFS=$'\t' read -r OUT URL _T < <(hr_new_output "$TRANSCRIPT" "narrative" "$PORT")
bash "$PLUGIN_DIR/lib/narrative-render.sh" \
  "$PLUGIN_DIR" "$OUT" "$URL" "$TRANSCRIPT" >>"$STATE_DIR/.renderer.log" 2>&1
log "  → dispatched narrative renderer out=$OUT"
exit 0
