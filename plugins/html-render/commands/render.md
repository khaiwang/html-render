---
description: Re-render the last assistant turn as HTML (auto-detect diff vs narrative). Output is produced by a background subagent — main context stays plain text.
---

Dispatch the html-renderer agent in the background to render the previous assistant turn as HTML.

Steps:
1. Resolve the plugin directory (the parent of this commands/ folder).
2. Ensure the server is running: `bash <plugin-dir>/server/start.sh`
3. Compute the output path, URL, and resolved transcript:
   `bash <plugin-dir>/lib/session-path.sh --new "$CLAUDE_TRANSCRIPT_PATH" manual "${HTML_RENDER_PORT:-7777}"`
   It prints `OUT=`, `URL=`, and `TRANSCRIPT=`. (`$CLAUDE_TRANSCRIPT_PATH` is normally empty for commands; the helper then resolves the current session's transcript from `$CLAUDE_CODE_SESSION_ID`.) Use those exact values.
4. Use the Task tool with `subagent_type: "general-purpose"` and `run_in_background: true` to dispatch a worker with this prompt:
   > Read `<plugin-dir>/agents/html-renderer.md` and follow it. Mode: auto. Source: the transcript at the `TRANSCRIPT` value from step 3 (render the previous assistant turn — auto-detect diff vs narrative). Write the HTML to the `OUT` path from step 3 and print exactly `rendered: <URL>` using the `URL` from step 3.
5. Report to the user only the one-line URL the subagent returns; do NOT discuss what was rendered.

If `$ARGUMENTS` is non-empty, pass it through as a hint (e.g. user can type `/render diff` or `/render plan`).
