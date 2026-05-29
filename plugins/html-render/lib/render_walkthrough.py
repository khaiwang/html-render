#!/usr/bin/env python3
"""Deterministic code-walkthrough renderer (two columns: code | walkthrough).

Takes a JSON array of segments produced by the walkthrough agent:
  [{"file": "...", "start": 63, "end": 141, "title": "...", "note": "<md>"}]
For each segment it slices the REAL file at [start,end] into the code column
and renders the note (light markdown) in the walkthrough column. The LLM picks
boundaries + writes prose; Python owns the code + layout, so it can't drift.

Usage:
  render_walkthrough.py --segments SEG.json --out FILE.html --url URL
                        [--repo DIR] [--title T] [--transcript T.jsonl]
"""
import argparse
import html
import json
import os
import re

_file_cache = {}


def load_segments(path):
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return []
    i, j = raw.find("["), raw.rfind("]")
    if i == -1 or j == -1 or j < i:
        return []
    try:
        data = json.loads(raw[i:j + 1])
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _suffix_search(repo, rel):
    """Find a file under repo whose path ends with `rel` (handles worktrees /
    a session cwd that differs from where the agent read the file)."""
    if not repo or not os.path.isdir(repo):
        return None
    rel = rel.lstrip("./")
    base = os.path.basename(rel)
    matches = []
    for dirpath, dirnames, filenames in os.walk(repo):
        # prune heavy/noise dirs
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")]
        if base in filenames:
            full = os.path.join(dirpath, base)
            if full.replace(os.sep, "/").endswith(rel):
                matches.append(full)
        if len(matches) > 8:
            break
    return matches[0] if matches else None


def file_lines(repo, path):
    if not path:
        return None
    key = (repo, path)
    if key in _file_cache:
        return _file_cache[key]
    candidates = [path]
    if repo and not os.path.isabs(path):
        candidates.insert(0, os.path.join(repo, path))
    lines = None
    for c in candidates:
        try:
            with open(c, encoding="utf-8", errors="replace") as f:
                lines = f.read().split("\n")
            break
        except Exception:
            continue
    if lines is None:                      # fallback: search by path suffix
        found = _suffix_search(repo, path)
        if found:
            try:
                with open(found, encoding="utf-8", errors="replace") as f:
                    lines = f.read().split("\n")
            except Exception:
                lines = None
    _file_cache[key] = lines
    return lines


def md_inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md2html(text):
    out = []
    list_type = None        # None | "ul" | "ol"
    in_code = False
    code = []

    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    def flush_code():
        nonlocal in_code, code
        body = "\n".join(html.escape(c, quote=False) for c in code)
        out.append(f'<pre class="cb"><code>{body}</code></pre>')
        code, in_code = [], False

    for ln in str(text).split("\n"):
        if ln.strip().startswith("```"):
            if in_code:
                flush_code()
            else:
                close_list(); in_code = True
            continue
        if in_code:
            code.append(ln)
            continue
        st = ln.strip()
        if not st:
            close_list()
            continue
        h = re.match(r"^(#{1,6})\s+(.*)", st)
        if h:
            close_list()
            lvl = min(6, len(h.group(1)) + 2)   # # -> h3, ## -> h4, ...
            out.append(f"<h{lvl}>{md_inline(h.group(2))}</h{lvl}>")
            continue
        ol = re.match(r"^(\d+)[.)]\s+(.*)", st)
        ul = re.match(r"^[-*•]\s+(.*)", st)
        if ol:
            if list_type != "ol":
                close_list(); out.append("<ol>"); list_type = "ol"
            out.append(f"<li>{md_inline(ol.group(2))}</li>")
        elif ul:
            if list_type != "ul":
                close_list(); out.append("<ul>"); list_type = "ul"
            out.append(f"<li>{md_inline(ul.group(1))}</li>")
        else:
            close_list()
            out.append(f"<p>{md_inline(st)}</p>")
    if in_code:
        flush_code()
    close_list()
    return "\n".join(out)


CSS = """
@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root { color-scheme: light dark;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:'Hanken Grotesk',ui-sans-serif,system-ui,-apple-system,sans-serif;
  --bg:#fafafa; --surface:#ffffff; --surface-dim:#f1f1f3; --text:#1a1a1f; --dim:#6b7280;
  --border:#e3e3e8; --accent:#2563eb; --accent-soft:rgba(37,99,235,.10);
  --code-bg:rgba(130,130,140,.06); --note-bg:rgba(130,130,140,.05); }
@media (prefers-color-scheme: dark) { :root {
  --bg:#161618; --surface:#1d1d20; --surface-dim:#26262a; --text:#e9e9ec; --dim:#9aa0a6;
  --border:rgba(255,255,255,.11); --accent:#7aa2f7; --accent-soft:rgba(122,162,247,.14);
  --code-bg:rgba(255,255,255,.05); --note-bg:rgba(255,255,255,.04); } }
* { box-sizing: border-box; }
body { font-family: var(--sans); background: var(--bg); color: var(--text);
  max-width: 920px; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.6; }
h1 { font-family: var(--sans); font-weight: 700; font-size: 1.5rem; letter-spacing:-.01em; margin: 0 0 .25rem; }
.meta { color: var(--dim); font-size: .82rem; margin-bottom: .5rem; }
.prompt { margin: .75rem 0 1.5rem; padding: .55rem .85rem; border-left: 3px solid var(--accent);
  background: var(--accent-soft); color: var(--dim); font-size: .85rem; border-radius: 0 4px 4px 0; }
.prompt b { color: var(--text); margin-right: .4rem; }
.seg { border: 1px solid var(--border); border-radius: 10px; margin-bottom: 1.75rem; overflow: hidden;
  background: var(--surface); }
.seg__title { font-family: var(--sans); font-weight: 700; font-size: 1.05rem;
  padding: .7rem 1.1rem; background: var(--surface-dim); border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; gap: 1rem; align-items: baseline; }
.seg__title .loc { font-weight: 400; font-size: .78rem; color: var(--dim); font-family: var(--mono);
  white-space: nowrap; }
/* Collapsible code under each section's prose. */
.seg__codewrap { border-top: 1px dashed var(--border); }
.seg__codewrap > summary { cursor: pointer; user-select: none; list-style: none;
  padding: .5rem 1.1rem; font-family: var(--mono); font-size: .8rem; color: var(--accent); }
.seg__codewrap > summary::-webkit-details-marker { display: none; }
.seg__codewrap > summary::before { content: "▸ "; }
.seg__codewrap[open] > summary::before { content: "▾ "; }
.seg__codewrap > summary:hover { background: var(--surface-dim); }
.seg__code { background: var(--code-bg); overflow-x: auto; border-top: 1px solid var(--border);
  font-family: var(--mono); font-size: 12.5px; line-height: 1.5; }
.seg__code pre { margin: 0; padding: .6rem .8rem; }
.seg__code code { font-family: var(--mono); }
/* highlight.js: let our container provide the background/padding */
.hljs { background: transparent !important; padding: 0 !important; }
/* highlightjs-line-numbers plugin renders a table */
.hljs-ln-numbers { text-align: right; color: var(--dim); user-select: none;
  padding-right: 1em; white-space: nowrap; border-right: 1px solid var(--border); }
.hljs-ln-code { padding-left: 1em; }
.miss { color: var(--dim); font-style: italic; padding: .4rem 1.1rem; }
.seg__note { padding: .9rem 1.1rem; font-size: 15px; }
.seg__note p { margin: 0 0 .6rem; }
.seg__note ul, .seg__note ol { margin: 0 0 .6rem; padding-left: 1.3rem; }
.seg__note li { margin-bottom: .3rem; }
.seg__note h3, .seg__note h4, .seg__note h5, .seg__note h6 {
  font-family: var(--sans); font-weight: 700; margin: .7rem 0 .35rem; line-height: 1.25; }
.seg__note h3 { font-size: 1rem; } .seg__note h4 { font-size: .92rem; }
.seg__note h5, .seg__note h6 { font-size: .85rem; color: var(--dim); }
.seg__note code { font-family: var(--mono); font-size: .9em; background: rgba(127,127,127,.15);
  padding: .05rem .3rem; border-radius: 3px; }
.seg__note pre.cb { background: var(--code-bg); border: 1px solid var(--border); border-radius: 5px;
  padding: .5rem .7rem; overflow-x: auto; font-size: 12px; margin: 0 0 .6rem; }
.seg__note pre.cb code { background: none; padding: 0; }
.empty { color: var(--dim); font-style: italic; }
.note-banner { background: rgba(212,167,58,.14); border:1px solid rgba(212,167,58,.4);
  border-radius:6px; padding:.5rem .85rem; font-size:.85rem; margin-bottom:1.25rem; }
"""


def esc(s):
    return html.escape(s, quote=False)


# Map file extensions to highlight.js language ids. Unknown → "" (auto-detect).
EXT_LANG = {
    "py": "python", "js": "javascript", "jsx": "javascript", "mjs": "javascript",
    "ts": "typescript", "tsx": "typescript", "sh": "bash", "bash": "bash", "zsh": "bash",
    "json": "json", "html": "xml", "xml": "xml", "css": "css", "scss": "scss",
    "c": "c", "h": "c", "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp",
    "go": "go", "rs": "rust", "java": "java", "rb": "ruby", "php": "php",
    "yaml": "yaml", "yml": "yaml", "toml": "ini", "ini": "ini", "md": "markdown",
    "sql": "sql", "lua": "lua", "swift": "swift", "kt": "kotlin", "scala": "scala",
    "r": "r", "jl": "julia", "ex": "elixir", "exs": "elixir", "pl": "perl",
    "dockerfile": "dockerfile", "make": "makefile", "vue": "xml",
}

# highlight.js assets (loaded only on pages that contain code).
HLJS_HEAD = (
    '<link rel="stylesheet" '
    'href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css" '
    'media="(prefers-color-scheme: light)">'
    '<link rel="stylesheet" '
    'href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css" '
    'media="(prefers-color-scheme: dark)">'
)
HLJS_SCRIPTS = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlightjs-line-numbers.js/2.8.0/highlightjs-line-numbers.min.js"></script>
<script>
document.querySelectorAll('pre code').forEach(function(el){
  try { hljs.highlightElement(el); } catch (e) {}
  try {
    var start = parseInt(el.parentElement.getAttribute('data-start') || '1', 10);
    if (window.hljs && hljs.lineNumbersBlock) hljs.lineNumbersBlock(el, {startFrom: start});
  } catch (e) {}
});
</script>"""


def lang_for(path):
    ext = os.path.splitext(path or "")[1].lower().lstrip(".")
    if not ext and os.path.basename(path or "").lower() == "dockerfile":
        ext = "dockerfile"
    return EXT_LANG.get(ext, "")


def code_block(repo, path, start, end):
    lines = file_lines(repo, path)
    if lines is None:
        return f'<div class="miss">({esc(path or "?")} not found)</div>'
    try:
        s = max(1, int(start)); e = int(end)
    except (TypeError, ValueError):
        s, e = 1, len(lines)
    if e < s or e <= 0:
        e = len(lines)
    snippet = "\n".join(lines[s - 1:min(e, len(lines))])
    if not snippet.strip():
        return '<div class="miss">(empty range)</div>'
    lang = lang_for(path)
    cls = f' class="language-{lang}"' if lang else ""
    return f'<pre data-start="{s}"><code{cls}>{esc(snippet)}</code></pre>'


def render(segments, title, url, prompt_text, repo, placeholder=False):
    head_extra = "" if placeholder else HLJS_HEAD
    out = [f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<title>{esc(title)}</title>{head_extra}<style>{CSS}</style></head><body>',
           f"<h1>{esc(title)}</h1>"]
    if prompt_text:
        out.append(f'<div class="prompt"><b>Prompt</b>{esc(prompt_text)}</div>')
    if placeholder:
        out.append('<div class="note-banner">Generating walkthrough… this page '
                   'will fill in automatically once the agent finishes (~1 min). Refresh.</div>')
    elif not segments:
        out.append('<p class="empty">No walkthrough segments were produced.</p>')

    for seg in segments:
        if not isinstance(seg, dict):
            continue
        f = seg.get("file", "")
        s, e = seg.get("start"), seg.get("end")
        base = os.path.basename(f) if f else ""
        loc = f"{base}:{s}-{e}" if f else ""
        # Stacked: full-width prose first, then the code collapsed beneath it.
        code = ""
        if f:
            code = (
                f'<details class="seg__codewrap"><summary>{esc(base)} · lines {s}–{e}</summary>'
                f'<div class="seg__code">{code_block(repo, f, s, e)}</div></details>'
            )
        out.append(
            '<div class="seg"><div class="seg__title">'
            f'<span>{esc(str(seg.get("title", "")))}</span>'
            f'<span class="loc">{esc(loc)}</span></div>'
            f'<div class="seg__note">{md2html(seg.get("note", ""))}</div>'
            f'{code}</div>')
    if not placeholder:
        out.append(HLJS_SCRIPTS)
    out.append("</body></html>")
    return "\n".join(out)


def eliciting_prompt(transcript):
    if not transcript or not os.path.isfile(transcript):
        return ""
    try:
        events = [json.loads(l) for l in open(transcript) if l.strip()]
    except Exception:
        return ""
    for e in reversed(events):
        role = e.get("role") or (e.get("message") or {}).get("role")
        if role != "user" or e.get("isMeta"):
            continue
        content = (e.get("message") or e).get("content")
        if isinstance(content, list) and any(
                isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
            continue
        text = content if isinstance(content, str) else ""
        if isinstance(content, list):
            text = "".join(c.get("text", "") for c in content
                           if isinstance(c, dict) and c.get("type") == "text")
        text = " ".join(text.split())
        if text and not text.startswith("<"):
            return text[:280] + ("…" if len(text) > 280 else "")
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="")
    ap.add_argument("--segments")
    ap.add_argument("--repo")
    ap.add_argument("--title", default="Code walkthrough")
    ap.add_argument("--transcript")
    ap.add_argument("--placeholder", action="store_true")
    a = ap.parse_args()

    segments = [] if a.placeholder else load_segments(a.segments)
    out_html = render(segments, a.title, a.url, eliciting_prompt(a.transcript),
                      a.repo, placeholder=a.placeholder)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out_html)
    if a.url:
        print(f"rendered: {a.url}")


if __name__ == "__main__":
    main()
