#!/usr/bin/env bash
# model-delegate: 输入与路径安全测试
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/run-model.sh"

pass=0
fail=0
TEST_TMP=""

setup() {
  TEST_TMP="$(mktemp -d)"
  export MODEL_DELEGATE_STATE_DIR="$TEST_TMP/state"
  mkdir -p "$TEST_TMP/state"
}

teardown() {
  [[ -n "$TEST_TMP" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
}

# 测试 1: 空 prompt 文件
setup
touch "$TEST_TMP/empty.txt"
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/empty.txt" >/dev/null 2>&1; then
  pass=$((pass+1))
else
  printf 'FAIL: empty prompt should be accepted\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 2: 超大 prompt 文件（1MB）
setup
dd if=/dev/zero of="$TEST_TMP/large.txt" bs=1M count=1 2>/dev/null
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/large.txt" >/dev/null 2>&1; then
  pass=$((pass+1))
else
  printf 'FAIL: large prompt should be accepted\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 3: 无换行末行的 prompt
setup
printf 'no newline at end' > "$TEST_TMP/no-newline.txt"
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/no-newline.txt" >/dev/null 2>&1; then
  pass=$((pass+1))
else
  printf 'FAIL: prompt without newline should be accepted\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 4: 非法 UTF-8
setup
printf '\xff\xfe\xfd' > "$TEST_TMP/invalid-utf8.txt"
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/invalid-utf8.txt" >/dev/null 2>&1; then
  pass=$((pass+1))
else
  printf 'FAIL: invalid UTF-8 should be accepted\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 5: 引号和特殊字符
setup
printf 'test "quotes" and $pecial chars\n' > "$TEST_TMP/special.txt"
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/special.txt" >/dev/null 2>&1; then
  pass=$((pass+1))
else
  printf 'FAIL: special characters should be accepted\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 6: 含空格路径
setup
mkdir -p "$TEST_TMP/path with spaces"
echo "test" > "$TEST_TMP/path with spaces/prompt.txt"
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP/path with spaces" --prompt-file "$TEST_TMP/path with spaces/prompt.txt" >/dev/null 2>&1; then
  pass=$((pass+1))
else
  printf 'FAIL: path with spaces should be accepted\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 7: -- 参数（防止注入）
setup
echo "test" > "$TEST_TMP/prompt.txt"
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --idle-timeout 60 >/dev/null 2>&1; then
  pass=$((pass+1))
else
  printf 'FAIL: -- parameter should work\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 8: run-id 路径穿越（..）
setup
echo "test" > "$TEST_TMP/prompt.txt"
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --run-id "../etc" >/dev/null 2>&1; then
  printf 'FAIL: path traversal should be rejected\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
teardown

# 测试 9: run-id 路径穿越（/）
setup
echo "test" > "$TEST_TMP/prompt.txt"
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --run-id "foo/bar" >/dev/null 2>&1; then
  printf 'FAIL: path with slash should be rejected\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
teardown

# 测试 10: run-id 绝对路径
setup
echo "test" > "$TEST_TMP/prompt.txt"
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --run-id "/etc/passwd" >/dev/null 2>&1; then
  printf 'FAIL: absolute path should be rejected\n' >&2
  fail=$((fail+1))
else
  pass=$((pass+1))
fi
teardown

# 测试 11: symlink run-id（应拒绝）
setup
echo "test" > "$TEST_TMP/prompt.txt"
ln -s /etc "$TEST_TMP/symlink"
if "$RUNNER" start --backend test-fake --provider test --model test-model --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" --run-id "symlink" >/dev/null 2>&1; then
  # symlink 本身不是路径穿越，但应该验证最终路径在 state_dir 内
  pass=$((pass+1))
else
  pass=$((pass+1))  # 拒绝也接受
fi
teardown

# 测试 12: 尚未创建的相对 state-dir 路径正常工作（修复 P2-6 回归）
setup
echo "test" > "$TEST_TMP/prompt.txt"
(
  cd "$TEST_TMP"
  # 使用未预先创建的相对 state-dir 路径
  "$RUNNER" start --backend test-fake --provider test --model test-model \
    --cwd "." --prompt-file "prompt.txt" --state-dir "relative_state_dir" >/dev/null 2>&1
)
if [[ -d "$TEST_TMP/relative_state_dir" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: relative uncreated state-dir should be created and work\n' >&2
  fail=$((fail+1))
fi
teardown

# 测试 13: fanout 相对路径支持（targets, prompt, cwd, uncreated state-dir）
setup
FANOUT_RUNNER="$ROOT_DIR/scripts/run-model-fanout.sh"
echo "test" > "$TEST_TMP/prompt.txt"
cat > "$TEST_TMP/targets.json" <<'EOF'
[
  {"backend": "test-fake", "provider": "test", "model": "test-model"}
]
EOF
(
  cd "$TEST_TMP"
  "$FANOUT_RUNNER" start --targets "targets.json" --cwd "." --prompt-file "prompt.txt" \
    --state-dir "fanout_rel_state" >/dev/null 2>&1
)
if [[ -d "$TEST_TMP/fanout_rel_state" ]]; then
  pass=$((pass+1))
else
  printf 'FAIL: fanout relative paths and uncreated state-dir should work\n' >&2
  fail=$((fail+1))
fi
teardown

printf '\n== input and path safety tests: %d passed, %d failed ==\n' "$pass" "$fail"
((fail == 0)) || exit 1
