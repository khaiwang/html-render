#!/usr/bin/env bash
# E2E simulation: drive the Stop hook with fixture transcripts, with a
# stubbed `claude` CLI so we don't actually spawn an LLM. Verify the hook
# constructs the right prompt and would dispatch the renderer correctly.
# Then start the real server, curl it, and confirm pages are served.

set -u
PASS=0
FAIL=0
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN="$ROOT"

# Isolated env
WORK="$(mktemp -d -t htmlrender-e2e.XXXX)"
export HTML_RENDER_DIR="$WORK/data"
export HTML_RENDER_PORT="$(python3 -c "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1]);s.close()")"
mkdir -p "$HTML_RENDER_DIR"

# Stub `claude` on PATH so the hook can "dispatch" without burning tokens.
STUB="$WORK/stub-bin"
PROMPTS_DIR="$WORK/prompts"
mkdir -p "$STUB" "$PROMPTS_DIR"
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
# Pretends to be the claude CLI; writes the prompt it received to a unique file
# and produces a placeholder HTML page so the workflow looks complete.
PROMPT="\$*"
PROMPT_FILE="$PROMPTS_DIR/prompt.\$\$.\$(date +%s%N).txt"
echo "\$PROMPT" > "\$PROMPT_FILE"
OUT_PATH=\$(echo "\$PROMPT" | grep -oE 'Output: [^ ]+' | head -1 | awk '{print \$2}')
if [ -n "\$OUT_PATH" ]; then
  cat > "\$OUT_PATH" <<HTML
<!DOCTYPE html>
<html><head><title>STUB Render — sample</title></head>
<body><p>stub-rendered page</p></body></html>
HTML
fi
exit 0
EOF
chmod +x "$STUB/claude"
export PATH="$STUB:$PATH"

run_hook() {
  local fixture="$1"
  local fake_transcript="$WORK/transcript-$fixture.jsonl"
  cp "$ROOT/tests/fixtures/$fixture" "$fake_transcript"
  echo "{\"transcript_path\": \"$fake_transcript\"}" | bash "$PLUGIN/hooks/stop-classifier.sh"
  sleep 0.4   # let nohup'd stub finish writing
}

count_prompts_with_mode() {
  grep -l "Mode: $1" "$PROMPTS_DIR"/*.txt 2>/dev/null | wc -l | tr -d ' '
}

count_all_prompts() {
  ls "$PROMPTS_DIR"/*.txt 2>/dev/null | wc -l | tr -d ' '
}

expect_dispatched() {
  local label="$1" want_mode="$2" before_count="$3"
  local now_count=$(count_prompts_with_mode "$want_mode")
  if [ "$now_count" -gt "$before_count" ]; then
    echo "  PASS  $label  dispatched with mode=$want_mode (count: $before_count -> $now_count)"
    PASS=$((PASS+1))
  else
    echo "  FAIL  $label  no new dispatch with mode=$want_mode (still $now_count)"
    FAIL=$((FAIL+1))
  fi
}

expect_no_new_dispatch() {
  local label="$1" before_count="$2"
  local now_count=$(count_all_prompts)
  if [ "$now_count" = "$before_count" ]; then
    echo "  PASS  $label  correctly skipped (no new dispatch)"
    PASS=$((PASS+1))
  else
    echo "  FAIL  $label  unexpectedly dispatched (count: $before_count -> $now_count)"
    FAIL=$((FAIL+1))
  fi
}

echo "=== E2E: hook dispatch behavior ==="
before_diff=$(count_prompts_with_mode "diff")
run_hook "edit_turn.jsonl"
expect_dispatched "edit turn" "diff" "$before_diff"

before_narr=$(count_prompts_with_mode "narrative")
run_hook "narrative_plan.jsonl"
expect_dispatched "narrative plan" "narrative" "$before_narr"

before_all=$(count_all_prompts)
run_hook "trivial_reply.jsonl"
expect_no_new_dispatch "trivial reply" "$before_all"

before_all=$(count_all_prompts)
run_hook "long_qa.jsonl"
expect_no_new_dispatch "long Q&A no markers" "$before_all"

echo
echo "=== E2E: rendered file lands in data dir, server serves it ==="

# After dispatching narrative_plan, the stub wrote an HTML file to data dir
ls "$HTML_RENDER_DIR"/*.html >/dev/null 2>&1 || {
  echo "  FAIL  no HTML files were written"
  FAIL=$((FAIL+1))
}

# Start the real server
bash "$PLUGIN/server/start.sh" >/dev/null 2>&1 || {
  echo "  FAIL  server failed to start"; FAIL=$((FAIL+1));
}
sleep 0.5

# Fetch index
INDEX=$(curl -s "http://127.0.0.1:$HTML_RENDER_PORT/")
if echo "$INDEX" | grep -q "STUB Render"; then
  echo "  PASS  index lists the stub-rendered page"
  PASS=$((PASS+1))
else
  echo "  FAIL  index does not list rendered pages"
  echo "$INDEX" | head -20
  FAIL=$((FAIL+1))
fi

# Stop the server
bash "$PLUGIN/server/stop.sh" >/dev/null 2>&1 || true

# Show hook log
echo
echo "=== hook log (last 8 lines) ==="
tail -n 8 "$HTML_RENDER_DIR/.stop-hook.log" 2>/dev/null | sed 's/^/  /'

echo
echo "Result: $PASS passed, $FAIL failed"
echo "Work dir: $WORK"
[ "$FAIL" = "0" ]
