#!/usr/bin/env bash
# model-delegate: test backend adapter（使用 fake-backend.sh 进行测试）
# 仅用于测试，不用于生产

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES_DIR="$(cd "$SCRIPT_DIR/../../tests/fixtures" && pwd)"

backend_probe() {
  printf '%s\n' "$(jq -nc '{contract_version: "1", cli_version: "fake-1.0", provider: "test", provider_ready: "yes", framing: "jsonl"}')"
}

backend_init() {
  BACKEND_ID="test-fake"
  declare -gA BACKEND_CAPABILITIES
  BACKEND_CAPABILITIES[context_limit]="8000"
  BACKEND_CAPABILITIES[supports_write]="false"
  BACKEND_CAPABILITIES[supports_resume]="false"
  BACKEND_CAPABILITIES[supports_cancel]="true"
  BACKEND_CAPABILITIES[framing]="jsonl"
}

backend_start() {
  local action="$1"
  local run_dir="$2"
  local prompt_file="$3"

  BACKEND_CMD=("$FIXTURES_DIR/fake-backend.sh")
  # 注入最小环境基线（PATH 等），env -i 清空后子进程需要 PATH
  build_child_env_baseline
  BACKEND_ENV=("${CHILD_ENV_BASELINE[@]}")
  if [[ -n "${FAKE_BACKEND_MODE:-}" ]]; then
    BACKEND_ENV+=("FAKE_BACKEND_MODE=$FAKE_BACKEND_MODE")
  fi
  if [[ -n "${FAKE_BACKEND_ENV_LOG:-}" ]]; then
    BACKEND_ENV+=("FAKE_BACKEND_ENV_LOG=$FAKE_BACKEND_ENV_LOG")
  fi
}

backend_normalizer() {
  # 复用 pi-normalize.jq（fake backend 输出格式与 pi 一致）
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  printf '%s' "$script_dir/pi-normalize.jq"
}

backend_complete() {
  local run_dir="$1"
  local exit_code="$2"

  local raw_log="$run_dir/raw-events.jsonl"
  local status="completed"
  local failure_mode=""
  local resume_token=""
  local final_text=""
  local usage_json="{}"
  local has_agent_end=false

  if ((exit_code == 143 || exit_code == 137)); then
    status="cancelled"
    failure_mode="cancelled"
  elif ((exit_code != 0)); then
    status="failed"
    local err_log="$run_dir/stderr.log"
    if [[ -f "$err_log" ]]; then
      local err_content
      err_content="$(cat "$err_log")"
      if echo "$err_content" | grep -qiE '(401|403|auth|credential)'; then
        failure_mode="auth"
      elif echo "$err_content" | grep -qiE '(timeout|connection|network)'; then
        failure_mode="network"
      elif echo "$err_content" | grep -qiE '(unknown provider|unknown model)'; then
        failure_mode="invalid_input"
      else
        failure_mode="protocol"
      fi
    else
      failure_mode="protocol"
    fi
  elif [[ ! -f "$raw_log" ]]; then
    status="failed"
    failure_mode="invalid_output"
  else
    local scan_result
    scan_result="$(jq -sc '
      (map(select(.type == "session")) | first | .id // null) as $session_id |
      (map(select(.type == "agent_end")) | length > 0) as $has_agent_end |
      (map(select(.type == "message_end" and .message.role == "assistant")) | last | .message.content? // [] | map(select(.type == "text")) | first | .text? // "") as $final_text |
      (map(select(.type == "message_end" and .message.usage)) | last | .message.usage? // {}) as $usage |
      {session_id: $session_id, has_agent_end: $has_agent_end, final_text: $final_text, usage: $usage}
    ' "$raw_log" 2>/dev/null)" || scan_result=""

    if [[ -z "$scan_result" ]]; then
      status="failed"
      failure_mode="invalid_output"
    else
      resume_token="$(echo "$scan_result" | jq -r '.session_id // ""')"
      has_agent_end="$(echo "$scan_result" | jq -r '.has_agent_end')"
      final_text="$(echo "$scan_result" | jq -r '.final_text // ""')"
      usage_json="$(echo "$scan_result" | jq -c '.usage // {}')"

      if [[ "$has_agent_end" != "true" ]]; then
        status="failed"
        failure_mode="protocol"
      elif [[ -z "$final_text" ]]; then
        status="incomplete"
        failure_mode=""
      fi
    fi
  fi

  jq -nc \
    --arg status "$status" \
    --arg failure_mode "$failure_mode" \
    --arg resume_token "$resume_token" \
    --arg final_text "$final_text" \
    --argjson usage "$usage_json" \
    --argjson has_agent_end "$has_agent_end" \
    --argjson resumable "$(if [[ -n "$resume_token" ]]; then printf 'true'; else printf 'false'; fi)" \
    --arg feedback_quality "$(if [[ -n "$final_text" ]]; then printf 'structured'; else printf 'none'; fi)" \
    '{status: $status, failure_mode: $failure_mode, resume_token: $resume_token, resumable: $resumable, final_text: $final_text, feedback_quality: $feedback_quality, usage: $usage, has_agent_end: $has_agent_end}'
}

backend_cancel() {
  return 0
}

backend_validate_provider_model() {
  # test-fake backend 不做验证
  return 0
}
