---
description: Render the current git diff as a clean HTML page (GitHub-style, deterministic — no subagent).
---

Render `$ARGUMENTS` (a git ref; defaults to the working tree) as an HTML diff.

Steps:
1. Resolve the plugin directory.
2. Ensure the server is running: `bash <plugin-dir>/server/start.sh`
3. Compute the output path and URL:
   `bash <plugin-dir>/lib/session-path.sh --new "$CLAUDE_TRANSCRIPT_PATH" diff "${HTML_RENDER_PORT:-7777}"`
   It prints `OUT=`, `URL=`, and `TRANSCRIPT=`. (`$CLAUDE_TRANSCRIPT_PATH` is normally empty for commands; the helper resolves the session from `$CLAUDE_CODE_SESSION_ID` so the file lands in the right session folder.)
4. Render the diff deterministically — no subagent, the Python renderer parses the diff and writes aligned HTML:
   `python3 <plugin-dir>/lib/render_diff.py --git "${ARGUMENTS:-working}" --out "<OUT>" --url "<URL>" --transcript "<TRANSCRIPT>"`
   Run it from the repo you want diffed (its cwd is the git repo).
5. Report only the `URL` to the user.
