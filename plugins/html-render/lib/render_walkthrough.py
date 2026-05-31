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


def _callout_kind(line):
    """Detect a callout paragraph → (kind, body) or None. Recognizes the
    leading '▎' rail and common emoji/keyword markers used in walkthroughs."""
    s = line.lstrip("▎ \t").strip()
    table = [
        ("warn", ("⚠️", "⚠", "warning:", "caution:", "gotcha:")),
        ("bug", ("🐞", "🐛", "bug:", "finding:", "issue:")),
        ("tip", ("💡", "✅", "note:", "tip:", "key:", "🔑", "📌")),
    ]
    low = s.lower()
    for kind, markers in table:
        for m in markers:
            if s.startswith(m) or low.startswith(m):
                return kind, s[len(m):].lstrip(" :").strip() or s
    # A bare '▎ ' rail with no marker → neutral callout.
    if line.lstrip().startswith("▎"):
        return "note", s
    return None


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
        callout = _callout_kind(st)
        ol = re.match(r"^(\d+)[.)]\s+(.*)", st)
        ul = re.match(r"^[-*•]\s+(.*)", st)
        if callout:
            close_list()
            kind, body = callout
            out.append(f'<div class="callout callout-{kind}">{md_inline(body)}</div>')
        elif ol:
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


# Core palette/fonts/reset come from /_assets/base.css (linked in the head).
# Layout mirrors the narrative template: sticky-sidebar TOC + paper article.
CSS = """
:root { --max:820px; }
body { margin:0; background:var(--bg); color:var(--text); font-family:var(--sans);
  font-size:16px; line-height:1.65; -webkit-font-smoothing:antialiased; }

/* shell */
.shell { display:grid; grid-template-columns:268px minmax(0,1fr); max-width:1480px; margin:0 auto; }
.toc { position:sticky; top:0; align-self:start; height:100vh; overflow-y:auto;
  padding:38px 22px 40px 30px; border-right:1px solid var(--border);
  background:linear-gradient(180deg,#fbfaf7,#f5f4f0); }
.toc__brand { font-family:var(--display); font-weight:700; font-size:.74rem; letter-spacing:.16em;
  text-transform:uppercase; color:var(--accent); margin:0 0 4px; }
.toc__sub { font-size:.78rem; color:var(--text-dim); margin:0 0 22px; line-height:1.4; }
.toc nav { display:flex; flex-direction:column; gap:1px; }
.toc a { display:flex; gap:8px; align-items:baseline; text-decoration:none; color:var(--text-soft);
  font-size:.84rem; padding:6px 10px; border-radius:7px; border-left:2px solid transparent;
  transition:background .15s,color .15s,border-color .15s; }
.toc a:hover { background:#eef0eb; color:var(--text); }
.toc a.active { background:var(--accent-soft); color:var(--accent); border-left-color:var(--accent); font-weight:600; }
.toc a .num { font-family:var(--mono); font-size:.72rem; color:var(--text-dim); flex:0 0 auto; }
.toc a.active .num { color:var(--accent); }
.toc a .loc { display:block; font-family:var(--mono); font-size:.68rem; color:var(--text-dim); margin-top:1px; }

.main { min-width:0; }
.article { background:var(--surface); min-height:100vh; padding:56px clamp(24px,4vw,64px) 120px; }
.prose { max-width:var(--max); margin:0 auto; }

h1.title { font-family:var(--display); font-weight:700; font-size:clamp(1.8rem,3.4vw,2.5rem);
  line-height:1.1; letter-spacing:-.018em; margin:0 0 16px; }
.prompt { margin:0 0 1.8rem; padding:.6rem .9rem; border-left:3px solid var(--accent);
  background:var(--accent-soft); color:var(--text-soft); font-size:.85rem; line-height:1.5; border-radius:0 6px 6px 0; }
.prompt b { color:var(--text); margin-right:.4rem; }
.note-banner { background:var(--amber-soft); border:1px solid var(--amber-line); border-radius:8px;
  padding:.6rem .9rem; font-size:.88rem; margin-bottom:1.25rem; }
.empty { color:var(--text-dim); font-style:italic; }

/* segments — narrative-primary: prose first, code collapsible under it */
.seg { margin-bottom:2.4em; scroll-margin-top:24px; }
.seg__title { font-family:var(--display); font-weight:700; font-size:1.4rem; letter-spacing:-.01em;
  margin:0 0 .5em; padding-bottom:.25em; border-bottom:1px solid var(--border);
  display:flex; gap:.5em; align-items:baseline; }
.seg__n { font-family:var(--mono); font-size:1rem; color:var(--accent); font-weight:600; }
.seg__title .loc { margin-left:auto; font-weight:400; font-size:.74rem; color:var(--text-dim);
  font-family:var(--mono); white-space:nowrap; }
.seg__note { font-size:16px; color:var(--text); }
.seg__note p { margin:1em 0; } .seg__note > :first-child { margin-top:0; }
.seg__note ul, .seg__note ol { margin:1em 0; padding-left:1.35em; }
.seg__note li { margin:.45em 0; } .seg__note li::marker { color:var(--accent); }
.seg__note b, .seg__note strong { font-weight:700; color:var(--text); }
.seg__note a { color:var(--accent); text-decoration:none; border-bottom:1px solid var(--accent-line); }
.seg__note a:hover { border-bottom-color:var(--accent); }
.seg__note h3, .seg__note h4, .seg__note h5, .seg__note h6 {
  font-family:var(--display); font-weight:600; line-height:1.2; }
.seg__note h3 { font-size:1.18rem; margin:1.4em 0 .4em; }
.seg__note h4 { font-size:1.04rem; margin:1.2em 0 .35em; }
.seg__note h5 { font-size:.9rem; margin:1em 0 .3em; text-transform:uppercase; letter-spacing:.04em; color:var(--text-dim); }
.seg__note h6 { font-size:.85rem; margin:.9em 0 .3em; color:var(--text-dim); }
.seg__note code { font-family:var(--mono); font-size:.86em; background:var(--code-bg);
  border:1px solid var(--border-soft); border-radius:5px; padding:1px 6px; color:#3a4256; white-space:nowrap; }
.seg__note pre.cb { background:var(--code-bg); border:1px solid var(--border); border-radius:10px;
  padding:14px 18px; overflow-x:auto; font-size:.84rem; margin:1.2em 0; }
.seg__note pre.cb code { background:none; border:0; padding:0; color:#41485c; white-space:pre; }

/* callouts (markdown ▎ rails → boxes) */
.seg__note .callout { margin:1.3em 0; border-radius:12px; padding:14px 18px 12px; border:1px solid var(--border);
  background:#fbfaf7; font-size:.95rem; }
.callout-warn { background:var(--amber-soft); border-color:var(--amber-line); border-left:4px solid var(--amber); }
.callout-bug { background:var(--red-soft); border-color:var(--red-line); border-left:4px solid var(--red); }
.callout-tip { background:var(--accent-soft); border-color:var(--accent-line); border-left:4px solid var(--accent); }
.callout-note { border-left:4px solid var(--text-dim); }

/* collapsible code */
.seg__codewrap { margin:1.2em 0 0; border:1px solid var(--border); border-radius:11px; overflow:hidden; background:var(--code-bg); }
.seg__codewrap > summary { cursor:pointer; user-select:none; list-style:none; padding:.55rem 1rem;
  font-family:var(--mono); font-size:.78rem; color:var(--accent); background:#fbfaf7; border-bottom:1px solid var(--border); }
.seg__codewrap:not([open]) > summary { border-bottom:0; }
.seg__codewrap > summary::-webkit-details-marker { display:none; }
.seg__codewrap > summary::before { content:"▸ "; }
.seg__codewrap[open] > summary::before { content:"▾ "; }
.seg__codewrap > summary:hover { color:var(--text); }
.seg__code { overflow:auto; max-height:460px; font-family:var(--mono); font-size:12.5px; line-height:1.55; }
.seg__code pre { margin:0; padding:.7rem .9rem; white-space:pre; }
.seg__code code { font-family:var(--mono); }
/* highlight.js: let our container provide the background/padding */
.hljs { background:transparent !important; padding:0 !important; }
/* highlightjs-line-numbers plugin renders a table. Our sliced copies live in a
   <div> (not a <pre>), so the code cell MUST set white-space:pre itself or
   leading indentation collapses. */
.seg__code table.hljs-ln { border-collapse:collapse; width:100%; margin:.6rem 0; }
.hljs-ln td { padding:0; border:0; vertical-align:top; }
.hljs-ln-numbers { text-align:right; color:var(--text-dim); user-select:none;
  padding:0 1em 0 .8rem; white-space:nowrap; border-right:1px solid var(--border); }
.hljs-ln-code { white-space:pre; padding:0 .8rem 0 1em; }
.miss { color:var(--text-dim); font-style:italic; padding:.6rem .9rem; }
.srcpool { display:none; }

@media(max-width:1000px){ .shell { grid-template-columns:1fr; } .toc { display:none; } }
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

# highlight.js theme (light-only, to match the page palette).
HLJS_HEAD = (
    '<link rel="stylesheet" '
    'href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/atom-one-light.min.css">'
)
HLJS_SCRIPTS = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlightjs-line-numbers.js/2.8.0/highlightjs-line-numbers.min.js"></script>
<script>
(function(){
  if (!window.hljs) return;  // offline → plain fallbacks remain, still readable
  // 1) Highlight each FULL source file once (correct multi-line context) and
  //    number its lines. Slicing a fragment instead would mis-color code that
  //    spans the cut (docstrings, block comments).
  document.querySelectorAll('.srcfull code').forEach(function(el){
    try { hljs.highlightElement(el); } catch (e) {}
    try { if (hljs.lineNumbersBlock) hljs.lineNumbersBlock(el, {startFrom: 1}); } catch (e) {}
  });
  // 2) Inline note snippets: highlight only (no line numbers).
  document.querySelectorAll('.seg__note pre code').forEach(function(el){
    try { hljs.highlightElement(el); } catch (e) {}
  });
  // 3) Once the line-numbers tables exist, copy each section's line range out
  //    of its full-file table. If anything fails, the plain slice stays.
  function sliceAll(){
    document.querySelectorAll('.seg__code[data-src]').forEach(function(box){
      try {
        var src = document.getElementById(box.getAttribute('data-src'));
        var table = src && src.querySelector('table.hljs-ln');
        if (!table) return;
        var s = parseInt(box.getAttribute('data-start'), 10);
        var e = parseInt(box.getAttribute('data-end'), 10);
        var tbody = document.createElement('tbody');
        table.querySelectorAll('tr').forEach(function(tr){
          var cell = tr.querySelector('.hljs-ln-code');
          var n = cell ? parseInt(cell.getAttribute('data-line-number'), 10) : 0;
          if (n >= s && n <= e) tbody.appendChild(tr.cloneNode(true));
        });
        if (tbody.children.length){
          var t = document.createElement('table');
          t.className = 'hljs hljs-ln';
          t.appendChild(tbody);
          box.innerHTML = '';
          box.appendChild(t);
        }
      } catch (e) {}
    });
  }
  (function wait(n){
    if (document.querySelector('.srcfull table.hljs-ln') || n <= 0) return sliceAll();
    setTimeout(function(){ wait(n - 1); }, 30);
  })(25);
})();
// Sidebar scroll-spy: highlight the section currently in view.
(function(){
  var nav = document.getElementById('toc-nav');
  if (!nav) return;
  var links = Array.prototype.slice.call(nav.querySelectorAll('a'));
  var map = {}, targets = [];
  links.forEach(function(a){
    var id = a.getAttribute('href').slice(1);
    var t = document.getElementById(id);
    if (t){ map[id] = a; targets.push(t); }
  });
  function onScroll(){
    var top = window.scrollY + 120, cur = null;
    targets.forEach(function(t){ if (t.offsetTop <= top) cur = t.id; });
    links.forEach(function(a){ a.classList.remove('active'); });
    if (cur && map[cur]) map[cur].classList.add('active');
  }
  window.addEventListener('scroll', onScroll, {passive:true});
  onScroll();
})();
</script>"""


def lang_for(path):
    ext = os.path.splitext(path or "")[1].lower().lstrip(".")
    if not ext and os.path.basename(path or "").lower() == "dockerfile":
        ext = "dockerfile"
    return EXT_LANG.get(ext, "")


def clamp_range(lines, start, end):
    try:
        s = max(1, int(start)); e = int(end)
    except (TypeError, ValueError):
        s, e = 1, len(lines)
    if e < s or e <= 0:
        e = len(lines)
    return s, min(e, len(lines))


def render(segments, title, url, prompt_text, repo, placeholder=False):
    head_extra = "" if placeholder else HLJS_HEAD
    head = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{esc(title)}</title>'
            f'<link rel="stylesheet" href="/_assets/base.css">'
            f'{head_extra}<style>{CSS}</style></head><body>')

    if placeholder:
        return (head + '<div class="shell"><main class="main"><article class="article">'
                f'<div class="prose"><h1 class="title">{esc(title)}</h1>'
                '<div class="note-banner">Generating walkthrough… this page will fill in '
                'automatically once the agent finishes (~1 min). Refresh.</div>'
                '</div></article></main></div></body></html>')

    segs = [s for s in segments if isinstance(s, dict)]

    # Sticky sidebar TOC, built from the segments (numbers + file:line locs).
    nav = []
    for i, seg in enumerate(segs, 1):
        f = seg.get("file", "")
        base = os.path.basename(f) if f else ""
        s, e = seg.get("start"), seg.get("end")
        locb = f'<span class="loc">{esc(base)}:{s}–{e}</span>' if f else ""
        nav.append(f'<a href="#seg-{i}"><span class="num">{i}</span>'
                   f'<span>{esc(str(seg.get("title", "") or "section"))}{locb}</span></a>')
    sidebar = (f'<aside class="toc"><p class="toc__brand">Walkthrough</p>'
               f'<p class="toc__sub">{esc(title)}</p>'
               f'<nav id="toc-nav">{"".join(nav)}</nav></aside>')

    out = [head, '<div class="shell">', sidebar,
           '<main class="main"><article class="article"><div class="prose">',
           f'<h1 class="title">{esc(title)}</h1>']
    if prompt_text:
        out.append(f'<div class="prompt"><b>Prompt</b>{esc(prompt_text)}</div>')
    if not segs:
        out.append('<p class="empty">No walkthrough segments were produced.</p>')

    # Embed each referenced file ONCE (deduped). Highlighting happens on the
    # whole file (correct multi-line context); each section then shows only its
    # slice. Slicing a fragment and highlighting that is what mis-colors code
    # (a range cutting through a docstring leaves unbalanced quotes).
    sources = {}   # file-string -> {"id","lines","lang"}

    def source_for(fpath):
        if fpath in sources:
            return sources[fpath]
        lines = file_lines(repo, fpath)
        if lines is None:
            sources[fpath] = None
            return None
        sources[fpath] = {"id": f"src-{len(sources)}", "lines": lines,
                          "lang": lang_for(fpath)}
        return sources[fpath]

    for i, seg in enumerate(segs, 1):
        f = seg.get("file", "")
        s, e = seg.get("start"), seg.get("end")
        base = os.path.basename(f) if f else ""
        loc = f"{base}:{s}-{e}" if f else ""
        code = ""
        if f:
            src = source_for(f)
            if src is None:
                inner = f'<div class="miss">({esc(f)} not found)</div>'
            else:
                a, b = clamp_range(src["lines"], s, e)
                snippet = "\n".join(src["lines"][a - 1:b])
                # Plain fallback (shown if JS/CDN fails); JS replaces it with the
                # correctly-highlighted slice taken from the full-file render.
                inner = (f'<div class="seg__code" data-src="{src["id"]}" '
                         f'data-start="{a}" data-end="{b}">'
                         f'<pre><code>{esc(snippet)}</code></pre></div>')
            code = (f'<details class="seg__codewrap" open>'
                    f'<summary>{esc(base)} · lines {s}–{e}</summary>{inner}</details>')
        out.append(
            f'<section class="seg" id="seg-{i}">'
            f'<div class="seg__title"><span class="seg__n">{i}</span>'
            f'{esc(str(seg.get("title", "")))}'
            f'<span class="loc">{esc(loc)}</span></div>'
            f'<div class="seg__note">{md2html(seg.get("note", ""))}</div>'
            f'{code}</section>')

    out.append('</div></article></main></div>')  # close .prose / .article / .main / .shell

    # Hidden full-file sources for correct, context-aware highlighting.
    pool = []
    for src in sources.values():
        if not src:
            continue
        cls = f' class="language-{src["lang"]}"' if src["lang"] else ""
        body = esc("\n".join(src["lines"]))
        pool.append(f'<pre class="srcfull" id="{src["id"]}"><code{cls}>{body}</code></pre>')
    if pool:
        out.append(f'<div class="srcpool" hidden aria-hidden="true">{"".join(pool)}</div>')

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
