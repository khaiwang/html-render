#!/usr/bin/env python3
"""Extract just the last assistant turn (+ eliciting prompt) from a Claude Code
transcript, as a small markdown file for the renderer to consume.

The transcript JSONL grows to MANY MB over a session, but a render only needs
the final turn (a few % of the file). Handing the LLM renderer the whole
transcript makes it read ~hundreds of K tokens — the dominant cause of multi-
minute renders. We do the extraction here (deterministic, instant) so the agent
reads a tiny file instead.

  extract_turn.py <transcript.jsonl> <out.md>

Writes <out.md> and prints its path. On any failure, writes a minimal file
pointing back at the transcript so the renderer can still fall back.
"""
import json
import os
import sys


def role_of(e):
    return e.get("role") or (e.get("message") or {}).get("role")


def is_human(e):
    # A genuine human turn. Claude Code records tool results as role 'user'
    # too; exclude those so the boundary is the real prompt, not a tool result.
    if role_of(e) != "user" or e.get("isMeta"):
        return False
    content = (e.get("message") or e).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        types = {c.get("type") for c in content if isinstance(c, dict)}
        return "tool_result" not in types
    return False


def msg_text(e):
    content = (e.get("message") or e).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content
                       if isinstance(c, dict) and c.get("type") == "text")
    return ""


def extract(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        events = [json.loads(line) for line in f if line.strip()]
    last_user = -1
    for i in range(len(events) - 1, -1, -1):
        if is_human(events[i]):
            last_user = i
            break
    prompt = msg_text(events[last_user]).strip() if last_user >= 0 else ""
    since = events[last_user + 1:] if last_user >= 0 else events
    chunks = []
    for e in since:
        if role_of(e) != "assistant":
            continue
        chunks.append(msg_text(e))
    return prompt, "\n".join(c for c in chunks if c).strip()


def main():
    transcript, out = sys.argv[1], sys.argv[2]
    try:
        prompt, turn = extract(transcript)
    except Exception as exc:  # fall back: leave a pointer to the transcript
        prompt, turn = "", ""
        sys.stderr.write(f"extract_turn: {exc}\n")
    body = []
    body.append("<!-- Eliciting user prompt (for the {{PROMPT}} block; do not render as content) -->")
    body.append("# Eliciting prompt\n")
    body.append(prompt if prompt else "(none found)")
    body.append("\n---\n")
    body.append("<!-- The assistant turn to render as the page body -->")
    body.append("# Assistant turn to render\n")
    body.append(turn if turn else f"(could not extract; read the transcript at {transcript})")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(body) + "\n")
    print(out)


if __name__ == "__main__":
    main()
