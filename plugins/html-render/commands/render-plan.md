---
description: Render the last narrative output (plan, review, recap) as an HTML page. Runs in a background subagent.
---

Dispatch the html-renderer agent in narrative mode against the most recent assistant turn.

Steps:
1. Resolve the plugin directory.
2. Ensure the server is running.
3. Dispatch the subagent in the background:
   > Read `<plugin-dir>/agents/html-renderer.md`. Mode: narrative. Source: the transcript at `$CLAUDE_TRANSCRIPT_PATH`. Write to `~/.html-render/<timestamp>-plan.html`. Print only the URL.
4. Report only the URL to the user.
