#!/usr/bin/env bash

set -euo pipefail

mode="${FAKE_CODEX_MODE:-success}"
args_file="${FAKE_CODEX_ARGS_FILE:-}"
env_file="${FAKE_CODEX_ENV_FILE:-}"
ready_file="${FAKE_CODEX_READY_FILE:-}"
step_delay="${FAKE_CODEX_STEP_DELAY:-0.2}"
quiet_delay="${FAKE_CODEX_QUIET_DELAY:-2}"
output_file=""
is_resume=false

if [[ -n "$args_file" ]]; then
  printf '%s\n' "$@" >"$args_file"
fi

if [[ -n "$env_file" ]]; then
  {
    printf 'HTTPS_PROXY=%s\n' "${HTTPS_PROXY-__unset__}"
    printf 'HTTP_PROXY=%s\n' "${HTTP_PROXY-__unset__}"
    printf 'ALL_PROXY=%s\n' "${ALL_PROXY-__unset__}"
    printf 'https_proxy=%s\n' "${https_proxy-__unset__}"
    printf 'http_proxy=%s\n' "${http_proxy-__unset__}"
    printf 'all_proxy=%s\n' "${all_proxy-__unset__}"
    printf 'NO_PROXY=%s\n' "${NO_PROXY-__unset__}"
    printf 'no_proxy=%s\n' "${no_proxy-__unset__}"
  } >"$env_file"
fi

args=("$@")
for ((index = 0; index < ${#args[@]}; index++)); do
  case "${args[$index]}" in
    resume)
      is_resume=true
      ;;
    -o|--output-last-message)
      ((index++))
      output_file="${args[$index]:-}"
      ;;
  esac
done

[[ -n "$output_file" ]] || {
  echo "fake-codex: missing output file" >&2
  exit 2
}

while IFS= read -r _; do
  :
done

if [[ -n "$ready_file" ]]; then
  printf '%s\n' "ready" >"$ready_file"
fi

if [[ "$mode" == "pre-thread-timeout" ]]; then
  trap 'exit 130' INT TERM HUP
  sleep 30
  exit 0
fi

thread_id="thread-started"
if [[ "$is_resume" == "true" ]]; then
  thread_id="thread-resumed"
fi

printf '{"type":"thread.started","thread_id":"%s"}\n' "$thread_id"

case "$mode" in
  success)
    printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"CODEX_PROGRESS: Bounded work completed. Next: final response."}}'
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}'
    printf '%s\n' 'bounded final answer' >"$output_file"
    ;;
  incomplete)
    printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"partial only"}}'
    ;;
  whitespace-final)
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}'
    printf '  \n' >"$output_file"
    ;;
  corrupt-success)
    printf '%s\n' 'not-json'
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":2,"output_tokens":1}}'
    printf '%s\n' 'final survives one malformed event' >"$output_file"
    ;;
  large-output)
    printf -v payload '%*s' 1024 ''
    payload="${payload// /x}"
    for ((index = 0; index < 256; index++)); do
      printf '{"type":"item.completed","item":{"type":"agent_message","text":"%s"}}\n' "$payload"
    done
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":1000,"output_tokens":500}}'
    {
      for ((index = 0; index < 64; index++)); do
        printf '%s' "$payload"
      done
      printf '\n'
    } >"$output_file"
    ;;
  phased)
    trap 'exit 130' INT TERM HUP
    printf '%s\n' '{"type":"turn.started"}'
    printf '%s\n' '{"type":"item.completed","item":{"type":"reasoning","text":"PRIVATE_REASONING_MUST_NOT_LEAK"}}'
    printf '%s\n' '{"type":"item.completed","item":{"type":"plan_update","plan":[{"step":"inspect","status":"completed"},{"step":"implement","status":"in_progress"},{"step":"verify","status":"pending"}]}}'
    sleep "$step_delay"
    printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"CODEX_PROGRESS: Investigation completed: the bounded fixture identified the implementation target. Next: implementation."}}'
    printf '%s\n' '{"type":"item.started","item":{"type":"file_change","changes":[{"path":"private-file.txt","kind":"update","diff":"PRIVATE_DIFF_MUST_NOT_LEAK"}]}}'
    printf '%s\n' '{"type":"item.completed","item":{"type":"file_change","changes":[{"path":"private-file.txt","kind":"update","diff":"PRIVATE_DIFF_MUST_NOT_LEAK"}]}}'
    sleep "$quiet_delay"
    printf '%s\n' '{"type":"item.started","item":{"type":"command_execution","command":"pytest -q","aggregated_output":"PRIVATE_COMMAND_OUTPUT_MUST_NOT_LEAK"}}'
    printf '%s\n' '{"type":"item.completed","item":{"type":"command_execution","command":"pytest -q","aggregated_output":"PRIVATE_COMMAND_OUTPUT_MUST_NOT_LEAK","exit_code":0}}'
    printf '%s\n' '{"type":"item.completed","item":{"type":"plan_update","plan":[{"step":"inspect","status":"completed"},{"step":"implement","status":"completed"},{"step":"verify","status":"completed"}]}}'
    printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"CODEX_PROGRESS: Verification completed: focused checks passed. Next: final response."}}'
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":30,"output_tokens":12}}'
    printf '%s\n' 'phased final answer' >"$output_file"
    ;;
  activity-burst)
    printf '%s\n' '{"type":"turn.started"}'
    printf '%s\n' '{"type":"item.completed","item":{"type":"reasoning","text":"BURST_REASONING_MUST_NOT_LEAK"}}'
    for ((index = 0; index < 32; index++)); do
      printf '{"type":"item.completed","item":{"type":"command_execution","command":"command-%s","aggregated_output":"BURST_OUTPUT_MUST_NOT_LEAK"}}\n' "$index"
    done
    printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"CODEX_PROGRESS: Burst processing completed. Next: final response."}}'
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":40,"output_tokens":10}}'
    printf '%s\n' 'burst final answer' >"$output_file"
    ;;
  unicode-checkpoint)
    printf -v payload '%*s' 512 ''
    payload="${payload// /界}"
    printf '%s\n' '{"type":"turn.started"}'
    printf '{"type":"item.completed","item":{"type":"agent_message","text":"CODEX_PROGRESS: %s"}}\n' "$payload"
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":20,"output_tokens":8}}'
    printf '%s\n' 'unicode checkpoint final answer' >"$output_file"
    ;;
  partial-line)
    trap 'exit 130' INT TERM HUP
    printf '%s' '{"type":"item.completed","item":{"type":"agent_message","text":"CODEX_PROGRESS: partial'
    sleep "$quiet_delay"
    printf '%s\n' ' checkpoint"}}'
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":4,"output_tokens":2}}'
    printf '%s\n' 'partial-line final answer' >"$output_file"
    ;;
  failed)
    printf '%s\n' '{"type":"turn.failed","error":{"message":"simulated failure"}}'
    exit 1
    ;;
  sensitive-progress)
    printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"token=SYNTHETIC_OMP_61e8530c90d0 PRIVATE_UNTAGGED_MESSAGE"}}'
    printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"CODEX_PROGRESS: Authorization: Bearer synthetic-secret PRIVATE_TAGGED_MESSAGE"}}'
    printf '%s\n' '{"type":"error","message":"password=hunter2 PRIVATE_ERROR_MESSAGE"}'
    printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":8,"output_tokens":4}}'
    printf '%s\n' 'sensitive fixture final answer' >"$output_file"
    ;;
  sensitive-failure)
    printf '%s\n' '{"type":"turn.failed","error":{"message":"api_key=SYNTHETIC_OMP_66cc6c602b1d PRIVATE_TURN_FAILURE"}}'
    exit 1
    ;;
  timeout)
    trap 'exit 130' INT TERM HUP
    sleep 30
    ;;
  *)
    echo "fake-codex: unknown mode: $mode" >&2
    exit 2
    ;;
esac
