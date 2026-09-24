#!/usr/bin/env bash
# model-delegate: 并发竞态测试
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/run-model.sh"
# 直接 source supervisor 以便测试 md_commit_terminal_status CAS 语义
source "$ROOT_DIR/scripts/lib/supervisor.sh"

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

# 测试 1: 同一 run 重复 cancel（不应崩溃）
setup
export FAKE_BACKEND_MODE=hang
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" &
runner_pid=$!
sleep 2
run_id="$(ls "$TEST_TMP/state" | head -1)"
# 多次 cancel
"$RUNNER" cancel --run-id "$run_id" >/dev/null 2>&1 || true
"$RUNNER" cancel --run-id "$run_id" >/dev/null 2>&1 || true
"$RUNNER" cancel --run-id "$run_id" >/dev/null 2>&1 || true
wait "$runner_pid" 2>/dev/null || true
# 验证 status.json 存在且为终态
if [[ -f "$TEST_TMP/state/$run_id/status.json" ]]; then
  status="$(jq -r '.status' "$TEST_TMP/state/$run_id/status.json")"
  if [[ "$status" == "cancelled" ]]; then
    pass=$((pass+1))
  else
    printf 'FAIL: status should be cancelled\n' >&2
    fail=$((fail+1))
  fi
else
  printf 'FAIL: status.json should exist\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 2: status/cancel 并发（不应崩溃）
setup
export FAKE_BACKEND_MODE=hang
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" &
runner_pid=$!
sleep 2
run_id="$(ls "$TEST_TMP/state" | head -1)"
# 并发 status 和 cancel
"$RUNNER" status --run-id "$run_id" >/dev/null 2>&1 &
"$RUNNER" cancel --run-id "$run_id" >/dev/null 2>&1 &
wait
wait "$runner_pid" 2>/dev/null || true
# 验证最终状态为终态
if [[ -f "$TEST_TMP/state/$run_id/status.json" ]]; then
  terminal="$(jq -r '.terminal' "$TEST_TMP/state/$run_id/status.json")"
  if [[ "$terminal" == "true" ]]; then
    pass=$((pass+1))
  else
    printf 'FAIL: status should be terminal\n' >&2
    fail=$((fail+1))
  fi
else
  printf 'FAIL: status.json should exist\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 3: 超时与正常退出同时发生（不应崩溃）
setup
export FAKE_BACKEND_MODE=success
export FAKE_BACKEND_STEP_DELAY=0.01
# 设置很短的 idle timeout
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --idle-timeout 1 >/dev/null 2>&1 || true
run_id="$(ls "$TEST_TMP/state" | head -1)"
# 验证最终状态为终态
if [[ -f "$TEST_TMP/state/$run_id/status.json" ]]; then
  terminal="$(jq -r '.terminal' "$TEST_TMP/state/$run_id/status.json")"
  if [[ "$terminal" == "true" ]]; then
    pass=$((pass+1))
  else
    printf 'FAIL: status should be terminal\n' >&2
    fail=$((fail+1))
  fi
else
  printf 'FAIL: status.json should exist\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 4: 两个进程争用同一 run-id（应拒绝第二个）
setup
export FAKE_BACKEND_MODE=success
run_id="test-run-001"
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --run-id "$run_id" >/dev/null 2>&1 &
pid1=$!
# 轮询等待第一个 runner 创建 run 目录（避免负载下 0.5s 不够）
for _ in $(seq 1 50); do
  [[ -d "$TEST_TMP/state/$run_id" ]] && break
  sleep 0.1
done
# 尝试启动第二个相同 run-id 的进程
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --run-id "$run_id" >/dev/null 2>&1; then
  printf 'FAIL: second process should be rejected\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
wait "$pid1" 2>/dev/null || true
teardown

# 测试 5: CAS 竞态 —— completed-vs-cancel（cancel 不可覆盖 completed）
setup
export FAKE_BACKEND_MODE=success
run_id="cas-completed-vs-cancel"
run_dir="$TEST_TMP/state/$run_id"
mkdir -p "$run_dir"
completed_json='{"schemaVersion":"1","runId":"cas-completed-vs-cancel","status":"completed","terminal":true}'
md_commit_terminal_status "$run_dir" "$completed_json" >/dev/null 2>&1
# 现在尝试用 cancelled 覆盖（应被拒绝）
cancelled_json='{"schemaVersion":"1","runId":"cas-completed-vs-cancel","status":"cancelled","terminal":true}'
if md_commit_terminal_status "$run_dir" "$cancelled_json" >/dev/null 2>&1; then
  printf 'FAIL: CAS should reject cancel over completed\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
# 验证状态仍为 completed
status="$(jq -r '.status' "$run_dir/status.json")"
[[ "$status" == "completed" ]] && pass=$((pass+1)) || { printf 'FAIL: status changed to %s\n' "$status" >&2; fail=$((fail+1)); }
teardown

# 测试 6: CAS 竞态 —— timeout-vs-complete（两个终端态同时争抢，仅一个赢）
setup
run_id="cas-timeout-vs-complete"
run_dir="$TEST_TMP/state/$run_id"
mkdir -p "$run_dir"
timeout_json='{"schemaVersion":"1","runId":"cas","status":"timeout","terminal":true}'
complete_json='{"schemaVersion":"1","runId":"cas","status":"completed","terminal":true}'
# 并发提交两个不同终态（if-form 捕获 rc，避免 set -e 提前终止子 shell）
( if md_commit_terminal_status "$run_dir" "$timeout_json" >/dev/null 2>&1; then echo 0 > "$TEST_TMP/timeout_rc"; else echo 1 > "$TEST_TMP/timeout_rc"; fi ) &
p1=$!
( if md_commit_terminal_status "$run_dir" "$complete_json" >/dev/null 2>&1; then echo 0 > "$TEST_TMP/complete_rc"; else echo 1 > "$TEST_TMP/complete_rc"; fi ) &
p2=$!
wait "$p1" "$p2" 2>/dev/null || true
rc_timeout="$(cat "$TEST_TMP/timeout_rc")"
rc_complete="$(cat "$TEST_TMP/complete_rc")"
# 恰好一个成功，一个失败
if [[ "$rc_timeout" == "0" && "$rc_complete" == "1" ]] || [[ "$rc_timeout" == "1" && "$rc_complete" == "0" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: expected exactly one CAS winner, got timeout=%s complete=%s\n' "$rc_timeout" "$rc_complete" >&2
  fail=$((fail+1))
fi
teardown

# 测试 7: CAS 竞态 —— 双 cancel（两次并发 cancel，CAS 保证一致）
setup
run_id="cas-double-cancel"
run_dir="$TEST_TMP/state/$run_id"
mkdir -p "$run_dir"
cancel_json='{"schemaVersion":"1","runId":"cas-double-cancel","status":"cancelled","terminal":true}'
# 并发两次 cancel
( if md_commit_terminal_status "$run_dir" "$cancel_json" >/dev/null 2>&1; then echo 0 > "$TEST_TMP/cancel_rc1"; else echo 1 > "$TEST_TMP/cancel_rc1"; fi ) &
p1=$!
( if md_commit_terminal_status "$run_dir" "$cancel_json" >/dev/null 2>&1; then echo 0 > "$TEST_TMP/cancel_rc2"; else echo 1 > "$TEST_TMP/cancel_rc2"; fi ) &
p2=$!
wait "$p1" "$p2" 2>/dev/null || true
rc1="$(cat "$TEST_TMP/cancel_rc1")"
rc2="$(cat "$TEST_TMP/cancel_rc2")"
# 恰好一个赢家（真并发下任意一个子 shell 都可能先拿到锁）
if [[ ( "$rc1" == "0" && "$rc2" == "1" ) || ( "$rc1" == "1" && "$rc2" == "0" ) ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: double cancel should have exactly one winner, got rc1=%s rc2=%s\n' "$rc1" "$rc2" >&2
  fail=$((fail+1))
fi
teardown

# 测试 8: CAS 竞态 —— signal-vs-complete（signal 处理器不覆盖正常完成）
setup
export FAKE_BACKEND_MODE=success
run_id="signal-vs-complete"
run_dir="$TEST_TMP/state/$run_id"
mkdir -p "$run_dir"
# 先正常完成
complete_json='{"schemaVersion":"1","runId":"signal-vs-complete","status":"completed","terminal":true}'
md_commit_terminal_status "$run_dir" "$complete_json" >/dev/null 2>&1
mtime_before="$(stat -c %Y "$run_dir/status.json")"
sleep 1.1
# 模拟 signal 处理器尝试写入 cancelled
signal_json='{"schemaVersion":"1","runId":"signal-vs-complete","status":"cancelled","terminal":true}'
md_commit_terminal_status "$run_dir" "$signal_json" >/dev/null 2>&1 || true
# 状态不被改写
status="$(jq -r '.status' "$run_dir/status.json")"
if [[ "$status" == "completed" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: signal overwrote completed (now %s)\n' "$status" >&2
  fail=$((fail+1))
fi
teardown

# 测试 9: flock 互斥验证（两个进程并发提交，仅一个成功写入）
setup
run_id="flock-mutex"
run_dir="$TEST_TMP/state/$run_id"
mkdir -p "$run_dir"

# 并发两个进程尝试提交不同的终态
json1='{"schemaVersion":"1","runId":"flock-mutex","status":"completed","terminal":true}'
json2='{"schemaVersion":"1","runId":"flock-mutex","status":"failed","terminal":true}'

( if md_commit_terminal_status "$run_dir" "$json1" >/dev/null 2>&1; then echo 0 > "$TEST_TMP/flock_rc1"; else echo 1 > "$TEST_TMP/flock_rc1"; fi ) &
p1=$!
( if md_commit_terminal_status "$run_dir" "$json2" >/dev/null 2>&1; then echo 0 > "$TEST_TMP/flock_rc2"; else echo 1 > "$TEST_TMP/flock_rc2"; fi ) &
p2=$!
wait "$p1" "$p2" 2>/dev/null || true
rc1="$(cat "$TEST_TMP/flock_rc1")"
rc2="$(cat "$TEST_TMP/flock_rc2")"

# 恰好一个成功（第一个获取锁的进程）
if [[ ( "$rc1" == "0" && "$rc2" == "1" ) || ( "$rc1" == "1" && "$rc2" == "0" ) ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: flock mutex should have exactly one winner, got rc1=%s rc2=%s\n' "$rc1" "$rc2" >&2
  fail=$((fail+1))
fi

# 验证最终状态是两者之一
status="$(jq -r '.status' "$run_dir/status.json" 2>/dev/null || echo "")"
if [[ "$status" == "completed" || "$status" == "failed" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: final status should be completed or failed, got %s\n' "$status" >&2
  fail=$((fail+1))
fi
teardown

printf '\n== concurrency tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
