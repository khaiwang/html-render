---
description: Render the current git diff as a 3-column HTML page (before | after | explanation). Runs in a background subagent.
---

Dispatch the html-renderer agent in diff mode against `$ARGUMENTS` (defaults to the working tree).

Steps:
1. Resolve the plugin directory.
2. Ensure the server is running.
3. Dispatch the subagent in the background:
   > Read `<plugin-dir>/agents/html-renderer.md`. Mode: diff. Source: `${ARGUMENTS:-working}`. Write to `~/.html-render/<timestamp>-diff.html`. Print only the URL.
4. Report only the URL to the user.
