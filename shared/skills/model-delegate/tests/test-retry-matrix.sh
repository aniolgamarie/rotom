#!/usr/bin/env bash
# model-delegate: 重试矩阵测试
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

# 测试 1: network 错误应标记为可重试
setup
export FAKE_BACKEND_MODE=network-fail
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
failure_mode="$(echo "$receipt" | jq -r '.completion.failure_mode')"
if [[ "$failure_mode" == "network" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: network error should have failure_mode=network\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 2: auth 错误应标记为不可重试
setup
export FAKE_BACKEND_MODE=auth-fail
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
failure_mode="$(echo "$receipt" | jq -r '.completion.failure_mode')"
if [[ "$failure_mode" == "auth" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: auth error should have failure_mode=auth\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 3: protocol 错误应标记为不可重试
setup
export FAKE_BACKEND_MODE=no-agent-end
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
failure_mode="$(echo "$receipt" | jq -r '.completion.failure_mode')"
if [[ "$failure_mode" == "protocol" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: protocol error should have failure_mode=protocol\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 4: invalid_output 错误应标记为不可重试
setup
export FAKE_BACKEND_MODE=invalid-output
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
failure_mode="$(echo "$receipt" | jq -r '.completion.failure_mode')"
if [[ "$failure_mode" == "invalid_output" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: invalid_output error should have failure_mode=invalid_output\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 5: invalid_input 错误应标记为不可重试
setup
export FAKE_BACKEND_MODE=invalid-input
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
failure_mode="$(echo "$receipt" | jq -r '.completion.failure_mode')"
if [[ "$failure_mode" == "invalid_input" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: invalid_input error should have failure_mode=invalid_input\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 6: cancelled 错误应标记为不可重试
setup
export FAKE_BACKEND_MODE=hang
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" &
runner_pid=$!
sleep 2
run_id="$(ls "$TEST_TMP/state" | head -1)"
"$RUNNER" cancel --run-id "$run_id" >/dev/null 2>&1
wait "$runner_pid" 2>/dev/null || true
receipt="$(cat "$TEST_TMP/state/$run_id/status.json")"
failure_mode="$(echo "$receipt" | jq -r '.completion.failure_mode')"
if [[ "$failure_mode" == "cancelled" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: cancelled error should have failure_mode=cancelled\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 7: 成功完成应无 failure_mode
setup
export FAKE_BACKEND_MODE=success
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1)"
receipt="$(echo "$output" | tail -1)"
failure_mode="$(echo "$receipt" | jq -r '.completion.failure_mode')"
if [[ "$failure_mode" == "" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: success should have empty failure_mode\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 8: 退避期间取消 → 不再重启，终态 cancelled（修复 P1 round13）
setup
export FAKE_BACKEND_MODE=network-fail
export MD_RETRY_MAX_ATTEMPTS=3
export MD_RETRY_BASE_DELAY=8
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1 &
runner_pid=$!
# 首次尝试立即失败并进入 8s 退避；2s 时取消，落在退避窗口内
sleep 2
run_id="$(ls "$TEST_TMP/state" | head -1)"
"$RUNNER" cancel --run-id "$run_id" >/dev/null 2>&1
wait "$runner_pid" 2>/dev/null || true
final_status="$(jq -r '.status' "$TEST_TMP/state/$run_id/status.json")"
if [[ "$final_status" == "cancelled" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: cancel during backoff should stay cancelled (got %s)\n' "$final_status" >&2
  fail=$((fail+1))
fi
teardown

# 测试 9: 超时预算耗尽 → 提交 timeout 而非无限重启（修复 P1 round13）
setup
export FAKE_BACKEND_MODE=network-fail
export MD_RETRY_MAX_ATTEMPTS=3
export MD_RETRY_BASE_DELAY=3
output="$($RUNNER start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --hard-timeout 2 2>&1 || true)"
receipt="$(echo "$output" | grep -E '^\{' | tail -1)"
final_status="$(echo "$receipt" | jq -r '.status // ""')"
completion_status="$(echo "$receipt" | jq -r '.completion.status // ""')"
if [[ "$final_status" == "timeout" && "$completion_status" == "failed" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: exhausted budget should commit timeout/failed (got %s/%s)\n' "$final_status" "$completion_status" >&2
  fail=$((fail+1))
fi
teardown

printf '\n== retry matrix tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
