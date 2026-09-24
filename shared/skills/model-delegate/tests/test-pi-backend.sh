#!/usr/bin/env bash
# model-delegate: Pi backend 端到端测试（使用 fake backend）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/run-model.sh"
TEST_TMP=""
pass=0
fail=0

setup() {
  TEST_TMP="$(mktemp -d)"
  export MODEL_DELEGATE_STATE_DIR="$TEST_TMP/state"
  mkdir -p "$TEST_TMP/state"
  echo "test prompt" > "$TEST_TMP/prompt.txt"
}

teardown() {
  [[ -n "$TEST_TMP" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
}

# assert_field_eq <actual_json> <jq_field> <expected_value> <msg>
assert_field_eq() {
  local actual="$1" field="$2" expected="$3" msg="${4:-}"
  local act_val
  act_val="$(printf '%s' "$actual" | jq -r "$field" 2>/dev/null || printf 'null')"
  if [[ "$act_val" == "$expected" ]]; then
    pass=$((pass+1))
  else
    printf 'FAIL: %s\n  field: %s\n  expected: %s\n  actual:   %s\n' "$msg" "$field" "$expected" "$act_val" >&2
    fail=$((fail+1))
  fi
}

assert_file_exists() {
  if [[ -f "$1" ]]; then
    pass=$((pass+1))
  else
    printf 'FAIL: file not found: %s\n' "$1" >&2
    fail=$((fail+1))
  fi
}

# 测试 1: 成功 run
setup
export FAKE_BACKEND_MODE=success
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1)"
receipt="$(echo "$output" | tail -1)"
assert_field_eq "$receipt" '.status' "completed" "success run status"
run_id="$(echo "$receipt" | jq -r '.runId')"
assert_file_exists "$TEST_TMP/state/$run_id/final.md"
final_text="$(cat "$TEST_TMP/state/$run_id/final.md")"
[[ "$final_text" == "Hello world" ]] && pass=$((pass+1)) || { printf 'FAIL: final text\n' >&2; fail=$((fail+1)); }
teardown

# 测试 2: auth 失败
setup
export FAKE_BACKEND_MODE=auth-fail
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
assert_field_eq "$receipt" '.completion.failure_mode' "auth" "auth failure mode"
teardown

# 测试 3: network 失败
setup
export FAKE_BACKEND_MODE=network-fail
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
assert_field_eq "$receipt" '.completion.failure_mode' "network" "network failure mode"
teardown

# 测试 4: invalid_input 失败
setup
export FAKE_BACKEND_MODE=invalid-input
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
assert_field_eq "$receipt" '.completion.failure_mode' "invalid_input" "invalid_input failure mode"
teardown

# 测试 5: invalid_output（非 JSON 输出）
setup
export FAKE_BACKEND_MODE=invalid-output
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
assert_field_eq "$receipt" '.completion.failure_mode' "invalid_output" "invalid_output failure mode"
teardown

# 测试 6: no-agent-end（protocol 错误）
setup
export FAKE_BACKEND_MODE=no-agent-end
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
assert_field_eq "$receipt" '.completion.failure_mode' "protocol" "no agent_end → protocol"
teardown

# 测试 7: empty-final（incomplete）
setup
export FAKE_BACKEND_MODE=empty-final
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
assert_field_eq "$receipt" '.completion.status' "incomplete" "empty final → incomplete"
teardown

# 测试 8: idle timeout
setup
export FAKE_BACKEND_MODE=hang
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --idle-timeout 3 2>&1 || true)"
receipt="$(echo "$output" | tail -1)"
assert_field_eq "$receipt" '.status' "idle_timeout" "idle timeout"
assert_field_eq "$receipt" '.completion.failure_mode' "network" "idle timeout failure_mode"
teardown

# 测试 9: cancel
setup
export FAKE_BACKEND_MODE=hang
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" &
runner_pid=$!
sleep 2
run_id="$(ls "$TEST_TMP/state" | head -1)"
"$RUNNER" cancel --run-id "$run_id" >/dev/null 2>&1
wait "$runner_pid" 2>/dev/null || true
receipt="$(cat "$TEST_TMP/state/$run_id/status.json")"
assert_field_eq "$receipt" '.status' "cancelled" "cancel status"
teardown

# 测试 10: status 命令
setup
export FAKE_BACKEND_MODE=success
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1
run_id="$(ls "$TEST_TMP/state" | head -1)"
status_output="$("$RUNNER" status --run-id "$run_id")"
assert_field_eq "$status_output" '.terminal' "true" "status terminal"
teardown

# 测试 11: resume 命令
setup
export FAKE_BACKEND_MODE=success
# 第一次启动
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1)"
receipt="$(echo "$output" | tail -1)"
run_id="$(echo "$receipt" | jq -r '.runId')"
# 验证第一次运行成功
assert_field_eq "$receipt" '.status' "completed" "first run status"
# 获取 session ID
session_id="$(echo "$receipt" | jq -r '.backend.resumeToken')"
[[ -n "$session_id" ]] && pass=$((pass+1)) || { printf 'FAIL: no session id\n' >&2; fail=$((fail+1)); }
# 第二次启动（resume）
echo "follow-up prompt" > "$TEST_TMP/prompt2.txt"
output2="$("$RUNNER" resume --run-id "$run_id" --prompt-file "$TEST_TMP/prompt2.txt" 2>&1 || true)"
receipt2="$(echo "$output2" | tail -1)"
# 验证 resume 成功（test-fake backend 支持 resume）
assert_field_eq "$receipt2" '.status' "completed" "resume status"
# 验证新 run 目录
run_id2="$(echo "$receipt2" | jq -r '.runId')"
[[ "$run_id" != "$run_id2" ]] && pass=$((pass+1)) || { printf 'FAIL: resume should create new run dir\n' >&2; fail=$((fail+1)); }
teardown

# 测试 12: cwd 断言
setup
export FAKE_BACKEND_MODE=success
# 创建特定的 cwd 目录
CWD_DIR="$TEST_TMP/custom_cwd"
mkdir -p "$CWD_DIR"
# 设置环境变量日志文件
ENV_LOG_FILE="$TEST_TMP/env.log"
export FAKE_BACKEND_ENV_LOG="$ENV_LOG_FILE"
# 启动 run
output="$("$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$CWD_DIR" --prompt-file "$TEST_TMP/prompt.txt" 2>&1)"
receipt="$(echo "$output" | tail -1)"
# 验证运行成功
assert_field_eq "$receipt" '.status' "completed" "cwd test status"
# 验证 PWD 环境变量匹配 cwd
if [[ -f "$ENV_LOG_FILE" ]]; then
  actual_pwd="$(grep '^PWD=' "$ENV_LOG_FILE" | cut -d= -f2-)"
  if [[ "$actual_pwd" == "$CWD_DIR" ]]; then
    pass=$((pass+1))
  else
    printf 'FAIL: PWD mismatch\n  expected: %s\n  actual:   %s\n' "$CWD_DIR" "$actual_pwd" >&2
    fail=$((fail+1))
  fi
else
  printf 'FAIL: ENV_LOG_FILE not created\n' >&2
  fail=$((fail+1))
fi
teardown

printf '\n== pi-backend tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
