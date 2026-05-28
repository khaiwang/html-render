#!/usr/bin/env bash
# Render a diff to HTML, then (optionally) add the per-hunk explanation column.
#
#   diff-explain.sh <plugin_dir> <diff_file> <out_html> <url> <transcript> \
#                   [related_url] [related_label]
#
# Stage 1 (synchronous): render the side-by-side diff immediately so the URL
# works right away — deterministic, no LLM.
# Stage 2 (background): a capable `claude -p` EXPLORER agent — Read/Grep/Glob
# + read git context — actually investigates the repo (full changed files,
# callers, history), then returns one explanation per hunk (JSON array). It
# only produces text; Python owns the layout, so it can never misalign. It has
# NO Write/WebFetch, so even on a poisoned diff it cannot exfiltrate or clobber.
#
# Set HTML_RENDER_EXPLAIN=0 to skip stage 2 (pure before|after diff).
set -u

PLUGIN_DIR="$1"; DIFF="$2"; OUT="$3"; URL="$4"; TRANSCRIPT="${5:-}"
RELATED_URL="${6:-}"; RELATED_LABEL="${7:-Session summary →}"
PY="$PLUGIN_DIR/lib/render_diff.py"

REL_ARGS=()
[ -n "$RELATED_URL" ] && REL_ARGS=(--related-url "$RELATED_URL" --related-label "$RELATED_LABEL")

# Stage 1 — always produce a valid page now.
python3 "$PY" --diff "$DIFF" --out "$OUT" --url "$URL" --transcript "$TRANSCRIPT" "${REL_ARGS[@]}"

[ "${HTML_RENDER_EXPLAIN:-1}" = "0" ] && exit 0
command -v claude >/dev/null 2>&1 || exit 0
[ -s "$DIFF" ] || exit 0

# Stage 2 — background: generate explanations and re-render.
NHUNKS="$(grep -c '^@@' "$DIFF" 2>/dev/null || echo 0)"
[ "$NHUNKS" -gt 0 ] 2>/dev/null || exit 0
EXPL="${OUT%.html}.expl.json"
PROMPT="You are explaining a git diff. The diff is at $DIFF; it has $NHUNKS hunks (blocks starting with @@), in order across all files.

Investigate before you explain — don't guess from the diff alone:
- Read the full changed files for surrounding context.
- Grep/Glob for callers, definitions, and related code.
- Use git (log/blame/show) to understand intent and history.

Then, for EACH hunk in order, write ONE concise sentence saying what the change does AND why it matters. Output ONLY a JSON array of exactly $NHUNKS strings — no markdown, no keys, no other text."

(
  # Capable explorer: read + search + read-only-ish git, but no Write/WebFetch.
  printf '%s' "$PROMPT" | HTML_RENDER_CHILD=1 claude -p \
    --permission-mode default \
    --allowedTools "Read Grep Glob Bash(git *)" >"$EXPL" 2>/dev/null
  if [ -s "$EXPL" ]; then
    python3 "$PY" --diff "$DIFF" --out "$OUT" --url "$URL" \
      --transcript "$TRANSCRIPT" --explanations "$EXPL" "${REL_ARGS[@]}"
  fi
) >/dev/null 2>&1 &
disown 2>/dev/null || true
