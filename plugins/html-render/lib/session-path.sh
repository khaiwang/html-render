#!/usr/bin/env bash
# Shared path resolution for html-render.
#
# Source it to use the hr_* functions, or run it directly:
#   session-path.sh <transcript>            -> prints that session's dir
#   session-path.sh --new <transcript> <mode> <port>
#                       -> prints OUT=<abs>, URL=<url>, TRANSCRIPT=<resolved>
# Pass "" as <transcript> and the current session's transcript is resolved
# from $CLAUDE_CODE_SESSION_ID (slash commands don't get a transcript path).
#
# Storage model (XDG):
#   pages (durable history)  -> $HTML_RENDER_DIR or $XDG_DATA_HOME/html-render
#   runtime junk (pid, logs) -> <data>/.state   (hidden; excluded from index)
#
# On-disk layout:
#   <data>/<project-slug>/<session-uuid>/meta.json
#   <data>/<project-slug>/<session-uuid>/<UTC-timestamp>-<mode>.html
set -u

hr_data_dir() {
  if [ -n "${HTML_RENDER_DIR:-}" ]; then
    printf '%s' "$HTML_RENDER_DIR"
  else
    printf '%s' "${XDG_DATA_HOME:-$HOME/.local/share}/html-render"
  fi
}

hr_state_dir() {
  printf '%s' "$(hr_data_dir)/.state"
}

# hr_resolve_transcript [maybe-path] -> a usable transcript path.
# Slash commands do NOT get $CLAUDE_TRANSCRIPT_PATH (only the Stop hook does,
# via stdin), so when handed an empty/invalid path we locate the current
# session's transcript via $CLAUDE_CODE_SESSION_ID, then fall back to the most
# recently modified transcript.
hr_resolve_transcript() {
  local given="${1:-}" base="$HOME/.claude/projects" sid f
  if [ -n "$given" ] && [ -f "$given" ]; then
    printf '%s' "$given"; return 0
  fi
  sid="${CLAUDE_CODE_SESSION_ID:-}"
  if [ -n "$sid" ]; then
    f="$(find "$base" -maxdepth 2 -name "$sid.jsonl" -print 2>/dev/null | head -1)"
    if [ -n "$f" ]; then printf '%s' "$f"; return 0; fi
  fi
  find "$base" -maxdepth 2 -name '*.jsonl' -printf '%T@\t%p\n' 2>/dev/null \
    | sort -rn | head -1 | cut -f2- | tr -d '\n'
}

# hr_write_meta <transcript> <session> <project>  -> meta.json on stdout
hr_write_meta() {
  local transcript="$1" session="$2" project="$3"
  HR_PWD="${PWD:-}" python3 - "$transcript" "$session" "$project" <<'PY'
import json, os, sys
transcript, session, project = sys.argv[1], sys.argv[2], sys.argv[3]
title, started, cwd = "", "", ""
try:
    with open(transcript) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not started:
                started = e.get("timestamp") or ""
            if not cwd:
                cwd = e.get("cwd") or ""
            if not title:
                role = e.get("role") or (e.get("message") or {}).get("role")
                if role == "user" and not e.get("isMeta"):
                    msg = e.get("message") or e
                    content = msg.get("content")
                    text = content if isinstance(content, str) else ""
                    if isinstance(content, list):
                        text = "".join(
                            c.get("text", "")
                            for c in content
                            if isinstance(c, dict) and c.get("type") == "text"
                        )
                    text = " ".join(text.split())
                    # Skip system-reminder / tool noise; keep the real prompt.
                    if text and not text.startswith("<"):
                        title = text[:80]
            if title and started and cwd:
                break
except Exception:
    pass
# The transcript's own recorded cwd is authoritative; fall back to wherever
# the hook ran ($PWD) only if the transcript never recorded one.
if not cwd:
    cwd = os.environ.get("HR_PWD", "")
print(json.dumps({
    "session_id": session,
    "project_slug": project,
    "project_path": cwd,
    "started": started,
    "title": title,
}, indent=2))
PY
}

# hr_session_dir <transcript>  -> creates + prints the session directory
hr_session_dir() {
  local transcript data session project sdir
  transcript="$(hr_resolve_transcript "${1:-}")"
  data="$(hr_data_dir)"
  session="$(basename "$transcript" .jsonl)"
  project="$(basename "$(dirname "$transcript")")"
  [ -n "$session" ] || session="unknown"
  [ -n "$project" ] || project="unknown"
  sdir="$data/$project/$session"
  mkdir -p "$sdir"
  if [ ! -f "$sdir/meta.json" ]; then
    hr_write_meta "$transcript" "$session" "$project" >"$sdir/meta.json" 2>/dev/null || true
  fi
  printf '%s' "$sdir"
}

# hr_new_output <transcript> <mode> <port>  -> "<abs_out>\t<url>\t<transcript>"
hr_new_output() {
  local transcript mode="$2" port="$3" sdir slug out data rel
  transcript="$(hr_resolve_transcript "${1:-}")"
  sdir="$(hr_session_dir "$transcript")"
  slug="$(date -u +%Y%m%dT%H%M%SZ)-$mode"
  out="$sdir/$slug.html"
  data="$(hr_data_dir)"
  rel="${out#"$data"/}"
  printf '%s\t%s\t%s' "$out" "http://localhost:$port/$rel" "$transcript"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    --new)
      shift
      [ $# -ge 2 ] || { echo "usage: session-path.sh --new <transcript> <mode> [port]" >&2; exit 2; }
      ou="$(hr_new_output "${1:-}" "$2" "${3:-7777}")"
      IFS=$'\t' read -r _o _u _t <<<"$ou"
      printf 'OUT=%s\nURL=%s\nTRANSCRIPT=%s\n' "$_o" "$_u" "$_t"
      ;;
    "")
      echo "usage: session-path.sh <transcript> | --new <transcript> <mode> [port]" >&2
      exit 2
      ;;
    *)
      hr_session_dir "$1"; echo
      ;;
  esac
fi
