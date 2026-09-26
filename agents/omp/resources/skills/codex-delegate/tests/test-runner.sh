#!/usr/bin/env bash
# Exercise runner completion, partial output, parser, timeout, and resume behavior.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$SKILL_DIR"
RUNNER="$SKILL_DIR/scripts/run-codex.sh"
FAKE_CODEX="$SKILL_DIR/tests/fixtures/fake-codex.sh"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/codex-runner-test.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_receipt() {
  local receipt_file="$1"
  local expression="$2"
  local message="$3"
  jq -e "$expression" "$receipt_file" >/dev/null || fail "$message"
}

wait_for_file() {
  local path="$1"
  local attempt
  for ((attempt = 1; attempt <= 200; attempt++)); do
    [[ -s "$path" ]] && return 0
    sleep 0.01
  done
  fail "timed out waiting for file: $path"
}

wait_for_pattern() {
  local path="$1"
  local pattern="$2"
  local attempt
  for ((attempt = 1; attempt <= 200; attempt++)); do
    if [[ -f "$path" ]] && grep -Fq "$pattern" "$path"; then
      return 0
    fi
    sleep 0.01
  done
  fail "timed out waiting for '$pattern' in $path"
}

test -x "$RUNNER" || fail "runner is not executable"
test -x "$FAKE_CODEX" || fail "fake Codex fixture is not executable"
command -v jq >/dev/null 2>&1 || fail "jq is required"
command -v git >/dev/null 2>&1 || fail "git is required"

prompt_file="$TMP_ROOT/prompt.txt"
printf '%s\n' 'Perform one bounded read-only review.' >"$prompt_file"
state_dir="$TMP_ROOT/state"
mkdir -p "$state_dir"

echo "== Codex runner behavior validation =="

success_dir="$state_dir/run-success"
mkdir "$success_dir"
caller_https_before="${HTTPS_PROXY-__unset__}"
caller_http_before="${HTTP_PROXY-__unset__}"
HTTPS_PROXY="http://caller.invalid:9999" \
HTTP_PROXY="http://caller.invalid:9999" \
ALL_PROXY="socks5://caller.invalid:9999" \
NO_PROXY="api.openai.com" \
FAKE_CODEX_MODE=success \
FAKE_CODEX_ARGS_FILE="$TMP_ROOT/success-args.txt" \
FAKE_CODEX_ENV_FILE="$TMP_ROOT/success-env.txt" \
"$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$success_dir" \
  --state-dir "$state_dir" \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/success-receipt.json"

assert_receipt "$TMP_ROOT/success-receipt.json" \
  '.status == "completed" and .turnCompleted and .finalNonempty and .codexExit == 0 and .parsedEvents == 3' \
  "successful run did not satisfy strict completion semantics"
assert_receipt "$TMP_ROOT/success-receipt.json" \
  '.usage.input_tokens == 10 and .usage.output_tokens == 5' \
  "usage was not preserved in the receipt"
assert_receipt "$TMP_ROOT/success-receipt.json" \
  '.proxy.scope == "codex-child" and .proxy.mode == "direct" and (.proxy | has("url") | not)' \
  "receipt did not report direct child networking without a proxy value"
assert_receipt "$TMP_ROOT/success-receipt.json" \
  '.configMode == "isolated"' \
  "default run did not record isolated Codex configuration"
grep -Fxq -- '--ignore-user-config' "$TMP_ROOT/success-args.txt" \
  || fail "default start did not ignore user-level Codex configuration"
for proxy_name in HTTPS_PROXY HTTP_PROXY ALL_PROXY https_proxy http_proxy all_proxy NO_PROXY no_proxy; do
  grep -Fxq "$proxy_name=__unset__" "$TMP_ROOT/success-env.txt" \
    || fail "direct Codex child inherited caller proxy variable $proxy_name"
done
[[ "${HTTPS_PROXY-__unset__}" == "$caller_https_before" ]] \
  || fail "runner changed the caller HTTPS_PROXY"
[[ "${HTTP_PROXY-__unset__}" == "$caller_http_before" ]] \
  || fail "runner changed the caller HTTP_PROXY"
[[ "$(wc -l <"$TMP_ROOT/success-receipt.json")" -eq 1 ]] \
  || fail "runner stdout must contain one compact receipt line"
[[ "$(stat -c '%a' "$success_dir")" == "700" ]] || fail "run directory must be private"
[[ "$(stat -c '%a' "$success_dir/events.jsonl")" == "600" ]] || fail "artifacts must be private"
[[ "$(stat -c '%a' "$success_dir/.codex-delegate-run.json")" == "600" ]] \
  || fail "run ownership marker must be private"

proxy_dir="$state_dir/run-proxy"
mkdir "$proxy_dir"
CODEX_DELEGATE_PROXY_URL="http://127.0.0.1:18080" \
FAKE_CODEX_MODE=success \
FAKE_CODEX_ENV_FILE="$TMP_ROOT/proxy-env.txt" \
"$RUNNER" start --cwd "$ROOT_DIR" --prompt-file "$prompt_file" \
  --run-dir "$proxy_dir" --state-dir "$state_dir" --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/proxy-receipt.json"
assert_receipt "$TMP_ROOT/proxy-receipt.json" \
  '.proxy == {scope: "codex-child", mode: "configured"}' \
  "configured proxy receipt leaked or omitted proxy mode"
for proxy_name in HTTPS_PROXY HTTP_PROXY ALL_PROXY https_proxy http_proxy all_proxy; do
  grep -Fxq "$proxy_name=http://127.0.0.1:18080" "$TMP_ROOT/proxy-env.txt" \
    || fail "configured proxy was not scoped to Codex child variable $proxy_name"
done

invalid_proxy_output="$TMP_ROOT/invalid-proxy-output.txt"
set +e
CODEX_DELEGATE_PROXY_URL="http://user:SYNTHETIC_SECRET@proxy.invalid:8080" \
  "$RUNNER" start --cwd "$ROOT_DIR" --prompt-file "$prompt_file" \
  --state-dir "$state_dir" --codex-bin "$FAKE_CODEX" >"$invalid_proxy_output" 2>&1
invalid_proxy_exit="$?"
set -e
[[ "$invalid_proxy_exit" -eq 64 ]] || fail "credential-bearing proxy URL was not rejected"
! grep -Fq 'SYNTHETIC_SECRET' "$invalid_proxy_output" \
  || fail "credential-bearing proxy value leaked in diagnostics"

incomplete_dir="$state_dir/run-incomplete"
mkdir "$incomplete_dir"
set +e
FAKE_CODEX_MODE=incomplete "$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$incomplete_dir" \
  --state-dir "$state_dir" \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/incomplete-receipt.json"
incomplete_exit=$?
set -e
[[ "$incomplete_exit" -eq 65 ]] || fail "partial success must exit 65, got $incomplete_exit"
assert_receipt "$TMP_ROOT/incomplete-receipt.json" \
  '.status == "incomplete" and .resumable and (.turnCompleted | not) and (.finalNonempty | not)' \
  "intermediate agent_message was incorrectly accepted as final"

whitespace_dir="$state_dir/run-whitespace"
mkdir "$whitespace_dir"
set +e
FAKE_CODEX_MODE=whitespace-final "$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$whitespace_dir" \
  --state-dir "$state_dir" \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/whitespace-receipt.json"
whitespace_exit=$?
set -e
[[ "$whitespace_exit" -eq 65 ]] || fail "whitespace final must exit 65, got $whitespace_exit"
assert_receipt "$TMP_ROOT/whitespace-receipt.json" \
  '.status == "incomplete" and .turnCompleted and (.finalNonempty | not)' \
  "whitespace-only final was incorrectly accepted"

corrupt_dir="$state_dir/run-corrupt"
mkdir "$corrupt_dir"
FAKE_CODEX_MODE=corrupt-success "$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$corrupt_dir" \
  --state-dir "$state_dir" \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/corrupt-receipt.json"
assert_receipt "$TMP_ROOT/corrupt-receipt.json" \
  '.status == "completed" and .invalidLines == 1 and .parsedEvents == 2' \
  "runner did not tolerate and report a malformed JSONL line"

large_dir="$state_dir/run-large"
mkdir "$large_dir"
FAKE_CODEX_MODE=large-output "$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$large_dir" \
  --state-dir "$state_dir" \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/large-receipt.json"
assert_receipt "$TMP_ROOT/large-receipt.json" \
  '.status == "completed" and .eventBytes > 250000 and .finalBytes > 64000 and .parsedEvents == 258' \
  "large JSONL/final output was not preserved in artifacts"
[[ "$(wc -c <"$TMP_ROOT/large-receipt.json")" -lt 4096 ]] \
  || fail "large Codex output leaked into the bounded stdout receipt"

padding=""
printf -v padding '%070d' 0
budget_state_dir="$TMP_ROOT/long-state"
for segment in 1 2 3 4 5 6 7 8; do
  budget_state_dir="$budget_state_dir/segment-${segment}-${padding}"
done
mkdir -p "$budget_state_dir"
budget_run_dir="$budget_state_dir/run-blocking-budget"
FAKE_CODEX_MODE=success "$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$budget_run_dir" \
  --state-dir "$budget_state_dir" \
  --poll-interval 0.1 \
  --output-budget 4096 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/blocking-budget-receipt.json"
assert_receipt "$TMP_ROOT/blocking-budget-receipt.json" \
  '.status == "completed"
    and .terminal
    and .compact
    and .artifacts.relativeToRunDir' \
  "blocking terminal output did not compact long artifact paths"
[[ "$(LC_ALL=C wc -c <"$TMP_ROOT/blocking-budget-receipt.json")" -le 4096 ]] \
  || fail "blocking terminal receipt exceeded 4096 bytes"
jq -e --arg runDir "$budget_run_dir" \
  '.status == "completed" and .runDir == $runDir and (.compact // false | not)' \
  "$budget_run_dir/status.json" >/dev/null \
  || fail "full blocking receipt was not preserved in status.json"

timeout_dir="$state_dir/run-timeout"
mkdir "$timeout_dir"
set +e
FAKE_CODEX_MODE=timeout "$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$timeout_dir" \
  --state-dir "$state_dir" \
  --idle-timeout 1 \
  --hard-timeout 5 \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/timeout-receipt.json"
timeout_exit=$?
set -e
[[ "$timeout_exit" -eq 124 ]] || fail "runner timeout must exit 124, got $timeout_exit"
assert_receipt "$TMP_ROOT/timeout-receipt.json" \
  '.status == "resumable_timeout" and .resumable and .processGroupStopped and .threadId == "thread-started" and .terminationReason == "idle_timeout"' \
  "timeout did not preserve an explicit resumable thread"

hard_timeout_dir="$state_dir/run-hard-timeout"
mkdir "$hard_timeout_dir"
set +e
FAKE_CODEX_MODE=timeout "$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$hard_timeout_dir" \
  --state-dir "$state_dir" \
  --idle-timeout 0 \
  --hard-timeout 1 \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/hard-timeout-receipt.json"
hard_timeout_exit=$?
set -e
[[ "$hard_timeout_exit" -eq 124 ]] || fail "hard timeout must exit 124, got $hard_timeout_exit"
assert_receipt "$TMP_ROOT/hard-timeout-receipt.json" \
  '.status == "resumable_timeout" and .processGroupStopped and .terminationReason == "hard_timeout"' \
  "hard timeout was not classified separately"

cancel_dir="$state_dir/run-cancel-after-thread"
mkdir "$cancel_dir"
FAKE_CODEX_MODE=timeout "$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$cancel_dir" \
  --state-dir "$state_dir" \
  --idle-timeout 0 \
  --hard-timeout 0 \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/cancel-after-thread-receipt.json" &
cancel_pid=$!
wait_for_pattern "$cancel_dir/events.jsonl" '"type":"thread.started"'
kill -TERM "$cancel_pid"
set +e
wait "$cancel_pid"
cancel_exit=$?
set -e
[[ "$cancel_exit" -eq 143 ]] || fail "TERM cancellation must exit 143, got $cancel_exit"
assert_receipt "$TMP_ROOT/cancel-after-thread-receipt.json" \
  '.status == "cancelled"
    and .signal == "TERM"
    and .terminationReason == "signal_TERM"
    and .threadId == "thread-started"
    and .processGroupStopped
    and .resumable' \
  "post-thread cancellation did not produce a safe resumable receipt"
cmp -s "$TMP_ROOT/cancel-after-thread-receipt.json" "$cancel_dir/status.json" \
  || fail "cancelled stdout receipt and persisted status differ"

pre_thread_dir="$state_dir/run-cancel-before-thread"
mkdir "$pre_thread_dir"
FAKE_CODEX_MODE=pre-thread-timeout \
FAKE_CODEX_READY_FILE="$TMP_ROOT/pre-thread-ready" \
"$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$pre_thread_dir" \
  --state-dir "$state_dir" \
  --idle-timeout 0 \
  --hard-timeout 0 \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/cancel-before-thread-receipt.json" &
pre_thread_pid=$!
wait_for_file "$TMP_ROOT/pre-thread-ready"
kill -HUP "$pre_thread_pid"
set +e
wait "$pre_thread_pid"
pre_thread_exit=$?
set -e
[[ "$pre_thread_exit" -eq 129 ]] || fail "pre-thread HUP cancellation must exit 129, got $pre_thread_exit"
assert_receipt "$TMP_ROOT/cancel-before-thread-receipt.json" \
  '.status == "cancelled"
    and .signal == "HUP"
    and .terminationReason == "signal_HUP"
    and .threadId == null
    and .processGroupStopped
    and (.resumable | not)' \
  "pre-thread cancellation was incorrectly marked resumable"

resume_dir="$state_dir/run-resume"
mkdir "$resume_dir"
FAKE_CODEX_MODE=success \
FAKE_CODEX_ARGS_FILE="$TMP_ROOT/resume-args.txt" \
FAKE_CODEX_ENV_FILE="$TMP_ROOT/resume-env.txt" \
"$RUNNER" resume \
  --thread-id "thread-started" \
  --prompt-file "$prompt_file" \
  --run-dir "$resume_dir" \
  --state-dir "$state_dir" \
  --sandbox read-only \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/resume-receipt.json"
assert_receipt "$TMP_ROOT/resume-receipt.json" \
  '.status == "completed" and .action == "resume" and .threadId == "thread-resumed"' \
  "explicit resume did not complete"
grep -Fxq 'thread-started' "$TMP_ROOT/resume-args.txt" || fail "resume command omitted the explicit thread ID"
grep -Fxq 'sandbox_mode="read-only"' "$TMP_ROOT/resume-args.txt" || fail "resume command did not enforce sandbox mode"
grep -Fxq -- '--ignore-user-config' "$TMP_ROOT/resume-args.txt" \
  || fail "default resume did not ignore user-level Codex configuration"
grep -Fxq 'HTTPS_PROXY=__unset__' "$TMP_ROOT/resume-env.txt" \
  || fail "direct resume inherited a caller proxy"
if grep -Fxq -- '--last' "$TMP_ROOT/resume-args.txt"; then
  fail "resume command used unsafe --last selection"
fi

inherited_dir="$state_dir/run-inherited-config"
mkdir "$inherited_dir"
FAKE_CODEX_MODE=success \
FAKE_CODEX_ARGS_FILE="$TMP_ROOT/inherited-args.txt" \
"$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$inherited_dir" \
  --state-dir "$state_dir" \
  --inherit-user-config \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/inherited-receipt.json"
assert_receipt "$TMP_ROOT/inherited-receipt.json" \
  '.status == "completed" and .configMode == "inherited"' \
  "explicit user-config inheritance was not recorded"
if grep -Fxq -- '--ignore-user-config' "$TMP_ROOT/inherited-args.txt"; then
  fail "explicit user-config inheritance still passed --ignore-user-config"
fi

outside_run="$TMP_ROOT/run-outside"
set +e
"$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$outside_run" \
  --state-dir "$state_dir" \
  --codex-bin "$FAKE_CODEX" >/dev/null 2>&1
outside_exit=$?
set -e
[[ "$outside_exit" -eq 64 && ! -e "$outside_run" ]] \
  || fail "foreground --run-dir outside --state-dir was not rejected without side effects"

workspace_repo="$TMP_ROOT/workspace-repo"
fake_worktree="$TMP_ROOT/fake-linked-worktree"
git init -q "$workspace_repo"
git -C "$workspace_repo" -c user.name="Codex Delegate Test" -c user.email="test@example.invalid" \
  commit -q --allow-empty -m "test base"
git -C "$workspace_repo" worktree add -q -b codex-delegate-test "$fake_worktree"
mkdir "$fake_worktree/project"
set +e
FAKE_CODEX_MODE=success "$RUNNER" start \
  --cwd "$fake_worktree/project" \
  --prompt-file "$prompt_file" \
  --state-dir "$state_dir" \
  --sandbox workspace-write \
  --codex-bin "$FAKE_CODEX" >/dev/null 2>&1
workspace_missing_exit=$?
set -e
[[ "$workspace_missing_exit" -eq 64 ]] \
  || fail "workspace-write without explicit authorization was accepted"

workspace_dir="$state_dir/run-workspace-write"
mkdir "$workspace_dir"
FAKE_CODEX_MODE=success "$RUNNER" start \
  --cwd "$fake_worktree/project" \
  --prompt-file "$prompt_file" \
  --run-dir "$workspace_dir" \
  --state-dir "$state_dir" \
  --sandbox workspace-write \
  --allow-workspace-write \
  --worktree-root "$fake_worktree" \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/workspace-receipt.json"
assert_receipt "$TMP_ROOT/workspace-receipt.json" \
  '.status == "completed" and (.worktreeRoot | endswith("fake-linked-worktree"))' \
  "authorized linked-worktree workspace-write did not complete"

init_cancel_dir="$state_dir/run-init-cancel"
mkdir "$init_cancel_dir"
CODEX_DELEGATE_TEST_INIT_DELAY=5 \
FAKE_CODEX_MODE=success \
"$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --run-dir "$init_cancel_dir" \
  --state-dir "$state_dir" \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/init-cancel-receipt.json" &
init_cancel_pid=$!
wait_for_file "$init_cancel_dir/.codex-delegate-run.json"
kill -TERM "$init_cancel_pid"
set +e
wait "$init_cancel_pid"
init_cancel_exit=$?
set -e
[[ "$init_cancel_exit" -eq 143 ]] || fail "initialization cancellation exited with $init_cancel_exit"
assert_receipt "$TMP_ROOT/init-cancel-receipt.json" \
  '.status == "cancelled"
    and .signal == "TERM"
    and .threadId == null
    and .processGroupStopped
    and (.resumable | not)' \
  "initialization cancellation did not persist a non-resumable terminal receipt"
[[ ! -s "$init_cancel_dir/events.jsonl" ]] \
  || fail "initialization cancellation launched Codex"

prune_state="$TMP_ROOT/prune-state"
FAKE_CODEX_MODE=success "$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --state-dir "$prune_state" \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/prune-old-receipt.json"
old_run="$(jq -r '.runDir' "$TMP_ROOT/prune-old-receipt.json")"
touch -d "20 days ago" "$old_run/status.json"

FAKE_CODEX_MODE=success "$RUNNER" start \
  --cwd "$ROOT_DIR" \
  --prompt-file "$prompt_file" \
  --state-dir "$prune_state" \
  --poll-interval 0.1 \
  --codex-bin "$FAKE_CODEX" >"$TMP_ROOT/prune-recent-receipt.json"
recent_run="$(jq -r '.runDir' "$TMP_ROOT/prune-recent-receipt.json")"

unmarked_run="$prune_state/run-unmarked"
mkdir "$unmarked_run"
jq -cn --arg runDir "$unmarked_run" \
  '{status: "completed", runDir: $runDir}' >"$unmarked_run/status.json"
touch -d "20 days ago" "$unmarked_run/status.json"

linked_target="$TMP_ROOT/linked-target"
mkdir "$linked_target"
jq -cn --arg runDir "$prune_state/run-linked" \
  '{status: "completed", runDir: $runDir}' >"$linked_target/status.json"
jq -cn --arg runDir "$prune_state/run-linked" \
  '{format: "codex-delegate-run-v1", runDir: $runDir}' >"$linked_target/.codex-delegate-run.json"
touch -d "20 days ago" "$linked_target/status.json"
ln -s "$linked_target" "$prune_state/run-linked"

"$RUNNER" prune \
  --state-dir "$prune_state" \
  --older-than-days 14 >"$TMP_ROOT/prune-preview.json"
assert_receipt "$TMP_ROOT/prune-preview.json" \
  '.status == "prune_preview"
    and (.applied | not)
    and .eligible == 1
    and .removed == 0
    and .skipped == 1' \
  "prune preview did not report exactly the eligible owned run"
[[ -d "$old_run" ]] || fail "prune preview deleted an eligible run"

"$RUNNER" prune \
  --state-dir "$prune_state" \
  --older-than-days 14 \
  --apply >"$TMP_ROOT/prune-apply.json"
assert_receipt "$TMP_ROOT/prune-apply.json" \
  '.status == "pruned"
    and .applied
    and .eligible == 1
    and .removed == 1
    and .skipped == 1' \
  "prune apply did not delete exactly the eligible owned run"
[[ ! -e "$old_run" ]] || fail "prune apply retained the eligible old run"
[[ -d "$recent_run" ]] || fail "prune apply deleted a recent run"
[[ -d "$unmarked_run" ]] || fail "prune apply deleted an unowned run"
[[ -L "$prune_state/run-linked" && -f "$linked_target/status.json" ]] \
  || fail "prune followed a symlink outside the state directory"

prune_budget_state="$TMP_ROOT/prune-budget"
segment_index=0
while ((${#prune_budget_state} < 3960)); do
  segment_index="$((segment_index + 1))"
  prune_budget_state="$prune_budget_state/segment-${segment_index}-000000000000000000000000000000000000000000000000"
done
mkdir -p "$prune_budget_state"
"$RUNNER" prune \
  --state-dir "$prune_budget_state" \
  --older-than-days 14 >"$TMP_ROOT/prune-budget.json"
assert_receipt "$TMP_ROOT/prune-budget.json" \
  '.status == "prune_preview"
    and .compact
    and .stateDirOmitted
    and .examined == 0' \
  "prune response did not compact an over-budget state directory"
[[ "$(LC_ALL=C wc -c <"$TMP_ROOT/prune-budget.json")" -le 4096 ]] \
  || fail "compact prune response exceeded 4096 bytes"

echo "OK: Runner validates completion, cancellation, resume, proxy scope, and safe artifact pruning"
