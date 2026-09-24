#!/usr/bin/env bash
# model-delegate: JSONL 行边界确定性测试（修复 P2 round13）
# 验证：完整行被消费；无换行的部分行不被消费、不推进 offset；drain 保留部分行
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# supervisor 与 credentials 均需加载：monitor 管道依赖 md_redact_stream（生产中由 run-model.sh 一并 source）
source "$ROOT_DIR/scripts/lib/supervisor.sh"
source "$ROOT_DIR/scripts/lib/credentials.sh"

pass=0
fail=0
TEST_TMP="$(mktemp -d)"
trap '[[ -n "$TEST_TMP" ]] && rm -rf "$TEST_TMP"' EXIT

# 简易 normalizer：透传 JSON 对象
NORMALIZER="$TEST_TMP/normalize.jq"
printf '%s' '.' > "$NORMALIZER"

# 场景 1: 完整行消费、部分行保留
run_dir="$TEST_TMP/run-1"
mkdir -p "$run_dir"
setsid sleep 30 >/dev/null 2>&1 &
pgid=$!
printf '%s' "$pgid" > "$run_dir/pgid"
printf '%s\n%s' '{"seq":1}' '{"partial' > "$run_dir/raw-events.jsonl"

set +e
md_monitor_loop "$run_dir" "$NORMALIZER" 0 2 "" >/dev/null 2>&1
ret1=$?
set -e
kill -KILL -- -"$pgid" 2>/dev/null || true
wait "$pgid" 2>/dev/null || true

events1="$(wc -l < "$run_dir/events.jsonl" 2>/dev/null || echo 0)"
if [[ "$events1" == "1" && "$ret1" == "124" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: expected 1 event + 124, got %s events, ret=%s\n' "$events1" "$ret1" >&2
  fail=$((fail+1))
fi

# 场景 2: 同一次 monitor 调用内补全部分行（修复 round16：两次调用 offset 归零，
# 无法验证 offset 保留；本场景在 monitor 运行中追加数据）
# 断言：事件恰 2 条（seq:1 + seq:9 各一次）。
# 变异分析：若实现错误越界消费（offset=file_size 含部分行字节），追加的字节
# 在 offset 之后…… 不，越界时 offset 已越过部分行，追加内容从旧 file_size 之后
# 开始写入——seq:9 行仍会被读到？否：越界实现把 offset 推进到 file_size（含
# 部分行），追加后的新字节位于该 offset 之后，会被消费——故补充断言：
# 恰好 2 条且无重复。若实现丢弃部分行（旧 bug：$() 丢换行导致少算），
# seq:9 在 monitor#1 轮询中被跳过且补全后偏移错位 → 事件数 ≠ 2。
run_dir2="$TEST_TMP/run-2"
mkdir -p "$run_dir2"
setsid sleep 30 >/dev/null 2>&1 &
pgid2=$!
printf '%s' "$pgid2" > "$run_dir2/pgid"
printf '%s\n{"seq":9' '{"seq":1}' > "$run_dir2/raw-events.jsonl"
: > "$run_dir2/events.jsonl"

# 后台启动 monitor（硬超时 15s 兜底）
# 修复 P2（round17）：固定 sleep 假定首轮已消费存在调度竞争——
# 改为同步等待首条事件确认落盘后再补全部分行
md_monitor_loop "$run_dir2" "$NORMALIZER" 0 15 "" >/dev/null 2>&1 &
mon_pid=$!

events_first=0
for _ in $(seq 1 50); do
  events_first="$(wc -l < "$run_dir2/events.jsonl" 2>/dev/null || printf '0')"
  [[ "$events_first" -ge 1 ]] && break
  sleep 0.1
done
[[ "$events_first" -ge 1 ]] || { printf 'FAIL: first event never consumed\n' >&2; fail=$((fail+1)); }

# 首条已确认消费（offset 已推进），运行中补全部分行为合法 JSON
printf '%s\n' '}' >> "$run_dir2/raw-events.jsonl"

# 最多等 5s 让 monitor 消费第二条
events2=0
for _ in $(seq 1 50); do
  events2="$(wc -l < "$run_dir2/events.jsonl" 2>/dev/null || printf '0')"
  [[ "$events2" -ge 2 ]] && break
  sleep 0.1
done
kill "$mon_pid" 2>/dev/null || true
wait "$mon_pid" 2>/dev/null || true
kill -KILL -- -"$pgid2" 2>/dev/null || true
wait "$pgid2" 2>/dev/null || true

# 修复 P2（round17）：不仅断言行数，还解析 seq 序列恰为 [1,9]（各一次、顺序正确）
seqs="$(jq -sc '[.[].seq]' "$run_dir2/events.jsonl" 2>/dev/null || printf "[]")"

if [[ "$events2" == "2" && "$seqs" == "[1,9]" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: in-invocation partial completion expected 2 events [1,9], got %s %s\n' "$events2" "$seqs" >&2
  fail=$((fail+1))
fi

# 场景 3（修复 P1 round14）: observe 输出不得泄漏解码后的 secret
run_dir3="$TEST_TMP/run-3"
mkdir -p "$run_dir3"
MD_SECRETS=("sk-test")
setsid sleep 30 >/dev/null 2>&1 &
pgid4=$!
printf '%s' "$pgid4" > "$run_dir3/pgid"
# summary 内含 \uXXXX 转义的 secret；normalizer '.' 透传全文
printf '%s\n' '{"summary":"token sk-\u0074est embedded"}' > "$run_dir3/raw-events.jsonl"
observe_out="$TEST_TMP/observe.out"
exec 3>"$observe_out"
set +e
md_monitor_loop "$run_dir3" "$NORMALIZER" 0 2 3 >/dev/null 2>&1
set -e
exec 3>&-
kill -KILL -- -"$pgid4" 2>/dev/null || true
wait "$pgid4" 2>/dev/null || true

if [[ -s "$observe_out" ]] && ! grep -q 'sk-test' "$observe_out" && grep -q 'REDACTED' "$observe_out"; then
  pass=$((pass+1))
else
  printf 'FAIL: observe leaked decoded secret or no output\n' >&2
  printf '  observe: %s\n' "$(cat "$observe_out" 2>/dev/null)" >&2
  fail=$((fail+1))
fi
unset MD_SECRETS

printf '\n== jsonl boundary tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
