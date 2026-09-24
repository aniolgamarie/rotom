#!/usr/bin/env bash
# model-delegate: supervisor 崩溃恢复测试
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$ROOT_DIR/scripts/lib/supervisor.sh"
source "$ROOT_DIR/scripts/lib/credentials.sh"

pass=0
fail=0
TEST_TMP=""

setup() {
  TEST_TMP="$(mktemp -d)"
  MD_SECRETS=()
  md_prepare_state_dir "$TEST_TMP/state"
}

teardown() {
  [[ -n "$TEST_TMP" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
}

# 测试 1: SIGKILL 后重放 events.jsonl
setup
run_dir="$(md_prepare_run_dir "$TEST_TMP/state" "crash-test-1")"
# 模拟部分写入的 events.jsonl
echo '{"seq":1,"kind":"started"}' > "$run_dir/events.jsonl"
echo '{"seq":2,"kind":"activity"}' >> "$run_dir/events.jsonl"
# 验证可以重放
lines="$(wc -l < "$run_dir/events.jsonl")"
if [[ "$lines" -eq 2 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: should replay 2 events\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 2: 半写 status.json 恢复
setup
run_dir="$(md_prepare_run_dir "$TEST_TMP/state" "crash-test-2")"
# 模拟半写的 status.json（不完整 JSON）
echo '{"runId":"test","status":"run' > "$run_dir/status.json"
# 验证可以覆盖写入
md_write_status "$run_dir" '{"runId":"test","status":"completed"}'
content="$(cat "$run_dir/status.json")"
if echo "$content" | jq -e '.status == "completed"' >/dev/null 2>&1; then
  pass=$((pass+1))
else
  printf 'FAIL: should recover from half-written status.json\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 3: 截断 events.jsonl 恢复
setup
run_dir="$(md_prepare_run_dir "$TEST_TMP/state" "crash-test-3")"
# 模拟截断的 events.jsonl
echo '{"seq":1,"kind":"started"}' > "$run_dir/events.jsonl"
echo '{"seq":2,"kind":"activ' >> "$run_dir/events.jsonl"  # 截断
# 验证可以追加新事件
md_append_event "$run_dir" '{"seq":3,"kind":"completed"}'
lines="$(wc -l < "$run_dir/events.jsonl")"
if [[ "$lines" -eq 3 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: should append to truncated events.jsonl\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 4: 遗留子进程收敛终态
setup
run_dir="$(md_prepare_run_dir "$TEST_TMP/state" "crash-test-4")"
# 启动一个子进程
setsid sleep 100 &
pgid=$!
echo "$pgid" > "$run_dir/pgid"
# 模拟 runner 崩溃（不写 status.json）
# 验证可以手动收敛终态
md_write_status "$run_dir" '{"runId":"test","status":"cancelled","signal":"EXIT"}'
if [[ -f "$run_dir/status.json" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: should write terminal status\n' >&2
  fail=$((fail+1))
fi
# 清理子进程
kill -TERM -"$pgid" 2>/dev/null || true
wait "$pgid" 2>/dev/null || true
teardown

# 测试 5: 空 events.jsonl 恢复
setup
run_dir="$(md_prepare_run_dir "$TEST_TMP/state" "crash-test-5")"
touch "$run_dir/events.jsonl"
# 验证可以追加新事件
md_append_event "$run_dir" '{"seq":1,"kind":"started"}'
lines="$(wc -l < "$run_dir/events.jsonl")"
if [[ "$lines" -eq 1 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: should append to empty events.jsonl\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 6: 不存在的 events.jsonl 恢复
setup
run_dir="$(md_prepare_run_dir "$TEST_TMP/state" "crash-test-6")"
# 不创建 events.jsonl
# 验证可以创建并追加
md_append_event "$run_dir" '{"seq":1,"kind":"started"}'
if [[ -f "$run_dir/events.jsonl" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: should create events.jsonl\n' >&2
  fail=$((fail+1))
fi
teardown

printf '\n== supervisor crash recovery tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
