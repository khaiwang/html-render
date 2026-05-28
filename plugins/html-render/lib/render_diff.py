#!/usr/bin/env python3
"""Deterministic git-diff -> HTML renderer (side-by-side, optional explanations).

Renders a unified diff as a clean two-column side-by-side table
(before | after): one continuous, single-scroll block per file with
line-number gutters and +/- coloring. No LLM in the layout, so it's always
aligned — no per-line cells/scrollbars.

If --explanations is given (a JSON array of strings, one per hunk in order,
typically produced by the LLM), a third column is added: each explanation
spans its hunk's rows via a deterministic rowspan (Python computes it, so it
can't misalign).

Usage:
  render_diff.py --out FILE.html --url URL [--diff DIFF_FILE | --git REF]
                 [--transcript T.jsonl] [--repo DIR] [--title T]
                 [--explanations EXPL_FILE]
"""
import argparse
import html
import json
import os
import re
import subprocess
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
    """-> list of files: {path, adds, dels, hunks:[{header, rows}]}."""
    files, cur, hunk = [], None, None
    old_n = new_n = 0
    for line in diff_text.splitlines():
        if line.startswith("=== "):
            continue
        if line.startswith("diff --git"):
            m = re.search(r" b/(.+)$", line)
            cur = {"path": m.group(1) if m else line, "adds": 0, "dels": 0, "hunks": []}
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if line[:4] in ("+++ ", "--- ") or line.startswith((
                "index ", "new file", "deleted file", "similarity",
                "rename ", "old mode", "new mode", "\\ No newline")):
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
        else:
            text = line[1:] if line.startswith(" ") else line
            hunk["rows"].append(("ctx", old_n, new_n, text)); old_n += 1; new_n += 1
    return files


def side_by_side(rows):
    """Pair a hunk's rows into side-by-side (left, right) display rows."""
    out, dels, adds = [], [], []

    def flush():
        for i in range(max(len(dels), len(adds))):
            left = (dels[i][0], dels[i][1], "del") if i < len(dels) else None
            right = (adds[i][0], adds[i][1], "add") if i < len(adds) else None
            out.append((left, right))
        dels.clear(); adds.clear()

    for kind, oldn, newn, text in rows:
        if kind == "del":
            dels.append((oldn, text))
        elif kind == "add":
            adds.append((newn, text))
        else:
            flush()
            out.append(((oldn, text, "ctx"), (newn, text, "ctx")))
    flush()
    return out


def load_explanations(path):
    if not path or not os.path.isfile(path):
        return []
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
    return [str(x) for x in data] if isinstance(data, list) else []


CSS = """
:root { color-scheme: light dark; --add-bg:rgba(63,185,80,.16); --del-bg:rgba(248,81,73,.16);
  --add-gut:#2ea043; --del-gut:#cf222e; --border:rgba(127,127,127,.25); --dim:#888;
  --blank:rgba(127,127,127,.05); --why-bg:rgba(101,116,205,.08);
  --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
* { box-sizing: border-box; }
body { font-family: ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  max-width: 1400px; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.5; }
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
.scroll { overflow-x: auto; }
table.diff { border-collapse: collapse; width: 100%; font-size: 12.5px; table-layout: fixed; }
table.diff td { padding: 0 .3rem; vertical-align: top; }
td.ln { text-align: right; color: var(--dim); user-select: none; white-space: nowrap; padding: 0 .5rem; }
td.code { white-space: pre; overflow-wrap: anywhere; padding-left: .4rem; }
table.diff.with-why td.code { white-space: pre-wrap; }   /* wrap so the why column stays visible */
td.code.del { background: var(--del-bg); } td.ln.del { background: var(--del-bg); }
td.code.add { background: var(--add-bg); } td.ln.add { background: var(--add-bg); }
td.code.blank, td.ln.blank { background: var(--blank); }
td.code.del::before { content:"- "; color: var(--del-gut); }
td.code.add::before { content:"+ "; color: var(--add-gut); }
td.ln.new, td.code.new-side { border-left: 1px solid var(--border); }
td.why { white-space: normal; font-family: var(--sans); font-size: 12px; line-height: 1.45;
  color: var(--dim); background: var(--why-bg); border-left: 2px solid var(--border);
  padding: .35rem .7rem; vertical-align: top; }
tr.hunk td { background: rgba(127,127,127,.06); color: var(--dim); font-size: .75rem;
  padding: .25rem .8rem; border-top: 1px solid var(--border); }
.empty { color: var(--dim); font-style: italic; }
.narrative { background: rgba(127,127,127,.05); border: 1px solid var(--border);
  border-radius: 8px; padding: .8rem 1.1rem; margin-bottom: 1.5rem;
  font-family: var(--sans); font-size: 14px; line-height: 1.55; }
.narrative p { margin: 0 0 .6rem; }
.narrative ul, .narrative ol { margin: 0 0 .6rem; padding-left: 1.3rem; }
.narrative li { margin-bottom: .3rem; }
.narrative h3, .narrative h4, .narrative h5, .narrative h6 {
  font-family: var(--sans); margin: .7rem 0 .35rem; line-height: 1.25; font-weight: 600; }
.narrative h3 { font-size: 1rem; } .narrative h4 { font-size: .94rem; }
.narrative h5, .narrative h6 { font-size: .88rem; color: var(--dim); }
.narrative code { font-family: ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size: .9em; background: rgba(127,127,127,.15); padding: .05rem .3rem; border-radius: 3px; }
.narrative pre.cb { background: rgba(127,127,127,.08); border: 1px solid var(--border);
  border-radius: 5px; padding: .5rem .7rem; overflow-x: auto; font-size: 12px; margin: 0 0 .6rem; }
.narrative pre.cb code { background: none; padding: 0; }
"""


def esc(s):
    return html.escape(s, quote=False)


def md_inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md2html(text):
    out, list_type, in_code, code = [], None, False, []

    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>"); list_type = None

    def flush_code():
        nonlocal in_code, code
        body = "\n".join(html.escape(c, quote=False) for c in code)
        out.append(f'<pre class="cb"><code>{body}</code></pre>')
        code, in_code = [], False

    for ln in str(text).split("\n"):
        if ln.strip().startswith("```"):
            if in_code: flush_code()
            else: close_list(); in_code = True
            continue
        if in_code:
            code.append(ln); continue
        st = ln.strip()
        if not st:
            close_list(); continue
        h = re.match(r"^(#{1,6})\s+(.*)", st)
        if h:
            close_list()
            lvl = min(6, len(h.group(1)) + 2)
            out.append(f"<h{lvl}>{md_inline(h.group(2))}</h{lvl}>"); continue
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
    if in_code: flush_code()
    close_list()
    return "\n".join(out)


def last_assistant_text(transcript):
    """Assistant prose from the most recent turn (since the last human msg)."""
    if not transcript or not os.path.isfile(transcript):
        return ""
    try:
        events = [json.loads(l) for l in open(transcript) if l.strip()]
    except Exception:
        return ""

    def role(e):
        return e.get("role") or (e.get("message") or {}).get("role")

    def is_human(e):
        if role(e) != "user" or e.get("isMeta"):
            return False
        c = (e.get("message") or e).get("content")
        if isinstance(c, str):
            return True
        if isinstance(c, list):
            return "tool_result" not in {x.get("type") for x in c if isinstance(x, dict)}
        return False

    last_user = -1
    for i in range(len(events) - 1, -1, -1):
        if is_human(events[i]):
            last_user = i; break
    parts = []
    for e in events[last_user + 1:]:
        if role(e) != "assistant":
            continue
        c = (e.get("message") or e).get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for x in c:
                if isinstance(x, dict) and x.get("type") == "text":
                    parts.append(x.get("text", ""))
    return "\n".join(parts).strip()


def cell(item, new_side):
    ln_extra = " new" if new_side else ""
    code_extra = " new-side" if new_side else ""
    if item is None:
        return (f'<td class="ln blank{ln_extra}"></td>'
                f'<td class="code blank{code_extra}"></td>')
    lineno, text, css = item
    return (f'<td class="ln {css}{ln_extra}">{lineno}</td>'
            f'<td class="code {css}{code_extra}">{esc(text)}</td>')


def render(files, title, url, prompt_text, explanations, narrative=""):
    has_why = bool(explanations)
    ncols = 5 if has_why else 4
    total_a = sum(f["adds"] for f in files)
    total_d = sum(f["dels"] for f in files)
    out = [f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<title>{esc(title)}</title><style>{CSS}</style></head><body>',
           f"<h1>{esc(title)}</h1>",
           f'<div class="meta">{len(files)} file(s) · '
           f'<span style="color:var(--add-gut)">+{total_a}</span> '
           f'<span style="color:var(--del-gut)">−{total_d}</span> · '
           f'{datetime.now().strftime("%Y-%m-%d %H:%M")}</div>']
    if prompt_text:
        out.append(f'<div class="prompt"><b>Prompt</b>{esc(prompt_text)}</div>')
    # The assistant's prose around the edits — render above the diff so the
    # explanation isn't discarded when a turn has both narrative + edits.
    if narrative and len(narrative) >= 20:
        out.append(f'<div class="narrative">{md2html(narrative)}</div>')
    if not files:
        out.append('<p class="empty">No changes to show.</p>')

    if has_why:
        cols = ('<colgroup><col style="width:4%"><col style="width:31%">'
                '<col style="width:4%"><col style="width:31%">'
                '<col style="width:30%"></colgroup>')
    else:
        cols = ('<colgroup><col style="width:5%"><col style="width:45%">'
                '<col style="width:5%"><col style="width:45%"></colgroup>')

    hunk_idx = 0
    for f in files:
        cls = "diff with-why" if has_why else "diff"
        out.append('<div class="file"><div class="file__head">'
                   f'<span>{esc(f["path"])}</span>'
                   f'<span class="file__stat"><span class="a">+{f["adds"]}</span> '
                   f'<span class="d">−{f["dels"]}</span></span></div>'
                   f'<div class="scroll"><table class="{cls}">{cols}<tbody>')
        for h in f["hunks"]:
            hdr = f"@@ {esc(h['header'])}" if h["header"] else "@@"
            out.append(f'<tr class="hunk"><td colspan="{ncols}">{hdr}</td></tr>')
            rows = side_by_side(h["rows"])
            expl = explanations[hunk_idx] if hunk_idx < len(explanations) else ""
            hunk_idx += 1
            for r_i, (left, right) in enumerate(rows):
                cells = cell(left, False) + cell(right, True)
                if has_why and r_i == 0:
                    cells += f'<td class="why" rowspan="{len(rows)}">{esc(expl)}</td>'
                out.append("<tr>" + cells + "</tr>")
        out.append("</tbody></table></div></div>")
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
    ap.add_argument("--diff")
    ap.add_argument("--git")
    ap.add_argument("--repo")
    ap.add_argument("--transcript")
    ap.add_argument("--title")
    ap.add_argument("--explanations")
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

    out_html = render(files, title, a.url, eliciting_prompt(a.transcript),
                      load_explanations(a.explanations),
                      narrative=last_assistant_text(a.transcript))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out_html)
    if a.url:
        print(f"rendered: {a.url}")


if __name__ == "__main__":
    main()
