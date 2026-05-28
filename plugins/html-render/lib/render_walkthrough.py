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
    out, in_ul = [], False
    for ln in str(text).split("\n"):
        st = ln.strip()
        if not st:
            if in_ul:
                out.append("</ul>"); in_ul = False
            continue
        m = re.match(r"^[-*•]\s+(.*)", st)
        if m:
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append(f"<li>{md_inline(m.group(1))}</li>")
        else:
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append(f"<p>{md_inline(st)}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


CSS = """
:root { color-scheme: light dark; --border:rgba(127,127,127,.25); --dim:#888;
  --code-bg:rgba(127,127,127,.06); --note-bg:rgba(101,116,205,.06);
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
* { box-sizing: border-box; }
body { font-family: var(--sans); max-width: 1500px; margin: 2rem auto;
  padding: 0 1.25rem; line-height: 1.55; }
h1 { font-family: var(--sans); font-weight: 600; font-size: 1.5rem; margin: 0 0 .25rem; }
.meta { color: var(--dim); font-size: .82rem; margin-bottom: .5rem; }
.prompt { margin: .75rem 0 1.5rem; padding: .55rem .85rem; border-left: 3px solid var(--dim);
  background: rgba(127,127,127,.08); color: var(--dim); font-size: .85rem; border-radius: 0 4px 4px 0; }
.prompt b { color: inherit; margin-right: .4rem; }
.seg { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 1.5rem; overflow: hidden; }
.seg__title { font-family: var(--sans); font-weight: 600; font-size: .95rem;
  padding: .55rem .9rem; background: rgba(127,127,127,.08); border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; gap: 1rem; align-items: baseline; }
.seg__title .loc { font-weight: 400; font-size: .78rem; color: var(--dim); font-family: var(--mono); }
.seg__body { display: grid; grid-template-columns: 1fr 1fr; align-items: stretch; }
@media (max-width: 950px) { .seg__body { grid-template-columns: 1fr; } }
.seg__code { background: var(--code-bg); overflow-x: auto; border-right: 1px solid var(--border);
  font-family: var(--mono); font-size: 12.5px; padding: .5rem 0; }
.cl { display: flex; white-space: pre; }
.cl .ln { width: 3.2em; flex: 0 0 auto; text-align: right; padding: 0 .7em; color: var(--dim);
  user-select: none; }
.cl code { font-family: var(--mono); }
.cl.miss { color: var(--dim); font-style: italic; padding: .3rem 1rem; }
.seg__note { background: var(--note-bg); padding: .6rem 1rem; font-size: 13.5px; }
.seg__note p { margin: 0 0 .6rem; } .seg__note ul { margin: 0 0 .6rem; padding-left: 1.2rem; }
.seg__note li { margin-bottom: .3rem; }
.seg__note code { font-family: var(--mono); font-size: .9em; background: rgba(127,127,127,.15);
  padding: .05rem .3rem; border-radius: 3px; }
.empty { color: var(--dim); font-style: italic; }
.note-banner { background: rgba(212,167,58,.14); border:1px solid rgba(212,167,58,.4);
  border-radius:6px; padding:.5rem .85rem; font-size:.85rem; margin-bottom:1.25rem; }
"""


def esc(s):
    return html.escape(s, quote=False)


def code_block(repo, path, start, end):
    lines = file_lines(repo, path)
    if lines is None:
        return f'<div class="cl miss">({esc(path or "?")} not found)</div>'
    try:
        s = max(1, int(start)); e = int(end)
    except (TypeError, ValueError):
        s, e = 1, len(lines)
    if e < s or e <= 0:
        e = len(lines)
    rows = []
    for n in range(s, min(e, len(lines)) + 1):
        rows.append(f'<div class="cl"><span class="ln">{n}</span>'
                    f'<code>{esc(lines[n - 1])}</code></div>')
    return "".join(rows) or '<div class="cl miss">(empty range)</div>'


def render(segments, title, url, prompt_text, repo, placeholder=False):
    out = [f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<title>{esc(title)}</title><style>{CSS}</style></head><body>',
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
        loc = f"{os.path.basename(f) if f else ''}:{s}-{e}" if f else ""
        out.append(
            '<div class="seg"><div class="seg__title">'
            f'<span>{esc(str(seg.get("title", "")))}</span>'
            f'<span class="loc">{esc(loc)}</span></div>'
            '<div class="seg__body">'
            f'<div class="seg__code">{code_block(repo, f, s, e)}</div>'
            f'<div class="seg__note">{md2html(seg.get("note", ""))}</div>'
            '</div></div>')
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
