#!/usr/bin/env bash
# Validate the codex-delegate invocation, safety, and completion contract.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_FILE="$SKILL_DIR/SKILL.md"
RUNNER="$SKILL_DIR/scripts/run-codex.sh"
PROTOCOL_FILE="$SKILL_DIR/references/progress-protocol.md"
OBSERVE_EXAMPLE="$SKILL_DIR/examples/observable-progress.md"
OPENAI_METADATA="$SKILL_DIR/agents/openai.yaml"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require_text() {
  local pattern="$1"
  local file="$2"
  local message="$3"
  grep -Eq -- "$pattern" "$file" || fail "$message"
}

echo "== Codex delegate skill contract validation =="

test -f "$SKILL_FILE" || fail "missing SKILL.md"
test -x "$RUNNER" || fail "CLI runner must exist and be executable"
test -f "$OPENAI_METADATA" || fail "missing agents/openai.yaml"

require_text '^description:.*explicit' "$SKILL_FILE" "frontmatter must require explicit user intent"
require_text 'Dedicated controller task' "$SKILL_FILE" "controller task lifecycle owner must be documented"
require_text '"\$RUNNER" start --observe' "$SKILL_FILE" "foreground observe must be the portable path"
require_text '"\$RUNNER" start --detach' "$SKILL_FILE" "detached polling compatibility must remain documented"
require_text 'heartbeat-seconds 60' "$SKILL_FILE" "default reporting cadence must be 60 seconds"
require_text 'no Node, npm, SDK, MCP server' "$SKILL_FILE" "skill must declare its CLI-only dependency boundary"
require_text 'turn.completed' "$SKILL_FILE" "completion must require turn.completed"
require_text 'final.md.*non-empty' "$SKILL_FILE" "completion must require a non-empty final artifact"
require_text 'pointer-first' "$SKILL_FILE" "skill must use pointer-first context"
require_text 'fullOutputPath' "$SKILL_FILE" "skill must describe guarded output recovery"
require_text 'CODEX_DELEGATE_PROXY_URL' "$SKILL_FILE" "skill must document explicit optional proxy configuration"
require_text 'default.*direct|direct.*default' "$SKILL_FILE" "skill must document direct connection as the default"
require_text 'Codex child environment' "$SKILL_FILE" "skill must isolate proxy settings to Codex children"
require_text 'cancelled.*resumable.*processGroupStopped' "$SKILL_FILE" \
  "skill must require safe cancellation receipts"
require_text '"\$RUNNER" prune --older-than-days 14 --apply' "$SKILL_FILE" \
  "skill must document explicit artifact pruning"
require_text 'CODEX_PROGRESS:' "$SKILL_FILE" "skill must require explicitly tagged checkpoints"
require_text '--allow-workspace-write' "$SKILL_FILE" \
  "skill must require explicit workspace-write authorization"
require_text '--worktree-root' "$SKILL_FILE" "skill must require an isolated worktree root"
require_text '--inherit-user-config' "$SKILL_FILE" \
  "skill must document explicit user-config inheritance"

require_text 'Foreground observable' "$PROTOCOL_FILE" "protocol must define foreground observe"
require_text '[Dd]edicated controller (agent/task|task)' "$PROTOCOL_FILE" \
  "protocol must define controller task behavior"
require_text 'status.json.*final.md' "$OBSERVE_EXAMPLE" "observe example must verify terminal artifacts"
require_text 'CODEX_DELEGATE_PROXY_URL' "$RUNNER" "runner must use the explicit optional proxy variable"
require_text 'proxy_command=\(' "$RUNNER" "runner must build an invocation-scoped proxy command"
require_text '--observe' "$RUNNER" "runner must implement foreground observe"
require_text 'DEFAULT_HEARTBEAT_SECONDS=60' "$RUNNER" "runner heartbeat default must be 60 seconds"
require_text '--ignore-user-config' "$RUNNER" "runner must isolate user Codex configuration by default"
require_text 'default_prompt:.*\$codex-delegate' "$OPENAI_METADATA" \
  "skill metadata must provide an explicit invocation prompt"

if grep -Eq '^[[:space:]]*export[[:space:]]+.*[Pp][Rr][Oo][Xx][Yy]' "$RUNNER" "$SKILL_FILE"; then
  fail "runner and skill must not export proxy variables"
fi

if grep -Eq '^disable-model-invocation:[[:space:]]*true' "$SKILL_FILE"; then
  fail "skill must remain visible for explicit natural-language delegation"
fi

if stale_mcp="$(grep -R -n -E --include='*.md' -- \
  'mcp[(]|codex_codex|codex-reply|delegate_start|delegate_poll' \
  "$SKILL_FILE" "$SKILL_DIR/examples")"; then
  printf '%s\n' "$stale_mcp" | sed -n '1,20p' >&2
  fail "skill or examples still contain an MCP invocation path"
fi

test ! -e "$SKILL_DIR/mcp" || fail "MCP adapter package must be absent"
test ! -e "$SKILL_DIR/tests/test-mcp-config.sh" \
  || fail "MCP config test must be absent"

if stale_cli="$(grep -R -n --include='*.md' -E -- 'codex exec (--quiet|--resume)' \
  "$SKILL_FILE" "$SKILL_DIR/examples")"; then
  printf '%s\n' "$stale_cli" | sed -n '1,20p' >&2
  fail "skill examples contain stale or unsafe Codex CLI syntax"
fi

if implicit_resume="$(grep -R -n --include='*.md' -E -- '^[[:space:]]*codex exec resume --last' \
  "$SKILL_FILE" "$SKILL_DIR/examples")"; then
  printf '%s\n' "$implicit_resume" | sed -n '1,20p' >&2
  fail "skill examples contain an executable implicit-resume command"
fi

echo "OK: Skill is CLI-only with controller/observe lifecycles and strict completion semantics"
