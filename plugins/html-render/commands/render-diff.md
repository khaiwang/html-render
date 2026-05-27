---
description: Render the current git diff as a 3-column HTML page (before | after | explanation). Runs in a background subagent.
---

Dispatch the html-renderer agent in diff mode against `$ARGUMENTS` (defaults to the working tree).

Steps:
1. Resolve the plugin directory.
2. Ensure the server is running: `bash <plugin-dir>/server/start.sh`
3. Compute the session-scoped output path and URL:
   `bash <plugin-dir>/lib/session-path.sh --new "$CLAUDE_TRANSCRIPT_PATH" diff "${HTML_RENDER_PORT:-7777}"`
   It prints `OUT=…` and `URL=…`.
4. Dispatch the subagent in the background:
   > Read `<plugin-dir>/agents/html-renderer.md`. Mode: diff. Source: `${ARGUMENTS:-working}` (a git ref — run git yourself). Write to the `OUT` path from step 3. Print exactly `rendered: <URL>`.
5. Report only the URL to the user.
