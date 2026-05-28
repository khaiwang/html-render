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

PLUGIN_DIR="$1"; OUT="$2"; URL="$3"; TRANSCRIPT="${4:-}"
PYW="$PLUGIN_DIR/lib/render_walkthrough.py"
REPO="${PWD:-$(pwd)}"

# Stage 1 — placeholder now.
python3 "$PYW" --out "$OUT" --url "$URL" --transcript "$TRANSCRIPT" --placeholder

command -v claude >/dev/null 2>&1 || exit 0

SEG="${OUT%.html}.segments.json"
PROMPT="The transcript at $TRANSCRIPT ends with an assistant 'code walkthrough' — prose that explains source code, usually in sections that reference files and line ranges. Your job: turn it into aligned segments.

Steps:
1. Read that last assistant turn to get the walkthrough prose and its section structure.
2. For each section, find the source file and the exact line range it covers. READ the referenced files (paths are relative to $REPO) to get accurate, current line numbers — do not trust line numbers in the prose blindly; verify against the file.
3. Output ONLY a JSON array, in reading order, of objects:
   {\"file\": \"<path relative to repo>\", \"start\": <int>, \"end\": <int>, \"title\": \"<short section heading>\", \"note\": \"<the section's walkthrough prose, as markdown — reuse the existing text>\"}
No prose outside the JSON. If a section references no specific code, use the most relevant range you can find."

(
  printf '%s' "$PROMPT" | HTML_RENDER_CHILD=1 claude -p \
    --permission-mode default --allowedTools "Read Grep Glob" >"$SEG" 2>/dev/null
  if [ -s "$SEG" ]; then
    python3 "$PYW" --segments "$SEG" --out "$OUT" --url "$URL" \
      --repo "$REPO" --transcript "$TRANSCRIPT"
  fi
) >/dev/null 2>&1 &
disown 2>/dev/null || true
