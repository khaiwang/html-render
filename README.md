# html-render

A Claude Code plugin that turns assistant outputs — **plans/reviews, git diffs, and code walkthroughs** — into clean HTML pages served on a small local web server. Generation happens in the background, so your main session stays plain text. Pages are organized by project and session and browsable from one index.

## What it renders

| Mode | What it is | How it's rendered |
| --- | --- | --- |
| **narrative** | A plan, review, design, or long structured answer | LLM fills a rich template (`plan.html` / `review.html`) |
| **diff** | The session's `git diff` | **Deterministic** Python: side-by-side *before \| after*, line gutters, `+/−` coloring, plus an optional **per-hunk explanation column** written by a code-exploring agent |
| **walkthrough** | A "walk me through this code" answer | Stacked, narrative-primary: full-width prose per section with the referenced **source code collapsible beneath it**, syntax-highlighted |
| **diff + narrative** | A turn that both edits code *and* explains it | Two **cross-linked** pages: the diff, and a normal narrative "session summary" page |

## How it works

- A `Stop` hook classifies each finished turn and, if it's worth rendering, dispatches the right renderer **in the background**. Detection:
  - "walk me through …" / "walkthrough" in your prompt → **walkthrough**
  - the turn used `Edit`/`Write` → **diff** (or **diff + narrative** if it also carries a substantial explanation)
  - otherwise a substantial structured answer → **narrative**
- Pages are written under `$XDG_DATA_HOME/html-render/<project>/<session>/` and a small stdlib Python server (default `http://127.0.0.1:7777`) serves a collapsible **project → session → render** index.
- Every auto-trigger also has a **manual command** (for when detection misses): `/render`, `/render-plan`, `/render-diff`, `/walkthrough`.

## Install

```bash
# 1. Add this repo as a marketplace
claude plugin marketplace add <your-github-user>/html-render

# 2. Install the plugin
claude plugin install html-render@html-render

# 3. Restart Claude Code so commands/agents load
```

From a local clone instead:

```bash
git clone https://github.com/<your-github-user>/html-render.git
claude plugin marketplace add ./html-render
claude plugin install html-render@html-render
```

> Auto-render only works in sessions started **after** install (hooks bind at session start). The slash commands work as soon as you restart.

## Requirements

- `python3` — standard library only, **no pip packages**.
- The render server must be running for URLs to resolve. The `/render*` commands start it automatically; manually:
  ```bash
  bash plugins/html-render/server/start.sh
  bash plugins/html-render/server/stop.sh
  ```
- **Walkthrough syntax highlighting** loads highlight.js from a CDN. With no internet the code still renders as plain (unhighlighted) text. No other feature needs the network.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `HTML_RENDER_PORT` | `7777` | Port the server binds to (`127.0.0.1` only). |
| `HTML_RENDER_DIR` | `$XDG_DATA_HOME/html-render` (`~/.local/share/html-render`) | Where rendered pages live. |
| `HTML_RENDER_TITLE` | `<user>'s Claude sessions` | Index page heading. |
| `HTML_RENDER_RECENT` | `3` | Newest renders shown per session before the rest collapse behind a "N older" toggle. |
| `HTML_RENDER_EXPLAIN` | `1` | Set `0` to skip the diff per-hunk explanation column (pure before/after). |

Runtime files (pid, logs) live in `<data>/.state/`, separate from the rendered history.

## Security

The background renderers are **confined** so an unattended render can't be turned into arbitrary execution by injected content:

- Diffs are rendered **deterministically in Python** — no LLM, no shell.
- The narrative renderer runs with `--permission-mode default` and only `Read/Write/Edit/Glob/Grep` — no `Bash`, no network.
- The diff-explanation and walkthrough agents get `Read/Grep/Glob` (the diff explainer also gets read-only `git`) — enough to investigate the repo, but **no `Write`/`WebFetch`**.
- The hook ignores its own renderer subprocesses (no self-render recursion).

## Components

- **Hook:** `Stop` → `hooks/stop-classifier.sh` — classify the turn, dispatch a renderer.
- **Commands:** `/render`, `/render-plan`, `/render-diff`, `/walkthrough`.
- **Agent:** `html-renderer` (narrative HTML generator).
- **lib/**
  - `session-path.sh` — XDG paths + project/session resolution (single source of truth).
  - `render_diff.py` — deterministic side-by-side diff renderer.
  - `diff-explain.sh` — render the diff, then add the per-hunk explanation column.
  - `render_walkthrough.py` — stacked, highlighted code-walkthrough renderer.
  - `walkthrough-render.sh` — placeholder + segment-extraction agent.
  - `narrative-render.sh` — dispatch the narrative render + cross-link.
- **Server:** `server/server.py` (stdlib HTTP server + index).
- **templates/** `plan.html`, `review.html` (narrative templates).

## Uninstall

```bash
claude plugin uninstall html-render@html-render
claude plugin marketplace remove html-render
```

## License

MIT
