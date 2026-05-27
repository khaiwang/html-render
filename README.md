# html-render

A Claude Code plugin that renders assistant outputs — plans, reviews, and git diffs — as self-contained HTML pages served on a small local web server. All HTML/CSS generation runs in an isolated background subagent, so your main session stays plain text.

## How it works

- A `Stop` hook classifies the last assistant turn. If it's worth rendering (a plan, a review, a diff, a long answer), it dispatches the `html-renderer` agent **in the background**.
- The agent writes a self-contained `.html` file into `~/.html-render/` and a tiny Python server (default `http://127.0.0.1:7777`) serves a reverse-chronological index of them.
- You can also render on demand with the `/render`, `/render-plan`, and `/render-diff` commands.

## Install

```bash
# 1. Add this repo as a marketplace
claude plugin marketplace add <your-github-user>/html-render

# 2. Install the plugin
claude plugin install html-render@html-render

# 3. Restart Claude Code so commands/agents load
```

Installing from a local clone instead of GitHub:

```bash
git clone https://github.com/<your-github-user>/html-render.git
claude plugin marketplace add ./html-render
claude plugin install html-render@html-render
```

## Requirements

- `python3` (standard library only — no pip packages).
- The render server must be running for the URLs to resolve. The `/render*` commands start it automatically; you can also start/stop it manually:

  ```bash
  bash plugins/html-render/server/start.sh
  bash plugins/html-render/server/stop.sh
  ```

## Configuration

| Env var            | Default          | Purpose                                  |
| ------------------ | ---------------- | ---------------------------------------- |
| `HTML_RENDER_PORT` | `7777`           | Port the local server binds to (127.0.0.1). |
| `HTML_RENDER_DIR`  | `~/.html-render` | Where rendered pages and logs are stored. |

## Components

- **Hook:** `Stop` → `hooks/stop-classifier.sh` (auto-render on turn end).
- **Agent:** `html-renderer` (isolated HTML generator).
- **Commands:** `/render`, `/render-plan`, `/render-diff`.
- **Server:** `server/server.py` (stdlib HTTP server).

## Uninstall

```bash
claude plugin uninstall html-render@html-render
claude plugin marketplace remove html-render
```

## License

MIT
