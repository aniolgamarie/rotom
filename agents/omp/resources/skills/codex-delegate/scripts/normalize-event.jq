def bounded($limit):
  tostring
  | gsub("[[:cntrl:]]"; " ")
  | gsub("  +"; " ")
  | if length > $limit then .[0:$limit] + "…" else . end;

def checkpoint_payload:
  if type == "string" and startswith("CODEX_PROGRESS:") then
    ltrimstr("CODEX_PROGRESS:")
    | sub("^ +"; "")
  else
    null
  end;

def unsafe_checkpoint:
  . as $original
  | ascii_downcase as $lower
  | ($original | test("[[:cntrl:]]"))
    or ($original | test("```|^diff --git |^--- |^\\+\\+\\+ "))
    or ($lower | test("authorization[[:space:]]*:|bearer[[:space:]]+[a-z0-9._~+/-]+"))
    or ($lower | test("(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|token)[[:space:]]*[:=]"))
    or ($original | test("(^|[^[:alnum:]_])sk-[A-Za-z0-9_-]{8,}"))
    or ($original | test("AKIA[0-9A-Z]{16}"))
    or ($lower | test("-----begin ([a-z0-9 ]+ )?private key-----"));

def item_type:
  (.item.type // "");

def plan_items:
  if (.item.plan | type) == "array" then .item.plan
  elif (.item.items | type) == "array" then .item.items
  else []
  end;

def milestone_summary:
  plan_items as $plan
  | ($plan | length) as $total
  | ($plan | map(select((.status // "") | IN("completed", "done"))) | length) as $completed
  | {
      completed: $completed,
      total: $total
    };

def is_test_command:
  ((.item.command // "") | ascii_downcase)
  | test("(^|[ /_-])(test|tests|pytest|busted|rspec|jest|vitest|cargo test|go test|npm test|pnpm test|yarn test|make test)([ /_-]|$)");

def normalize_event:
if .type == "thread.started" then
  {
    kind: "phase_changed",
    phase: "starting",
    summary: "Codex thread started.",
    threadId: (.thread_id // null),
    activity: true
  }
elif .type == "turn.started" then
  {
    kind: "activity",
    phase: "working",
    summary: "Codex turn started.",
    activity: true
  }
elif .type == "turn.completed" then
  {
    kind: "phase_changed",
    phase: "finalizing",
    summary: "Codex turn completed; final receipt is being verified.",
    usage: (.usage // null),
    turnCompleted: true,
    activity: true
  }
elif .type == "turn.failed" then
  {
    kind: "warning",
    phase: "finalizing",
    summary: "Codex turn failed; private diagnostics are available in the run artifacts.",
    turnFailed: true,
    activity: true
  }
elif .type == "error" then
  {
    kind: "warning",
    summary: "Codex reported an error; private diagnostics are available in the run artifacts.",
    activity: true
  }
elif .type == "item.completed" and item_type == "agent_message" then
  ((.item.text // "") | checkpoint_payload) as $checkpoint
  | if $checkpoint == null then
      {
        kind: null,
        summary: "Codex produced a private agent message.",
        activity: true,
        privateMessageExcluded: true
      }
    elif ($checkpoint | length) == 0 or ($checkpoint | unsafe_checkpoint) then
      {
        kind: "checkpoint",
        summary: "Codex reported a checkpoint; details remain in private artifacts.",
        activity: true,
        checkpointRejected: true
      }
    else
      {
        kind: "checkpoint",
        summary: ($checkpoint | bounded(320)),
        activity: true
      }
    end
elif .type == "item.started" and item_type == "agent_message" then
  {
    kind: null,
    summary: "Codex is preparing a private agent message.",
    activity: true,
    privateMessageExcluded: true
  }
elif (.type | IN("item.started", "item.completed")) and (item_type | IN("plan", "plan_update")) then
  milestone_summary as $milestones
  | {
      kind: "phase_changed",
      phase: (if $milestones.total > 0 and $milestones.completed == $milestones.total then "working" else "planning" end),
      summary: (
        if $milestones.total > 0 then
          "Codex plan updated: \($milestones.completed)/\($milestones.total) milestones complete."
        else
          "Codex updated its plan."
        end
      ),
      milestones: (if $milestones.total > 0 then $milestones else null end),
      activity: true
    }
elif (.type | IN("item.started", "item.completed")) and item_type == "command_execution" then
  {
    kind: "activity",
    phase: (if is_test_command then "verifying" else "working" end),
    summary: (
      if .type == "item.started" then
        (if is_test_command then "Verification command started." else "Command execution started." end)
      else
        (if is_test_command then "Verification command completed." else "Command execution completed." end)
      end
    ),
    activity: true
  }
elif (.type | IN("item.started", "item.completed")) and item_type == "file_change" then
  {
    kind: "phase_changed",
    phase: "implementing",
    summary: (if .type == "item.started" then "Codex started applying file changes." else "Codex completed a file-change step." end),
    activity: true
  }
elif (.type | IN("item.started", "item.completed"))
  and (item_type | IN("mcp_tool_call", "mcpToolCall", "dynamic_tool_call", "web_search", "webSearch")) then
  {
    kind: "activity",
    phase: "investigating",
    summary: "Codex is gathering external or tool-provided evidence.",
    activity: true
  }
elif (.type | IN("item.started", "item.completed")) and item_type == "reasoning" then
  {
    kind: null,
    summary: "Codex is working.",
    activity: true,
    reasoningExcluded: true
  }
else
  {
    kind: null,
    summary: "Codex emitted an unclassified event.",
    activity: true
  }
end;

if type == "string" then
  split("\n")
  | if length > 0 and .[-1] == "" then .[:-1] else . end
  | to_entries
  | map(
      . as $entry
      | (try ($entry.value | fromjson) catch null) as $event
      | (
          if $event == null then
            {
              kind: "warning",
              summary: "Codex emitted a malformed JSONL event; raw data was preserved.",
              activity: true
            }
          else
            ($event | normalize_event)
          end
        )
      + {sourceLine: ($offset + $entry.key + 1)}
    )
else
  normalize_event
end
