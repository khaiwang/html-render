---
description: Render the last narrative output (plan, review, recap) as an HTML page. Runs in a background subagent.
---

Dispatch the html-renderer agent in narrative mode against the most recent assistant turn.

Steps:
1. Resolve the plugin directory.
2. Ensure the server is running: `bash <plugin-dir>/server/start.sh`
3. Compute the session-scoped output path and URL:
   `bash <plugin-dir>/lib/session-path.sh --new "$CLAUDE_TRANSCRIPT_PATH" plan "${HTML_RENDER_PORT:-7777}"`
   It prints `OUT=…` and `URL=…`.
4. Dispatch the subagent in the background:
   > Read `<plugin-dir>/agents/html-renderer.md`. Mode: narrative. Source: the transcript at `$CLAUDE_TRANSCRIPT_PATH`. Write to the `OUT` path from step 3. Print exactly `rendered: <URL>`.
5. Report only the URL to the user.
