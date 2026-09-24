#!/usr/bin/env bash
# Codex backend adapter 测试
# 使用 golden fixtures 验证 adapter 行为

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FIXTURES_DIR="$ROOT_DIR/tests/fixtures/codex"

pass=0
fail=0

# 测试 1: backend_probe 成功
echo "Test 1: backend_probe 成功"
if output=$("$ROOT_DIR/scripts/backends/codex.sh" probe 2>&1); then
    if echo "$output" | jq -e '.status == "ready"' >/dev/null 2>&1; then
        echo "  ✓ probe 返回 ready"
        pass=$((pass+1))
    else
        echo "  ✗ probe 未返回 ready"
        fail=$((fail+1))
    fi
else
    echo "  ✗ probe 执行失败"
    fail=$((fail+1))
fi

# 测试 2: backend_init 设置正确的 capabilities
echo "Test 2: backend_init 设置 capabilities"
if output=$("$ROOT_DIR/scripts/backends/codex.sh" init 2>&1); then
    if echo "$output" | grep -q "BACKEND_ID=codex"; then
        echo "  ✓ BACKEND_ID=codex"
        pass=$((pass+1))
    else
        echo "  ✗ BACKEND_ID 未设置"
        fail=$((fail+1))
    fi
else
    echo "  ✗ init 执行失败"
    fail=$((fail+1))
fi

# 测试 3: codex-normalize.jq 处理 thread.started
echo "Test 3: codex-normalize.jq 处理 thread.started"
if echo '{"type":"thread.started","thread_id":"test-123"}' | \
    jq -f "$ROOT_DIR/scripts/backends/codex-normalize.jq" | \
    jq -e '.kind == "started" and .phase == "starting"' >/dev/null 2>&1; then
    echo "  ✓ thread.started 正确映射"
    pass=$((pass+1))
else
    echo "  ✗ thread.started 映射错误"
    fail=$((fail+1))
fi

# 测试 4: codex-normalize.jq 处理 turn.completed
echo "Test 4: codex-normalize.jq 处理 turn.completed"
if echo '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":50,"total_tokens":150}}' | \
    jq -f "$ROOT_DIR/scripts/backends/codex-normalize.jq" | \
    jq -e '.kind == "phase_changed" and .phase == "finalizing"' >/dev/null 2>&1; then
    echo "  ✓ turn.completed 正确映射"
    pass=$((pass+1))
else
    echo "  ✗ turn.completed 映射错误"
    fail=$((fail+1))
fi

# 测试 5: codex-normalize.jq 处理 turn.failed
echo "Test 5: codex-normalize.jq 处理 turn.failed"
if echo '{"type":"turn.failed","error":"test error"}' | \
    jq -f "$ROOT_DIR/scripts/backends/codex-normalize.jq" | \
    jq -e '.kind == "phase_changed" and .phase == "finalizing"' >/dev/null 2>&1; then
    echo "  ✓ turn.failed 正确映射"
    pass=$((pass+1))
else
    echo "  ✗ turn.failed 映射错误"
    fail=$((fail+1))
fi

# 测试 6: backend_complete 处理 turn-completed.jsonl fixture
echo "Test 6: backend_complete 处理 turn-completed.jsonl"
tmpdir=$(mktemp -d)
cp "$FIXTURES_DIR/turn-completed.jsonl" "$tmpdir/raw-events.jsonl"
echo "Test output" > "$tmpdir/final.txt"
if output=$("$ROOT_DIR/scripts/backends/codex.sh" complete "$tmpdir" 2>&1); then
    if echo "$output" | jq -e '.status == "completed" and .resumable == true' >/dev/null 2>&1; then
        echo "  ✓ turn-completed.jsonl 正确判定为 completed"
        pass=$((pass+1))
    else
        echo "  ✗ turn-completed.jsonl 判定错误"
        echo "  输出: $output"
        fail=$((fail+1))
    fi
else
    echo "  ✗ complete 执行失败"
    fail=$((fail+1))
fi
rm -rf "$tmpdir"

# 测试 7: backend_complete 处理 turn-failed.jsonl fixture
echo "Test 7: backend_complete 处理 turn-failed.jsonl"
tmpdir=$(mktemp -d)
cp "$FIXTURES_DIR/turn-failed.jsonl" "$tmpdir/raw-events.jsonl"
if output=$("$ROOT_DIR/scripts/backends/codex.sh" complete "$tmpdir" 2>&1); then
    if echo "$output" | jq -e '.status == "failed" and .failure_mode == "protocol"' >/dev/null 2>&1; then
        echo "  ✓ turn-failed.jsonl 正确判定为 failed/protocol"
        pass=$((pass+1))
    else
        echo "  ✗ turn-failed.jsonl 判定错误"
        echo "  输出: $output"
        fail=$((fail+1))
    fi
else
    echo "  ✗ complete 执行失败"
    fail=$((fail+1))
fi
rm -rf "$tmpdir"

# 测试 8: backend_complete 处理 empty-final.jsonl fixture
echo "Test 8: backend_complete 处理 empty-final.jsonl"
tmpdir=$(mktemp -d)
cp "$FIXTURES_DIR/empty-final.jsonl" "$tmpdir/raw-events.jsonl"
touch "$tmpdir/final.txt"  # 空文件
if output=$("$ROOT_DIR/scripts/backends/codex.sh" complete "$tmpdir" 2>&1); then
    if echo "$output" | jq -e '.status == "incomplete"' >/dev/null 2>&1; then
        echo "  ✓ empty-final.jsonl 正确判定为 incomplete"
        pass=$((pass+1))
    else
        echo "  ✗ empty-final.jsonl 判定错误"
        echo "  输出: $output"
        fail=$((fail+1))
    fi
else
    echo "  ✗ complete 执行失败"
    fail=$((fail+1))
fi
rm -rf "$tmpdir"

# 测试 9: backend_complete 处理 malformed.jsonl fixture
echo "Test 9: backend_complete 处理 malformed.jsonl"
tmpdir=$(mktemp -d)
cp "$FIXTURES_DIR/malformed.jsonl" "$tmpdir/raw-events.jsonl"
if output=$("$ROOT_DIR/scripts/backends/codex.sh" complete "$tmpdir" 2>&1); then
    if echo "$output" | jq -e '.status == "failed" and .failure_mode == "invalid_output"' >/dev/null 2>&1; then
        echo "  ✓ malformed.jsonl 正确判定为 failed/invalid_output"
        pass=$((pass+1))
    else
        echo "  ✗ malformed.jsonl 判定错误"
        echo "  输出: $output"
        fail=$((fail+1))
    fi
else
    echo "  ✗ complete 执行失败"
    fail=$((fail+1))
fi
rm -rf "$tmpdir"

# 测试 10: backend_complete 处理 usage.jsonl fixture
echo "Test 10: backend_complete 处理 usage.jsonl"
tmpdir=$(mktemp -d)
cp "$FIXTURES_DIR/usage.jsonl" "$tmpdir/raw-events.jsonl"
echo "Test output" > "$tmpdir/final.txt"
if output=$("$ROOT_DIR/scripts/backends/codex.sh" complete "$tmpdir" 2>&1); then
    if echo "$output" | jq -e '.status == "completed" and .usage.input == 5000 and .usage.output == 2500 and .usage.totalTokens == 7500' >/dev/null 2>&1; then
        echo "  ✓ usage.jsonl 正确映射 usage 字段"
        pass=$((pass+1))
    else
        echo "  ✗ usage.jsonl usage 映射错误"
        echo "  输出: $output"
        fail=$((fail+1))
    fi
else
    echo "  ✗ complete 执行失败"
    fail=$((fail+1))
fi
rm -rf "$tmpdir"

# 测试 11: backend_complete 处理缺失 raw-events.jsonl
# 修复 F2：补充含 secret 的 final.txt 回归测试
echo "Test 11: backend_complete 处理缺失 raw-events.jsonl 并清洗 final.txt"
tmpdir=$(mktemp -d)
# 创建含 secret 的 final.txt
echo "This contains sk-test-12345" > "$tmpdir/final.txt"
# 创建 status.json 以提供 provider 信息
cat > "$tmpdir/status.json" <<'STATUSJSON'
{
  "backend": {
    "provider": "test-provider"
  }
}
STATUSJSON
# 模拟 pi auth print-api-key 返回 secret
export PI_MOCK_API_KEY="sk-test-12345"
if output=$("$ROOT_DIR/scripts/backends/codex.sh" complete "$tmpdir" 2>&1); then
    if echo "$output" | jq -e '.status == "failed" and .failure_mode == "invalid_output"' >/dev/null 2>&1; then
        echo "  ✓ 缺失 raw-events.jsonl 正确判定为 failed/invalid_output"
        # 检查 final.txt 是否已清洗（验证精确内容）
        actual_content="$(cat "$tmpdir/final.txt" 2>/dev/null || echo "")"
        expected_content="This contains [REDACTED]"
        if [[ "$actual_content" == "$expected_content" ]]; then
            echo "  ✓ final.txt 已精确清洗，内容等于 '$expected_content'"
            pass=$((pass+1))
        else
            echo "  ✗ final.txt 内容不匹配"
            echo "    期望: '$expected_content'"
            echo "    实际: '$actual_content'"
            fail=$((fail+1))
        fi
        pass=$((pass+1))
    else
        echo "  ✗ 缺失 raw-events.jsonl 判定错误"
        echo "  输出: $output"
        fail=$((fail+1))
    fi
else
    echo "  ✗ complete 执行失败"
    fail=$((fail+1))
fi
unset PI_MOCK_API_KEY
rm -rf "$tmpdir"

echo ""
echo "=================================="
echo "测试完成: $pass 通过, $fail 失败"
echo "=================================="

if [[ $fail -gt 0 ]]; then
    exit 1
fi
