#!/usr/bin/env bash
# Exercise normalized progress, asynchronous lifecycle, cursor, heartbeat, and safety behavior.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$SKILL_DIR"
RUNNER="$SKILL_DIR/scripts/run-codex.sh"
FAKE_CODEX="$SKILL_DIR/tests/fixtures/fake-codex.sh"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/codex-progress-test.XXXXXX")"
STATE_DIR="$TMP_ROOT/state"
PROMPT_FILE="$TMP_ROOT/prompt.txt"
ACTIVE_RUNS=()

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

cleanup() {
  local run_id
  for run_id in "${ACTIVE_RUNS[@]-}"; do
    "$RUNNER" cancel --run-id "$run_id" --state-dir "$STATE_DIR" >/dev/null 2>&1 || true
  done
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

assert_json() {
  local json="$1"
  local expression="$2"
  local message="$3"
  jq -e "$expression" <<<"$json" >/dev/null || fail "$message"
}

track_run() {
  ACTIVE_RUNS+=("$1")
}

wait_for_terminal() {
  local run_id="$1"
  local attempt response
  for ((attempt = 1; attempt <= 300; attempt++)); do
    response="$("$RUNNER" status --run-id "$run_id" --state-dir "$STATE_DIR")"
    if jq -e '.terminal == true' <<<"$response" >/dev/null; then
      printf '%s\n' "$response"
      return 0
    fi
    sleep 0.05
  done
  fail "timed out waiting for terminal run: $run_id"
}

start_detached() {
  local mode="$1"
  shift
  FAKE_CODEX_MODE="$mode" "$RUNNER" start --detach \
    --cwd "$ROOT_DIR" \
    --prompt-file "$PROMPT_FILE" \
    --state-dir "$STATE_DIR" \
    --poll-interval 0.1 \
    --codex-bin "$FAKE_CODEX" \
    "$@"
}

test -x "$RUNNER" || fail "runner is not executable"
test -x "$FAKE_CODEX" || fail "fake Codex fixture is not executable"
command -v jq >/dev/null 2>&1 || fail "jq is required"

mkdir -p "$STATE_DIR"
printf '%s\n' 'Perform one bounded observable read-only review.' >"$PROMPT_FILE"

echo "== Codex observable progress validation =="

phased_start="$(
  FAKE_CODEX_STEP_DELAY=0.1 \
  FAKE_CODEX_QUIET_DELAY=10 \
    start_detached phased --stale-after 10
)"
phased_id="$(jq -r '.runId' <<<"$phased_start")"
track_run "$phased_id"
phased_dir="$STATE_DIR/$phased_id"
cursor="$(jq -r '.nextCursor' <<<"$phased_start")"
assert_json "$phased_start" \
  '.operation == "start" and .state == "running" and (.terminal | not) and .report.reason == "started"' \
  "detached start did not return a ready observable run"
[[ "$(wc -c <<<"$phased_start")" -le 4096 ]] || fail "start response exceeded the default budget"

checkpoint_seen=false
milestone_seen=false
for ((attempt = 1; attempt <= 20; attempt++)); do
  poll_json="$("$RUNNER" poll \
    --run-id "$phased_id" \
    --after "$cursor" \
    --wait-seconds 1 \
    --state-dir "$STATE_DIR")"
  [[ "$(wc -c <<<"$poll_json")" -le 4096 ]] || fail "poll response exceeded the default budget"
  if jq -e '.events[]? | select(.kind == "checkpoint")' <<<"$poll_json" >/dev/null; then
    checkpoint_seen=true
  fi
  if jq -e '.events[]?.milestones | select(.total == 3)' <<<"$poll_json" >/dev/null; then
    milestone_seen=true
  fi
  cursor="$(jq -r '.nextCursor' <<<"$poll_json")"
  if [[ "$checkpoint_seen" == "true" && "$milestone_seen" == "true" ]]; then
    break
  fi
done
[[ "$checkpoint_seen" == "true" ]] || fail "semantic checkpoint was not exposed"
[[ "$milestone_seen" == "true" ]] || fail "explicit milestone totals were not preserved"

for ((attempt = 1; attempt <= 20; attempt++)); do
  drain_json="$("$RUNNER" events \
    --run-id "$phased_id" \
    --after "$cursor" \
    --state-dir "$STATE_DIR")"
  cursor="$(jq -r '.nextCursor' <<<"$drain_json")"
  jq -e '.hasMore == false' <<<"$drain_json" >/dev/null && break
done

for ((attempt = 1; attempt <= 5; attempt++)); do
  heartbeat_json="$("$RUNNER" poll \
    --run-id "$phased_id" \
    --after "$cursor" \
    --wait-seconds 1 \
    --state-dir "$STATE_DIR")"
  if jq -e '.report.reason == "heartbeat" and (.events | length) == 0' \
    <<<"$heartbeat_json" >/dev/null; then
    break
  fi
  cursor="$(jq -r '.nextCursor' <<<"$heartbeat_json")"
done
assert_json "$heartbeat_json" \
  ".report.recommended
    and .report.reason == \"heartbeat\"
    and .nextCursor == $cursor
    and (.events | length) == 0" \
  "quiet poll did not return a cursor-stable heartbeat"

phased_terminal="$(wait_for_terminal "$phased_id")"
assert_json "$phased_terminal" \
  '.state == "completed" and .terminal and .threadId == "thread-started"' \
  "phased run did not reach strict completion"
jq -se '
  [.[].seq] as $sequences
  | ($sequences | length) == ($sequences | unique | length)
  and all(
    range(1; ($sequences | length));
    . as $index | $sequences[$index] > $sequences[$index - 1]
  )
' "$phased_dir/progress.jsonl" >/dev/null \
  || fail "normalized event sequences are not unique and monotonic"
if rg -q 'PRIVATE_REASONING|PRIVATE_DIFF|PRIVATE_COMMAND_OUTPUT' \
  "$phased_dir/progress.json" "$phased_dir/progress.jsonl"; then
  fail "private reasoning, diff, or command output leaked into progress artifacts"
fi

replay_one="$("$RUNNER" events --run-id "$phased_id" --after 0 --state-dir "$STATE_DIR")"
replay_two="$("$RUNNER" events --run-id "$phased_id" --after 0 --state-dir "$STATE_DIR")"
[[ "$(jq -c '[.events[].seq]' <<<"$replay_one")" == "$(jq -c '[.events[].seq]' <<<"$replay_two")" ]] \
  || fail "independent cursor readers received different replay prefixes"

burst_start="$(start_detached activity-burst)"
burst_id="$(jq -r '.runId' <<<"$burst_start")"
track_run "$burst_id"
burst_terminal="$(wait_for_terminal "$burst_id")"
assert_json "$burst_terminal" '.state == "completed"' "activity-burst run did not complete"
burst_events="$("$RUNNER" events \
  --run-id "$burst_id" \
  --after 0 \
  --max-events 1 \
  --state-dir "$STATE_DIR")"
assert_json "$burst_events" \
  '.hasMore and (.events | length) == 1 and .nextCursor == .events[0].seq' \
  "bounded event response did not preserve whole-event continuation"
[[ "$(wc -c <<<"$burst_events")" -le 4096 ]] || fail "bounded event response exceeded 4096 bytes"
if rg -q 'BURST_REASONING|BURST_OUTPUT' "$STATE_DIR/$burst_id/progress.json"*; then
  fail "burst private content leaked into normalized progress"
fi

sensitive_start="$(start_detached sensitive-progress)"
sensitive_id="$(jq -r '.runId' <<<"$sensitive_start")"
track_run "$sensitive_id"
sensitive_terminal="$(wait_for_terminal "$sensitive_id")"
assert_json "$sensitive_terminal" '.state == "completed"' "sensitive-progress run did not complete"
sensitive_dir="$STATE_DIR/$sensitive_id"
rg -q 'PRIVATE_UNTAGGED_MESSAGE' "$sensitive_dir/events.jsonl" \
  || fail "sensitive fixture did not preserve its raw private message"
rg -q 'PRIVATE_ERROR_MESSAGE' "$sensitive_dir/events.jsonl" \
  || fail "sensitive fixture did not preserve its raw private error"
if rg -q \
  'SYNTHETIC_OMP_61e8530c90d0|synthetic-secret|PRIVATE_UNTAGGED_MESSAGE|PRIVATE_TAGGED_MESSAGE|PRIVATE_ERROR_MESSAGE|hunter2' \
  "$sensitive_dir/progress.json" "$sensitive_dir/progress.jsonl"; then
  fail "sensitive model-authored text leaked into normalized progress"
fi
jq -se '
  any(.[]; .kind == "checkpoint" and .summary == "Codex reported a checkpoint; details remain in private artifacts.")
  and any(.[]; .kind == "warning" and .summary == "Codex reported an error; private diagnostics are available in the run artifacts.")
' "$sensitive_dir/progress.jsonl" >/dev/null \
  || fail "unsafe checkpoint or private error was not replaced with a generic normalized summary"

sensitive_failure_start="$(start_detached sensitive-failure)"
sensitive_failure_id="$(jq -r '.runId' <<<"$sensitive_failure_start")"
track_run "$sensitive_failure_id"
sensitive_failure_terminal="$(wait_for_terminal "$sensitive_failure_id")"
assert_json "$sensitive_failure_terminal" \
  '.state == "failed_resumable" and .terminal and .resumable' \
  "sensitive turn failure did not reach its expected terminal state"
sensitive_failure_dir="$STATE_DIR/$sensitive_failure_id"
if rg -q 'SYNTHETIC_OMP_66cc6c602b1d|PRIVATE_TURN_FAILURE' \
  "$sensitive_failure_dir/progress.json" "$sensitive_failure_dir/progress.jsonl"; then
  fail "private turn failure diagnostic leaked into normalized progress"
fi
rg -q 'Codex turn failed; private diagnostics are available in the run artifacts.' \
  "$sensitive_failure_dir/progress.jsonl" \
  || fail "private turn failure did not produce a generic warning"

partial_start="$(
  FAKE_CODEX_QUIET_DELAY=2 \
    start_detached partial-line
)"
partial_id="$(jq -r '.runId' <<<"$partial_start")"
track_run "$partial_id"
sleep 0.5
if rg -q 'malformed JSONL' "$STATE_DIR/$partial_id/progress.jsonl"; then
  fail "an incomplete trailing JSONL line was treated as malformed"
fi
partial_terminal="$(wait_for_terminal "$partial_id")"
assert_json "$partial_terminal" '.state == "completed"' "partial-line run did not complete"
rg -q 'partial checkpoint' "$STATE_DIR/$partial_id/progress.jsonl" \
  || fail "completed partial line was not normalized"

caller_https_before="${HTTPS_PROXY-__unset__}"
proxy_env_file="$TMP_ROOT/async-proxy-env.txt"
timeout_start="$(
  HTTPS_PROXY="http://caller.invalid:9999" \
  HTTP_PROXY="http://caller.invalid:9999" \
  ALL_PROXY="socks5://caller.invalid:9999" \
  FAKE_CODEX_MODE=timeout \
  FAKE_CODEX_ENV_FILE="$proxy_env_file" \
    "$RUNNER" start --detach \
      --cwd "$ROOT_DIR" \
      --prompt-file "$PROMPT_FILE" \
      --state-dir "$STATE_DIR" \
      --idle-timeout 0 \
      --hard-timeout 0 \
      --poll-interval 0.1 \
      --stale-after 1 \
      --codex-bin "$FAKE_CODEX"
)"
timeout_id="$(jq -r '.runId' <<<"$timeout_start")"
track_run "$timeout_id"
sleep 2
stale_status="$("$RUNNER" status --run-id "$timeout_id" --state-dir "$STATE_DIR" --stale-after 1)"
assert_json "$stale_status" \
  '.state == "running" and .stale and .supervisorAlive and (.processGroupStopped | not)' \
  "live quiet run was not distinguished as stale"
[[ "${HTTPS_PROXY-__unset__}" == "$caller_https_before" ]] || fail "detached start changed caller proxy variables"
for proxy_name in HTTPS_PROXY HTTP_PROXY ALL_PROXY https_proxy http_proxy all_proxy NO_PROXY no_proxy; do
  rg -q "^${proxy_name}=__unset__$" "$proxy_env_file" \
    || fail "detached direct Codex child inherited caller proxy in $proxy_name"
done

cancel_status="$("$RUNNER" cancel --run-id "$timeout_id" --state-dir "$STATE_DIR")"
assert_json "$cancel_status" \
  '.state == "cancelled" and .terminal and .resumable and .processGroupStopped' \
  "asynchronous cancel did not produce a resumable terminal receipt"

resume_start="$(
  FAKE_CODEX_MODE=success \
    "$RUNNER" resume --run-id "$timeout_id" --detach \
      --prompt-file "$PROMPT_FILE" \
      --state-dir "$STATE_DIR" \
      --poll-interval 0.1 \
      --codex-bin "$FAKE_CODEX"
)"
resume_id="$(jq -r '.runId' <<<"$resume_start")"
track_run "$resume_id"
[[ "$resume_id" != "$timeout_id" ]] || fail "resume reused the prior run ID"
resume_terminal="$(wait_for_terminal "$resume_id")"
assert_json "$resume_terminal" \
  '.state == "completed" and .threadId == "thread-resumed"' \
  "linked asynchronous resume did not complete"
jq -e --arg prior "$timeout_id" '.resumedFromRunId == $prior' \
  "$STATE_DIR/$resume_id/.codex-delegate-run.json" >/dev/null \
  || fail "resumed run did not record its source run"

hard_timeout_start="$(
  FAKE_CODEX_MODE=timeout \
    start_detached timeout --idle-timeout 0 --hard-timeout 1
)"
hard_timeout_id="$(jq -r '.runId' <<<"$hard_timeout_start")"
track_run "$hard_timeout_id"
bounded_wait="$("$RUNNER" wait \
  --run-id "$hard_timeout_id" \
  --wait-seconds 1 \
  --state-dir "$STATE_DIR")"
assert_json "$bounded_wait" \
  '.operation == "wait" and (.state == "running" or .terminal)' \
  "bounded wait did not return a valid current state"
hard_timeout_terminal="$(wait_for_terminal "$hard_timeout_id")"
assert_json "$hard_timeout_terminal" \
  '.state == "resumable_timeout" and .terminal and .resumable and .processGroupStopped' \
  "detached hard timeout did not preserve resumable terminal state"
jq -e '.terminationReason == "hard_timeout"' "$STATE_DIR/$hard_timeout_id/status.json" >/dev/null \
  || fail "detached hard timeout lost its termination reason"

set +e
readiness_json="$(
  CODEX_DELEGATE_TEST_READY_DELAY=5 \
  FAKE_CODEX_MODE=timeout \
    "$RUNNER" start --detach \
      --cwd "$ROOT_DIR" \
      --prompt-file "$PROMPT_FILE" \
      --state-dir "$STATE_DIR" \
      --idle-timeout 0 \
      --hard-timeout 0 \
      --poll-interval 0.1 \
      --ready-timeout 0.1 \
      --codex-bin "$FAKE_CODEX"
)"
readiness_exit="$?"
set -e
[[ "$readiness_exit" -eq 70 ]] || fail "readiness timeout exited with $readiness_exit instead of 70"
readiness_id="$(jq -r '.runId' <<<"$readiness_json")"
track_run "$readiness_id"
assert_json "$readiness_json" \
  '.startupTimedOut
    and .terminal
    and .state == "cancelled"
    and .processGroupStopped
    and .retrySafe' \
  "readiness timeout did not stop its validated supervisor and return a terminal receipt"
jq -e '.status == "cancelled" and .processGroupStopped' \
  "$STATE_DIR/$readiness_id/status.json" >/dev/null \
  || fail "readiness timeout did not persist its cancellation receipt"

active_start="$(
  FAKE_CODEX_MODE=timeout \
    start_detached timeout --idle-timeout 0 --hard-timeout 0
)"
active_id="$(jq -r '.runId' <<<"$active_start")"
track_run "$active_id"
touch -d "20 days ago" "$STATE_DIR/$active_id/progress.json"
"$RUNNER" prune --state-dir "$STATE_DIR" --older-than-days 0 --apply >/dev/null
[[ -d "$STATE_DIR/$active_id" ]] || fail "prune deleted an active run with progress artifacts"
"$RUNNER" cancel --run-id "$active_id" --state-dir "$STATE_DIR" >/dev/null

orphan_start="$(
  FAKE_CODEX_MODE=timeout \
    start_detached timeout --idle-timeout 0 --hard-timeout 0
)"
orphan_id="$(jq -r '.runId' <<<"$orphan_start")"
track_run "$orphan_id"
orphan_supervisor="$STATE_DIR/$orphan_id/supervisor.json"
orphan_pid="$(jq -r '.pid' "$orphan_supervisor")"
orphan_group="$(jq -r '.processGroupId' "$orphan_supervisor")"
kill -KILL "$orphan_pid"
for ((attempt = 1; attempt <= 100; attempt++)); do
  kill -0 "$orphan_pid" 2>/dev/null || break
  sleep 0.02
done
orphan_status="$("$RUNNER" status --run-id "$orphan_id" --state-dir "$STATE_DIR")"
assert_json "$orphan_status" \
  '.state == "orphaned" and (.terminal | not) and (.processGroupStopped | not)' \
  "missing supervisor without a receipt was misclassified"
kill -KILL -- "-$orphan_group" 2>/dev/null || true

unmarked="$STATE_DIR/run-unmarked"
mkdir "$unmarked"
set +e
"$RUNNER" status --run-id run-unmarked --state-dir "$STATE_DIR" >/dev/null 2>&1
unmarked_exit="$?"
set -e
[[ "$unmarked_exit" -eq 64 ]] || fail "unmarked control target was not rejected"

linked_target="$TMP_ROOT/linked-target"
mkdir "$linked_target"
ln -s "$linked_target" "$STATE_DIR/run-linked"
set +e
"$RUNNER" status --run-id run-linked --state-dir "$STATE_DIR" >/dev/null 2>&1
linked_exit="$?"
set -e
[[ "$linked_exit" -eq 64 ]] || fail "symlinked control target was not rejected"

echo "OK: Observable progress is incremental, bounded, private, resumable, and host-neutral"
