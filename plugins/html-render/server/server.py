#!/usr/bin/env python3
"""html-render local HTTP server.

Serves ~/.html-render/ on a fixed port (default 7777, override with
HTML_RENDER_PORT). GET / renders a reverse-chronological index of all
.html files in the directory, parsing <title> tags for display names.
"""

import html
import os
import re
import sys
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(os.environ.get("HTML_RENDER_DIR", "~/.html-render")).expanduser()
PORT = int(os.environ.get("HTML_RENDER_PORT", "7777"))

INDEX_CSS = """
:root { color-scheme: light dark; }
body {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  max-width: 880px;
  margin: 2.5rem auto;
  padding: 0 1.5rem;
  line-height: 1.55;
}
h1 { font-size: 1.25rem; margin-bottom: 0.25rem; }
.sub { color: #888; font-size: 0.85rem; margin-bottom: 2rem; }
ul { list-style: none; padding: 0; }
li {
  padding: 0.75rem 0;
  border-bottom: 1px solid rgba(127,127,127,0.18);
  display: grid;
  grid-template-columns: 9rem 1fr;
  gap: 1rem;
  align-items: baseline;
}
li:last-child { border-bottom: none; }
.ts { color: #888; font-size: 0.8rem; }
a {
  color: inherit;
  text-decoration: none;
  border-bottom: 1px dashed rgba(127,127,127,0.4);
}
a:hover { border-bottom-style: solid; }
.empty { color: #888; font-style: italic; margin-top: 2rem; }
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
    if "diff" in name:
        return "diff"
    if "plan" in name:
        return "plan"
    if "review" in name or "recap" in name:
        return "review"
    return ""


def render_index() -> bytes:
    if not ROOT.exists():
        ROOT.mkdir(parents=True, exist_ok=True)

    files = sorted(
        (p for p in ROOT.glob("*.html") if p.name != "index.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    items = []
    for p in files:
        ts = p.stat().st_mtime
        title = extract_title(p)
        tag = classify_tag(p.name)
        tag_html = (
            f'<span class="tag tag-{tag}">{tag}</span>' if tag else ""
        )
        from datetime import datetime
        ts_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        items.append(
            f'<li><span class="ts">{ts_str}</span>'
            f'<span><a href="/{html.escape(p.name)}">{html.escape(title)}</a>{tag_html}</span></li>'
        )

    body = (
        "<ul>" + "".join(items) + "</ul>"
        if items
        else '<p class="empty">No pages yet. Trigger a render to populate this list.</p>'
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>html-render</title>
<style>{INDEX_CSS}</style>
</head>
<body>
<h1>html-render</h1>
<div class="sub">{html.escape(str(ROOT))} · port {PORT} · {len(files)} page(s)</div>
{body}
</body>
</html>"""
    return page.encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
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
