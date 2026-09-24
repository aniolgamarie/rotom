#!/usr/bin/env bash
# model-delegate: fan-out 测试
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FANOUT_RUNNER="$ROOT_DIR/scripts/run-model-fanout.sh"

pass=0
fail=0

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

TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

export MODEL_DELEGATE_STATE_DIR="$TEST_TMP/state"
mkdir -p "$TEST_TMP/state"
echo "test prompt" > "$TEST_TMP/prompt.txt"

# 测试 1: 创建 targets JSON
cat > "$TEST_TMP/targets.json" <<'EOF'
[
  {"backend": "test-fake", "provider": "test", "model": "model1"},
  {"backend": "test-fake", "provider": "test", "model": "model2"}
]
EOF

assert_file_exists "$TEST_TMP/targets.json"

# 测试 2: 启动 fan-out（使用 test-fake backend）
export FAKE_BACKEND_MODE=success
output="$("$FANOUT_RUNNER" start \
  --targets "$TEST_TMP/targets.json" \
  --cwd "$TEST_TMP" \
  --prompt-file "$TEST_TMP/prompt.txt" \
  --max-concurrent 2 \
  --hard-timeout 30 2>&1)"

receipt="$(echo "$output" | head -1)"
assert_field_eq "$receipt" '.status' "running" "fan-out start status"
batch_id="$(echo "$receipt" | jq -r '.batchId')"

# 等待执行完成（最多 10 秒）
for i in {1..20}; do
  status_output="$("$FANOUT_RUNNER" status --batch-id "$batch_id" 2>&1)"
  batch_status="$(echo "$status_output" | jq -r '.status')"
  if [[ "$batch_status" != "running" ]]; then
    break
  fi
  sleep 1 # wait
done

# 测试 3: 验证 batch 状态
assert_field_eq "$status_output" '.status' "completed" "fan-out batch status"

# 测试 4: 验证 runs 数量
run_count="$(echo "$status_output" | jq '.runs | length')"
if [[ "$run_count" -eq 2 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: expected 2 runs, got %s\n' "$run_count" >&2
  fail=$((fail+1))
fi

# 测试 5: 生成聚合报告
aggregate_output="$("$FANOUT_RUNNER" aggregate --batch-id "$batch_id" 2>&1)"
assert_field_eq "$aggregate_output" '.status' "completed" "aggregate status"

# 测试 6: 验证 results.json 和 final.md 生成
batch_dir="$TEST_TMP/state/$batch_id"
assert_file_exists "$batch_dir/results.json"
assert_file_exists "$batch_dir/final.md"

# 测试 7: 验证 results.json 内容
results="$(cat "$batch_dir/results.json")"
result_count="$(echo "$results" | jq '.results | length')"
if [[ "$result_count" -eq 2 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: expected 2 results, got %s\n' "$result_count" >&2
  fail=$((fail+1))
fi

# 测试 8: 测试 fail-fast
cat > "$TEST_TMP/targets-fail.json" <<'EOF'
[
  {"backend": "test-fake", "provider": "test", "model": "model1"},
  {"backend": "test-fake", "provider": "test", "model": "model2"}
]
EOF

export FAKE_BACKEND_MODE=auth-fail
output="$("$FANOUT_RUNNER" start \
  --targets "$TEST_TMP/targets-fail.json" \
  --cwd "$TEST_TMP" \
  --prompt-file "$TEST_TMP/prompt.txt" \
  --max-concurrent 1 \
  --hard-timeout 30 \
  --fail-fast 2>&1 || true)"

receipt="$(echo "$output" | head -1)"
batch_id2="$(echo "$receipt" | jq -r '.batchId')"

# 等待执行完成
for i in {1..20}; do
  status_output="$("$FANOUT_RUNNER" status --batch-id "$batch_id2" 2>&1)"
  batch_status="$(echo "$status_output" | jq -r '.status')"
  if [[ "$batch_status" != "running" ]]; then
    break
  fi
  sleep 1 # wait
done

# 测试 9: 验证全部失败场景（两个 target 均 auth-fail → status=failed，仍产出报告）
assert_field_eq "$status_output" '.status' "failed" "all-fail batch status"

# 测试 10: 测试 batch cancel
export FAKE_BACKEND_MODE=hang
output="$("$FANOUT_RUNNER" start \
  --targets "$TEST_TMP/targets.json" \
  --cwd "$TEST_TMP" \
  --prompt-file "$TEST_TMP/prompt.txt" \
  --max-concurrent 2 \
  --hard-timeout 60 2>&1)"

receipt="$(echo "$output" | head -1)"
batch_id3="$(echo "$receipt" | jq -r '.batchId')"

sleep 2

# 取消 batch
cancel_output="$("$FANOUT_RUNNER" cancel --batch-id "$batch_id3" 2>&1)"
assert_field_eq "$cancel_output" '.status' "cancelled" "batch cancel status"

# 测试 11: 路径遍历攻击（batch-id 包含 ..）
if "$FANOUT_RUNNER" status --batch-id "../etc" 2>/dev/null; then
  printf 'FAIL: path traversal should be rejected\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 12: 路径遍历攻击（batch-id 包含 /）
if "$FANOUT_RUNNER" cancel --batch-id "/tmp/malicious" 2>/dev/null; then
  printf 'FAIL: absolute path should be rejected\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 测试 13: 非法字符 batch-id
if "$FANOUT_RUNNER" aggregate --batch-id "test.batch" 2>/dev/null; then
  printf 'FAIL: invalid characters should be rejected\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi

printf '\n== fan-out tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
