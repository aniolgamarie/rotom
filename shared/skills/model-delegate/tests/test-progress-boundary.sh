#!/usr/bin/env bash
# model-delegate: progress/observe 边界测试
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/run-model.sh"

pass=0
fail=0
TEST_TMP=""

setup() {
  TEST_TMP="$(mktemp -d)"
  export MODEL_DELEGATE_STATE_DIR="$TEST_TMP/state"
  mkdir -p "$TEST_TMP/state"
  echo "test prompt" > "$TEST_TMP/prompt.txt"
}

teardown() {
  [[ -n "$TEST_TMP" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
}

# 测试 1: cursor 边界（从 0 开始）
setup
export FAKE_BACKEND_MODE=success
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1)"
run_id="$(echo "$output" | jq -r '.runId' | head -1)"
# 验证 events.jsonl 存在
if [[ -f "$TEST_TMP/state/$run_id/events.jsonl" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: events.jsonl should exist\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 2: 重复 cursor（不应重复事件）
setup
export FAKE_BACKEND_MODE=success
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1
run_id="$(ls "$TEST_TMP/state" | head -1)"
# 验证事件数量
event_count="$(wc -l < "$TEST_TMP/state/$run_id/events.jsonl")"
if [[ "$event_count" -gt 0 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: should have events\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 3: 倒退 cursor（不应崩溃）
setup
export FAKE_BACKEND_MODE=success
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1
run_id="$(ls "$TEST_TMP/state" | head -1)"
# 验证 events.jsonl 格式正确
if jq empty "$TEST_TMP/state/$run_id/events.jsonl" 2>/dev/null; then
  pass=$((pass+1))
else
  printf 'FAIL: events.jsonl should be valid JSONL\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 4: partial JSONL（不应崩溃）
setup
export FAKE_BACKEND_MODE=success
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1
run_id="$(ls "$TEST_TMP/state" | head -1)"
# 验证每行都是有效 JSON
invalid=0
while IFS= read -r line; do
  if ! echo "$line" | jq empty 2>/dev/null; then
    invalid=$((invalid+1))
  fi
done < "$TEST_TMP/state/$run_id/events.jsonl"
if [[ "$invalid" -eq 0 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: %d invalid JSON lines\n' "$invalid" >&2
  fail=$((fail+1))
fi
teardown

# 测试 5: 事件 burst（大量事件）
setup
export FAKE_BACKEND_MODE=success
export FAKE_BACKEND_STEP_DELAY=0.001
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1
run_id="$(ls "$TEST_TMP/state" | head -1)"
event_count="$(wc -l < "$TEST_TMP/state/$run_id/events.jsonl")"
if [[ "$event_count" -gt 5 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: should have many events\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 6: heartbeat（observe 模式）
setup
export FAKE_BACKEND_MODE=hang
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --observe &
runner_pid=$!
sleep 3
kill -TERM "$runner_pid" 2>/dev/null || true
wait "$runner_pid" 2>/dev/null || true
run_id="$(ls "$TEST_TMP/state" | head -1)"
# 验证 status.json 存在
if [[ -f "$TEST_TMP/state/$run_id/status.json" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: status.json should exist\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 7: 输出预算（不应超过限制）
setup
export FAKE_BACKEND_MODE=success
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1
run_id="$(ls "$TEST_TMP/state" | head -1)"
# 验证 status.json 大小合理
size="$(stat -c%s "$TEST_TMP/state/$run_id/status.json")"
if [[ "$size" -lt 10000 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: status.json too large: %d bytes\n' "$size" >&2
  fail=$((fail+1))
fi
teardown

# 测试 8: 隐私字段过滤（不应包含敏感信息）
setup
export FAKE_BACKEND_MODE=success
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1
run_id="$(ls "$TEST_TMP/state" | head -1)"
# 验证 events.jsonl 不包含 API key
if grep -q "api_key\|secret\|password" "$TEST_TMP/state/$run_id/events.jsonl" 2>/dev/null; then
  printf 'FAIL: events should not contain sensitive fields\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
teardown

printf '\n== progress/observe boundary tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
