#!/usr/bin/env bash
# model-delegate: 宿主互操作测试
# 验证无 subagent 的宿主（qwencli/pi/Claude 等）仅通过 shell 调用
# 即可完成：单 run → batch fanout → status → aggregate → cancel 全链路
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/run-model.sh"
FANOUT="$ROOT_DIR/scripts/run-model-fanout.sh"

pass=0
fail=0
TEST_TMP=""

setup() {
  TEST_TMP="$(mktemp -d)"
  export MODEL_DELEGATE_STATE_DIR="$TEST_TMP/state"
  mkdir -p "$TEST_TMP/state"
  printf 'Say hello\n' > "$TEST_TMP/prompt.txt"
}

teardown() {
  [[ -n "$TEST_TMP" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
}

# 测试 1: 宿主仅用 shell —— 单 run start/status/final 链路
setup
export FAKE_BACKEND_MODE=success
run_output="$(cd "$TEST_TMP" && "$RUNNER" start \
  --backend test-fake --provider test --model m1 \
  --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" 2>&1)"
run_id="$(printf '%s' "$run_output" | head -1 | jq -r '.runId // empty' 2>/dev/null)"
if [[ -n "$run_id" ]] && [[ -f "$TEST_TMP/state/$run_id/final.md" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: single-run shell interop chain broken\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 2: 宿主仅用 shell —— fanout start → wait → aggregate 链路
setup
cat > "$TEST_TMP/targets.json" <<'EOF'
[
  {"backend": "test-fake", "provider": "test", "model": "m1"},
  {"backend": "test-fake", "provider": "test", "model": "m2"}
]
EOF
export FAKE_BACKEND_MODE=success
batch_output="$(cd "$TEST_TMP" && "$FANOUT" start \
  --targets "$TEST_TMP/targets.json" \
  --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" \
  --max-concurrent 2 --hard-timeout 60 2>&1)"
batch_id="$(printf '%s' "$batch_output" | head -1 | jq -r '.batchId // empty' 2>/dev/null)"
if [[ -z "$batch_id" ]]; then
  printf 'FAIL: fanout start did not emit batchId\n' >&2
  fail=$((fail+1))
else
  # 轮询等待完成（最多 30 秒）
  final_status="running"
  for _ in $(seq 1 30); do
    sleep 1
    final_status="$("$FANOUT" status --batch-id "$batch_id" 2>/dev/null | jq -r '.status // "running"')"
    [[ "$final_status" != "running" ]] && break
  done
  # aggregate 产物存在
  if [[ "$final_status" != "running" ]] \
     && [[ -f "$TEST_TMP/state/$batch_id/results.json" ]] \
     && [[ -f "$TEST_TMP/state/$batch_id/final.md" ]]; then
    pass=$((pass+1))
  else
    printf 'FAIL: fanout aggregate chain broken (status=%s)\n' "$final_status" >&2
    fail=$((fail+1))
  fi
fi
teardown

# 测试 3: 宿主仅用 shell —— 批量 cancel 链路
setup
cat > "$TEST_TMP/targets.json" <<'EOF'
[
  {"backend": "test-fake", "provider": "test", "model": "m1"}
]
EOF
export FAKE_BACKEND_MODE=hang
batch_output="$(cd "$TEST_TMP" && "$FANOUT" start \
  --targets "$TEST_TMP/targets.json" \
  --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" \
  --max-concurrent 1 --hard-timeout 120 2>&1)"
batch_id="$(printf '%s' "$batch_output" | head -1 | jq -r '.batchId // empty' 2>/dev/null)"
sleep 3
cancel_ok="$("$FANOUT" cancel --batch-id "$batch_id" 2>/dev/null | jq -r '.status // ""' 2>/dev/null || echo "")"
# 修复 P2（round18/19）：等待后台 executor 退出后再断言（覆盖 cancel 返回后
# executor 迟到收尾的时序），最终报告必须存在、状态一致、且无 running 残留
exec_pid="$(cat "$TEST_TMP/state/$batch_id/pid" 2>/dev/null || echo "")"
executor_exited=no
if [[ -n "$exec_pid" ]]; then
  for _ in $(seq 1 100); do
    if ! kill -0 "$exec_pid" 2>/dev/null; then
      executor_exited=yes
      break
    fi
    sleep 0.1
  done
else
  executor_exited=yes
fi
if [[ "$executor_exited" == "yes" ]] \
   && [[ "$cancel_ok" == "cancelled" ]] \
   && [[ -f "$TEST_TMP/state/$batch_id/results.json" ]] \
   && [[ "$(jq -r '.status' "$TEST_TMP/state/$batch_id/results.json" 2>/dev/null)" == "cancelled" ]] \
   && [[ "$(jq -r '[.results[] | select(.status == "running")] | length' "$TEST_TMP/state/$batch_id/results.json" 2>/dev/null)" == "0" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: batch cancel interop broken (got: %s, executor exited=%s, report complete=%s)\n' \
    "$cancel_ok" "$executor_exited" "$([[ -f "$TEST_TMP/state/$batch_id/results.json" ]] && echo yes || echo no)" >&2
  fail=$((fail+1))
fi
teardown

# 测试 4: 宿主仅用 shell —— 降级（全部失败）也产出完整 aggregate 报告
setup
cat > "$TEST_TMP/targets.json" <<'EOF'
[
  {"backend": "test-fake", "provider": "test", "model": "m1"},
  {"backend": "test-fake", "provider": "test", "model": "m2"}
]
EOF
export FAKE_BACKEND_MODE=auth-fail
batch_output="$(cd "$TEST_TMP" && "$FANOUT" start \
  --targets "$TEST_TMP/targets.json" \
  --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" \
  --max-concurrent 2 --hard-timeout 60 2>&1)"
batch_id="$(printf '%s' "$batch_output" | head -1 | jq -r '.batchId // empty' 2>/dev/null)"
if [[ -n "$batch_id" ]]; then
  final_status="running"
  for _ in $(seq 1 30); do
    sleep 1
    final_status="$("$FANOUT" status --batch-id "$batch_id" 2>/dev/null | jq -r '.status // "running"')"
    [[ "$final_status" != "running" ]] && break
  done
  if [[ -f "$TEST_TMP/state/$batch_id/results.json" ]]; then
    result_count="$(jq '.results | length' "$TEST_TMP/state/$batch_id/results.json" 2>/dev/null || echo 0)"
    if [[ "$result_count" -eq 2 ]]; then
      pass=$((pass+1))
    else
      printf 'FAIL: partial-failure aggregate incomplete (%s results)\n' "$result_count" >&2
      fail=$((fail+1))
    fi
  else
    printf 'FAIL: partial-failure produced no results.json\n' >&2
    fail=$((fail+1))
  fi
else
  printf 'FAIL: partial-failure batch did not start\n' >&2
  fail=$((fail+1))
fi
teardown

printf '\n== host interop tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
