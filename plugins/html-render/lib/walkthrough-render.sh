#!/usr/bin/env bash
# Render a code walkthrough as a two-column page (code | walkthrough).
#
#   walkthrough-render.sh <plugin_dir> <out_html> <url> <transcript>
#
# Stage 1 (synchronous): write a "generating…" placeholder so the URL works.
# Stage 2 (background): a capable `claude -p` agent (Read/Grep/Glob) reads the
# walkthrough turn AND the referenced source files, and emits a JSON array of
# segments {file,start,end,title,note} reusing the turn's prose. Then
# render_walkthrough.py slices the real files into the code column and lays the
# prose beside it. The LLM picks boundaries/text; Python owns code + layout.
set -u

# ---- Stage-2 worker: re-invoked as `bash "$0" __bg ...` under setsid so the
# segmenting render runs in its OWN session (no Stop-hook process-group stall;
# survives the session ending). ----
if [ "${1:-}" = "__bg" ]; then
  PLUGIN_DIR="$2"; OUT="$3"; URL="$4"; TRANSCRIPT="${5:-}"; REPO="${6:-$PWD}"
  PYW="$PLUGIN_DIR/lib/render_walkthrough.py"
  SEG="${OUT%.html}.segments.json"; RLOG="${OUT%.html}.render.log"
  echo "[$(date -Iseconds)] walkthrough stage 2 → $URL"
  MODEL="${HTML_RENDER_MODEL:-haiku}"
  printf '%s' "${HTML_RENDER_PROMPT:-}" | HTML_RENDER_CHILD=1 claude -p \
    ${MODEL:+--model "$MODEL"} --permission-mode default --allowedTools "Read Grep Glob" >"$SEG" 2>>"$RLOG"
  if [ -s "$SEG" ]; then
    python3 "$PYW" --segments "$SEG" --out "$OUT" --url "$URL" \
      --repo "$REPO" --transcript "$TRANSCRIPT"
    echo "[$(date -Iseconds)] walkthrough stage 2: rendered segments"
  else
    echo "[$(date -Iseconds)] walkthrough stage 2 FAILED: no segments"
  fi
  exit 0
fi

PLUGIN_DIR="$1"; OUT="$2"; URL="$3"; TRANSCRIPT="${4:-}"
PYW="$PLUGIN_DIR/lib/render_walkthrough.py"
REPO="${PWD:-$(pwd)}"

# Stage 1 — placeholder now.
python3 "$PYW" --out "$OUT" --url "$URL" --transcript "$TRANSCRIPT" --placeholder

command -v claude >/dev/null 2>&1 || exit 0

# Extract the last turn to a tiny file (the full transcript is often multi-MB).
SRC="${OUT%.html}.source.md"
python3 "$PLUGIN_DIR/lib/extract_turn.py" "$TRANSCRIPT" "$SRC" >/dev/null 2>&1 || SRC="$TRANSCRIPT"

SEG="${OUT%.html}.segments.json"
PROMPT="The file $SRC contains an assistant 'code walkthrough' — prose that explains source code, usually in sections that reference files and line ranges. Your job: turn it into aligned segments.

The session worked in $REPO, but the actual file may live in a git worktree or subdirectory — use Grep/Glob to LOCATE the real file before reading it.

Steps:
1. Read $SRC to get the walkthrough prose and its section structure (do NOT read the full transcript).
2. For each section, find the source file and READ it to get accurate, current line numbers — do not trust line numbers in the prose blindly; verify against the file.
3. Output ONLY a JSON array, in reading order, of objects:
   {\"file\": \"<ABSOLUTE path to the file you actually read>\", \"start\": <int>, \"end\": <int>, \"title\": \"<short section heading>\", \"note\": \"<the section's walkthrough prose, as markdown — reuse the existing text>\"}
The \"file\" MUST be the absolute path you opened (e.g. /disk/u/.../worktrees/x/src/...py), so the renderer can find it regardless of cwd. No prose outside the JSON. If a section references no specific code, omit \"file\"/\"start\"/\"end\" and just give title+note."

RLOG="${OUT%.html}.render.log"
if command -v setsid >/dev/null 2>&1; then
  HTML_RENDER_PROMPT="$PROMPT" setsid bash "$0" __bg \
    "$PLUGIN_DIR" "$OUT" "$URL" "$TRANSCRIPT" "$REPO" </dev/null >>"$RLOG" 2>&1 &
else
  HTML_RENDER_PROMPT="$PROMPT" bash "$0" __bg \
    "$PLUGIN_DIR" "$OUT" "$URL" "$TRANSCRIPT" "$REPO" </dev/null >>"$RLOG" 2>&1 &
fi
disown 2>/dev/null || true
