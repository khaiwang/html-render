---
description: Re-render the last assistant turn as HTML (auto-detect diff vs narrative). Output is produced by a background subagent — main context stays plain text.
---

Dispatch the html-renderer agent in the background to render the previous assistant turn as HTML.

Steps:
1. Resolve the plugin directory (the parent of this commands/ folder).
2. Ensure the server is running: `bash <plugin-dir>/server/start.sh`
3. Generate an output slug: `$(date -u +%Y%m%dT%H%M%SZ)-manual`
4. Use the Task tool with `subagent_type: "general-purpose"` and `run_in_background: true` to dispatch a worker with this prompt:
   > Read `<plugin-dir>/agents/html-renderer.md` and follow it. Mode: auto. Source: the transcript at `$CLAUDE_TRANSCRIPT_PATH` (the previous assistant turn — auto-detect whether to render as diff or narrative based on the content). Write the HTML to `~/.html-render/<slug>.html` and print only the resulting URL.
5. Report to the user only the one-line URL the subagent returns; do NOT discuss what was rendered.

If `$ARGUMENTS` is non-empty, pass it through as a hint (e.g. user can type `/render diff` or `/render plan`).
