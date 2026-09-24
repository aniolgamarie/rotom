#!/usr/bin/env bash
# model-delegate: parallel policy 静态契约测试
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_FILE="$ROOT_DIR/SKILL.md"

pass=0
fail=0

assert_contains() {
  local pattern="$1" msg="${2:-}"
  if grep -q "$pattern" "$SKILL_FILE" 2>/dev/null; then
    pass=$((pass+1))
  else
    printf 'FAIL: %s\n  pattern: %s\n' "$msg" "$pattern" >&2
    fail=$((fail+1))
  fi
}

# 测试 1: SKILL.md 存在
[[ -f "$SKILL_FILE" ]] && pass=$((pass+1)) || { printf 'FAIL: SKILL.md not found\n' >&2; fail=$((fail+1)); exit 1; }

# 测试 2: 包含并行策略章节
assert_contains "Parallel delegation policy" "parallel policy section"

# 测试 3: 包含并行规则
assert_contains "MUST.*subagent.*并行" "parallel MUST rule"
assert_contains "MUST NOT.*依赖链" "parallel MUST NOT rule"

# 测试 4: 包含并行模式模板
assert_contains "Parallel review pattern" "parallel review pattern"
assert_contains "Parallel investigation pattern" "parallel investigation pattern"

# 测试 5: 包含 fallback 指导
assert_contains "无.*subagent.*串行" "fallback guidance"

# 测试 6: 包含依赖边定义
assert_contains "依赖边" "dependency edge definition"

# 测试 7: 包含综合去重规则
assert_contains "综合" "synthesis rule"

printf '\n== parallel policy tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
