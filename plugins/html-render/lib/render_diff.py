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
@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root { color-scheme: light dark;
  --sans:'Hanken Grotesk',ui-sans-serif,system-ui,-apple-system,sans-serif;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --bg:#fafafa; --surface:#ffffff; --surface-dim:#f1f1f3; --text:#1a1a1f; --dim:#6b7280;
  --border:#e3e3e8; --accent:#2563eb; --accent-soft:rgba(37,99,235,.10);
  --add-bg:rgba(35,160,85,.12); --del-bg:rgba(210,55,55,.10);
  --add-gut:#1a7f37; --del-gut:#c0362c; --blank:rgba(130,130,140,.05);
  --why-bg:rgba(130,130,140,.06); }
@media (prefers-color-scheme: dark) { :root {
  --bg:#161618; --surface:#1d1d20; --surface-dim:#26262a; --text:#e9e9ec; --dim:#9aa0a6;
  --border:rgba(255,255,255,.11); --accent:#7aa2f7; --accent-soft:rgba(122,162,247,.14);
  --add-bg:rgba(60,170,90,.18); --del-bg:rgba(220,80,70,.18); --blank:rgba(255,255,255,.04);
  --why-bg:rgba(255,255,255,.05); } }
* { box-sizing: border-box; }
body { font-family: var(--mono); background: var(--bg); color: var(--text);
  max-width: 1400px; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.5; }
h1 { font-family: var(--sans); font-size: 1.4rem; font-weight: 700; letter-spacing:-.01em; margin: 0 0 .3rem; }
.meta { color: var(--dim); font-size: .82rem; margin-bottom: .5rem; font-family: var(--sans); }
.prompt { margin: .75rem 0 1.5rem; padding: .55rem .85rem; border-left: 3px solid var(--accent);
  background: var(--accent-soft); color: var(--dim); font-size: .82rem; border-radius: 0 4px 4px 0;
  font-family: var(--sans); }
.prompt b { color: var(--text); margin-right: .4rem; }
.file { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 1.5rem; overflow: hidden;
  background: var(--surface); }
.file__head { display:flex; justify-content:space-between; gap:1rem; align-items:baseline;
  padding: .5rem .8rem; background: var(--surface-dim); border-bottom: 1px solid var(--border);
  font-size: .85rem; font-weight: 600; font-family: var(--sans); }
.file__stat { font-weight: 400; font-size: .78rem; }
.file__stat .a { color: var(--add-gut); } .file__stat .d { color: var(--del-gut); }
.scroll { overflow-x: auto; }
table.diff { border-collapse: collapse; width: 100%; font-size: 12.5px; table-layout: fixed; }
table.diff td { padding: 0 .3rem; vertical-align: top; }
td.ln { text-align: right; color: var(--dim); user-select: none; white-space: nowrap; padding: 0 .5rem; }
/* Always wrap code: with table-layout:fixed, non-wrapping lines overflow into
   adjacent columns and shove the explanation out. Wrapping keeps every cell
   inside its column. Indentation is preserved by pre-wrap. */
td.code { white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
  padding-left: .4rem; min-width: 0; }
td.code.del { background: var(--del-bg); } td.ln.del { background: var(--del-bg); }
td.code.add { background: var(--add-bg); } td.ln.add { background: var(--add-bg); }
td.code.blank, td.ln.blank { background: var(--blank); }
td.code.del::before { content:"- "; color: var(--del-gut); }
td.code.add::before { content:"+ "; color: var(--add-gut); }
td.ln.new, td.code.new-side { border-left: 1px solid var(--border); }
td.why { white-space: normal; font-family: var(--sans); font-size: 12px; line-height: 1.45;
  color: var(--dim); background: var(--why-bg); border-left: 2px solid var(--accent);
  padding: .35rem .7rem; vertical-align: top; }
tr.hunk td { background: var(--surface-dim); color: var(--dim); font-size: .75rem;
  padding: .25rem .8rem; border-top: 1px solid var(--border); font-family: var(--sans); }
.empty { color: var(--dim); font-style: italic; }
.xref { margin: 0 0 1.25rem; }
.xref a { display: inline-block; padding: .4rem .8rem; border-radius: 6px; font-family: var(--sans);
  font-size: 14px; border: 1px solid var(--border); background: var(--surface-dim);
  color: var(--accent); text-decoration: none; font-weight: 500; }
.xref a:hover { border-color: var(--accent); }
"""


def esc(s):
    return html.escape(s, quote=False)


def cell(item, new_side):
    ln_extra = " new" if new_side else ""
    code_extra = " new-side" if new_side else ""
    if item is None:
        return (f'<td class="ln blank{ln_extra}"></td>'
                f'<td class="code blank{code_extra}"></td>')
    lineno, text, css = item
    return (f'<td class="ln {css}{ln_extra}">{lineno}</td>'
            f'<td class="code {css}{code_extra}">{esc(text)}</td>')


def render(files, title, url, prompt_text, explanations, related=None):
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
    # Cross-link to the companion explanation page (when a turn had both a diff
    # and a narrative explanation, each is rendered on its own page).
    if related and related.get("url"):
        out.append(f'<div class="xref"><a href="{esc(related["url"])}">'
                   f'{esc(related.get("label", "Explanation →"))}</a></div>')
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
    ap.add_argument("--related-url")
    ap.add_argument("--related-label", default="Explanation →")
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

    related = {"url": a.related_url, "label": a.related_label} if a.related_url else None
    out_html = render(files, title, a.url, eliciting_prompt(a.transcript),
                      load_explanations(a.explanations), related=related)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out_html)
    if a.url:
        print(f"rendered: {a.url}")


if __name__ == "__main__":
    main()
