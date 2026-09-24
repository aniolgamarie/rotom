#!/usr/bin/env bash
# model-delegate: adapter 契约测试
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$ROOT_DIR/scripts/lib/contract.sh"

pass=0
fail=0

assert_ok() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    ((pass++))
  else
    printf 'FAIL: %s\n' "$desc" >&2
    ((fail++))
  fi
}

assert_fail() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf 'FAIL (expected failure): %s\n' "$desc" >&2
    ((fail++))
  else
    ((pass++))
  fi
}

# 测试 1: 缺少函数
unset -f backend_probe backend_init backend_start backend_normalizer backend_complete backend_cancel backend_validate_provider_model 2>/dev/null || true
BACKEND_ID="test"
declare -A BACKEND_CAPABILITIES=()
assert_fail "missing functions" validate_backend_contract

# 测试 2: 空 BACKEND_ID
backend_probe() { :; }
backend_init() { :; }
backend_start() { :; }
backend_normalizer() { :; }
backend_complete() { :; }
backend_cancel() { :; }
backend_validate_provider_model() { :; }
BACKEND_ID=""
declare -A BACKEND_CAPABILITIES=()
assert_fail "empty BACKEND_ID" validate_backend_contract

# 测试 3: 非法 BACKEND_ID（大写）
BACKEND_ID="Invalid"
declare -A BACKEND_CAPABILITIES=()
assert_fail "invalid BACKEND_ID" validate_backend_contract

# 测试 4: BACKEND_CAPABILITIES 未声明（普通变量）
unset BACKEND_CAPABILITIES
BACKEND_CAPABILITIES="not-an-array"
assert_fail "non-associative BACKEND_CAPABILITIES" validate_backend_contract
# 恢复为关联数组供后续测试
declare -A BACKEND_CAPABILITIES=()

# 测试 5: 合法契约
BACKEND_ID="test"
declare -A BACKEND_CAPABILITIES=([context_limit]=8000)
assert_ok "valid contract" validate_backend_contract

# 测试 6: backend_start 输出校验 — 空 BACKEND_CMD
BACKEND_CMD=()
BACKEND_ENV=()
assert_fail "empty BACKEND_CMD" validate_backend_start_output

# 测试 7: backend_start 输出校验 — 合法
BACKEND_CMD=(echo hello)
BACKEND_ENV=(FOO=bar)
assert_ok "valid backend_start output" validate_backend_start_output

# 测试 8: normalizer 路径校验 — 相对路径
backend_normalizer() { printf 'relative/path.jq'; }
assert_fail "relative normalizer path" validate_backend_normalizer

# 测试 9: normalizer 路径校验 — 不存在
backend_normalizer() { printf '/nonexistent/path.jq'; }
assert_fail "nonexistent normalizer" validate_backend_normalizer

# 测试 10: normalizer 路径校验 — 合法
backend_normalizer() { printf '%s' "$ROOT_DIR/scripts/backends/pi-normalize.jq"; }
assert_ok "valid normalizer path" validate_backend_normalizer

printf '\n== contract tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
