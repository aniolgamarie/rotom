#!/usr/bin/env bash
# model-delegate: memory system 测试
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$ROOT_DIR/scripts/lib/memory.sh"

pass=0
fail=0

assert_ok() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    pass=$((pass+1))
  else
    printf 'FAIL: %s\n' "$desc" >&2
    fail=$((fail+1))
  fi
}

assert_fail() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf 'FAIL (expected failure): %s\n' "$desc" >&2
    fail=$((fail+1))
  else
    pass=$((pass+1))
  fi
}

assert_eq() {
  local expected="$1" actual="$2" msg="${3:-}"
  if [[ "$expected" == "$actual" ]]; then
    pass=$((pass+1))
  else
    printf 'FAIL: %s\n  expected: %s\n  actual:   %s\n' "$msg" "$expected" "$actual" >&2
    fail=$((fail+1))
  fi
}

TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

# 测试 1: 加载有效的 memory 文件
cat > "$TEST_TMP/memory.json" <<'EOF'
{
  "revision": "42",
  "entries": [
    {"id": "1", "kind": "decision", "claim": "Use PostgreSQL", "status": "confirmed"},
    {"id": "2", "kind": "fact", "claim": "API rate limit is 1000 req/min", "status": "confirmed"}
  ]
}
EOF
assert_ok "load valid memory file" md_load_memory "$TEST_TMP/memory.json"
assert_eq "42" "$MD_MEMORY_REVISION" "memory revision"

# 测试 2: 加载不存在的 memory 文件
assert_fail "load nonexistent memory file" md_load_memory "$TEST_TMP/nonexistent.json"

# 测试 3: 加载无效的 JSON
echo "not json" > "$TEST_TMP/invalid.json"
assert_fail "load invalid JSON" md_load_memory "$TEST_TMP/invalid.json"

# 测试 4: 加载缺少 entries 字段的 JSON
echo '{"revision": "1"}' > "$TEST_TMP/no-entries.json"
assert_fail "load memory without entries" md_load_memory "$TEST_TMP/no-entries.json"

# 测试 5: 投影 - 按优先级排序
cat > "$TEST_TMP/memory-priority.json" <<'EOF'
{
  "revision": "1",
  "entries": [
    {"id": "1", "kind": "lesson", "claim": "Lesson 1"},
    {"id": "2", "kind": "decision", "claim": "Decision 1"},
    {"id": "3", "kind": "fact", "claim": "Fact 1", "status": "confirmed"},
    {"id": "4", "kind": "hypothesis", "claim": "Hypothesis 1"}
  ]
}
EOF
md_load_memory "$TEST_TMP/memory-priority.json"
projected="$(md_project_memory "$MD_MEMORY_JSON" 1000)"
first_kind="$(echo "$projected" | jq -r '.[0].kind')"
assert_eq "decision" "$first_kind" "priority sort: decision first"

# 测试 6: 投影 - token 预算截断
cat > "$TEST_TMP/memory-large.json" <<EOF
{
  "revision": "1",
  "entries": [
    {"id": "1", "kind": "decision", "claim": "$(printf 'x%.0s' {1..200})"},
    {"id": "2", "kind": "decision", "claim": "$(printf 'y%.0s' {1..200})"},
    {"id": "3", "kind": "decision", "claim": "$(printf 'z%.0s' {1..200})"}
  ]
}
EOF
md_load_memory "$TEST_TMP/memory-large.json"
projected="$(md_project_memory "$MD_MEMORY_JSON" 100)"
count="$(echo "$projected" | jq 'length')"
[[ "$count" -lt 3 ]] && pass=$((pass+1)) || { printf 'FAIL: budget truncation\n' >&2; fail=$((fail+1)); }

# 测试 7: 脱敏 - 移除 credential 字段
cat > "$TEST_TMP/memory-secrets.json" <<'EOF'
{
  "revision": "1",
  "entries": [
    {"id": "1", "kind": "fact", "claim": "API key is sk-12345", "api_key": "secret123", "status": "confirmed"}
  ]
}
EOF
md_load_memory "$TEST_TMP/memory-secrets.json"
redacted="$(md_redact_memory "$MD_MEMORY_JSON")"
has_api_key="$(echo "$redacted" | jq '.[0] | has("api_key")')"
assert_eq "false" "$has_api_key" "redaction removes api_key field"

# 测试 8: 脱敏 - 替换 claim 中的 secret 模式
cat > "$TEST_TMP/memory-claim-secret.json" <<'EOF'
{
  "revision": "1",
  "entries": [
    {"id": "1", "kind": "fact", "claim": "The api_key=sk-secret123 is used", "status": "confirmed"}
  ]
}
EOF
md_load_memory "$TEST_TMP/memory-claim-secret.json"
redacted="$(md_redact_memory "$MD_MEMORY_JSON")"
claim="$(echo "$redacted" | jq -r '.[0].claim')"
[[ "$claim" != *"sk-secret123"* ]] && pass=$((pass+1)) || { printf 'FAIL: claim not redacted\n' >&2; fail=$((fail+1)); }

# 测试 9: 脱敏 - 大小写不敏感字段
cat > "$TEST_TMP/memory-case-secret.json" <<'EOF'
{
  "revision": "1",
  "entries": [
    {"id": "1", "kind": "fact", "claim": "Test", "Token": "secret-token", "API_KEY": "sk-123", "status": "confirmed"}
  ]
}
EOF
md_load_memory "$TEST_TMP/memory-case-secret.json"
redacted="$(md_redact_memory "$MD_MEMORY_JSON")"
has_token="$(echo "$redacted" | jq '.[0] | has("Token")')"
has_api_key="$(echo "$redacted" | jq '.[0] | has("API_KEY")')"
[[ "$has_token" == "false" && "$has_api_key" == "false" ]] && pass=$((pass+1)) || { printf 'FAIL: case-insensitive fields not removed\n' >&2; fail=$((fail+1)); }

# 测试 10: 脱敏 - Bearer token 模式
cat > "$TEST_TMP/memory-bearer.json" <<'EOF'
{
  "revision": "1",
  "entries": [
    {"id": "1", "kind": "fact", "claim": "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "status": "confirmed"}
  ]
}
EOF
md_load_memory "$TEST_TMP/memory-bearer.json"
redacted="$(md_redact_memory "$MD_MEMORY_JSON")"
claim="$(echo "$redacted" | jq -r '.[0].claim')"
[[ "$claim" != *"eyJhbGci"* ]] && pass=$((pass+1)) || { printf 'FAIL: Bearer token not redacted\n' >&2; fail=$((fail+1)); }

# 测试 9: 注入到 prompt
cat > "$TEST_TMP/prompt.txt" <<'EOF'
Please review the code.
EOF
cat > "$TEST_TMP/memory-inject.json" <<'EOF'
{
  "revision": "99",
  "entries": [
    {"id": "1", "kind": "decision", "claim": "Use TypeScript", "status": "confirmed"},
    {"id": "2", "kind": "fact", "claim": "Port is 8080", "status": "confirmed", "evidence": ["config.yaml"]}
  ]
}
EOF
output_file="$TEST_TMP/prompt-with-memory.md"
assert_ok "inject memory to prompt" md_inject_memory_to_prompt "$TEST_TMP/prompt.txt" "$TEST_TMP/memory-inject.json" "$output_file"
[[ -f "$output_file" ]] && pass=$((pass+1)) || { printf 'FAIL: output file not created\n' >&2; fail=$((fail+1)); }
content="$(cat "$output_file")"
[[ "$content" == *"Please review the code."* ]] && pass=$((pass+1)) || { printf 'FAIL: original prompt missing\n' >&2; fail=$((fail+1)); }
[[ "$content" == *"Use TypeScript"* ]] && pass=$((pass+1)) || { printf 'FAIL: memory not injected\n' >&2; fail=$((fail+1)); }
[[ "$content" == *"revision 99"* ]] && pass=$((pass+1)) || { printf 'FAIL: revision not shown\n' >&2; fail=$((fail+1)); }

# 测试 10: 边界 - 空 entries
cat > "$TEST_TMP/memory-empty.json" <<'EOF'
{
  "revision": "1",
  "entries": []
}
EOF
assert_ok "load memory with empty entries" md_load_memory "$TEST_TMP/memory-empty.json"
projected="$(md_project_memory "$MD_MEMORY_JSON" 100)"
count="$(echo "$projected" | jq 'length')"
assert_eq "0" "$count" "empty entries projection"

# 测试 11: 边界 - Unicode 内容
cat > "$TEST_TMP/memory-unicode.json" <<'EOF'
{
  "revision": "1",
  "entries": [
    {"id": "1", "kind": "fact", "claim": "用户名是 张三", "status": "confirmed"},
    {"id": "2", "kind": "fact", "claim": "Emoji test 🎉🚀", "status": "confirmed"}
  ]
}
EOF
assert_ok "load memory with unicode" md_load_memory "$TEST_TMP/memory-unicode.json"
projected="$(md_project_memory "$MD_MEMORY_JSON" 1000)"
first_claim="$(echo "$projected" | jq -r '.[0].claim')"
[[ "$first_claim" == *"张三"* ]] && pass=$((pass+1)) || { printf 'FAIL: unicode not preserved\n' >&2; fail=$((fail+1)); }

# 测试 12: Context window 预算计算
# 默认 8000 context_limit，空 prompt -> 6400
budget_default="$(md_calculate_memory_budget "8000" "")"
assert_eq "6400" "$budget_default" "context budget default 8000"

# 4000 context_limit，400 字符 prompt (100 tokens) -> 3200 - 100 = 3100
echo -n "$(head -c 400 </dev/zero | tr '\0' 'a')" > "$TEST_TMP/p400.txt"
budget_4000="$(md_calculate_memory_budget "4000" "$TEST_TMP/p400.txt")"
assert_eq "3100" "$budget_4000" "context budget 4000 with prompt"

# 超出预算时保底 100 tokens
echo -n "$(head -c 20000 </dev/zero | tr '\0' 'a')" > "$TEST_TMP/p_huge.txt"
budget_floor="$(md_calculate_memory_budget "4000" "$TEST_TMP/p_huge.txt")"
assert_eq "100" "$budget_floor" "context budget minimum floor"

# 非法 context_limit 回退到 8000 保守默认值
budget_fallback="$(md_calculate_memory_budget "invalid" "")"
assert_eq "6400" "$budget_fallback" "context budget invalid fallback to 8000"

printf '\n== memory tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
