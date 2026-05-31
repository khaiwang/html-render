#!/usr/bin/env bash
# Render the normal (rich, LLM-templated) narrative page — optionally
# cross-linked to a related page (e.g. the diff for the same turn).
#
#   narrative-render.sh <plugin_dir> <out_html> <url> <transcript> \
#                       [related_url] [related_label]
#
# Stage 1 (synchronous): write a themed "rendering…" placeholder, so the page
# (and any link pointing at it) ALWAYS resolves — never a 404 while the LLM
# works or if it fails.
# Stage 2 (background, DETACHED via setsid): the confined LLM renderer
# (Read/Write) overwrites the placeholder with the real page, then injects the
# cross-link banner. It runs in its OWN session so it (a) does not hold the Stop
# hook's process group — which would stall the interactive session until the
# multi-minute render finishes — and (b) survives the session ending instead of
# being reaped mid-render (which used to leave the placeholder stuck forever).
set -u

# ---- Stage-2 worker: re-invoked as `bash "$0" __bg ...` under setsid. ----
if [ "${1:-}" = "__bg" ]; then
  OUT="$2"; URL="$3"; RELATED_URL="${4:-}"; RELATED_LABEL="${5:-← Code diff}"
  RLOG="${OUT%.html}.render.log"
  echo "[$(date -Iseconds)] narrative stage 2 → $URL"
  # Render is a mechanical format-to-HTML task — default to the fastest model.
  # Override with HTML_RENDER_MODEL (e.g. sonnet or opus for higher quality).
  MODEL="${HTML_RENDER_MODEL:-haiku}"
  printf '%s' "${HTML_RENDER_PROMPT:-}" | HTML_RENDER_CHILD=1 claude -p \
    ${MODEL:+--model "$MODEL"} --permission-mode default \
    --allowedTools "Read Write Edit Glob Grep" >>"$RLOG" 2>&1
  rc=$?

  # If the renderer left our placeholder in place (errored / interrupted), don't
  # leave the page stuck on "Rendering…". Replace it with an honest failure page.
  if [ -f "$OUT" ] && grep -q 'html-render:placeholder' "$OUT"; then
    echo "[$(date -Iseconds)] narrative stage 2 FAILED (rc=$rc): placeholder not replaced; writing failure page"
    OUT="$OUT" python3 - <<'PY'
import os
out = os.environ["OUT"]
page = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Render didn't complete</title>
<style>body{font-family:'Hanken Grotesk',ui-sans-serif,system-ui,sans-serif;background:#f7f6f3;
color:#1d2230;max-width:760px;margin:3rem auto;padding:0 1.5rem;line-height:1.6}
.banner{border:1px solid #ecd9a8;border-left:4px solid #9a6b16;border-radius:0 8px 8px 0;
padding:1rem 1.25rem;background:#fbf2dd}code{font-family:'JetBrains Mono',monospace}</style>
</head><body>
<div class="banner"><b>This render didn't finish.</b><br>
The background renderer exited before writing the page — it may have errored, or
been interrupted. Re-run <code>/render</code> in that session to regenerate it.</div>
</body></html>"""
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
PY
  else
    echo "[$(date -Iseconds)] narrative stage 2 OK (rc=$rc)"
  fi

  # Cross-link banner: inject after <body...> once the file is (re)written.
  if [ -n "$RELATED_URL" ] && [ -f "$OUT" ]; then
    RELATED_URL="$RELATED_URL" RELATED_LABEL="$RELATED_LABEL" \
      python3 - "$OUT" <<'PY'
import os, re, sys, html
path = sys.argv[1]
url = html.escape(os.environ["RELATED_URL"], quote=True)
label = html.escape(os.environ["RELATED_LABEL"])
banner = (
    '<div class="html-render-xref" style="max-width:880px;margin:1rem auto -0.5rem;'
    'padding:0 1.5rem;font:14px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif">'
    f'<a href="{url}" style="display:inline-block;padding:.4rem .8rem;'
    'border:1px solid #bcd9c8;border-radius:6px;background:#e3f0e8;'
    f'color:#2f6d4f;text-decoration:none">{label}</a></div>'
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
  exit 0
fi

# ---- Stage 1: synchronous placeholder + dispatch the detached worker. ----
PLUGIN_DIR="$1"; OUT="$2"; URL="$3"; TRANSCRIPT="$4"
RELATED_URL="${5:-}"; RELATED_LABEL="${6:-}"

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
<title>Rendering… (fills in automatically)</title>
<!-- html-render:placeholder -->
<style>
@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;700&display=swap');
body {{ font-family:'Hanken Grotesk',ui-sans-serif,system-ui,sans-serif; background:#f7f6f3;
  color:#1d2230; max-width:880px; margin:3rem auto; padding:0 1.5rem; line-height:1.6; }}
a {{ color:#2f6d4f; }}
.banner {{ border:1px solid #bcd9c8; border-left:4px solid #2f6d4f; border-radius:0 8px 8px 0;
  padding:1rem 1.25rem; background:#e3f0e8; }}
</style></head><body>
{xref}
<div class="banner"><b>Rendering this page in the background…</b><br>
It replaces this placeholder automatically in about a minute — refresh. If it
never does, the background render was interrupted (e.g. the session ended first);
re-run <code>/render</code> in that session to regenerate it.</div>
</body></html>"""
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
PY

command -v claude >/dev/null 2>&1 || exit 0

# Extract ONLY the last turn (+ eliciting prompt) to a tiny file. The full
# transcript is often multi-MB; handing the renderer that is the dominant cause
# of slow renders (it reads ~hundreds of K tokens). Fall back to the transcript
# if extraction fails.
SRC="${OUT%.html}.source.md"
python3 "$PLUGIN_DIR/lib/extract_turn.py" "$TRANSCRIPT" "$SRC" >/dev/null 2>&1 || SRC="$TRANSCRIPT"

PROMPT="You are the html-renderer subagent. Read the instructions at $PLUGIN_DIR/agents/html-renderer.md.

Source: $SRC — a small markdown file with the eliciting user prompt and the assistant turn to render. Read THAT file; do NOT read the full transcript.
Mode: narrative
Output: $OUT
Server port: ${HTML_RENDER_PORT:-7777}
Plugin dir: $PLUGIN_DIR

The server is already running; you do not need to start it.
You have ONLY Read and Write tools — generate the HTML, write it to the output path, and print the URL.

Print exactly one line on success: rendered: $URL"

RLOG="${OUT%.html}.render.log"
# Detach the worker into its own session (setsid) so it doesn't hold the Stop
# hook's process group and survives the session ending. Fall back to a plain
# background job if setsid is unavailable.
if command -v setsid >/dev/null 2>&1; then
  HTML_RENDER_PROMPT="$PROMPT" setsid bash "$0" __bg \
    "$OUT" "$URL" "$RELATED_URL" "${RELATED_LABEL:-← Code diff}" \
    </dev/null >>"$RLOG" 2>&1 &
else
  HTML_RENDER_PROMPT="$PROMPT" bash "$0" __bg \
    "$OUT" "$URL" "$RELATED_URL" "${RELATED_LABEL:-← Code diff}" \
    </dev/null >>"$RLOG" 2>&1 &
fi
disown 2>/dev/null || true
