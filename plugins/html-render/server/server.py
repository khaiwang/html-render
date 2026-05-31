#!/usr/bin/env python3
"""html-render local HTTP server.

Serves the html-render data directory (default $XDG_DATA_HOME/html-render,
override with HTML_RENDER_DIR) on a fixed port (default 7777, override with
HTML_RENDER_PORT). GET / renders a project -> session -> page index, reading
each session's meta.json for display names. Pages live at
<root>/<project-slug>/<session-uuid>/<timestamp>-<mode>.html.
"""

import html
import json
import os
import re
import sys
from datetime import datetime
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("HTML_RENDER_DIR")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base).expanduser() / "html-render"


ROOT = data_dir()
PORT = int(os.environ.get("HTML_RENDER_PORT", "7777"))
# How many of a session's newest renders to show before collapsing the rest
# behind a "N older render(s)" expander. Override with HTML_RENDER_RECENT.
RECENT_LIMIT = max(1, int(os.environ.get("HTML_RENDER_RECENT", "3")))


def _default_title():
    try:
        import getpass
        return f"{getpass.getuser()}'s Claude sessions"
    except Exception:
        return "Claude sessions"


# Home-page heading/title. Override with HTML_RENDER_TITLE.
HOME_TITLE = os.environ.get("HTML_RENDER_TITLE") or _default_title()

# Canonical shared theme: fonts + core color tokens + the box-sizing reset.
# Served at /_assets/base.css and linked by every rendered page (and the index)
# so the palette lives in ONE place — change it here and all future renders pick
# it up. Page-specific tokens (diff add/del, review good/bad/ugly, etc.) stay
# inline in each page. --dim is an alias of --text-dim so both names resolve to
# one source value across renderers and templates.
BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
:root {
  color-scheme: light;
  --sans:'Hanken Grotesk',ui-sans-serif,system-ui,-apple-system,sans-serif;
  --display:'Bricolage Grotesque','Hanken Grotesk',ui-sans-serif,system-ui,sans-serif;
  --serif:var(--display);
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  /* warm editorial palette (light-only) */
  --bg:#f7f6f3;
  --surface:#ffffff;        /* paper */
  --surface-dim:#f4f3ef;    /* code / dim fills */
  --surface-recessed:#f1f0ea;
  --border:#e3e1da;         /* line */
  --border-soft:#eeede8;
  --text:#1d2230;           /* ink */
  --text-soft:#4a5165;
  --text-dim:#737b8f;
  --dim:var(--text-dim);
  --accent:#2f6d4f;         /* deep green */
  --accent-soft:#e3f0e8;
  --accent-line:#bcd9c8;
  --amber:#9a6b16; --amber-soft:#fbf2dd; --amber-line:#ecd9a8;
  --blue:#2b5d86;  --blue-soft:#e6eff7;  --blue-line:#cfdfee;
  --red:#b23a3a;   --red-soft:#fbe9e9;   --red-line:#edc4c4;
  --code-bg:#f4f3ef;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
"""

# Index-page-only rules. Core tokens/fonts/reset come from BASE_CSS (linked).
INDEX_CSS = """
body {
  font-family: var(--sans); background: var(--bg); color: var(--text);
  max-width: 900px; margin: 2.5rem auto; padding: 0 1.5rem; line-height: 1.55;
}
h1 { font-family: var(--display); font-weight: 700; font-size: 1.7rem; letter-spacing:-.02em; margin-bottom: 0.25rem; }
.sub { color: var(--dim); font-size: 0.82rem; margin-bottom: 2.5rem; font-family: var(--mono); }
.project { margin-bottom: 2.5rem; }
.project__name {
  font-family: var(--display); font-size: 1.05rem; font-weight: 700;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.35rem;
  margin-bottom: 1rem;
}
.session { margin: 0 0 1.5rem 0.25rem; }
.session__head { font-size: 0.88rem; margin-bottom: 0.4rem; }
.session__title { font-weight: 600; }
.session__meta { color: var(--dim); font-weight: 400; }
ul { list-style: none; padding: 0; margin: 0 0 0 1rem; }
li {
  padding: 0.4rem 0;
  display: grid;
  grid-template-columns: 7rem 1fr;
  gap: 1rem;
  align-items: baseline;
}
.ts { color: var(--dim); font-size: 0.78rem; font-family: var(--mono); }
a {
  color: inherit;
  text-decoration: none;
  border-bottom: 1px dashed var(--border);
}
a:hover { border-bottom-color: var(--accent); color: var(--accent); }
.empty { color: var(--dim); font-style: italic; margin-top: 2rem; }
.tag {
  display: inline-block;
  font-size: 0.7rem;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  margin-left: 0.5rem;
  vertical-align: middle;
}
.tag-diff { background: rgba(63, 185, 80, 0.18); color: #2ea043; }
.tag-plan { background: rgba(101, 116, 205, 0.18); color: #6574cd; }
.tag-review { background: rgba(212, 167, 58, 0.18); color: #b08a2e; }
.tag-walkthrough { background: rgba(31, 158, 137, 0.18); color: #1f9e89; }
summary { cursor: pointer; user-select: none; }
summary::-webkit-details-marker { color: var(--accent); }
summary::marker { color: var(--accent); }
details.session[open] > summary { margin-bottom: 0.4rem; }
details.session > summary { margin-bottom: 0; }
details.project { margin-bottom: 2rem; }
details.project > summary.project__name { margin-bottom: 1rem; }
details.session:not([open]) > summary .session__title { color: var(--dim); font-weight: 400; }
details.more { margin: 0.25rem 0 0.4rem 1rem; }
details.more > summary { color: var(--dim); font-size: 0.78rem; }
"""

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def extract_title(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
        m = TITLE_RE.search(head)
        if m:
            return html.unescape(m.group(1).strip()) or path.stem
    except OSError:
        pass
    return path.stem


def classify_tag(filename: str) -> str:
    name = filename.lower()
    if "walkthrough" in name:
        return "walkthrough"
    if "diff" in name:
        return "diff"
    if "plan" in name:
        return "plan"
    if "review" in name or "recap" in name:
        return "review"
    return ""


def load_meta(session_dir: Path) -> dict:
    try:
        with (session_dir / "meta.json").open() as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def fmt_time(epoch: float, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return datetime.fromtimestamp(epoch).strftime(fmt)


def fmt_started(meta: dict, fallback: float) -> str:
    raw = meta.get("started") or ""
    if raw:
        try:
            return (
                datetime.fromisoformat(raw.replace("Z", "+00:00"))
                .astimezone()
                .strftime("%Y-%m-%d %H:%M")
            )
        except ValueError:
            pass
    return fmt_time(fallback)


def page_li(rel_href: str, page: Path) -> str:
    tag = classify_tag(page.name)
    tag_html = f'<span class="tag tag-{tag}">{tag}</span>' if tag else ""
    return (
        f'<li><span class="ts">{fmt_time(page.stat().st_mtime, "%H:%M")}</span>'
        f'<span><a href="/{html.escape(rel_href)}">{html.escape(extract_title(page))}</a>'
        f'{tag_html}</span></li>'
    )


def collect():
    """Return (projects, legacy_pages), both ordered newest-first.

    Each project: {name, sessions, mtime}. Each session: {dir, pages, meta, mtime}.
    """
    projects = []
    legacy = []

    for proj in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        if proj.name.startswith("."):
            continue
        if proj.name == "_legacy":
            legacy.extend(
                sorted(proj.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
            )
            continue
        sessions = []
        for sess in proj.iterdir():
            if not sess.is_dir():
                continue
            pages = sorted(
                sess.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            if not pages:
                continue
            sessions.append({
                "dir": sess,
                "pages": pages,
                "meta": load_meta(sess),
                "mtime": max(p.stat().st_mtime for p in pages),
            })
        if not sessions:
            continue
        sessions.sort(key=lambda s: s["mtime"], reverse=True)
        name = next(
            (s["meta"].get("project_path") for s in sessions if s["meta"].get("project_path")),
            None,
        ) or proj.name
        projects.append({
            "name": name,
            "sessions": sessions,
            "mtime": max(s["mtime"] for s in sessions),
        })

    # Loose *.html directly under ROOT are treated as legacy too.
    legacy.extend(p for p in ROOT.glob("*.html") if p.name != "index.html")
    projects.sort(key=lambda x: x["mtime"], reverse=True)
    return projects, legacy


def render_index() -> bytes:
    ROOT.mkdir(parents=True, exist_ok=True)
    projects, legacy = collect()
    total = sum(len(s["pages"]) for proj in projects for s in proj["sessions"]) + len(legacy)

    # Tidy default view:
    #  - within each session, show the RECENT_LIMIT newest renders; older ones
    #    collapse behind a "N older render(s)" expander;
    #  - open only the newest session in each project, and only the newest
    #    project. Everything else starts collapsed (click any summary to open).
    newest_global = max(
        (s["mtime"] for proj in projects for s in proj["sessions"]), default=0.0)

    blocks = []
    for proj in projects:
        sblocks = []
        proj_newest = max((s["mtime"] for s in proj["sessions"]), default=0.0)
        for s in proj["sessions"]:
            meta = s["meta"]
            short = (meta.get("session_id") or s["dir"].name)[:8]
            title = meta.get("title") or "(untitled session)"
            rel_base = f"{s['dir'].parent.name}/{s['dir'].name}"
            visible, rest = s["pages"][:RECENT_LIMIT], s["pages"][RECENT_LIMIT:]
            lis = "".join(page_li(f"{rel_base}/{p.name}", p) for p in visible)
            more = ""
            if rest:
                more_lis = "".join(page_li(f"{rel_base}/{p.name}", p) for p in rest)
                more = (f'<details class="more"><summary>{len(rest)} older render(s)'
                        f'</summary><ul>{more_lis}</ul></details>')
            s_open = " open" if s["mtime"] == proj_newest else ""
            sblocks.append(
                f'<details class="session"{s_open}><summary class="session__head">'
                f'<span class="session__title">{html.escape(title)}</span> '
                f'<span class="session__meta">· {fmt_started(meta, s["mtime"])} '
                f'· {html.escape(short)} · {len(s["pages"])} render(s)</span></summary>'
                f'<ul>{lis}</ul>{more}</details>'
            )
        p_open = " open" if proj_newest == newest_global else ""
        blocks.append(
            f'<details class="project"{p_open}>'
            f'<summary class="project__name">{html.escape(proj["name"])} '
            f'<span class="session__meta">· {len(proj["sessions"])} session(s)</span></summary>'
            f'{"".join(sblocks)}</details>'
        )

    if legacy:
        lis = "".join(
            page_li(f"_legacy/{p.name}" if p.parent.name == "_legacy" else p.name, p)
            for p in legacy
        )
        blocks.append(
            '<details class="project"><summary class="project__name">_legacy '
            f'<span class="session__meta">· {len(legacy)} ungrouped page(s)</span></summary>'
            f'<ul>{lis}</ul></details>'
        )

    body = (
        "".join(blocks)
        if blocks
        else '<p class="empty">No pages yet. Trigger a render to populate this list.</p>'
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(HOME_TITLE)}</title>
<link rel="stylesheet" href="/_assets/base.css">
<style>{INDEX_CSS}</style>
</head>
<body>
<h1>{html.escape(HOME_TITLE)}</h1>
<div class="sub">{html.escape(str(ROOT))} · port {PORT} · {total} render(s)</div>
{body}
</body>
</html>"""
    return page.encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path == "/_assets/base.css":
            body = BASE_CSS.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path in ("/", "/index", "/index.html"):
            body = render_index()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def log_message(self, fmt, *args):
        # Quiet by default — uncomment to debug.
        pass


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        server = HTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print(
            f"[html-render] could not bind 127.0.0.1:{PORT}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[html-render] serving {ROOT} at http://127.0.0.1:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
