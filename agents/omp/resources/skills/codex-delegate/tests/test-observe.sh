#!/usr/bin/env bash
# Validate the foreground observable CLI stream without a detached lifecycle owner.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$SKILL_DIR"
RUNNER="$SKILL_DIR/scripts/run-codex.sh"
FAKE_CODEX="$SKILL_DIR/tests/fixtures/fake-codex.sh"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/codex-observe-test.XXXXXX")"
STATE_DIR="$TMP_ROOT/state"
PROMPT_FILE="$TMP_ROOT/prompt.txt"
ACTIVE_PIDS=()

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

cleanup() {
  local pid
  for pid in "${ACTIVE_PIDS[@]-}"; do
    kill -TERM "$pid" >/dev/null 2>&1 || true
    wait "$pid" >/dev/null 2>&1 || true
  done
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

assert_jsonl() {
  local path="$1"
  local message="$2"
  [[ -s "$path" ]] || fail "$message: output is empty"
  jq -e -s 'all(.[]; type == "object")' "$path" >/dev/null || fail "$message: invalid JSONL"
  while IFS= read -r line; do
    [[ -n "$line" ]] || fail "$message: output contains an empty physical line"
    jq -e -s 'length == 1 and (.[0] | type == "object")' <<<"$line" >/dev/null \
      || fail "$message: one physical line was not exactly one complete JSON object"
    [[ "$(LC_ALL=C printf '%s\n' "$line" | wc -c)" -le 4096 ]] \
      || fail "$message: one observable record exceeded 4096 bytes"
  done <"$path"
}

wait_for_json() {
  local path="$1"
  local expression="$2"
  local attempt
  for ((attempt = 1; attempt <= 300; attempt++)); do
    if [[ -s "$path" ]] && jq -e "$expression" "$path" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.02
  done
  fail "timed out waiting for $path to satisfy $expression"
}

wait_for_jsonl() {
  local path="$1"
  local expression="$2"
  local attempt
  for ((attempt = 1; attempt <= 500; attempt++)); do
    if [[ -s "$path" ]] && jq -e -s "$expression" "$path" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.02
  done
  fail "timed out waiting for JSONL $path to satisfy $expression"
}

test -x "$RUNNER" || fail "runner is not executable"
test -x "$FAKE_CODEX" || fail "fake Codex fixture is not executable"
command -v jq >/dev/null 2>&1 || fail "jq is required"

mkdir -p "$STATE_DIR"
printf '%s\n' "Perform one bounded observable read-only review." >"$PROMPT_FILE"

echo "== Codex foreground observe validation =="

phased_output="$TMP_ROOT/phased.jsonl"
proxy_env_file="$TMP_ROOT/proxy-env.txt"
caller_https_before="${HTTPS_PROXY-__unset__}"
HTTPS_PROXY="http://caller.invalid:9999" \
HTTP_PROXY="http://caller.invalid:9999" \
ALL_PROXY="socks5://caller.invalid:9999" \
FAKE_CODEX_MODE=phased \
FAKE_CODEX_STEP_DELAY=0.1 \
FAKE_CODEX_QUIET_DELAY=5 \
FAKE_CODEX_ENV_FILE="$proxy_env_file" \
  "$RUNNER" start --observe \
    --cwd "$ROOT_DIR" \
    --prompt-file "$PROMPT_FILE" \
    --state-dir "$STATE_DIR" \
    --poll-interval 0.1 \
    --heartbeat-seconds 1 \
    --codex-bin "$FAKE_CODEX" >"$phased_output" &
phased_pid="$!"
ACTIVE_PIDS+=("$phased_pid")
wait_for_jsonl "$phased_output" 'any(.[]; .terminal)'
phased_run_dir="$(jq -r -s '.[0].runDir' "$phased_output")"
jq -e '.status == "completed" and .turnCompleted and .finalNonempty' \
  "$phased_run_dir/status.json" >/dev/null \
  || fail "terminal observe record was visible before its strict completion receipt"
set +e
wait "$phased_pid"
phased_exit="$?"
set -e
[[ "$phased_exit" -eq 0 ]] || fail "phased observe exited with $phased_exit"
[[ "${HTTPS_PROXY-__unset__}" == "$caller_https_before" ]] || fail "observe changed caller proxy variables"

assert_jsonl "$phased_output" "phased observe"
jq -e -s '
  length >= 4
  and all(.[];
    .schemaVersion == 1
    and .operation == "observe"
    and (.runId | startswith("run-"))
  )
  and (map(.runId) | unique | length) == 1
  and any(.[]; any(.events[]?; .kind == "checkpoint"))
  and .[-1].terminal
  and .[-1].state == "completed"
  and .[-1].report.reason == "terminal"
' "$phased_output" >/dev/null || fail "observe stream missed checkpoint, heartbeat, or terminal state"
jq -e -s '
  [.[].nextCursor] as $cursors
  | all(
      range(1; ($cursors | length));
      . as $index | $cursors[$index] >= $cursors[$index - 1]
    )
' "$phased_output" >/dev/null || fail "observe cursors moved backwards"
if rg -q 'PRIVATE_REASONING|PRIVATE_DIFF|PRIVATE_COMMAND_OUTPUT' "$phased_output"; then
  fail "observe exposed private reasoning, diff, or command output"
fi
for proxy_name in HTTPS_PROXY HTTP_PROXY ALL_PROXY https_proxy http_proxy all_proxy NO_PROXY no_proxy; do
  rg -q "^${proxy_name}=__unset__$" "$proxy_env_file" \
    || fail "observe direct Codex child inherited caller proxy in $proxy_name"
done

jq -e '.status == "completed" and .turnCompleted and .finalNonempty' \
  "$phased_run_dir/status.json" >/dev/null \
  || fail "terminal observe record was not backed by a strict completion receipt"

cancel_run_dir="$STATE_DIR/run-observe-cancel"
cancel_output="$TMP_ROOT/cancel.jsonl"
FAKE_CODEX_MODE=timeout \
  "$RUNNER" start --observe \
    --cwd "$ROOT_DIR" \
    --prompt-file "$PROMPT_FILE" \
    --state-dir "$STATE_DIR" \
    --run-dir "$cancel_run_dir" \
    --idle-timeout 0 \
    --hard-timeout 0 \
    --poll-interval 0.1 \
    --heartbeat-seconds 1 \
    --codex-bin "$FAKE_CODEX" >"$cancel_output" &
cancel_pid="$!"
ACTIVE_PIDS+=("$cancel_pid")
wait_for_json "$cancel_run_dir/progress.json" '.threadId == "thread-started"'
wait_for_jsonl "$cancel_output" '
  [.[] | select(
    .report.reason == "heartbeat"
    and (.events | length) == 0
    and .nextCursor == .cursor
  )] | length >= 3
'
cancel_control="$("$RUNNER" cancel --run-id run-observe-cancel --state-dir "$STATE_DIR")"
jq -e '
  .operation == "cancel"
  and .state == "cancelled"
  and .terminal
  and .resumable
  and .processGroupStopped
' <<<"$cancel_control" >/dev/null || fail "run-id cancellation did not return a terminal receipt"
set +e
wait "$cancel_pid"
cancel_exit="$?"
set -e
[[ "$cancel_exit" -eq 143 ]] || fail "cancelled observe exited with $cancel_exit instead of 143"
assert_jsonl "$cancel_output" "cancelled observe"
jq -e -s '
  . as $records
  | any($records[];
    .report.reason == "heartbeat"
    and (.events | length) == 0
    and .nextCursor == .cursor
  )
  and all(
    range(1; ($records | length));
    . as $index
    | if $records[$index].report.reason == "heartbeat"
        and ($records[$index].events | length) == 0
      then $records[$index].nextCursor == $records[$index - 1].nextCursor
      else true
      end
  )
  and (
    [$records[] | select(.report.reason == "heartbeat") | .updatedAt] as $heartbeats
    | ($heartbeats | length) >= 3
    and all(
      range(1; ($heartbeats | length));
      . as $index | ($heartbeats[$index] - $heartbeats[$index - 1]) >= 1
    )
  )
  and $records[-1].terminal
  and $records[-1].state == "cancelled"
  and $records[-1].report.reason == "terminal"
' "$cancel_output" >/dev/null || fail "cancelled observe omitted its terminal record"
jq -e '
  .status == "cancelled"
  and .resumable
  and .processGroupStopped
  and .signal == "TERM"
' "$cancel_run_dir/status.json" >/dev/null || fail "cancelled observe did not persist its receipt"

resume_run_dir="$STATE_DIR/run-observe-resume"
resume_output="$TMP_ROOT/resume.jsonl"
FAKE_CODEX_MODE=success \
  "$RUNNER" resume --run-id run-observe-cancel --observe \
    --prompt-file "$PROMPT_FILE" \
    --state-dir "$STATE_DIR" \
    --run-dir "$resume_run_dir" \
    --poll-interval 0.1 \
    --heartbeat-seconds 1 \
    --codex-bin "$FAKE_CODEX" >"$resume_output"
assert_jsonl "$resume_output" "resumed observe"
jq -e -s '
  .[-1].terminal
  and .[-1].state == "completed"
  and .[-1].threadId == "thread-resumed"
' "$resume_output" >/dev/null || fail "resumed observe did not complete"
jq -e '.resumedFromRunId == "run-observe-cancel"' \
  "$resume_run_dir/.codex-delegate-run.json" >/dev/null \
  || fail "resumed observe lost its source run ID"

padding=""
printf -v padding '%070d' 0
budget_state_dir="$TMP_ROOT/long-state"
for segment in 1 2 3 4 5 6 7 8; do
  budget_state_dir="$budget_state_dir/segment-${segment}-${padding}"
done
mkdir -p "$budget_state_dir"
budget_run_dir="$budget_state_dir/run-observe-budget"
budget_output="$TMP_ROOT/budget.jsonl"
FAKE_CODEX_MODE=unicode-checkpoint \
  "$RUNNER" start --observe \
    --cwd "$ROOT_DIR" \
    --prompt-file "$PROMPT_FILE" \
    --state-dir "$budget_state_dir" \
    --run-dir "$budget_run_dir" \
    --poll-interval 0.1 \
    --heartbeat-seconds 1 \
    --output-budget 4096 \
    --codex-bin "$FAKE_CODEX" >"$budget_output"
assert_jsonl "$budget_output" "long-path observable budget"
jq -e -s '
  any(.[]; .compact == true and .artifacts.relativeToRunDir == true)
  and any(.[]; any(.events[]?; .kind == "checkpoint"))
  and .[-1].terminal
  and .[-1].state == "completed"
' "$budget_output" >/dev/null \
  || fail "compact observe envelope lost whole events, artifact references, or terminal state"
budget_status="$("$RUNNER" status \
  --run-id run-observe-budget \
  --state-dir "$budget_state_dir" \
  --output-budget 4096)"
jq -e '
  .compact
  and .terminal
  and .state == "completed"
  and .artifacts.relativeToRunDir
' <<<"$budget_status" >/dev/null || fail "long-path status response was not compact and terminal"
[[ "$(LC_ALL=C wc -c <<<"$budget_status")" -le 4096 ]] \
  || fail "long-path status response exceeded 4096 bytes"

timeout_run_dir="$STATE_DIR/run-observe-timeout"
timeout_output="$TMP_ROOT/timeout.jsonl"
set +e
FAKE_CODEX_MODE=timeout \
  "$RUNNER" start --observe \
    --cwd "$ROOT_DIR" \
    --prompt-file "$PROMPT_FILE" \
    --state-dir "$STATE_DIR" \
    --run-dir "$timeout_run_dir" \
    --idle-timeout 0 \
    --hard-timeout 1 \
    --poll-interval 0.1 \
    --heartbeat-seconds 1 \
    --codex-bin "$FAKE_CODEX" >"$timeout_output"
timeout_exit="$?"
set -e
[[ "$timeout_exit" -eq 124 ]] || fail "timed-out observe exited with $timeout_exit instead of 124"
assert_jsonl "$timeout_output" "timed-out observe"
jq -e -s '
  .[-1].terminal
  and .[-1].state == "resumable_timeout"
  and .[-1].resumable
  and .[-1].processGroupStopped
' "$timeout_output" >/dev/null || fail "timed-out observe omitted its resumable terminal state"
jq -e '.terminationReason == "hard_timeout"' "$timeout_run_dir/status.json" >/dev/null \
  || fail "timed-out observe receipt lost its termination reason"

set +e
"$RUNNER" start --detach --observe \
  --cwd "$ROOT_DIR" \
  --prompt-file "$PROMPT_FILE" \
  --state-dir "$STATE_DIR" \
  --codex-bin "$FAKE_CODEX" >/dev/null 2>&1
mutual_exit="$?"
set -e
[[ "$mutual_exit" -eq 64 ]] || fail "--detach and --observe were not rejected together"

set +e
"$RUNNER" status \
  --run-id run-observe-resume \
  --state-dir "$STATE_DIR" \
  --output-budget 4095 >/dev/null 2>&1
small_budget_exit="$?"
set -e
[[ "$small_budget_exit" -eq 64 ]] || fail "an unsafe sub-4-KiB response budget was accepted"

echo "OK: Foreground observe is bounded, private, cancellable, resumable, and receipt-backed"
