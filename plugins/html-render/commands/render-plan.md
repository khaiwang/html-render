---
description: Render the last narrative output (plan, review, recap) as an HTML page. Runs in a background subagent.
---

Dispatch the html-renderer agent in narrative mode against the most recent assistant turn.

Steps:
1. Resolve the plugin directory.
2. Ensure the server is running: `bash <plugin-dir>/server/start.sh`
3. Compute the output path, URL, and resolved transcript:
   `bash <plugin-dir>/lib/session-path.sh --new "$CLAUDE_TRANSCRIPT_PATH" plan "${HTML_RENDER_PORT:-7777}"`
   It prints `OUT=`, `URL=`, and `TRANSCRIPT=`. (`$CLAUDE_TRANSCRIPT_PATH` is normally empty for commands; the helper resolves the session transcript from `$CLAUDE_CODE_SESSION_ID`.)
4. Dispatch the subagent in the background:
   > Read `<plugin-dir>/agents/html-renderer.md`. Mode: narrative. Source: the transcript at the `TRANSCRIPT` value from step 3. Write to the `OUT` path from step 3. Print exactly `rendered: <URL>`.
5. Report only the URL to the user.
