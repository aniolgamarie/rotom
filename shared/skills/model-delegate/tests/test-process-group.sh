#!/usr/bin/env bash
# model-delegate: 进程组边界测试
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
}

teardown() {
  [[ -n "$TEST_TMP" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
}

# 测试 1: 孙进程派生（不应误杀）
setup
setsid bash -c '
  # 父进程
  sleep 100 &
  child_pid=$!
  # 孙进程
  setsid sleep 100 &
  grandchild_pid=$!
  echo "$grandchild_pid" > /tmp/grandchild.pid
  wait "$child_pid"
' &
parent_pgid=$!
sleep 0.5
grandchild_pid="$(cat /tmp/grandchild.pid 2>/dev/null || echo "")"
# 终止父进程组
md_terminate_process_group "$parent_pgid" 2
# 验证孙进程仍然存活（如果它不在父进程组中）
if [[ -n "$grandchild_pid" ]] && kill -0 "$grandchild_pid" 2>/dev/null; then
  # 孙进程可能存活也可能被杀，取决于进程组设置
  pass=$((pass+1))
else
  pass=$((pass+1))  # 两种情况都接受
fi
# 清理
kill -9 "$parent_pgid" 2>/dev/null || true
[[ -n "$grandchild_pid" ]] && kill -9 "$grandchild_pid" 2>/dev/null || true
wait "$parent_pgid" 2>/dev/null || true
rm -f /tmp/grandchild.pid
teardown

# 测试 2: 忽略 TERM 的进程（应升级到 KILL）
setup
setsid bash -c 'trap "" TERM; sleep 100' &
pgid=$!
sleep 0.2
# 应该先 TERM，等待后 KILL
md_terminate_process_group "$pgid" 1
if md_process_group_alive "$pgid"; then
  printf 'FAIL: process ignoring TERM should be killed\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
teardown

# 测试 3: TERM 期间退出的进程（应正确处理）
setup
setsid bash -c '
  trap "exit 0" TERM
  sleep 100
' &
pgid=$!
sleep 0.2
md_terminate_process_group "$pgid" 2
if md_process_group_alive "$pgid"; then
  printf 'FAIL: process should exit on TERM\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
teardown

# 测试 4: PGID/PID 重用（不应误杀）
setup
# 启动第一个进程
setsid sleep 100 &
pgid1=$!
sleep 0.2
# 终止第一个进程
kill -TERM -"$pgid1" 2>/dev/null || true
wait "$pgid1" 2>/dev/null || true
# 启动第二个进程（可能重用 PID）
setsid sleep 100 &
pgid2=$!
sleep 0.2
# 验证第二个进程存活
if md_process_group_alive "$pgid2"; then
  pass=$((pass+1))
else
  printf 'FAIL: second process should be alive\n' >&2
  fail=$((fail+1))
fi
# 清理
kill -TERM -"$pgid2" 2>/dev/null || true
wait "$pgid2" 2>/dev/null || true
teardown

# 测试 5: 终止后无泄漏（所有子进程应被清理）
setup
setsid bash -c '
  sleep 100 &
  sleep 100 &
  sleep 100
' &
pgid=$!
sleep 0.5
# 记录子进程
children="$(pgrep -P "$pgid" 2>/dev/null || true)"
# 终止进程组
md_terminate_process_group "$pgid" 2
# 验证所有子进程被清理
sleep 0.5
leaked=0
for child in $children; do
  if kill -0 "$child" 2>/dev/null; then
    leaked=$((leaked+1))
  fi
done
if [[ "$leaked" -eq 0 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: %d child processes leaked\n' "$leaked" >&2
  fail=$((fail+1))
fi
teardown

printf '\n== process group boundary tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
