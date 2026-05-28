#!/usr/bin/env bash
# Render the normal (rich, LLM-templated) narrative — the SESSION SUMMARY page
# (what the problem was / what was done) — optionally cross-linked to a related
# page (e.g. the diff for the same turn).
#
#   narrative-render.sh <plugin_dir> <out_html> <url> <transcript> \
#                       [related_url] [related_label]
#
# Stage 1 (synchronous): write a themed "generating…" placeholder, so the page
# (and any link pointing at it) ALWAYS resolves — never a 404 while the LLM
# works or if it fails.
# Stage 2 (background): the confined LLM renderer (Read/Write) overwrites it
# with the rich plan/review page; then we inject the cross-link banner.
set -u

PLUGIN_DIR="$1"; OUT="$2"; URL="$3"; TRANSCRIPT="$4"
RELATED_URL="${5:-}"; RELATED_LABEL="${6:-}"

# Stage 1 — placeholder now (always leaves a valid page at OUT).
OUT="$OUT" RELATED_URL="$RELATED_URL" RELATED_LABEL="${RELATED_LABEL:-← Code diff}" \
python3 - <<'PY'
import os, html
out = os.environ["OUT"]
ru, rl = os.environ.get("RELATED_URL", ""), os.environ.get("RELATED_LABEL", "")
xref = ""
if ru:
    xref = (f'<div class="html-render-xref" style="margin:0 0 1.25rem">'
            f'<a href="{html.escape(ru, quote=True)}">{html.escape(rl)}</a></div>')
page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Session summary (generating…)</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;700&display=swap');
body {{ font-family:'Hanken Grotesk',ui-sans-serif,system-ui,sans-serif; background:#fafafa;
  color:#1a1a1f; max-width:880px; margin:3rem auto; padding:0 1.5rem; line-height:1.6; }}
@media (prefers-color-scheme: dark) {{ body {{ background:#161618; color:#e9e9ec; }} }}
a {{ color:#2563eb; }}
.banner {{ border:1px solid #e3e3e8; border-left:3px solid #2563eb; border-radius:0 8px 8px 0;
  padding:1rem 1.25rem; background:rgba(37,99,235,.06); }}
@media (prefers-color-scheme: dark) {{ .banner {{ border-color:rgba(255,255,255,.11); }} }}
</style></head><body>
{xref}
<div class="banner"><b>Generating the session summary…</b><br>
This page fills in automatically once the renderer finishes (about a minute). Refresh.</div>
</body></html>"""
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
PY

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

  # Cross-link banner: inject after <body...> once the LLM has (re)written the file.
  if [ -n "$RELATED_URL" ] && [ -f "$OUT" ]; then
    RELATED_URL="$RELATED_URL" RELATED_LABEL="${RELATED_LABEL:-← Code diff}" \
      python3 - "$OUT" <<'PY'
import os, re, sys, html
path = sys.argv[1]
url = html.escape(os.environ["RELATED_URL"], quote=True)
label = html.escape(os.environ["RELATED_LABEL"])
banner = (
    '<div class="html-render-xref" style="max-width:880px;margin:1rem auto -0.5rem;'
    'padding:0 1.5rem;font:14px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif">'
    f'<a href="{url}" style="display:inline-block;padding:.4rem .8rem;'
    'border:1px solid #e3e3e8;border-radius:6px;background:rgba(37,99,235,.08);'
    f'color:#2563eb;text-decoration:none">{label}</a></div>'
)
try:
    s = open(path, encoding="utf-8").read()
    if "html-render-xref" not in s:
        s2 = re.sub(r"(<body[^>]*>)", r"\1\n" + banner, s, count=1)
        if s2 != s:
            open(path, "w", encoding="utf-8").write(s2)
except Exception:
    pass
PY
  fi
) >/dev/null 2>&1 &
disown 2>/dev/null || true
