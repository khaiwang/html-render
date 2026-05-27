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
4. From the repo you want diffed, snapshot the diff next to the output file:
   `{ git diff ${ARGUMENTS:-}; git diff --cached; } > "<OUT with .html replaced by .diff>"`
5. Render it (deterministic layout) and add the explanation column in the background:
   `bash <plugin-dir>/lib/diff-explain.sh "<plugin-dir>" "<DIFF_FILE>" "<OUT>" "<URL>" "<TRANSCRIPT>"`
   This writes the side-by-side diff immediately, then a capable explorer agent (Read/Grep/Glob + git) fills the per-hunk explanation column and re-renders. It prints `rendered: <URL>` once the first render is done.
6. Report only the `URL` to the user.
