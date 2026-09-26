#!/usr/bin/env bash

set -euo pipefail

umask 077

DEFAULT_IDLE_TIMEOUT=600
DEFAULT_HARD_TIMEOUT=1800
DEFAULT_POLL_INTERVAL=1
DEFAULT_CONTROL_WAIT=20
DEFAULT_STALE_AFTER=120
DEFAULT_MAX_EVENTS=3
DEFAULT_OUTPUT_BUDGET=4096
DEFAULT_HEARTBEAT_SECONDS=60
DEFAULT_READY_TIMEOUT=5
MAX_CONTROL_WAIT=30
CODEX_PROXY_URL="${CODEX_DELEGATE_PROXY_URL:-}"
CODEX_NO_PROXY="localhost,127.0.0.1,::1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
NORMALIZE_EVENT_FILTER="$SCRIPT_DIR/normalize-event.jq"

usage() {
  cat <<'EOF'
Usage:
  run-codex.sh start --cwd DIR --prompt-file FILE [--detach | --observe] [options]
  run-codex.sh resume (--thread-id ID | --run-id RUN_ID) --prompt-file FILE [--detach | --observe] [options]
  run-codex.sh status --run-id RUN_ID [options]
  run-codex.sh events --run-id RUN_ID [--after CURSOR] [options]
  run-codex.sh poll --run-id RUN_ID [--after CURSOR] [--wait-seconds SEC] [options]
  run-codex.sh wait --run-id RUN_ID [--wait-seconds SEC] [options]
  run-codex.sh cancel --run-id RUN_ID [options]
  run-codex.sh prune [--state-dir DIR] [--older-than-days N] [--apply]

Options:
  --detach                Start a durable supervisor and return a run receipt
  --observe               Stay foreground and emit bounded progress JSONL
  --heartbeat-seconds N   Observe heartbeat interval (default: 60)
  --sandbox MODE          read-only (default) or workspace-write
  --allow-workspace-write Required acknowledgement for workspace-write
  --worktree-root DIR     Existing linked Git worktree for workspace-write
  --approval-policy MODE never (default), on-request, or untrusted
  --inherit-user-config   Load CODEX_HOME/config.toml (isolated by default)
  --idle-timeout SEC      Stop after no JSONL growth (default: 600, 0 disables)
  --hard-timeout SEC      Absolute runtime limit (default: 1800, 0 disables)
  --poll-interval SEC     Monitor interval (default: 1)
  --ready-timeout SEC     Detached readiness bound (default: 5)
  --state-dir DIR         Parent directory for private run artifacts
  --run-dir DIR           Exact artifact directory; mainly for deterministic tests
  --run-id RUN_ID         Runner-owned direct child to inspect or control
  --after CURSOR          Return normalized events after this sequence (default: 0)
  --wait-seconds SEC      Long-poll bound, maximum 30 seconds (default: 20)
  --stale-after SEC       Mark a live quiet run stale after this duration (default: 120)
  --max-events N          Maximum whole events per response (default: 3)
  --output-budget BYTES   Serialized response budget (default/minimum: 4096)
  --codex-bin PATH        Codex executable (default: codex or CODEX_BIN)
  --model ID              Explicit Codex model (otherwise Codex default)
  --older-than-days N     Prune terminal runs older than N days (default: 14)
  --apply                 Delete eligible runs; prune defaults to preview only

Network:
  Direct connection is the default. Set CODEX_DELEGATE_PROXY_URL to an
  explicit proxy origin for the Codex child only. Credentials are rejected.
  The runner does not export or persist proxy settings.
EOF
}

fail_usage() {
  echo "run-codex: $*" >&2
  usage >&2
  exit 64
}

validate_proxy_url() {
  [[ -z "$CODEX_PROXY_URL" ]] && return 0
  if [[ "$CODEX_PROXY_URL" == *"@"* || "$CODEX_PROXY_URL" == *"?"* || "$CODEX_PROXY_URL" == *"#"* \
      || "$CODEX_PROXY_URL" =~ [[:space:][:cntrl:]] \
      || ! "$CODEX_PROXY_URL" =~ ^(http|https|socks5|socks5h)://[^/@\?\#[:space:]]+/?$ ]]; then
    fail_usage "CODEX_DELEGATE_PROXY_URL must be a credential-free proxy origin"
  fi
}

require_value() {
  local option="$1"
  local value="${2:-}"
  [[ -n "$value" ]] || fail_usage "$option requires a value"
}

require_uint() {
  local option="$1"
  local value="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || fail_usage "$option must be a non-negative integer"
}

require_number() {
  local option="$1"
  local value="$2"
  [[ "$value" =~ ^[0-9]+([.][0-9]+)?$ ]] || fail_usage "$option must be a non-negative number"
}

epoch_iso() {
  jq -nr --argjson epoch "$1" '$epoch | todateiso8601'
}

atomic_write_json() {
  local path="$1"
  local value="$2"
  local temporary="${path}.tmp.$$"
  printf '%s\n' "$value" >"$temporary"
  chmod 600 "$temporary"
  mv -f "$temporary" "$path"
}

choose_default_state_dir() {
  local state_home="${XDG_STATE_HOME:-$HOME/.local/state}"
  local generic="$state_home/codex-delegate"
  local legacy="$state_home/pi/codex-delegate"

  if [[ -n "${CODEX_DELEGATE_STATE_DIR:-}" ]]; then
    printf '%s\n' "$CODEX_DELEGATE_STATE_DIR"
  elif [[ -d "$legacy" && ! -e "$generic" ]]; then
    printf '%s\n' "$legacy"
  else
    printf '%s\n' "$generic"
  fi
}

prepare_state_dir() {
  mkdir -p "$state_dir"
  chmod 700 "$state_dir"
  state_dir="$(cd "$state_dir" && pwd -P)"
}

prepare_new_run_dir() {
  local requested_parent requested_name canonical_parent

  if [[ -n "$run_dir" ]]; then
    requested_parent="$(dirname "$run_dir")"
    requested_name="$(basename "$run_dir")"
    validate_run_id "$requested_name" || fail_usage "--run-dir basename must be a valid run ID"
    [[ -d "$requested_parent" && ! -L "$requested_parent" ]] \
      || fail_usage "--run-dir parent must be an existing non-symlink directory"
    canonical_parent="$(cd "$requested_parent" && pwd -P)"
    [[ "$canonical_parent" == "$state_dir" ]] \
      || fail_usage "--run-dir must be a direct child of --state-dir"
    run_dir="$canonical_parent/$requested_name"
    if [[ -e "$run_dir" ]]; then
      [[ -d "$run_dir" && ! -L "$run_dir" ]] || fail_usage "--run-dir must be a directory, not a symlink"
      [[ -z "$(find "$run_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
        || fail_usage "--run-dir must be empty"
    else
      mkdir "$run_dir"
    fi
  else
    run_dir="$(mktemp -d "$state_dir/run-XXXXXXXX")"
  fi
  chmod 700 "$run_dir"
  run_dir="$(cd "$run_dir" && pwd -P)"
}

validate_workspace_write_boundary() {
  local canonical_root canonical_cwd git_root

  if [[ "$sandbox" != "workspace-write" ]]; then
    [[ "$allow_workspace_write" == "false" && -z "$worktree_root" ]] \
      || fail_usage "--allow-workspace-write and --worktree-root require --sandbox workspace-write"
    return 0
  fi

  [[ "$allow_workspace_write" == "true" ]] \
    || fail_usage "--sandbox workspace-write requires --allow-workspace-write"
  [[ -n "$worktree_root" ]] \
    || fail_usage "--sandbox workspace-write requires --worktree-root"
  [[ -d "$worktree_root" && ! -L "$worktree_root" ]] \
    || fail_usage "--worktree-root must be an existing non-symlink directory"
  canonical_root="$(cd "$worktree_root" && pwd -P)"
  [[ -f "$canonical_root/.git" && ! -L "$canonical_root/.git" ]] \
    || fail_usage "--worktree-root must be a linked Git worktree (its .git entry must be a file)"
  command -v git >/dev/null 2>&1 || fail_usage "git is required for workspace-write validation"
  git_root="$(git -C "$canonical_root" rev-parse --show-toplevel 2>/dev/null || true)"
  [[ -n "$git_root" ]] || fail_usage "--worktree-root is not a valid Git worktree"
  git_root="$(cd "$git_root" && pwd -P)"
  [[ "$git_root" == "$canonical_root" ]] \
    || fail_usage "--worktree-root must match the linked Git worktree top level"

  if [[ "$action" == "start" ]]; then
    canonical_cwd="$(cd "$cwd" && pwd -P)"
    case "$canonical_cwd" in
      "$canonical_root"|"$canonical_root"/*) ;;
      *) fail_usage "--cwd must be inside --worktree-root for workspace-write" ;;
    esac
    cwd="$canonical_cwd"
  fi
  worktree_root="$canonical_root"
}

validate_run_id() {
  [[ "$1" =~ ^run-[A-Za-z0-9][A-Za-z0-9_-]*$ ]]
}

validate_owned_run_dir() {
  local candidate="$1"
  local requested_id canonical parent marker

  requested_id="$(basename "$candidate")"
  validate_run_id "$requested_id" || return 1
  [[ -d "$candidate" && ! -L "$candidate" ]] || return 1
  canonical="$(cd "$candidate" && pwd -P)" || return 1
  parent="$(dirname "$canonical")"
  [[ "$parent" == "$state_dir" && "$(basename "$canonical")" == "$requested_id" ]] || return 1
  marker="$canonical/.codex-delegate-run.json"
  [[ -f "$marker" && ! -L "$marker" ]] || return 1
  jq -e --arg runDir "$canonical" --arg runId "$requested_id" '
    .format == "codex-delegate-run-v1"
    and .runDir == $runDir
    and ((.runId // $runId) == $runId)
  ' "$marker" >/dev/null 2>&1 || return 1
  validated_run_dir="$canonical"
}

load_run_paths() {
  run_dir="$1"
  request_path="$run_dir/request.txt"
  events_path="$run_dir/events.jsonl"
  final_path="$run_dir/final.md"
  stderr_path="$run_dir/stderr.log"
  status_path="$run_dir/status.json"
  marker_path="$run_dir/.codex-delegate-run.json"
  progress_path="$run_dir/progress.json"
  progress_events_path="$run_dir/progress.jsonl"
  progress_state_path="$run_dir/.progress-state.json"
  supervisor_path="$run_dir/supervisor.json"
  supervisor_log_path="$run_dir/supervisor.log"
}

resolve_control_run() {
  local requested_id="$1"
  local candidate

  validate_run_id "$requested_id" || fail_usage "invalid --run-id: $requested_id"
  prepare_state_dir
  candidate="$state_dir/$requested_id"
  validate_owned_run_dir "$candidate" || fail_usage "run not found, unowned, or unsafe: $requested_id"
  load_run_paths "$validated_run_dir"
}

process_start_ticks() {
  local pid="$1"
  if [[ -r "/proc/$pid/stat" ]]; then
    awk '{print $22}' "/proc/$pid/stat" 2>/dev/null
  fi
}

load_supervisor_identity() {
  [[ -f "$supervisor_path" && ! -L "$supervisor_path" ]] || return 1
  supervisor_pid="$(jq -r '.pid // empty' "$supervisor_path" 2>/dev/null)"
  supervisor_start_ticks="$(jq -r '.processStartTicks // empty' "$supervisor_path" 2>/dev/null)"
  [[ "$supervisor_pid" =~ ^[1-9][0-9]*$ ]] || return 1
}

supervisor_identity_alive() {
  local current_ticks="" process_state=""
  load_supervisor_identity || return 1
  kill -0 "$supervisor_pid" 2>/dev/null || return 1
  if [[ -r "/proc/$supervisor_pid/stat" ]]; then
    process_state="$(awk '{print $3}' "/proc/$supervisor_pid/stat" 2>/dev/null)"
    [[ "$process_state" != "Z" ]] || return 1
  fi
  if [[ -n "$supervisor_start_ticks" ]]; then
    current_ticks="$(process_start_ticks "$supervisor_pid")"
    [[ -n "$current_ticks" && "$current_ticks" == "$supervisor_start_ticks" ]] || return 1
  fi
}

stored_process_group_alive() {
  local stored_group=""
  [[ -f "$supervisor_path" ]] || return 1
  stored_group="$(jq -r '.processGroupId // empty' "$supervisor_path" 2>/dev/null)"
  [[ "$stored_group" =~ ^[1-9][0-9]*$ ]] || return 1
  kill -0 -- "-$stored_group" 2>/dev/null
}

control_snapshot_json() {
  local now progress_json terminal_json marker_json alive=false group_alive=false

  now="$(date +%s)"
  progress_json="$(jq -c '.' "$progress_path" 2>/dev/null || printf '{}')"
  terminal_json="$(jq -c '.' "$status_path" 2>/dev/null || printf 'null')"
  marker_json="$(jq -c '.' "$marker_path" 2>/dev/null || printf '{}')"
  if [[ "$terminal_json" == "null" ]] && supervisor_identity_alive; then
    alive=true
  fi
  if [[ "$terminal_json" == "null" ]] && stored_process_group_alive; then
    group_alive=true
  fi

  jq -cn \
    --arg operation "status" \
    --arg runId "$(basename "$run_dir")" \
    --arg runDir "$run_dir" \
    --arg progressPath "$progress_path" \
    --arg progressEventsPath "$progress_events_path" \
    --arg statusPath "$status_path" \
    --arg eventsPath "$events_path" \
    --arg finalMessagePath "$final_path" \
    --arg stderrPath "$stderr_path" \
    --argjson now "$now" \
    --argjson staleAfter "$stale_after" \
    --argjson alive "$alive" \
    --argjson groupAlive "$group_alive" \
    --argjson progress "$progress_json" \
    --argjson terminal "$terminal_json" \
    --argjson marker "$marker_json" \
    '
      ($progress.startedAt // $marker.createdAt // $now) as $startedAt
      | ($progress.lastActivityAt // $startedAt) as $lastActivityAt
      | ([0, ($now - $startedAt)] | max) as $elapsed
      | ([0, ($now - $lastActivityAt)] | max) as $lastAge
      | ($terminal != null) as $isTerminal
      | (
          if $isTerminal then $terminal.status
          elif $alive then ($progress.state // "running")
          else "orphaned"
          end
        ) as $state
      | (($isTerminal | not) and $alive and $lastAge >= $staleAfter) as $stale
      | {
          schemaVersion: 1,
          operation: $operation,
          runId: $runId,
          runDir: $runDir,
          state: $state,
          status: $state,
          phase: ($progress.phase // "working"),
          terminal: $isTerminal,
          stale: $stale,
          startedAt: $startedAt,
          updatedAt: ($progress.updatedAt // $startedAt),
          lastActivityAt: $lastActivityAt,
          elapsedSeconds: $elapsed,
          lastActivityAgeSeconds: $lastAge,
          threadId: ($terminal.threadId // $progress.threadId // null),
          resumable: ($terminal.resumable // $progress.resumable // false),
          configMode: ($terminal.configMode // $marker.configMode // "isolated"),
          worktreeRoot: ($terminal.worktreeRoot // $marker.worktreeRoot // null),
          cursor: ($progress.latestSeq // 0),
          supervisorAlive: $alive,
          processGroupStopped: ($terminal.processGroupStopped // ($groupAlive | not)),
          milestones: ($progress.milestones // null),
          lastSummary: ($progress.lastSummary // "No normalized activity is available yet."),
          artifacts: ($progress.artifacts // {
            progressPath: $progressPath,
            progressEventsPath: $progressEventsPath,
            statusPath: $statusPath,
            eventsPath: $eventsPath,
            finalMessagePath: $finalMessagePath,
            stderrPath: $stderrPath
          }),
          report: (
            if $isTerminal then {
              recommended: true,
              reason: "terminal",
              text: "Codex \($state) after \($elapsed)s."
            }
            elif ($alive | not) then {
              recommended: true,
              reason: "warning",
              text: "Codex supervisor is no longer running and no terminal receipt exists."
            }
            elif $stale then {
              recommended: true,
              reason: "heartbeat",
              text: "Codex is still running but has been quiet for \($lastAge)s."
            }
            else {
              recommended: false,
              reason: "heartbeat",
              text: "Codex is \($progress.phase // "working"); elapsed \($elapsed)s; last activity \($lastAge)s ago."
            }
            end
          ),
          nextPollAfterSeconds: (if $isTerminal then 0 else 20 end)
        }
    '
}

compact_control_response() {
  local response="$1"

  jq -c '
    {
      schemaVersion,
      operation,
      runId,
      state,
      status,
      phase,
      terminal,
      stale,
      elapsedSeconds,
      lastActivityAgeSeconds,
      threadId,
      resumable,
      configMode,
      worktreeRoot: (if .worktreeRoot == null then null else "." end),
      cursor,
      supervisorAlive,
      processGroupStopped,
      startupTimedOut: (.startupTimedOut // false),
      retrySafe: (.retrySafe // false),
      cancellationPending: (.cancellationPending // false),
      milestones,
      report: (
        if ((.events // []) | length) > 0 then {
          recommended: true,
          reason: .report.reason,
          text: "A normalized \(.report.reason) event is available in events."
        }
        else .report
        end
      ),
      nextPollAfterSeconds,
      events: (.events // []),
      nextCursor: (.nextCursor // .cursor),
      hasMore: (.hasMore // false),
      compact: true,
      artifacts: {
        relativeToRunDir: true,
        progressPath: "progress.json",
        progressEventsPath: "progress.jsonl",
        statusPath: "status.json",
        eventsPath: "events.jsonl",
        finalMessagePath: "final.md",
        stderrPath: "stderr.log"
      }
    }
  ' <<<"$response"
}

compact_terminal_receipt() {
  local response="$1"

  jq -c '
    {
      schemaVersion,
      status,
      state: (.state // .status),
      action,
      runId,
      resumedFromRunId,
      threadId,
      terminal: true,
      resumable,
      processGroupStopped,
      proxy,
      configMode,
      worktreeRoot: (if .worktreeRoot == null then null else "." end),
      codexExit,
      signal,
      terminationReason,
      durationSeconds,
      turnCompleted,
      finalNonempty,
      latestSeq,
      usage,
      compact: true,
      artifacts: {
        relativeToRunDir: true,
        finalMessagePath: "final.md",
        eventsPath: "events.jsonl",
        stderrPath: "stderr.log",
        requestPath: "request.txt",
        statusPath: "status.json",
        progressPath: "progress.json",
        progressEventsPath: "progress.jsonl",
        supervisorPath: "supervisor.json"
      }
    }
  ' <<<"$response"
}

emit_bounded_terminal_receipt() {
  local response="$1"
  local bytes compact_response compact_bytes

  bytes="$(LC_ALL=C printf '%s\n' "$response" | wc -c)"
  bytes="${bytes//[[:space:]]/}"
  if ((bytes <= output_budget)); then
    printf '%s\n' "$response"
    return 0
  fi

  compact_response="$(compact_terminal_receipt "$response")"
  compact_bytes="$(LC_ALL=C printf '%s\n' "$compact_response" | wc -c)"
  compact_bytes="${compact_bytes//[[:space:]]/}"
  if ((compact_bytes <= output_budget)); then
    printf '%s\n' "$compact_response"
    return 0
  fi

  echo "run-codex: terminal receipt exceeds --output-budget after compacting; full receipt is in status.json" >&2
  return 70
}

emit_bounded_start_response() {
  local response="$1"
  local compact_response

  compact_response="$(jq -c '
    {
      schemaVersion,
      status,
      state: (.state // .status),
      operation: (.operation // "start"),
      runId,
      terminal,
      retrySafe: (.retrySafe // false),
      cancellationPending: (.cancellationPending // false),
      inspectWith: ("status --run-id " + .runId),
      compact: true
    }
  ' <<<"$response")"
  if (( $(LC_ALL=C printf '%s\n' "$response" | wc -c) <= output_budget )); then
    printf '%s\n' "$response"
  elif (( $(LC_ALL=C printf '%s\n' "$compact_response" | wc -c) <= output_budget )); then
    printf '%s\n' "$compact_response"
  else
    echo "run-codex: startup response exceeds --output-budget after compacting" >&2
    return 70
  fi
}

emit_bounded_prune_response() {
  local response="$1"
  local compact_response

  compact_response="$(jq -c '
    {
      schemaVersion,
      status,
      olderThanDays,
      applied,
      examined,
      eligible,
      removed,
      skipped,
      stateDirOmitted: true,
      compact: true
    }
  ' <<<"$response")"
  if (( $(LC_ALL=C printf '%s\n' "$response" | wc -c) <= output_budget )); then
    printf '%s\n' "$response"
  elif (( $(LC_ALL=C printf '%s\n' "$compact_response" | wc -c) <= output_budget )); then
    printf '%s\n' "$compact_response"
  else
    echo "run-codex: prune response exceeds --output-budget after compacting" >&2
    return 70
  fi
}

emit_bounded_control_response() {
  local response="$1"
  local bytes compact_response compact_bytes

  bytes="$(printf '%s\n' "$response" | wc -c)"
  bytes="${bytes//[[:space:]]/}"
  if ((bytes <= output_budget)); then
    printf '%s\n' "$response"
    return 0
  fi

  compact_response="$(compact_control_response "$response")"
  compact_bytes="$(printf '%s\n' "$compact_response" | wc -c)"
  compact_bytes="${compact_bytes//[[:space:]]/}"
  if ((compact_bytes <= output_budget)); then
    printf '%s\n' "$compact_response"
    return 0
  fi

  echo "run-codex: response envelope exceeds --output-budget after compacting" >&2
  return 70
}

build_events_response() {
  local operation="$1"
  local heartbeat_recommended="$2"
  local base all_events total limit selected count next_cursor has_more
  local response bytes compact_response compact_bytes

  base="$(control_snapshot_json)"
  all_events='[]'
  if [[ -f "$progress_events_path" ]]; then
    all_events="$(jq -sc --argjson after "$after_cursor" '[.[] | select(.seq > $after)]' \
      "$progress_events_path" 2>/dev/null || printf '[]')"
  fi
  total="$(jq 'length' <<<"$all_events")"
  limit="$max_events"

  while :; do
    selected="$(jq -c --argjson limit "$limit" '.[0:$limit]' <<<"$all_events")"
    count="$(jq 'length' <<<"$selected")"
    next_cursor="$(jq -r --argjson fallback "$after_cursor" 'if length > 0 then .[-1].seq else $fallback end' \
      <<<"$selected")"
    if ((total > count)); then
      has_more=true
    else
      has_more=false
    fi
    response="$(jq -cn \
      --arg operation "$operation" \
      --argjson base "$base" \
      --argjson events "$selected" \
      --argjson nextCursor "$next_cursor" \
      --argjson hasMore "$has_more" \
      --argjson heartbeatRecommended "$heartbeat_recommended" \
      '
        ($events | map(select(.reportable == true)) | last // null) as $reportEvent
        | $base
        | .operation = $operation
        | .events = $events
        | .nextCursor = $nextCursor
        | .cursor = $nextCursor
        | .hasMore = $hasMore
        | .report = (
            if $reportEvent != null then {
              recommended: true,
              reason: $reportEvent.kind,
              text: $reportEvent.summary
            }
            elif .terminal or .state == "orphaned" or .stale then .report
            elif $heartbeatRecommended then (.report | .recommended = true)
            else .report
            end
          )
        | .nextPollAfterSeconds = (if $hasMore then 0 else .nextPollAfterSeconds end)
      ')"
    bytes="$(printf '%s\n' "$response" | wc -c)"
    bytes="${bytes//[[:space:]]/}"
    if ((bytes <= output_budget)); then
      printf '%s\n' "$response"
      return 0
    fi

    compact_response="$(compact_control_response "$response")"
    compact_bytes="$(printf '%s\n' "$compact_response" | wc -c)"
    compact_bytes="${compact_bytes//[[:space:]]/}"
    if ((compact_bytes <= output_budget)); then
      printf '%s\n' "$compact_response"
      return 0
    fi

    if ((limit == 0)); then
      echo "run-codex: response envelope exceeds --output-budget after compacting" >&2
      return 70
    fi
    limit="$((limit - 1))"
  done
}

emit_observe_updates() {
  local allow_heartbeat="${1:-false}"
  local response event_count next_cursor has_more now emitted=false

  [[ "$observe" == "true" ]] || return 0

  while :; do
    after_cursor="$observe_cursor"
    response="$(build_events_response "observe" false)"
    event_count="$(jq -r '.events | length' <<<"$response")"
    next_cursor="$(jq -r '.nextCursor' <<<"$response")"
    has_more="$(jq -r '.hasMore' <<<"$response")"

    if ((event_count > 0)); then
      if jq -e '.report.recommended == true or .terminal == true or .state == "orphaned"' \
        <<<"$response" >/dev/null; then
        printf '%s\n' "$response"
        observe_last_report_at="$(date +%s)"
        emitted=true
      fi
      if [[ "$next_cursor" == "$observe_cursor" ]]; then
        break
      fi
      observe_cursor="$next_cursor"
      [[ "$has_more" == "true" ]] && continue
    fi
    break
  done

  now="$(date +%s)"
  if [[ "$allow_heartbeat" == "true" && "$emitted" == "false" ]] \
    && ((now - observe_last_report_at >= heartbeat_seconds)); then
    after_cursor="$observe_cursor"
    response="$(build_events_response "observe" true)"
    if jq -e '.terminal == false and (.events | length) == 0' <<<"$response" >/dev/null; then
      printf '%s\n' "$response"
      observe_last_report_at="$now"
    fi
  fi
}

run_control_status() {
  local response
  response="$(control_snapshot_json)"
  emit_bounded_control_response "$response"
}

run_control_events() {
  build_events_response "events" false
}

run_control_poll() {
  local started now latest=0
  started="$(date +%s)"
  while :; do
    if [[ -f "$status_path" ]]; then
      build_events_response "poll" false
      return 0
    fi
    if [[ -f "$progress_path" ]]; then
      latest="$(jq -r '.latestSeq // 0' "$progress_path" 2>/dev/null || printf '0')"
      if [[ "$latest" =~ ^[0-9]+$ ]] && ((latest > after_cursor)); then
        build_events_response "poll" false
        return 0
      fi
    fi
    now="$(date +%s)"
    if ((now - started >= wait_seconds)); then
      build_events_response "poll" true
      return 0
    fi
    sleep 0.2
  done
}

run_control_wait() {
  local started now response
  started="$(date +%s)"
  while [[ ! -f "$status_path" ]]; do
    now="$(date +%s)"
    if ((now - started >= wait_seconds)); then
      response="$(control_snapshot_json | jq -c '.operation = "wait"')"
      emit_bounded_control_response "$response"
      return 0
    fi
    sleep 0.2
  done
  response="$(control_snapshot_json | jq -c '.operation = "wait"')"
  emit_bounded_control_response "$response"
}

run_control_cancel() {
  local started now response
  if [[ -f "$status_path" ]]; then
    response="$(control_snapshot_json | jq -c '.operation = "cancel"')"
    emit_bounded_control_response "$response"
    return 0
  fi
  if ! supervisor_identity_alive; then
    response="$(control_snapshot_json | jq -c '.operation = "cancel"')"
    emit_bounded_control_response "$response"
    return 0
  fi

  kill -TERM "$supervisor_pid" 2>/dev/null || true
  started="$(date +%s)"
  while [[ ! -f "$status_path" ]]; do
    now="$(date +%s)"
    if ((now - started >= 15)); then
      response="$(control_snapshot_json | jq -c '. + {cancellationPending: true}')"
      emit_bounded_control_response "$response"
      return 0
    fi
    sleep 0.2
  done
  response="$(control_snapshot_json | jq -c '.operation = "cancel"')"
  emit_bounded_control_response "$response"
}

run_prune() {
  require_uint "--older-than-days" "$older_than_days"
  command -v find >/dev/null 2>&1 || fail_usage "find is required for prune"
  command -v jq >/dev/null 2>&1 || fail_usage "jq is required for prune"
  if [[ "$prune_apply" == "true" ]]; then
    command -v rm >/dev/null 2>&1 || fail_usage "rm is required for prune --apply"
  fi

  mkdir -p "$state_dir"
  chmod 700 "$state_dir"
  state_dir="$(cd "$state_dir" && pwd -P)"

  local examined=0
  local eligible=0
  local removed=0
  local skipped=0
  local status_file candidate candidate_name marker response

  while IFS= read -r -d '' status_file; do
    candidate="${status_file%/status.json}"
    candidate_name="${candidate##*/}"
    marker="$candidate/.codex-delegate-run.json"
    examined="$((examined + 1))"

    if ! validate_owned_run_dir "$candidate"; then
      skipped="$((skipped + 1))"
      continue
    fi
    if ! jq -e --arg runDir "$candidate" '
      .runDir == $runDir
      and (.status | IN(
        "completed", "incomplete", "failed", "failed_resumable",
        "resumable_timeout", "timed_out", "cancelled"
      ))
    ' "$status_file" >/dev/null 2>&1; then
      skipped="$((skipped + 1))"
      continue
    fi

    eligible="$((eligible + 1))"
    if [[ "$prune_apply" == "true" ]]; then
      rm -rf -- "$candidate"
      removed="$((removed + 1))"
    fi
  done < <(
    find "$state_dir" -mindepth 2 -maxdepth 2 -type f -name status.json \
      -mmin "+$((older_than_days * 1440))" -print0
  )

  response="$(jq -cn \
    --argjson schemaVersion 1 \
    --arg status "$(if [[ "$prune_apply" == "true" ]]; then printf pruned; else printf prune_preview; fi)" \
    --arg stateDir "$state_dir" \
    --argjson olderThanDays "$older_than_days" \
    --argjson applied "$prune_apply" \
    --argjson examined "$examined" \
    --argjson eligible "$eligible" \
    --argjson removed "$removed" \
    --argjson skipped "$skipped" \
    '{
      schemaVersion: $schemaVersion,
      status: $status,
      stateDir: $stateDir,
      olderThanDays: $olderThanDays,
      applied: $applied,
      examined: $examined,
      eligible: $eligible,
      removed: $removed,
      skipped: $skipped
    }')"
  emit_bounded_prune_response "$response"
}

write_supervisor_metadata() {
  local ready="$1"
  local now ticks group_json=null metadata
  now="$(date +%s)"
  ticks="$(process_start_ticks "$$")"
  if [[ "${process_group_id:-}" =~ ^[1-9][0-9]*$ ]]; then
    group_json="$process_group_id"
  fi
  metadata="$(jq -cn \
    --arg runId "$(basename "$run_dir")" \
    --argjson pid "$$" \
    --arg processStartTicks "$ticks" \
    --argjson processGroupId "$group_json" \
    --argjson ready "$ready" \
    --argjson startedAt "$started_at" \
    --argjson updatedAt "$now" \
    '{
      schemaVersion: 1,
      runId: $runId,
      pid: $pid,
      processStartTicks: (if $processStartTicks == "" then null else $processStartTicks end),
      processGroupId: $processGroupId,
      ready: $ready,
      startedAt: $startedAt,
      updatedAt: $updatedAt
    }')"
  atomic_write_json "$supervisor_path" "$metadata"
}

load_progress_state() {
  processed_lines="$(jq -r '.processedLines // 0' "$progress_state_path")"
  next_seq="$(jq -r '.nextSeq // 1' "$progress_state_path")"
  phase="$(jq -r '.phase // "working"' "$progress_state_path")"
  last_activity_at="$(jq -r '.lastActivityAt // 0' "$progress_state_path")"
  last_activity_summary="$(jq -r '.lastActivitySummary // "Codex is working."' "$progress_state_path")"
  last_activity_event_at="$(jq -r '.lastActivityEventAt // 0' "$progress_state_path")"
  last_checkpoint_event_at="$(jq -r '.lastCheckpointEventAt // 0' "$progress_state_path")"
  progress_thread_id="$(jq -r '.threadId // empty' "$progress_state_path")"
  milestones_json="$(jq -c '.milestones // null' "$progress_state_path")"
}

persist_progress_state() {
  local state_json
  state_json="$(jq -cn \
    --arg phase "$phase" \
    --arg lastActivitySummary "$last_activity_summary" \
    --arg threadId "$progress_thread_id" \
    --argjson processedLines "$processed_lines" \
    --argjson nextSeq "$next_seq" \
    --argjson lastActivityAt "$last_activity_at" \
    --argjson lastActivityEventAt "$last_activity_event_at" \
    --argjson lastCheckpointEventAt "$last_checkpoint_event_at" \
    --argjson milestones "$milestones_json" \
    '{
      schemaVersion: 1,
      processedLines: $processedLines,
      nextSeq: $nextSeq,
      phase: $phase,
      lastActivityAt: $lastActivityAt,
      lastActivitySummary: $lastActivitySummary,
      lastActivityEventAt: $lastActivityEventAt,
      lastCheckpointEventAt: $lastCheckpointEventAt,
      threadId: (if $threadId == "" then null else $threadId end),
      milestones: $milestones
    }')"
  atomic_write_json "$progress_state_path" "$state_json"
}

append_normalized_event() {
  local kind="$1"
  local event_phase="$2"
  local summary="$3"
  local reportable="$4"
  local source_line="$5"
  local event_state="$6"
  local event_milestones="${7:-null}"
  local now timestamp source_json=null event

  now="$(date +%s)"
  timestamp="$(epoch_iso "$now")"
  if [[ "$source_line" =~ ^[1-9][0-9]*$ ]]; then
    source_json="$source_line"
  fi
  if [[ -n "$event_phase" && "$event_phase" != "null" ]]; then
    phase="$event_phase"
  fi
  event="$(jq -cn \
    --arg runId "$(basename "$run_dir")" \
    --arg timestamp "$timestamp" \
    --arg kind "$kind" \
    --arg state "$event_state" \
    --arg phase "$phase" \
    --arg summary "$summary" \
    --argjson seq "$next_seq" \
    --argjson timestampEpoch "$now" \
    --argjson reportable "$reportable" \
    --argjson sourceLine "$source_json" \
    --argjson milestones "$event_milestones" \
    '{
      schemaVersion: 1,
      seq: $seq,
      runId: $runId,
      timestamp: $timestamp,
      timestampEpoch: $timestampEpoch,
      kind: $kind,
      state: $state,
      phase: $phase,
      summary: $summary,
      reportable: $reportable,
      sourceLine: $sourceLine,
      milestones: $milestones
    }')"
  printf '%s\n' "$event" >>"$progress_events_path"
  next_seq="$((next_seq + 1))"
  last_activity_summary="$summary"
}

write_progress_snapshot() {
  local snapshot_state="${1:-running}"
  local snapshot_resumable="${2:-false}"
  local group_stopped="${3:-false}"
  local now elapsed last_age stale=false group_json=null snapshot

  load_progress_state
  now="$(date +%s)"
  elapsed="$((now - started_at))"
  ((elapsed >= 0)) || elapsed=0
  last_age="$((now - last_activity_at))"
  ((last_age >= 0)) || last_age=0
  if [[ "$snapshot_state" == "running" && "$last_age" -ge "$stale_after" ]]; then
    stale=true
  fi
  if [[ "${process_group_id:-}" =~ ^[1-9][0-9]*$ ]]; then
    group_json="$process_group_id"
  fi
  snapshot="$(jq -cn \
    --arg runId "$(basename "$run_dir")" \
    --arg runDir "$run_dir" \
    --arg state "$snapshot_state" \
    --arg phase "$phase" \
    --arg lastSummary "$last_activity_summary" \
    --arg threadId "$progress_thread_id" \
    --arg progressPath "$progress_path" \
    --arg progressEventsPath "$progress_events_path" \
    --arg statusPath "$status_path" \
    --arg eventsPath "$events_path" \
    --arg finalMessagePath "$final_path" \
    --arg stderrPath "$stderr_path" \
    --argjson startedAt "$started_at" \
    --argjson updatedAt "$now" \
    --argjson lastActivityAt "$last_activity_at" \
    --argjson elapsedSeconds "$elapsed" \
    --argjson lastActivityAgeSeconds "$last_age" \
    --argjson stale "$stale" \
    --argjson resumable "$snapshot_resumable" \
    --argjson latestSeq "$((next_seq - 1))" \
    --argjson processGroupId "$group_json" \
    --argjson processGroupStopped "$group_stopped" \
    --argjson milestones "$milestones_json" \
    '{
      schemaVersion: 1,
      runId: $runId,
      runDir: $runDir,
      state: $state,
      phase: $phase,
      startedAt: $startedAt,
      updatedAt: $updatedAt,
      lastActivityAt: $lastActivityAt,
      elapsedSeconds: $elapsedSeconds,
      lastActivityAgeSeconds: $lastActivityAgeSeconds,
      stale: $stale,
      threadId: (if $threadId == "" then null else $threadId end),
      resumable: $resumable,
      latestSeq: $latestSeq,
      processGroupId: $processGroupId,
      processGroupStopped: $processGroupStopped,
      milestones: $milestones,
      lastSummary: $lastSummary,
      artifacts: {
        progressPath: $progressPath,
        progressEventsPath: $progressEventsPath,
        statusPath: $statusPath,
        eventsPath: $eventsPath,
        finalMessagePath: $finalMessagePath,
        stderrPath: $stderrPath
      }
    }')"
  atomic_write_json "$progress_path" "$snapshot"
}

initialize_progress() {
  local now initial_state
  now="$started_at"
  processed_lines=0
  next_seq=1
  phase="starting"
  last_activity_at="$now"
  last_activity_summary="Codex delegation initialized."
  last_activity_event_at=0
  last_checkpoint_event_at=0
  progress_thread_id=""
  milestones_json=null
  : >"$progress_events_path"
  append_normalized_event "started" "starting" "$last_activity_summary" true "" "running" null
  persist_progress_state
  write_supervisor_metadata false
  write_progress_snapshot "running" false false
  chmod 600 "$progress_events_path" "$progress_state_path" "$progress_path" "$supervisor_path"
}

normalize_progress() {
  local complete_lines candidates line_number kind candidate_phase summary activity
  local candidate_thread milestone_completed milestone_total candidate_milestones now reportable=false

  [[ -f "$progress_state_path" && -f "$events_path" ]] || return 0
  load_progress_state
  complete_lines="$(wc -l <"$events_path")"
  complete_lines="${complete_lines//[[:space:]]/}"
  [[ "$complete_lines" =~ ^[0-9]+$ ]] || complete_lines=0

  if ((complete_lines > processed_lines)); then
    candidates="$(
      sed -n "$((processed_lines + 1)),${complete_lines}p" "$events_path" \
        | jq -Rsc --argjson offset "$processed_lines" -f "$NORMALIZE_EVENT_FILTER"
    )"
    now="$(date +%s)"
    while IFS=$'\t' read -r line_number kind candidate_phase summary activity candidate_thread \
      milestone_completed milestone_total; do
      [[ "$kind" != "__none__" ]] || kind=""
      [[ "$candidate_phase" != "__none__" ]] || candidate_phase=""
      [[ "$candidate_thread" != "__none__" ]] || candidate_thread=""
      candidate_milestones=null
      if [[ "$milestone_completed" =~ ^[0-9]+$ && "$milestone_total" =~ ^[1-9][0-9]*$ ]]; then
        candidate_milestones="{\"completed\":$milestone_completed,\"total\":$milestone_total}"
      fi

      if [[ -n "$candidate_thread" ]]; then
        progress_thread_id="$candidate_thread"
      fi
      if [[ -n "$candidate_phase" ]]; then
        phase="$candidate_phase"
      fi
      if [[ "$candidate_milestones" != "null" ]]; then
        milestones_json="$candidate_milestones"
      fi
      if [[ "$activity" == "true" ]]; then
        last_activity_at="$now"
        last_activity_summary="$summary"
      fi

      reportable=false
      case "$kind" in
        activity)
          if ((now - last_activity_event_at >= 30)); then
            reportable=true
            last_activity_event_at="$now"
          else
            kind=""
          fi
          ;;
        checkpoint)
          if ((now - last_checkpoint_event_at >= 1)); then
            reportable=true
            last_checkpoint_event_at="$now"
          else
            kind=""
          fi
          ;;
        phase_changed|warning)
          reportable=true
          ;;
      esac

      if [[ -n "$kind" ]]; then
        append_normalized_event "$kind" "$candidate_phase" "$summary" "$reportable" \
          "$line_number" "running" "$candidate_milestones"
      fi
    done < <(
      jq -r '
        .[]
        | [
            (.sourceLine | tostring),
            (.kind // "__none__"),
            (.phase // "__none__"),
            (.summary // "Codex is working."),
            ((.activity // false) | tostring),
            (.threadId // "__none__"),
            ((.milestones.completed // -1) | tostring),
            ((.milestones.total // -1) | tostring)
          ]
        | @tsv
      ' <<<"$candidates"
    )
    processed_lines="$complete_lines"
    persist_progress_state
  fi
  write_progress_snapshot "running" false false
}

finalize_progress() {
  local final_state="$1"
  local final_summary="$2"
  local final_resumable="$3"
  local final_group_stopped="$4"
  local now

  normalize_progress
  load_progress_state
  now="$(date +%s)"
  last_activity_at="$now"
  phase="finalizing"
  append_normalized_event "terminal" "finalizing" "$final_summary" true "" "$final_state" "$milestones_json"
  persist_progress_state
  write_progress_snapshot "$final_state" "$final_resumable" "$final_group_stopped"
}

[[ $# -gt 0 ]] || fail_usage "missing action"
action="$1"
shift
[[ "$action" =~ ^(start|resume|status|events|poll|wait|cancel|prune)$ ]] \
  || fail_usage "unsupported action: $action"

cwd=""
prompt_file=""
thread_id=""
run_id=""
sandbox="read-only"
allow_workspace_write=false
worktree_root=""
approval_policy="never"
inherit_user_config=false
config_mode="isolated"
idle_timeout="$DEFAULT_IDLE_TIMEOUT"
hard_timeout="$DEFAULT_HARD_TIMEOUT"
poll_interval="$DEFAULT_POLL_INTERVAL"
ready_timeout="$DEFAULT_READY_TIMEOUT"
state_dir="$(choose_default_state_dir)"
run_dir=""
codex_bin="${CODEX_BIN:-codex}"
requested_model=""
older_than_days=14
prune_apply=false
prune_option_seen=false
detach=false
observe=false
internal_supervisor=false
resumed_from_run_id=""
after_cursor=0
wait_seconds="$DEFAULT_CONTROL_WAIT"
stale_after="$DEFAULT_STALE_AFTER"
max_events="$DEFAULT_MAX_EVENTS"
output_budget="$DEFAULT_OUTPUT_BUDGET"
heartbeat_seconds="$DEFAULT_HEARTBEAT_SECONDS"
heartbeat_option_seen=false
observe_cursor=0
observe_last_report_at=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cwd)
      require_value "$1" "${2:-}"
      cwd="$2"
      shift 2
      ;;
    --prompt-file)
      require_value "$1" "${2:-}"
      prompt_file="$2"
      shift 2
      ;;
    --thread-id)
      require_value "$1" "${2:-}"
      thread_id="$2"
      shift 2
      ;;
    --run-id)
      require_value "$1" "${2:-}"
      run_id="$2"
      shift 2
      ;;
    --detach)
      detach=true
      shift
      ;;
    --observe)
      observe=true
      shift
      ;;
    --heartbeat-seconds)
      require_value "$1" "${2:-}"
      heartbeat_seconds="$2"
      heartbeat_option_seen=true
      shift 2
      ;;
    --internal-supervisor)
      internal_supervisor=true
      shift
      ;;
    --resumed-from-run-id)
      require_value "$1" "${2:-}"
      resumed_from_run_id="$2"
      shift 2
      ;;
    --after)
      require_value "$1" "${2:-}"
      after_cursor="$2"
      shift 2
      ;;
    --wait-seconds)
      require_value "$1" "${2:-}"
      wait_seconds="$2"
      shift 2
      ;;
    --stale-after)
      require_value "$1" "${2:-}"
      stale_after="$2"
      shift 2
      ;;
    --max-events)
      require_value "$1" "${2:-}"
      max_events="$2"
      shift 2
      ;;
    --output-budget)
      require_value "$1" "${2:-}"
      output_budget="$2"
      shift 2
      ;;
    --sandbox)
      require_value "$1" "${2:-}"
      sandbox="$2"
      shift 2
      ;;
    --allow-workspace-write)
      allow_workspace_write=true
      shift
      ;;
    --worktree-root)
      require_value "$1" "${2:-}"
      worktree_root="$2"
      shift 2
      ;;
    --approval-policy)
      require_value "$1" "${2:-}"
      approval_policy="$2"
      shift 2
      ;;
    --inherit-user-config)
      inherit_user_config=true
      config_mode="inherited"
      shift
      ;;
    --idle-timeout)
      require_value "$1" "${2:-}"
      idle_timeout="$2"
      shift 2
      ;;
    --hard-timeout)
      require_value "$1" "${2:-}"
      hard_timeout="$2"
      shift 2
      ;;
    --poll-interval)
      require_value "$1" "${2:-}"
      poll_interval="$2"
      shift 2
      ;;
    --ready-timeout)
      require_value "$1" "${2:-}"
      ready_timeout="$2"
      shift 2
      ;;
    --state-dir)
      require_value "$1" "${2:-}"
      state_dir="$2"
      shift 2
      ;;
    --run-dir)
      require_value "$1" "${2:-}"
      run_dir="$2"
      shift 2
      ;;
    --codex-bin)
      require_value "$1" "${2:-}"
      codex_bin="$2"
      shift 2
      ;;
    --model)
      require_value "$1" "${2:-}"
      requested_model="$2"
      shift 2
      ;;
    --older-than-days)
      require_value "$1" "${2:-}"
      older_than_days="$2"
      prune_option_seen=true
      shift 2
      ;;
    --apply)
      prune_apply=true
      prune_option_seen=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail_usage "unknown option: $1"
      ;;
  esac
done

if [[ "$action" == "prune" ]]; then
  [[ -z "$cwd" && -z "$prompt_file" && -z "$thread_id" && -z "$run_id" && -z "$run_dir" \
    && "$detach" == "false" && "$observe" == "false" && "$heartbeat_option_seen" == "false" \
    && "$allow_workspace_write" == "false" && -z "$worktree_root" \
    && "$inherit_user_config" == "false" && "$ready_timeout" == "$DEFAULT_READY_TIMEOUT" ]] \
    || fail_usage "prune only accepts --state-dir, --older-than-days, and --apply"
  run_prune
  exit 0
fi

[[ "$prune_option_seen" == "false" ]] || fail_usage "prune options require the prune action"
require_uint "--after" "$after_cursor"
require_uint "--wait-seconds" "$wait_seconds"
require_uint "--stale-after" "$stale_after"
require_uint "--max-events" "$max_events"
require_uint "--output-budget" "$output_budget"
require_uint "--heartbeat-seconds" "$heartbeat_seconds"
require_number "--ready-timeout" "$ready_timeout"
((wait_seconds <= MAX_CONTROL_WAIT)) || fail_usage "--wait-seconds must not exceed $MAX_CONTROL_WAIT"
((max_events > 0)) || fail_usage "--max-events must be greater than zero"
((output_budget >= DEFAULT_OUTPUT_BUDGET)) \
  || fail_usage "--output-budget must be at least $DEFAULT_OUTPUT_BUDGET bytes"
((heartbeat_seconds > 0)) || fail_usage "--heartbeat-seconds must be greater than zero"
command -v jq >/dev/null 2>&1 || fail_usage "jq is required"

if [[ "$action" =~ ^(status|events|poll|wait|cancel)$ ]]; then
  [[ -n "$run_id" ]] || fail_usage "--run-id is required for $action"
  [[ -z "$cwd" && -z "$prompt_file" && -z "$thread_id" && -z "$run_dir" \
    && "$detach" == "false" && "$observe" == "false" && "$heartbeat_option_seen" == "false" \
    && "$allow_workspace_write" == "false" && -z "$worktree_root" \
    && "$inherit_user_config" == "false" && "$ready_timeout" == "$DEFAULT_READY_TIMEOUT" ]] \
    || fail_usage "$action only accepts control and state-directory options"
  resolve_control_run "$run_id"
  case "$action" in
    status) run_control_status ;;
    events) run_control_events ;;
    poll) run_control_poll ;;
    wait) run_control_wait ;;
    cancel) run_control_cancel ;;
  esac
  exit 0
fi

[[ -n "$prompt_file" ]] || fail_usage "--prompt-file is required"
[[ -r "$prompt_file" ]] || fail_usage "prompt file is not readable: $prompt_file"
[[ "$detach" == "false" || "$observe" == "false" ]] \
  || fail_usage "--detach and --observe are mutually exclusive"
[[ "$heartbeat_option_seen" == "false" || "$observe" == "true" ]] \
  || fail_usage "--heartbeat-seconds requires --observe"
[[ "$ready_timeout" == "$DEFAULT_READY_TIMEOUT" || "$detach" == "true" ]] \
  || fail_usage "--ready-timeout requires --detach"

if [[ "$action" == "start" ]]; then
  [[ -n "$cwd" ]] || fail_usage "--cwd is required for start"
  [[ -d "$cwd" ]] || fail_usage "working directory does not exist: $cwd"
  [[ -z "$thread_id" ]] || fail_usage "--thread-id is only valid for resume"
  [[ -z "$run_id" ]] || fail_usage "--run-id is only valid for resume or control actions"
else
  if [[ -n "$run_id" ]]; then
    [[ -z "$thread_id" ]] || fail_usage "resume accepts either --thread-id or --run-id, not both"
    requested_new_run_dir="$run_dir"
    resolve_control_run "$run_id"
    jq -e '.resumable == true and .processGroupStopped == true and (.threadId | type == "string" and length > 0)' \
      "$status_path" >/dev/null 2>&1 \
      || fail_usage "run is not safely resumable: $run_id"
    thread_id="$(jq -r '.threadId' "$status_path")"
    if [[ "$sandbox" == "workspace-write" && -z "$worktree_root" ]]; then
      worktree_root="$(jq -r '.worktreeRoot // empty' "$status_path")"
    fi
    resumed_from_run_id="$run_id"
    run_dir="$requested_new_run_dir"
    run_id=""
  fi
  [[ -n "$thread_id" ]] || fail_usage "--thread-id or --run-id is required for resume"
  [[ -z "$cwd" ]] || fail_usage "resume uses the thread's original working directory; omit --cwd"
fi

[[ "$sandbox" == "read-only" || "$sandbox" == "workspace-write" ]] \
  || fail_usage "--sandbox must be read-only or workspace-write"
[[ "$approval_policy" == "never" || "$approval_policy" == "on-request" || "$approval_policy" == "untrusted" ]] \
  || fail_usage "unsupported --approval-policy: $approval_policy"
require_uint "--idle-timeout" "$idle_timeout"
require_uint "--hard-timeout" "$hard_timeout"
require_number "--poll-interval" "$poll_interval"
validate_workspace_write_boundary
validate_proxy_url
command -v "$codex_bin" >/dev/null 2>&1 || fail_usage "Codex executable not found: $codex_bin"
command -v env >/dev/null 2>&1 || fail_usage "env is required for invocation-scoped proxy settings"
command -v setsid >/dev/null 2>&1 || fail_usage "setsid is required for safe process-group termination"
[[ -r "$NORMALIZE_EVENT_FILTER" ]] || fail_usage "progress normalizer is missing: $NORMALIZE_EVENT_FILTER"

prepare_state_dir
prepare_new_run_dir

if [[ "$detach" == "true" && "$internal_supervisor" == "false" ]]; then
  detached_run_id="$(basename "$run_dir")"
  launch_log="$state_dir/.${detached_run_id}.supervisor.log"
  worker_command=(
    "$SCRIPT_PATH" "$action"
    --prompt-file "$prompt_file"
    --sandbox "$sandbox"
    --approval-policy "$approval_policy"
    --idle-timeout "$idle_timeout"
    --hard-timeout "$hard_timeout"
    --poll-interval "$poll_interval"
    --stale-after "$stale_after"
    --state-dir "$state_dir"
    --run-dir "$run_dir"
    --codex-bin "$codex_bin"
    --internal-supervisor
  )
  if [[ "$inherit_user_config" == "true" ]]; then
    worker_command+=(--inherit-user-config)
  fi
  if [[ -n "$requested_model" ]]; then
    worker_command+=(--model "$requested_model")
  fi
  if [[ "$sandbox" == "workspace-write" ]]; then
    worker_command+=(--allow-workspace-write --worktree-root "$worktree_root")
  fi
  if [[ "$action" == "start" ]]; then
    worker_command+=(--cwd "$cwd")
  else
    worker_command+=(--thread-id "$thread_id")
  fi
  if [[ -n "$resumed_from_run_id" ]]; then
    worker_command+=(--resumed-from-run-id "$resumed_from_run_id")
  fi

  if ! setsid --fork "${worker_command[@]}" < /dev/null >"$launch_log" 2>&1; then
    startup_response="$(jq -cn \
      --arg status "failed_to_start" \
      --arg runId "$detached_run_id" \
      --arg runDir "$run_dir" \
      '{
        schemaVersion: 1,
        status: $status,
        state: $status,
        runId: $runId,
        runDir: $runDir,
        terminal: true,
        retrySafe: true
      }')"
    emit_bounded_start_response "$startup_response"
    exit 70
  fi
  ready=false
  ready_attempts="$(awk -v seconds="$ready_timeout" 'BEGIN { print int((seconds * 100) + 0.999999) }')"
  for ((attempt = 0; attempt <= ready_attempts; attempt++)); do
    if [[ -f "$run_dir/supervisor.json" ]] \
      && jq -e '.ready == true' "$run_dir/supervisor.json" >/dev/null 2>&1; then
      ready=true
      break
    fi
    ((attempt < ready_attempts)) || break
    sleep 0.01
  done
  if [[ -d "$run_dir" && -f "$launch_log" ]]; then
    mv -f "$launch_log" "$run_dir/supervisor.log"
    chmod 600 "$run_dir/supervisor.log"
  fi
  if [[ "$ready" != "true" ]]; then
    ownership_ready=false
    for ((attempt = 1; attempt <= 200; attempt++)); do
      if [[ -f "$run_dir/.codex-delegate-run.json" && -f "$run_dir/supervisor.json" ]]; then
        ownership_ready=true
        break
      fi
      sleep 0.01
    done

    if [[ "$ownership_ready" == "true" ]]; then
      resolve_control_run "$detached_run_id"
      if supervisor_identity_alive; then
        kill -TERM "$supervisor_pid" 2>/dev/null || true
      fi
      for ((attempt = 1; attempt <= 75; attempt++)); do
        [[ -f "$status_path" ]] && break
        sleep 0.2
      done
      if [[ -f "$status_path" ]]; then
        startup_response="$(control_snapshot_json | jq -c --arg operation "$action" '
          .operation = $operation
          | .startupTimedOut = true
          | .retrySafe = (.terminal and .processGroupStopped)
          | .report = {
              recommended: true,
              reason: "warning",
              text: "Detached readiness timed out; the supervisor was stopped and a terminal receipt was preserved."
            }
        ')"
        emit_bounded_control_response "$startup_response"
        exit 70
      fi
    fi

    startup_response="$(jq -cn \
      --arg runId "$detached_run_id" \
      --arg runDir "$run_dir" \
      '{
        schemaVersion: 1,
        status: "start_unknown",
        state: "start_unknown",
        operation: "start",
        runId: $runId,
        runDir: $runDir,
        terminal: false,
        retrySafe: false,
        cancellationPending: true,
        report: {
          recommended: true,
          reason: "warning",
          text: "Detached readiness timed out and writer termination could not be confirmed. Inspect this run ID; do not start a replacement blindly."
        }
      }')"
    emit_bounded_start_response "$startup_response"
    exit 70
  fi
  resolve_control_run "$detached_run_id"
  detached_response="$(control_snapshot_json | jq -c --arg operation "$action" '
    .operation = $operation
    | .nextCursor = .cursor
    | .report = {
        recommended: true,
        reason: "started",
        text: "Codex delegation started."
      }
  ')"
  emit_bounded_control_response "$detached_response"
  exit 0
fi

load_run_paths "$run_dir"
started_at="$(date +%s)"
process_group_id=""
launcher_pid=""
process_group_path="$run_dir/.process-group.id"
cancellation_signal=""
termination_reason=""
process_group_stopped=true

process_group_alive() {
  [[ -n "$process_group_id" ]] && kill -0 -- "-$process_group_id" 2>/dev/null
}

load_process_group_id() {
  local candidate=""
  [[ -s "$process_group_path" ]] || return 1
  IFS= read -r candidate <"$process_group_path"
  [[ "$candidate" =~ ^[1-9][0-9]*$ ]] || return 1
  process_group_id="$candidate"
}

signal_child() {
  local signal="$1"
  if process_group_alive; then
    kill "-$signal" -- "-$process_group_id" 2>/dev/null || true
  fi
}

terminate_child() {
  signal_child INT
  local attempt
  for attempt in 1 2 3 4 5; do
    process_group_alive || return 0
    sleep 0.2
  done
  signal_child TERM
  for attempt in 1 2 3 4 5; do
    process_group_alive || return 0
    sleep 0.2
  done
  signal_child KILL
  for attempt in 1 2 3 4 5; do
    process_group_alive || return 0
    sleep 0.2
  done
  return 1
}

signal_exit_code() {
  case "$1" in
    HUP) printf '129\n' ;;
    INT) printf '130\n' ;;
    TERM) printf '143\n' ;;
    *) printf '128\n' ;;
  esac
}

handle_runner_signal() {
  local received_signal="$1"
  local attempt

  if [[ -n "$cancellation_signal" ]]; then
    return 0
  fi

  cancellation_signal="$received_signal"
  termination_reason="signal_$received_signal"
  trap '' INT TERM HUP

  if [[ -z "$process_group_id" ]]; then
    for ((attempt = 1; attempt <= 200; attempt++)); do
      load_process_group_id && break
      if [[ -n "$launcher_pid" ]] && ! kill -0 "$launcher_pid" 2>/dev/null; then
        break
      fi
      [[ -n "$launcher_pid" ]] || break
      sleep 0.01 || true
    done
  fi

  if [[ -n "$process_group_id" ]]; then
    if ! terminate_child; then
      process_group_stopped=false
    fi
  elif [[ -n "$launcher_pid" ]] && kill -0 "$launcher_pid" 2>/dev/null; then
    kill -TERM "$launcher_pid" 2>/dev/null || true
    process_group_stopped=false
  fi
}

: >"$request_path"
: >"$events_path"
: >"$final_path"
: >"$stderr_path"
jq -cn \
  --arg format "codex-delegate-run-v1" \
  --arg runDir "$run_dir" \
  --arg runId "$(basename "$run_dir")" \
  --arg action "$action" \
  --arg resumedFromRunId "$resumed_from_run_id" \
  --arg configMode "$config_mode" \
  --arg worktreeRoot "$worktree_root" \
  --arg sandbox "$sandbox" \
  --arg cwd "$cwd" \
  --argjson createdAt "$started_at" \
  '{
    format: $format,
    runDir: $runDir,
    runId: $runId,
    action: $action,
    resumedFromRunId: (if $resumedFromRunId == "" then null else $resumedFromRunId end),
    configMode: $configMode,
    worktreeRoot: (if $worktreeRoot == "" then null else $worktreeRoot end),
    sandbox: $sandbox,
    cwd: (if $cwd == "" then null else $cwd end),
    createdAt: $createdAt
  }' >"$marker_path"
chmod 600 "$request_path" "$events_path" "$final_path" "$stderr_path" "$marker_path"
trap 'handle_runner_signal INT' INT
trap 'handle_runner_signal TERM' TERM
trap 'handle_runner_signal HUP' HUP
if [[ -n "${CODEX_DELEGATE_TEST_INIT_DELAY:-}" ]]; then
  sleep "$CODEX_DELEGATE_TEST_INIT_DELAY" || true
fi
cp "$prompt_file" "$request_path"
initialize_progress

approval_config="approval_policy=\"$approval_policy\""
sandbox_config="sandbox_mode=\"$sandbox\""
config_args=()
if [[ -n "$requested_model" ]]; then
  config_args+=(--model "$requested_model")
fi
if [[ "$inherit_user_config" == "false" ]]; then
  config_args+=(--ignore-user-config)
fi
proxy_command=(env
  -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY
  -u https_proxy -u http_proxy -u all_proxy
  -u NO_PROXY -u no_proxy)
proxy_mode="direct"
if [[ -n "$CODEX_PROXY_URL" ]]; then
  proxy_mode="configured"
  proxy_command+=(
    "HTTPS_PROXY=$CODEX_PROXY_URL"
    "HTTP_PROXY=$CODEX_PROXY_URL"
    "ALL_PROXY=$CODEX_PROXY_URL"
    "https_proxy=$CODEX_PROXY_URL"
    "http_proxy=$CODEX_PROXY_URL"
    "all_proxy=$CODEX_PROXY_URL"
    "NO_PROXY=$CODEX_NO_PROXY"
    "no_proxy=$CODEX_NO_PROXY"
  )
fi
if [[ "$action" == "start" ]]; then
  command_args=(
    "${proxy_command[@]}"
    "$codex_bin" exec "${config_args[@]}" --json
    -C "$cwd"
    -s "$sandbox"
    -c "$approval_config"
    -o "$final_path"
    -
  )
else
  command_args=(
    "${proxy_command[@]}"
    "$codex_bin" exec resume "${config_args[@]}" --json
    -c "$approval_config"
    -c "$sandbox_config"
    -o "$final_path"
    "$thread_id"
    -
  )
fi

codex_exit=125
if [[ -z "$cancellation_signal" ]]; then
  setsid --fork --wait bash -c '
    process_group_path="$1"
    shift
    printf "%s\n" "$$" >"$process_group_path"
    exec "$@"
  ' codex-delegate-launch "$process_group_path" "${command_args[@]}" \
    <"$request_path" >"$events_path" 2>"$stderr_path" &
  launcher_pid="$!"

  if [[ -n "$cancellation_signal" ]]; then
    for ((attempt = 1; attempt <= 200; attempt++)); do
      load_process_group_id && break
      kill -0 "$launcher_pid" 2>/dev/null || break
      sleep 0.01 || true
    done
    if [[ -n "$process_group_id" ]]; then
      if ! terminate_child; then
        process_group_stopped=false
      fi
    elif kill -0 "$launcher_pid" 2>/dev/null; then
      kill -TERM "$launcher_pid" 2>/dev/null || true
      process_group_stopped=false
    fi
  fi

  for ((attempt = 1; attempt <= 200; attempt++)); do
    [[ -z "$cancellation_signal" ]] || break
    load_process_group_id && break
    kill -0 "$launcher_pid" 2>/dev/null || break
    sleep 0.01 || true
  done
  rm -f "$process_group_path"

  if [[ ! "$process_group_id" =~ ^[1-9][0-9]*$ ]]; then
    set +e
    wait "$launcher_pid"
    codex_exit="$?"
    set -e
    if [[ -z "$cancellation_signal" ]]; then
      termination_reason="launch_failed"
      echo "run-codex: failed to establish process group (setsid exit $codex_exit); see $stderr_path" >&2
    fi
  else
    if [[ -n "${CODEX_DELEGATE_TEST_READY_DELAY:-}" ]]; then
      sleep "$CODEX_DELEGATE_TEST_READY_DELAY" || true
    fi
    write_supervisor_metadata true
    normalize_progress
    emit_observe_updates false

    last_bytes=0
    last_activity="$started_at"

    while [[ -z "$cancellation_signal" ]] && process_group_alive; do
      now="$(date +%s)"
      current_bytes="$(wc -c <"$events_path")"
      current_bytes="${current_bytes//[[:space:]]/}"
      if [[ "$current_bytes" != "$last_bytes" ]]; then
        last_bytes="$current_bytes"
        last_activity="$now"
        normalize_progress
      else
        write_progress_snapshot "running" false false
      fi
      emit_observe_updates true

      if ((idle_timeout > 0 && now - last_activity >= idle_timeout)); then
        termination_reason="idle_timeout"
        if ! terminate_child; then
          process_group_stopped=false
        fi
        break
      fi
      if ((hard_timeout > 0 && now - started_at >= hard_timeout)); then
        termination_reason="hard_timeout"
        if ! terminate_child; then
          process_group_stopped=false
        fi
        break
      fi
      sleep "$poll_interval" || true
    done

    normalize_progress
    emit_observe_updates false

    if [[ "$process_group_stopped" == "true" && -n "$launcher_pid" ]]; then
      set +e
      wait "$launcher_pid"
      codex_exit="$?"
      set -e
    fi
  fi
else
  codex_exit="$(signal_exit_code "$cancellation_signal")"
fi
trap - INT TERM HUP
finished_at="$(date +%s)"
duration_seconds="$((finished_at - started_at))"

event_summary="$(jq -Rsc '
  split("\n")
  | map(select(length > 0)) as $lines
  | ($lines | map(try fromjson catch null)) as $parsed
  | ($parsed | map(select(. != null))) as $events
  | {
      rawLines: ($lines | length),
      invalidLines: ($parsed | map(select(. == null)) | length),
      parsedEvents: ($events | length),
      threadId: ([$events[] | select(.type == "thread.started") | .thread_id][0] // ""),
      turnCompleted: any($events[]; .type == "turn.completed"),
      turnFailed: any($events[]; .type == "turn.failed"),
      usage: ([$events[] | select(.type == "turn.completed") | .usage][-1] // null)
    }
' "$events_path")"

parsed_thread_id="$(jq -r '.threadId' <<<"$event_summary")"
turn_completed="$(jq -r '.turnCompleted' <<<"$event_summary")"
turn_failed="$(jq -r '.turnFailed' <<<"$event_summary")"
parsed_events="$(jq -r '.parsedEvents' <<<"$event_summary")"
raw_lines="$(jq -r '.rawLines' <<<"$event_summary")"
invalid_lines="$(jq -r '.invalidLines' <<<"$event_summary")"
usage_json="$(jq -c '.usage' <<<"$event_summary")"
event_bytes="$(wc -c <"$events_path")"
event_bytes="${event_bytes//[[:space:]]/}"
final_bytes="$(wc -c <"$final_path")"
final_bytes="${final_bytes//[[:space:]]/}"
final_nonempty=false
if grep -q '[^[:space:]]' "$final_path"; then
  final_nonempty=true
fi

if [[ -z "$termination_reason" && "$codex_exit" -eq 124 ]]; then
  termination_reason="process_timeout"
fi

status="failed"
receipt_exit=1
resumable=false
if [[ -n "$cancellation_signal" ]]; then
  status="cancelled"
  if [[ -n "$parsed_thread_id" && "$process_group_stopped" == "true" ]]; then
    resumable=true
  fi
  receipt_exit="$(signal_exit_code "$cancellation_signal")"
elif [[ "$codex_exit" -eq 0 && "$turn_completed" == "true" && "$turn_failed" == "false" && "$final_nonempty" == "true" ]]; then
  status="completed"
  receipt_exit=0
elif [[ "$termination_reason" == "idle_timeout" || "$termination_reason" == "hard_timeout" \
  || "$termination_reason" == "process_timeout" ]]; then
  if [[ -n "$parsed_thread_id" ]]; then
    status="resumable_timeout"
    [[ "$process_group_stopped" == "true" ]] && resumable=true
  else
    status="timed_out"
  fi
  receipt_exit=124
elif [[ "$termination_reason" == "launch_failed" ]]; then
  status="failed"
  receipt_exit=70
elif [[ "$turn_failed" == "true" ]]; then
  if [[ -n "$parsed_thread_id" && "$process_group_stopped" == "true" ]]; then
    status="failed_resumable"
    resumable=true
  fi
elif [[ "$codex_exit" -eq 0 ]]; then
  status="incomplete"
  [[ -n "$parsed_thread_id" && "$process_group_stopped" == "true" ]] && resumable=true
  receipt_exit=65
elif [[ -n "$parsed_thread_id" && "$process_group_stopped" == "true" ]]; then
  status="failed_resumable"
  resumable=true
fi

case "$status" in
  completed) terminal_summary="Codex completed successfully; final output is ready." ;;
  cancelled) terminal_summary="Codex delegation was cancelled and a terminal receipt was preserved." ;;
  resumable_timeout|timed_out) terminal_summary="Codex delegation reached its configured timeout." ;;
  incomplete) terminal_summary="Codex exited without satisfying strict completion checks." ;;
  failed_resumable|failed) terminal_summary="Codex delegation failed; inspect the terminal receipt and diagnostics." ;;
  *) terminal_summary="Codex delegation reached terminal state: $status." ;;
esac
finalize_progress "$status" "$terminal_summary" "$resumable" "$process_group_stopped"
latest_progress_seq="$(jq -r '.latestSeq // 0' "$progress_path")"

process_group_json=null
if [[ "$process_group_id" =~ ^[1-9][0-9]*$ ]]; then
  process_group_json="$process_group_id"
fi

receipt="$(jq -cn \
  --arg requestedModel "$requested_model" \
  --arg status "$status" \
  --arg action "$action" \
  --arg runId "$(basename "$run_dir")" \
  --arg runDir "$run_dir" \
  --arg resumedFromRunId "$resumed_from_run_id" \
  --arg threadId "$parsed_thread_id" \
  --arg cancellationSignal "$cancellation_signal" \
  --arg terminationReason "$termination_reason" \
  --arg finalMessagePath "$final_path" \
  --arg eventsPath "$events_path" \
  --arg stderrPath "$stderr_path" \
  --arg requestPath "$request_path" \
  --arg statusPath "$status_path" \
  --arg progressPath "$progress_path" \
  --arg progressEventsPath "$progress_events_path" \
  --arg supervisorPath "$supervisor_path" \
  --arg proxyMode "$proxy_mode" \
  --arg configMode "$config_mode" \
  --arg worktreeRoot "$worktree_root" \
  --argjson resumable "$resumable" \
  --argjson processGroupId "$process_group_json" \
  --argjson processGroupStopped "$process_group_stopped" \
  --argjson codexExit "$codex_exit" \
  --argjson durationSeconds "$duration_seconds" \
  --argjson turnCompleted "$turn_completed" \
  --argjson finalNonempty "$final_nonempty" \
  --argjson rawLines "$raw_lines" \
  --argjson invalidLines "$invalid_lines" \
  --argjson parsedEvents "$parsed_events" \
  --argjson eventBytes "$event_bytes" \
  --argjson finalBytes "$final_bytes" \
  --argjson latestSeq "$latest_progress_seq" \
  --argjson usage "$usage_json" \
  '{
    schemaVersion: 1,
    requestedModel: (if $requestedModel == "" then null else $requestedModel end),
    status: $status,
    state: $status,
    terminal: true,
    action: $action,
    runId: $runId,
    runDir: $runDir,
    resumedFromRunId: (if $resumedFromRunId == "" then null else $resumedFromRunId end),
    threadId: (if $threadId == "" then null else $threadId end),
    resumable: $resumable,
    processGroupId: $processGroupId,
    processGroupStopped: $processGroupStopped,
    proxy: {scope: "codex-child", mode: $proxyMode},
    configMode: $configMode,
    worktreeRoot: (if $worktreeRoot == "" then null else $worktreeRoot end),
    codexExit: $codexExit,
    signal: (if $cancellationSignal == "" then null else $cancellationSignal end),
    terminationReason: (if $terminationReason == "" then null else $terminationReason end),
    durationSeconds: $durationSeconds,
    turnCompleted: $turnCompleted,
    finalNonempty: $finalNonempty,
    rawLines: $rawLines,
    invalidLines: $invalidLines,
    parsedEvents: $parsedEvents,
    eventBytes: $eventBytes,
    finalBytes: $finalBytes,
    finalMessagePath: $finalMessagePath,
    eventsPath: $eventsPath,
    stderrPath: $stderrPath,
    requestPath: $requestPath,
    statusPath: $statusPath,
    progressPath: $progressPath,
    progressEventsPath: $progressEventsPath,
    supervisorPath: $supervisorPath,
    latestSeq: $latestSeq,
    usage: $usage
  }'
)"

status_tmp="$run_dir/.status.json.tmp.$$"
printf '%s\n' "$receipt" >"$status_tmp"
chmod 600 "$status_tmp"
mv -f "$status_tmp" "$status_path"
if [[ "$observe" == "true" ]]; then
  emit_observe_updates false
else
  emit_bounded_terminal_receipt "$receipt"
fi
exit "$receipt_exit"
