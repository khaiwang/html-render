#!/usr/bin/env bash
# Dispatch the normal (rich, LLM-templated) narrative render in the background,
# optionally cross-linking it to a related page (e.g. the diff for the same
# turn).
#
#   narrative-render.sh <plugin_dir> <out_html> <url> <transcript> \
#                       [related_url] [related_label]
#
# The LLM renderer (confined to Read/Write) writes the rich plan/review page
# exactly as a normal /render-plan would. If a related page is given, once the
# file is written we deterministically inject a small cross-link banner near
# the top — so the two pages link to each other without relying on the LLM.
set -u

PLUGIN_DIR="$1"; OUT="$2"; URL="$3"; TRANSCRIPT="$4"
RELATED_URL="${5:-}"; RELATED_LABEL="${6:-}"

command -v claude >/dev/null 2>&1 || exit 0

PROMPT="You are the html-renderer subagent. Read the instructions at $PLUGIN_DIR/agents/html-renderer.md.

Source: the Claude Code transcript at $TRANSCRIPT (read the last assistant turn).
Mode: narrative
Output: $OUT
Server port: ${HTML_RENDER_PORT:-7777}
Plugin dir: $PLUGIN_DIR

The server is already running; you do not need to start it.
You have ONLY Read and Write tools — generate the HTML, write it to the output path, and print the URL.

Print exactly one line on success: rendered: $URL"

(
  printf '%s' "$PROMPT" | HTML_RENDER_CHILD=1 claude -p \
    --permission-mode default \
    --allowedTools "Read Write Edit Glob Grep" >/dev/null 2>&1

  # Cross-link banner: inject after <body...> once the file exists.
  if [ -n "$RELATED_URL" ] && [ -f "$OUT" ]; then
    RELATED_URL="$RELATED_URL" RELATED_LABEL="${RELATED_LABEL:-Related →}" \
      python3 - "$OUT" <<'PY'
import os, re, sys, html
path = sys.argv[1]
url = html.escape(os.environ["RELATED_URL"], quote=True)
label = html.escape(os.environ["RELATED_LABEL"])
banner = (
    '<div style="max-width:880px;margin:1rem auto -0.5rem;padding:0 1.5rem;'
    'font:14px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif">'
    f'<a href="{url}" style="display:inline-block;padding:.4rem .8rem;'
    'border:1px solid rgba(101,116,205,.5);border-radius:6px;'
    'background:rgba(101,116,205,.1);color:inherit;text-decoration:none">'
    f'{label}</a></div>'
)
try:
    s = open(path, encoding="utf-8").read()
    if "html-render-xref" not in s:
        s2 = re.sub(r"(<body[^>]*>)", r"\1\n" + banner.replace("<div ", '<div class="html-render-xref" ', 1), s, count=1)
        if s2 != s:
            open(path, "w", encoding="utf-8").write(s2)
except Exception:
    pass
PY
  fi
) >/dev/null 2>&1 &
disown 2>/dev/null || true
