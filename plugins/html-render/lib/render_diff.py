#!/usr/bin/env python3
"""Deterministic git-diff -> HTML renderer.

Renders a unified diff as a clean, GitHub-style table: one continuous code
block per file (single horizontal scroll, no per-line cells/scrollbars),
line-number gutters, and +/- coloring. No LLM involved, so the output is
always aligned and readable.

Usage:
  render_diff.py --out FILE.html --url URL [--diff DIFF_FILE | --git REF]
                 [--transcript T.jsonl] [--repo DIR]
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)")


def read_diff(args):
    if args.diff:
        with open(args.diff, encoding="utf-8", errors="replace") as f:
            return f.read()
    ref = args.git or ""
    cwd = args.repo or os.getcwd()
    parts = []
    try:
        if ref in ("", "working", "HEAD"):
            parts.append(subprocess.run(["git", "diff"], cwd=cwd,
                         capture_output=True, text=True).stdout)
            parts.append(subprocess.run(["git", "diff", "--cached"], cwd=cwd,
                         capture_output=True, text=True).stdout)
        else:
            parts.append(subprocess.run(["git", "diff", ref], cwd=cwd,
                         capture_output=True, text=True).stdout)
    except Exception:
        pass
    return "\n".join(p for p in parts if p)


def parse(diff_text):
    """-> list of files: {path, adds, dels, hunks:[{header, rows}]}.

    rows: (kind, old_no, new_no, text)  kind in {ctx, add, del}.
    """
    files = []
    cur = None
    hunk = None
    old_n = new_n = 0
    for line in diff_text.splitlines():
        if line.startswith("=== "):  # section markers from the hook's .diff
            continue
        if line.startswith("diff --git"):
            m = re.search(r" b/(.+)$", line)
            path = m.group(1) if m else line
            cur = {"path": path, "adds": 0, "dels": 0, "hunks": []}
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if line.startswith("+++ ") or line.startswith("--- ") or \
           line.startswith("index ") or line.startswith("new file") or \
           line.startswith("deleted file") or line.startswith("similarity") or \
           line.startswith("rename ") or line.startswith("old mode") or \
           line.startswith("new mode") or line.startswith("\\ No newline"):
            continue
        m = HUNK_RE.match(line)
        if m:
            old_n, new_n = int(m.group(1)), int(m.group(2))
            hunk = {"header": m.group(3).strip(), "rows": []}
            cur["hunks"].append(hunk)
            continue
        if hunk is None:
            continue
        if line.startswith("+"):
            hunk["rows"].append(("add", "", new_n, line[1:])); new_n += 1; cur["adds"] += 1
        elif line.startswith("-"):
            hunk["rows"].append(("del", old_n, "", line[1:])); old_n += 1; cur["dels"] += 1
        else:  # context (leading space, or blank)
            text = line[1:] if line.startswith(" ") else line
            hunk["rows"].append(("ctx", old_n, new_n, text)); old_n += 1; new_n += 1
    return files


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
            continue  # tool result, not a human message
        text = content if isinstance(content, str) else ""
        if isinstance(content, list):
            text = "".join(c.get("text", "") for c in content
                           if isinstance(c, dict) and c.get("type") == "text")
        text = " ".join(text.split())
        if text and not text.startswith("<"):
            return text[:280] + ("…" if len(text) > 280 else "")
    return ""


CSS = """
:root { color-scheme: light dark; --add-bg:rgba(63,185,80,.15); --del-bg:rgba(248,81,73,.15);
  --add-gut:#2ea043; --del-gut:#cf222e; --border:rgba(127,127,127,.25); --dim:#888; }
* { box-sizing: border-box; }
body { font-family: ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  max-width: 1100px; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.5; }
h1 { font-size: 1.2rem; margin: 0 0 .25rem; }
.meta { color: var(--dim); font-size: .82rem; margin-bottom: .5rem; }
.prompt { margin: .75rem 0 1.5rem; padding: .55rem .85rem; border-left: 3px solid var(--dim);
  background: rgba(127,127,127,.08); color: var(--dim); font-size: .82rem; border-radius: 0 4px 4px 0; }
.prompt b { color: inherit; margin-right: .4rem; }
.file { border: 1px solid var(--border); border-radius: 6px; margin-bottom: 1.5rem; overflow: hidden; }
.file__head { display:flex; justify-content:space-between; gap:1rem; align-items:baseline;
  padding: .5rem .8rem; background: rgba(127,127,127,.08); border-bottom: 1px solid var(--border);
  font-size: .85rem; font-weight: 600; }
.file__stat { font-weight: 400; font-size: .78rem; }
.file__stat .a { color: var(--add-gut); } .file__stat .d { color: var(--del-gut); }
.scroll { overflow-x: auto; }                 /* ONE scrollbar for the whole file */
table.diff { border-collapse: collapse; width: 100%; font-size: 12.5px; }
table.diff td { padding: 0 .3rem; vertical-align: top; }
td.ln { width: 1%; min-width: 3rem; text-align: right; color: var(--dim); user-select: none;
  white-space: nowrap; border-right: 1px solid var(--border); padding: 0 .5rem; }
td.code { white-space: pre; padding-left: .6rem; width: 100%; }
tr.add td.code { background: var(--add-bg); } tr.add td.ln { background: var(--add-bg); }
tr.del td.code { background: var(--del-bg); } tr.del td.ln { background: var(--del-bg); }
tr.add td.code::before { content:"+"; color: var(--add-gut); }
tr.del td.code::before { content:"-"; color: var(--del-gut); }
tr.ctx td.code::before { content:" "; }
tr.hunk td { background: rgba(127,127,127,.06); color: var(--dim); font-size: .75rem;
  padding: .25rem .8rem; border-top: 1px solid var(--border); }
.empty { color: var(--dim); font-style: italic; }
"""


def esc(s):
    return html.escape(s, quote=False)


def render(files, title, url, prompt_text):
    out = []
    total_a = sum(f["adds"] for f in files)
    total_d = sum(f["dels"] for f in files)
    out.append(f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
               f'<meta name="viewport" content="width=device-width, initial-scale=1">'
               f'<title>{esc(title)}</title><style>{CSS}</style></head><body>')
    out.append(f"<h1>{esc(title)}</h1>")
    out.append(f'<div class="meta">{len(files)} file(s) · '
               f'<span style="color:var(--add-gut)">+{total_a}</span> '
               f'<span style="color:var(--del-gut)">−{total_d}</span> · '
               f'{datetime.now().strftime("%Y-%m-%d %H:%M")}</div>')
    if prompt_text:
        out.append(f'<div class="prompt"><b>Prompt</b>{esc(prompt_text)}</div>')
    if not files:
        out.append('<p class="empty">No changes to show.</p>')
    for f in files:
        out.append('<div class="file"><div class="file__head">'
                   f'<span>{esc(f["path"])}</span>'
                   f'<span class="file__stat"><span class="a">+{f["adds"]}</span> '
                   f'<span class="d">−{f["dels"]}</span></span></div>'
                   '<div class="scroll"><table class="diff"><tbody>')
        for h in f["hunks"]:
            hdr = f"@@ {esc(h['header'])}" if h["header"] else "@@"
            out.append(f'<tr class="hunk"><td colspan="3">{hdr}</td></tr>')
            for kind, oldn, newn, text in h["rows"]:
                out.append(
                    f'<tr class="{kind}"><td class="ln">{oldn}</td>'
                    f'<td class="ln">{newn}</td>'
                    f'<td class="code">{esc(text)}</td></tr>')
        out.append("</tbody></table></div></div>")
    out.append("</body></html>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="")
    ap.add_argument("--diff")
    ap.add_argument("--git")
    ap.add_argument("--repo")
    ap.add_argument("--transcript")
    ap.add_argument("--title")
    a = ap.parse_args()

    files = parse(read_diff(a))
    if a.title:
        title = a.title
    elif len(files) == 1:
        title = f"{os.path.basename(files[0]['path'])} — diff"
    elif files:
        title = f"diff — {len(files)} files changed"
    else:
        title = "diff — no changes"

    out_html = render(files, title, a.url, eliciting_prompt(a.transcript))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out_html)
    if a.url:
        print(f"rendered: {a.url}")


if __name__ == "__main__":
    main()
