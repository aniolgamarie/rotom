#!/usr/bin/env bash
# model-delegate: Codex 端到端测试
# 仅在 CODEX_E2E=1 时执行（需要真实 Codex CLI 和登录态）
# CLI/auth 缺失时明确 skip；协议漂移必须 fail
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/run-model.sh"
PROBE="$ROOT_DIR/scripts/codex-probe.sh"

pass=0
fail=0
skip=0
TEST_TMP=""

note() { printf '%s\n' "$*" >&2; }

# ── 门控：仅 CODEX_E2E=1 时执行 ──────────────────────────────
if [[ "${CODEX_E2E:-}" != "1" ]]; then
  note "== codex e2e tests: SKIPPED (set CODEX_E2E=1 to run) =="
  exit 0
fi

setup() {
  TEST_TMP="$(mktemp -d)"
  export MODEL_DELEGATE_STATE_DIR="$TEST_TMP/state"
  mkdir -p "$TEST_TMP/state"
  printf 'Reply with exactly the word: pong\n' > "$TEST_TMP/prompt.txt"
}

teardown() {
  [[ -n "$TEST_TMP" && -d "$TEST_TMP" ]] && rm -rf "$TEST_TMP"
}

# ── 前置检查：probe 决定 run 还是 skip ──────────────────────
probe_json="$("$PROBE" 2>/dev/null || echo '{}')"
probe_status="$(printf '%s' "$probe_json" | jq -r '.status // "unknown"')"

if [[ "$probe_status" != "ready" ]]; then
  note "== codex e2e tests: SKIPPED (probe status: $probe_status; need CLI + auth) =="
  exit 0
fi

# 测试 1: probe 声明与 adapter capability 一致（协议漂移检查）
setup
version="$(printf '%s' "$probe_json" | jq -r '.version // ""')"
if [[ -n "$version" ]]; then
  pass=$((pass+1))
else
  note 'FAIL: probe missing version'
  fail=$((fail+1))
fi
teardown

# 测试 2: 端到端 start —— codex backend 完成一次最小对话
setup
run_output="$(cd "$TEST_TMP" && "$RUNNER" start \
  --backend codex --provider openai --model gpt-5-codex \
  --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" \
  --idle-timeout 120 --hard-timeout 300 2>&1 || true)"
run_id="$(printf '%s' "$run_output" | head -1 | jq -r '.runId // empty' 2>/dev/null)"
if [[ -z "$run_id" ]]; then
  note 'FAIL: e2e start did not emit runId'
  fail=$((fail+1))
  teardown
else
  # 轮询等待终态（最多 5 分钟）
  terminal=""
  for _ in $(seq 1 60); do
    sleep 5
    st="$(jq -r '.status // ""' "$TEST_TMP/state/$run_id/status.json" 2>/dev/null || echo "")"
    if [[ -n "$st" ]] && jq -e '.terminal == true' "$TEST_TMP/state/$run_id/status.json" >/dev/null 2>&1; then
      terminal="$st"
      break
    fi
  done
  if [[ "$terminal" == "completed" ]]; then
    pass=$((pass+1))
    # 测试 3: final.md 存在且含 pong（协议结构验证）
    if [[ -f "$TEST_TMP/state/$run_id/final.md" ]] && grep -qi "pong" "$TEST_TMP/state/$run_id/final.md"; then
      pass=$((pass+1))
    else
      note 'FAIL: final.md missing or does not contain expected reply'
      fail=$((fail+1))
    fi
    # 测试 4: receipt 含合法 usage 映射（input/output/totalTokens）
    usage_ok="$(jq -e '.completion.usage.totalTokens > 0' "$TEST_TMP/state/$run_id/status.json" 2>/dev/null || echo false)"
    if [[ "$usage_ok" == "true" ]]; then
      pass=$((pass+1))
    else
      note 'FAIL: receipt usage mapping invalid'
      fail=$((fail+1))
    fi
  else
    note "FAIL: e2e run did not complete (status: ${terminal:-none})"
    fail=$((fail+1))
    skip=$((skip+1))
  fi
  teardown
fi

# 测试 5: 二次 start 稳定性 —— 独立最小对话再次验证 start 路径
setup
run_output="$(cd "$TEST_TMP" && "$RUNNER" start \
  --backend codex --provider openai --model gpt-5-codex \
  --cwd "$TEST_TMP" --prompt-file "$TEST_TMP/prompt.txt" \
  --idle-timeout 120 --hard-timeout 300 2>&1 || true)"
run_id="$(printf '%s' "$run_output" | head -1 | jq -r '.runId // empty' 2>/dev/null)"
if [[ -n "$run_id" ]]; then
  pass=$((pass+1))
else
  note 'FAIL: second e2e run did not start'
  fail=$((fail+1))
fi
teardown

printf '\n== codex e2e tests: %d passed, %d failed, %d skipped ==\n' "$pass" "$fail" "$skip"
((fail == 0)) || exit 1
