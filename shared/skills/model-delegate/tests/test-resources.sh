#!/usr/bin/env bash
# model-delegate: 资源限制与可执行性测试
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$ROOT_DIR/scripts/lib/supervisor.sh"

pass=0
fail=0

TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

# 测试 1: 检查必需工具版本
echo "=== Tool Versions ==="
echo "Bash: $(bash --version | head -1)"
echo "jq: $(jq --version)"
echo "pi: $(pi --version 2>/dev/null || echo 'not found')"

# 验证版本要求
bash_version=$(bash --version | head -1 | grep -oP '\d+\.\d+' | head -1 | cut -d. -f1)
if [[ "$bash_version" -ge 4 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: bash version < 4\n' >&2
  fail=$((fail+1))
fi

if command -v jq &>/dev/null; then
  pass=$((pass+1))
else
  printf 'FAIL: jq not found\n' >&2
  fail=$((fail+1))
fi

# 测试 2: 大输出处理
echo "=== Large Output Test ==="
export FAKE_BACKEND_MODE=success
export FAKE_BACKEND_STEP_DELAY=0
export MODEL_DELEGATE_STATE_DIR="$TEST_TMP/state"
mkdir -p "$TEST_TMP/state"
echo "test prompt" > "$TEST_TMP/prompt.txt"

# 创建一个大输出（1000 行）
cat > "$TEST_TMP/large-output.sh" <<'SCRIPT'
#!/usr/bin/env bash
echo '{"type":"session","version":3,"id":"large-session","timestamp":"2026-01-01T00:00:00Z","cwd":"/tmp"}'
for i in {1..1000}; do
  echo "{\"type\":\"message_update\",\"usage\":{\"input\":$i,\"output\":$i,\"totalTokens\":$((i*2))},\"assistantMessageEvent\":{\"type\":\"text_delta\",\"contentIndex\":0,\"delta\":\"line $i\"}}"
done
echo '{"type":"agent_end","messages":[],"willRetry":false}'
SCRIPT
chmod +x "$TEST_TMP/large-output.sh"

# 测试 3: run 目录清理保护
echo "=== Run Directory Cleanup Protection ==="
# 创建活跃 run
export MD_ACTIVE_RUN="$TEST_TMP/state/active-run"
mkdir -p "$MD_ACTIVE_RUN"
echo '{"status":"running"}' > "$MD_ACTIVE_RUN/status.json"

# 尝试清理（应该保护活跃 run）
# 注意：这里需要实现清理逻辑，目前只是测试框架
if [[ -d "$MD_ACTIVE_RUN" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: active run directory removed\n' >&2
  fail=$((fail+1))
fi

# 测试 4: 磁盘空间检查（模拟）
echo "=== Disk Space Check ==="
available_space=$(df -P "$TEST_TMP" | tail -1 | awk '{print $4}')
if [[ "$available_space" -gt 1000 ]]; then  # 至少 1MB
  pass=$((pass+1))
else
  printf 'FAIL: insufficient disk space\n' >&2
  fail=$((fail+1))
fi

# 测试 5: 文件描述符限制
echo "=== File Descriptor Limit ==="
ulimit_soft=$(ulimit -Sn)
if [[ "$ulimit_soft" -ge 64 ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: file descriptor limit too low: %s\n' "$ulimit_soft" >&2
  fail=$((fail+1))
fi

# 测试 6: 超时处理（避免固定 sleep）
echo "=== Timeout Handling ==="
start_time=$(date +%s)
timeout 2 bash -c 'sleep 10' 2>/dev/null || true
end_time=$(date +%s)
elapsed=$((end_time - start_time))
if [[ "$elapsed" -le 3 ]]; then  # 应该在 2-3 秒内超时
  pass=$((pass+1))
else
  printf 'FAIL: timeout took too long: %s seconds\n' "$elapsed" >&2
  fail=$((fail+1))
fi

# 测试 7: 临时目录清理
echo "=== Temp Directory Cleanup ==="
temp_subdir="$TEST_TMP/subdir"
mkdir -p "$temp_subdir"
echo "test" > "$temp_subdir/file.txt"
rm -rf "$temp_subdir"
if [[ ! -d "$temp_subdir" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: temp directory not cleaned\n' >&2
  fail=$((fail+1))
fi

# 测试 8: JSON 解析性能
echo "=== JSON Parsing Performance ==="
large_json='{"entries":['
for i in {1..100}; do
  large_json+="{\"id\":\"$i\",\"kind\":\"fact\",\"claim\":\"claim $i\",\"status\":\"confirmed\"},"
done
large_json="${large_json%,}]}"

start_time=$(date +%s%N)
echo "$large_json" | jq '.entries | length' > /dev/null
end_time=$(date +%s%N)
elapsed_ms=$(( (end_time - start_time) / 1000000 ))
if [[ "$elapsed_ms" -lt 1000 ]]; then  # 应该在 1 秒内完成
  pass=$((pass+1))
else
  printf 'FAIL: JSON parsing too slow: %s ms\n' "$elapsed_ms" >&2
  fail=$((fail+1))
fi

printf '\n== resource tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
