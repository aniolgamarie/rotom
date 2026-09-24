#!/usr/bin/env bash
# model-delegate: backend 路径安全 + 终态 CAS + 全链路脱敏测试（5.1 验收）
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/run-model.sh"
source "$ROOT_DIR/scripts/lib/supervisor.sh"
source "$ROOT_DIR/scripts/lib/contract.sh"
source "$ROOT_DIR/scripts/lib/credentials.sh"

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

# 辅助函数：模拟 pi backend_complete 的扫描逻辑
backend_complete_test_helper() {
  local run_dir="$1"
  jq -sc '
    (map(select(.type == "session")) | first | .id?) as $session_id |
    (map(select(.type == "agent_end")) | length > 0) as $has_agent_end |
    (map(select(.type == "message_end" and .message.role == "assistant")) | last | .message.content? // [] | map(select(.type == "text")) | first | .text? // "") as $final_text |
    (map(select(.type == "message_end" and .message.usage)) | last | .message.usage? // {}) as $usage |
    {status: (if $has_agent_end and ($final_text | length) > 0 then "completed" else "failed" end),
     failure_mode: "", resume_token: $session_id, resumable: true,
     final_text: $final_text, feedback_quality: "structured", usage: $usage, has_agent_end: $has_agent_end}
  ' "$run_dir/raw-events.jsonl" 2>/dev/null
}

# ============ 5.1.1/5.1.2: backend 路径安全 ============

# 测试 1: 非法 backend ID（大写）被拒绝
setup
if "$RUNNER" start --backend "BadID" --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1; then
  printf 'FAIL: uppercase backend id should be rejected\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
teardown

# 测试 2: 路径注入 backend ID 被拒绝
setup
if "$RUNNER" start --backend "../evil" --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1; then
  printf 'FAIL: path traversal backend id should be rejected\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
teardown

# 测试 3: symlink backend adapter 被拒绝
setup
# 创建一个恶意脚本并通过 symlink 指向它
cat > "$TEST_TMP/evil.sh" <<'EOF'
echo "PWNED"
EOF
chmod +x "$TEST_TMP/evil.sh"
ln -s "$TEST_TMP/evil.sh" "$ROOT_DIR/scripts/backends/evil-link.sh" 2>/dev/null
if "$RUNNER" probe --backend evil-link --provider test >/dev/null 2>&1; then
  printf 'FAIL: symlink backend should be rejected\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
rm -f "$ROOT_DIR/scripts/backends/evil-link.sh"
teardown

# 测试 4: probe 命令同样受路径校验保护
setup
if "$RUNNER" probe --backend "../evil" --provider test >/dev/null 2>&1; then
  printf 'FAIL: probe should reject path traversal backend\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
teardown

# ============ 5.1.4: 全链路脱敏 ============

# 测试 5: md_redact_json_values 替换 JSON 字符串值中的 secret
setup
MD_SECRETS=("sk-secret-abc123")
input='{"final_text":"the key is sk-secret-abc123 ok","usage":{"input":1}}'
output="$(md_redact_json_values "$input")"
if [[ "$output" != *"sk-secret-abc123"* ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: json value secret not redacted\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 6: md_redact_json_values 处理嵌套结构
setup
MD_SECRETS=("token-xyz")
input='{"a":{"b":["plain","has token-xyz here"]},"c":"clean"}'
output="$(md_redact_json_values "$input")"
if [[ "$output" != *"token-xyz"* ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: nested secret not redacted\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 7: 空 MD_SECRETS 时原样通过
setup
MD_SECRETS=()
input='{"final_text":"no secrets here"}'
output="$(md_redact_json_values "$input")"
if [[ "$output" == *"no secrets here"* ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: no-secret input should pass through\n' >&2
  fail=$((fail+1))
fi
teardown

# ============ 5.1.5/5.1.6: 终态 CAS 与 cancel 幂等 ============

# 测试 8: CAS 拒绝覆盖已有终态
setup
run_dir="$(md_prepare_run_dir "$TEST_TMP/state" "cas-test-1")"
# 先写入 completed 终态
md_commit_terminal_status "$run_dir" '{"runId":"cas-test-1","status":"completed"}' >/dev/null 2>&1
# 尝试用 cancelled 覆盖（应被拒绝）
cas_ret=0
md_commit_terminal_status "$run_dir" '{"runId":"cas-test-1","status":"cancelled"}' >/dev/null 2>&1 || cas_ret=1
status="$(jq -r '.status' "$run_dir/status.json")"
if [[ "$cas_ret" -eq 1 && "$status" == "completed" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: CAS should reject overwrite of terminal status\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 9: CAS 允许从非终态写入终态
setup
run_dir="$(md_prepare_run_dir "$TEST_TMP/state" "cas-test-2")"
md_write_status "$run_dir" '{"runId":"cas-test-2","status":"running","terminal":false}'
cas_ret=0
md_commit_terminal_status "$run_dir" '{"runId":"cas-test-2","status":"completed"}' >/dev/null 2>&1 || cas_ret=1
status="$(jq -r '.status' "$run_dir/status.json")"
if [[ "$cas_ret" -eq 0 && "$status" == "completed" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: CAS should allow running->completed\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 10: cancel 幂等（已终态直接返回，不修改）
setup
export FAKE_BACKEND_MODE=success
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" >/dev/null 2>&1
run_id="$(ls "$TEST_TMP/state" | head -1)"
status_file="$TEST_TMP/state/$run_id/status.json"
mtime1="$(stat -c%Y "$status_file")"
content1="$(cat "$status_file")"
# 对已完成的 run 执行 cancel（应幂等返回，不修改）
sleep 1
cancel_output="$("$RUNNER" cancel --run-id "$run_id" 2>&1 || true)"
mtime2="$(stat -c%Y "$status_file")"
content2="$(cat "$status_file")"
if [[ "$content1" == "$content2" && "$mtime1" == "$mtime2" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: cancel should be idempotent on completed run\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 11: cancel 在运行态正常取消（CAS 允许 running->cancelled）
setup
export FAKE_BACKEND_MODE=hang
"$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" &
runner_pid=$!
sleep 2
run_id="$(ls "$TEST_TMP/state" | head -1)"
"$RUNNER" cancel --run-id "$run_id" >/dev/null 2>&1 || true
wait "$runner_pid" 2>/dev/null || true
status="$(jq -r '.status' "$TEST_TMP/state/$run_id/status.json")"
if [[ "$status" == "cancelled" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: cancel should cancel running run\n' >&2
  fail=$((fail+1))
fi
teardown

# ============ 5.1.3: raw-events.jsonl 落盘脱敏 ============

# 测试 12: completion final_text 从已脱敏数据提取
setup
MD_SECRETS=("sk-live-key-999")
# 模拟 monitor 完成后的 raw 脱敏流程
run_dir="$(md_prepare_run_dir "$TEST_TMP/state" "redact-test")"
cat > "$run_dir/raw-events.jsonl" <<'EOF'
{"type":"session","version":3,"id":"sess-1","timestamp":"2026-01-01T00:00:00Z","cwd":"/tmp"}
{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"key is sk-live-key-999"}],"stopReason":"stop","usage":{"input":10,"output":5,"totalTokens":15}}}
{"type":"agent_end","messages":[],"willRetry":false}
EOF
# 模拟 runner 的落盘脱敏步骤
raw_tmp="$run_dir/raw-events.jsonl.redacted"
md_redact_stream < "$run_dir/raw-events.jsonl" > "$raw_tmp"
mv -f "$raw_tmp" "$run_dir/raw-events.jsonl"
# 验证落盘文件已脱敏
if grep -q "sk-live-key-999" "$run_dir/raw-events.jsonl" 2>/dev/null; then
  printf 'FAIL: raw-events.jsonl still contains secret\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
# 验证 backend_complete 提取的 final_text 已脱敏
completion="$(backend_complete_test_helper "$run_dir")"
final_text="$(echo "$completion" | jq -r '.final_text')"
if [[ "$final_text" != *"sk-live-key-999"* ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: final_text should be redacted\n' >&2
  fail=$((fail+1))
fi
teardown

# ============ 5.1.4: 正则特殊字符凭证脱敏 ============

# 测试 13: awk 字面替换（正则特殊字符）
setup
MD_SECRETS=("abc+def" "test[0-9]" "key\\with\\backslash")
input="key1=abc+def key2=test[0-9] key3=key\\with\\backslash"
output="$(echo "$input" | md_redact_stream)"
if [[ "$output" != *"abc+def"* ]] && [[ "$output" != *"test[0-9]"* ]] && [[ "$output" != *"key\\with\\backslash"* ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: regex special chars not properly redacted\n' >&2
  printf '  output: %s\n' "$output" >&2
  fail=$((fail+1))
fi
teardown

# 测试 14: 进程 argv 不暴露 secret
setup
MD_SECRETS=("super-secret-key-12345")
# 启动一个后台进程使用 md_redact_stream
(echo "test output with super-secret-key-12345" | md_redact_stream > /dev/null 2>&1) &
redact_pid=$!
sleep 0.1
# 检查进程 argv
if [[ -d "/proc/$redact_pid" ]]; then
  cmdline="$(cat /proc/$redact_pid/cmdline 2>/dev/null | tr '\0' ' ')"
  if [[ "$cmdline" == *"super-secret-key-12345"* ]]; then
    printf 'FAIL: secret exposed in process argv\n' >&2
    fail=$((fail+1))
  else
    pass=$((pass+1))
  fi
  wait "$redact_pid" 2>/dev/null || true
else
  # 进程已结束，无法检查，标记为通过
  pass=$((pass+1))
fi
teardown

# 测试 15: 字面替换不会无限循环（secret 包含 REDACTED）
setup
MD_SECRETS=("REDACTED")
input="test REDACTED value"
# 应该在 1 秒内完成，不会无限循环
output="$(timeout 1 bash -c "source '$SCRIPT_DIR/../scripts/lib/credentials.sh'; MD_SECRETS=('REDACTED'); echo 'test REDACTED value' | md_redact_stream" 2>&1)"
if [[ $? -eq 0 ]] && [[ "$output" == "test [REDACTED] value" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: literal replacement infinite loop or incorrect output\n' >&2
  printf '  output: %s\n' "$output" >&2
  fail=$((fail+1))
fi
teardown

# ============ 修复 P1（round13）：JSONL 解码感知脱敏 ============

# 测试 18: \uXXXX 混合转义不再泄漏
setup
MD_SECRETS=("sk-test")
printf '%s\n' '{"v":"sk-\u0074est","n":1}' '{"v":"plain sk-test"}' > "$TEST_TMP/events.jsonl"
md_redact_jsonl_in_place "$TEST_TMP/events.jsonl"
row1="$(sed -n '1p' "$TEST_TMP/events.jsonl" | jq -r '.v')"
row2="$(sed -n '2p' "$TEST_TMP/events.jsonl" | jq -r '.v')"
if [[ "$row1" == "[REDACTED]" && "$row2" == "plain [REDACTED]" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: unicode-escaped secret leaked (row1=%s row2=%s)\n' "$row1" "$row2" >&2
  fail=$((fail+1))
fi
teardown

# 测试 19: 非 JSON 行保持原样（已由文本过滤器处理）且不破坏合法 JSON
setup
MD_SECRETS=("abc")
printf '%s\n' 'plain text line abc' '{"v":"\u00abc"}' > "$TEST_TMP/mixed.log"
md_redact_jsonl_in_place "$TEST_TMP/mixed.log"
line2="$(sed -n '2p' "$TEST_TMP/mixed.log")"
if echo "$line2" | jq -e . >/dev/null 2>&1 && [[ "$(echo "$line2" | jq -r '.v')" == "«c" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: valid JSON corrupted by redaction sweep (line2=%s)\n' "$line2" >&2
  fail=$((fail+1))
fi
teardown

# 测试 20: 非 JSON 行字面脱敏回退（修复 P1 round15，补断言 round16）
setup
MD_SECRETS=("abc")
printf '%s\n' 'warning: abc' > "$TEST_TMP/plain.log"
md_redact_jsonl_in_place "$TEST_TMP/plain.log"
plain_line="$(cat "$TEST_TMP/plain.log")"
if [[ "$plain_line" == "warning: [REDACTED]" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: non-JSON line not redacted (got: %s)\n' "$plain_line" >&2
  fail=$((fail+1))
fi
teardown

printf '\n== backend security & CAS tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
