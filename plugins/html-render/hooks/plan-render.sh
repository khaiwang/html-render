#!/usr/bin/env bash
# PreToolUse hook matching ExitPlanMode: render the plan the moment Claude
# presents it (before you approve), since the plan lives in the tool-call input
# — which the Stop classifier never sees — and the turn doesn't "Stop" while it
# awaits your decision. We render here and ALWAYS allow the tool to proceed.
set -u

# Never recurse: the render subagent is itself a `claude -p`; if it ever hits a
# plan tool, don't re-render.
if [ -n "${HTML_RENDER_CHILD:-}" ]; then
  exit 0
fi

INPUT="$(cat)"
PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=../lib/session-path.sh
. "$PLUGIN_DIR/lib/session-path.sh"

TOOL="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("tool_name",""))
except Exception: pass')"
[ "$TOOL" = "ExitPlanMode" ] || exit 0

TRANSCRIPT="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("transcript_path",""))
except Exception: pass')"

STATE_DIR="$(hr_state_dir)"; mkdir -p "$STATE_DIR"
LOG="$STATE_DIR/.stop-hook.log"
echo "[$(date -Iseconds)] PreToolUse ExitPlanMode transcript=${TRANSCRIPT:-<none>}" >>"$LOG"

command -v claude >/dev/null 2>&1 || exit 0
bash "$PLUGIN_DIR/server/start.sh" >>"$STATE_DIR/.server.log" 2>&1 || true
PORT="${HTML_RENDER_PORT:-7777}"

IFS=$'\t' read -r OUT URL T < <(hr_new_output "$TRANSCRIPT" "plan" "$PORT")

# Build the renderer source: the plan (from the tool input) as the turn to
# render, plus the eliciting prompt (last genuine human message in the
# transcript). The plan is NOT yet in the transcript at PreToolUse time, so it
# must come from the tool input.
SRC="${OUT%.html}.source.md"
printf '%s' "$INPUT" | SRC="$SRC" TRANSCRIPT="$T" python3 -c '
import json, sys, os
d = json.load(sys.stdin)
plan = (d.get("tool_input") or {}).get("plan", "") or ""
transcript = os.environ["TRANSCRIPT"]
prompt = ""
try:
    ev = [json.loads(l) for l in open(transcript, errors="replace") if l.strip()]
    def role(e): return e.get("role") or (e.get("message") or {}).get("role")
    for e in reversed(ev):
        if role(e) != "user" or e.get("isMeta"):
            continue
        c = (e.get("message") or e).get("content")
        if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
            continue
        prompt = c if isinstance(c, str) else "".join(
            x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
        prompt = prompt.strip()
        if prompt and not prompt.startswith("<"):
            break
except Exception:
    pass
out = os.environ["SRC"]
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write("# Eliciting prompt\n\n" + (prompt or "(none)") +
            "\n\n---\n\n# Assistant turn to render\n\n" + plan + "\n")
'

HTML_RENDER_SOURCE="$SRC" bash "$PLUGIN_DIR/lib/narrative-render.sh" \
  "$PLUGIN_DIR" "$OUT" "$URL" "$T" >>"$STATE_DIR/.renderer.log" 2>&1
echo "[$(date -Iseconds)]   → dispatched plan render out=$OUT" >>"$LOG"

# Allow the tool to proceed (no JSON on stdout = default allow).
exit 0
