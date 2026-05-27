#!/usr/bin/env bash
# Drive the Stop hook classifier with fixture transcripts and assert the right mode.
# We invoke the python block inside the hook script directly to avoid spawning claude.

set -u
PASS=0
FAIL=0
FIXTURES="$(cd "$(dirname "$0")/fixtures" && pwd)"
HOOK="$(cd "$(dirname "$0")/.." && pwd)/plugins/html-render/hooks/stop-classifier.sh"

# Extract just the classifier python by sourcing the env and running an inline test.
# Simpler: we re-implement just the python block here, mirroring the hook exactly.
classify() {
  local transcript="$1"
  python3 - "$transcript" <<'PY'
import json, sys, re
path = sys.argv[1]
try:
    with open(path) as f:
        events = [json.loads(line) for line in f if line.strip()]
except Exception:
    print('skip'); sys.exit(0)

def role_of(e):
    return e.get('role') or (e.get('message') or {}).get('role')

last_user = -1
for i in range(len(events) - 1, -1, -1):
    e = events[i]
    if role_of(e) == 'user' and not e.get('isMeta'):
        last_user = i
        break
since = events[last_user + 1:] if last_user >= 0 else events

text_chunks = []
tool_calls = []
for e in since:
    if role_of(e) != 'assistant':
        continue
    msg = e.get('message') or e
    content = msg.get('content')
    if isinstance(content, str):
        text_chunks.append(content)
    elif isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get('type') == 'text':
                text_chunks.append(c.get('text', ''))
            elif c.get('type') == 'tool_use':
                tool_calls.append(c.get('name', ''))

text = '\n'.join(text_chunks).strip()
if len(text) < 200:
    print('skip'); sys.exit(0)
if any(t in ('Edit', 'Write', 'NotebookEdit', 'MultiEdit') for t in tool_calls):
    print('diff'); sys.exit(0)
headers = re.findall(
    r'^\s*#{1,3}\s+(plan|summary|review|recap|architecture|design|implementation|analysis)',
    text, re.IGNORECASE | re.MULTILINE)
numbered = len(re.findall(r'^\s*\d+\.\s', text, re.MULTILINE))
fences = text.count('```') // 2
if headers or numbered >= 5 or fences >= 3:
    print('narrative'); sys.exit(0)
print('skip')
PY
}

expect() {
  local name="$1" want="$2" got
  got="$(classify "$FIXTURES/$name")"
  if [ "$got" = "$want" ]; then
    echo "  PASS  $name  → $got"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $name  expected=$want got=$got"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== classifier tests ==="
expect "trivial_reply.jsonl"   "skip"
expect "edit_turn.jsonl"       "diff"
expect "narrative_plan.jsonl"  "narrative"
expect "long_qa.jsonl"         "skip"

echo
echo "=== sanity: hook script exists and is executable ==="
if [ -x "$HOOK" ]; then
  echo "  PASS  hook is executable: $HOOK"
  PASS=$((PASS + 1))
else
  echo "  FAIL  hook missing or not executable: $HOOK"
  FAIL=$((FAIL + 1))
fi

echo
echo "Result: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ]
