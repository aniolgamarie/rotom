#!/usr/bin/env bash
# Validate explicit thread continuity and timeout recovery guidance.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_FILE="$SKILL_DIR/SKILL.md"
EXAMPLE_FILE="$SKILL_DIR/examples/multiturn-conversation.md"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "== Codex multi-turn and recovery contract validation =="

grep -Eq '"threadId": "[0-9a-f-]{16,}"' "$EXAMPLE_FILE" \
  || fail "multi-turn example must pass an explicit threadId"
grep -q 'resumable_timeout' "$SKILL_FILE" \
  || fail "SKILL.md must define resumable timeout handling"
grep -q -- '--thread-id "\$THREAD_ID"' "$EXAMPLE_FILE" \
  || fail "semantic CLI follow-up must resume an explicit thread ID"
grep -Eiq '(never|do not).*(duplicate writer)' "$SKILL_FILE" \
  || fail "timeout policy must prevent duplicate writers"
grep -Eiq '(host|宿主).*(timeout|停止等待|buffers|kills detached)' "$SKILL_FILE" \
  || fail "packaged skill must classify host lifecycle limits"

if grep -q "saveSessionState[(]'codexThreadId'" "$EXAMPLE_FILE"; then
  fail "example must not invent a host session API"
fi

grep -Eqi '(never|do not|禁止|永远不).*(--last|last session)' "$SKILL_FILE" "$EXAMPLE_FILE" \
  || fail "guidance must explicitly prohibit implicit last-session resume"

echo "OK: CLI multi-turn calls preserve explicit thread identity and recover without duplicate writers"
