---
description: Render the last code walkthrough as a two-column page (code | walkthrough). Use when auto-detection missed it.
---

Render the most recent assistant code-walkthrough as an aligned two-column page (code on the left, the walkthrough prose on the right).

Steps:
1. Resolve the plugin directory.
2. Ensure the server is running: `bash <plugin-dir>/server/start.sh`
3. Compute the output path and URL:
   `bash <plugin-dir>/lib/session-path.sh --new "$CLAUDE_TRANSCRIPT_PATH" walkthrough "${HTML_RENDER_PORT:-7777}"`
   It prints `OUT=`, `URL=`, and `TRANSCRIPT=`.
4. Render it (placeholder immediately; a capable agent then segments the walkthrough against the real source files and re-renders):
   `bash <plugin-dir>/lib/walkthrough-render.sh "<plugin-dir>" "<OUT>" "<URL>" "<TRANSCRIPT>"`
   Run it from the repo whose code is being walked through (its cwd is used to resolve file paths).
5. Report only the `URL` to the user.
