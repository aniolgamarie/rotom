#!/usr/bin/env bash
# model-delegate: fake backend for testing
# 通过 FAKE_BACKEND_MODE 环境变量控制行为
# 模式：success / hang / ignore-term / auth-fail / network-fail / invalid-output / no-agent-end / empty-final

set -uo pipefail

MODE="${FAKE_BACKEND_MODE:-success}"
ARGS_LOG="${FAKE_BACKEND_ARGS_LOG:-}"
ENV_LOG="${FAKE_BACKEND_ENV_LOG:-}"
READY_FILE="${FAKE_BACKEND_READY_FILE:-}"
STEP_DELAY="${FAKE_BACKEND_STEP_DELAY:-0.05}"

# 记录参数（用于测试验证）
if [[ -n "$ARGS_LOG" ]]; then
  printf '%s\n' "$@" > "$ARGS_LOG"
fi

# 记录环境
if [[ -n "$ENV_LOG" ]]; then
  env | sort > "$ENV_LOG"
fi

# 就绪信号（用于同步测试）
if [[ -n "$READY_FILE" ]]; then
  printf 'ready\n' > "$READY_FILE"
fi

emit_event() {
  printf '%s\n' "$1"
  sleep "$STEP_DELAY"
}

case "$MODE" in
  success)
    SESSION_ID="fake-session-$(date +%s)-$RANDOM"
    emit_event "{\"type\":\"session\",\"version\":3,\"id\":\"$SESSION_ID\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"cwd\":\"/tmp\"}"
    emit_event '{"type":"agent_start"}'
    emit_event '{"type":"turn_start"}'
    emit_event '{"type":"message_start","message":{"role":"user","content":[{"type":"text","text":"test prompt"}]}}'
    emit_event '{"type":"message_end","message":{"role":"user","content":[{"type":"text","text":"test prompt"}]}}'
    emit_event '{"type":"message_start","message":{"role":"assistant","content":[{"type":"text","text":""}],"stopReason":"pending"}}'
    emit_event '{"type":"message_update","usage":{"input":100,"output":10,"totalTokens":110},"assistantMessageEvent":{"type":"text_start","contentIndex":0}}'
    emit_event '{"type":"message_update","usage":{"input":100,"output":15,"totalTokens":115},"assistantMessageEvent":{"type":"text_delta","contentIndex":0,"delta":"Hello"}}'
    emit_event '{"type":"message_update","usage":{"input":100,"output":20,"totalTokens":120},"assistantMessageEvent":{"type":"text_delta","contentIndex":0,"delta":" world"}}'
    emit_event '{"type":"message_update","usage":{"input":100,"output":25,"totalTokens":125},"assistantMessageEvent":{"type":"text_end","contentIndex":0,"content":"Hello world"}}'
    emit_event '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"Hello world"}],"stopReason":"stop","usage":{"input":100,"output":25,"totalTokens":125}}}'
    emit_event '{"type":"turn_end","message":{"role":"assistant","content":[{"type":"text","text":"Hello world"}],"stopReason":"stop","usage":{"input":100,"output":25,"totalTokens":125}}}'
    emit_event '{"type":"agent_end","messages":[{"role":"assistant","content":[{"type":"text","text":"Hello world"}]}],"willRetry":false}'
    emit_event '{"type":"agent_settled"}'
    exit 0
    ;;

  hang)
    emit_event '{"type":"session","version":3,"id":"hang-session","timestamp":"2026-01-01T00:00:00Z","cwd":"/tmp"}'
    emit_event '{"type":"agent_start"}'
    # 永远不结束
    while true; do sleep 1; done
    ;;

  ignore-term)
    trap '' TERM
    emit_event '{"type":"session","version":3,"id":"ignore-term-session","timestamp":"2026-01-01T00:00:00Z","cwd":"/tmp"}'
    while true; do sleep 1; done
    ;;

  auth-fail)
    printf '403 Forbidden: invalid API key\n' >&2
    exit 1
    ;;

  network-fail)
    printf 'Connection timeout: network unreachable\n' >&2
    exit 1
    ;;

  invalid-input)
    printf 'Error: Unknown provider "nonexistent"\n' >&2
    exit 1
    ;;

  invalid-output)
    printf 'this is not json\n'
    printf 'neither is this\n'
    exit 0
    ;;

  no-agent-end)
    emit_event '{"type":"session","version":3,"id":"no-end-session","timestamp":"2026-01-01T00:00:00Z","cwd":"/tmp"}'
    emit_event '{"type":"agent_start"}'
    emit_event '{"type":"turn_start"}'
    # 没有 agent_end
    exit 0
    ;;

  empty-final)
    emit_event '{"type":"session","version":3,"id":"empty-final-session","timestamp":"2026-01-01T00:00:00Z","cwd":"/tmp"}'
    emit_event '{"type":"agent_start"}'
    emit_event '{"type":"agent_end","messages":[],"willRetry":false}'
    exit 0
    ;;

  *)
    printf 'unknown FAKE_BACKEND_MODE: %s\n' "$MODE" >&2
    exit 99
    ;;
esac
