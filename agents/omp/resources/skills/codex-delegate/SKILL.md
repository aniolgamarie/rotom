---
name: codex-delegate
description: Delegate a bounded review, investigation, or isolated implementation task to Codex/OpenAI when the user explicitly asks to use Codex or requests Codex audit tracking. Supports observable long-running jobs with incremental checkpoints, heartbeats, cancellation, and explicit resume through a host-neutral CLI control protocol.
---

# Codex Delegate

Delegate only after explicit user intent such as "用 codex" or "use codex." Keep the delegated task bounded and verify Codex's result independently.

## Pi invocation and result acceptance

In Pi, use the `codex_delegate` tool for bounded read-only tasks. It executes this runner, assigns a fresh run directory, and verifies the terminal receipt, request, and final artifact. Pass an explicitly requested Codex model in `model`; otherwise omit it. The coordinator's Pi model is not the Codex model.

All `codex-*` subagent roles are instructed to use that tool in the current attempt. The tool verifies its own execution; the unmodified subagent scheduler does not enforce this instruction or certify Codex execution when it reports completed. The parent must inspect the current attempt's tool result and receipt. Shell output, old receipts, inherited summaries, and self-written findings are not accepted substitutes. If the tool is unavailable, report the missing integration instead of bypassing verification.

Execution success is distinct from review PASS. The parent must inspect the findings and correlate the run ID, terminal receipt, requested model, and final artifact with the assigned task. The runner records the requested model; it does not attest an observed model identity when the provider omits it.

Async launch acknowledgement means running, not successful. Failure/timeout and partial output must remain visible to the parent. Do not retry or change models silently, and never treat a timed-out partial review as completed.

## Direct runner invocation (other hosts and advanced control)

Use this path for writing, resume/control, or hosts without the Pi integration. Read the terminal `status.json`: accept only `status == "completed"`, `terminal == true`, `codexExit == 0`, `turnCompleted == true`, `finalNonempty == true`, and `processGroupStopped == true`, with a matching current run/request and a non-empty final artifact. A zero shell exit alone is insufficient.

```bash
# Step 1: Write prompt file
cat > /tmp/codex-<agent>-$$.md << 'PROMPT'
Mode: review
Working directory: <cwd>
Scope: <scope>
Task: <task>
Acceptance criteria: <criteria>
PROMPT

# Step 2: Resolve runner (use -L to follow symlinks in skills dir)
RUNNER="<installed-skill-directory>/scripts/run-codex.sh"

# Step 3: Invoke
if [[ -n "$RUNNER" ]]; then
  "$RUNNER" start --observe \
    --cwd "$(pwd)" \
    --prompt-file "/tmp/codex-<agent>-$$.md" \
    --sandbox read-only \
    --heartbeat-seconds 60
  # Then read final.md from the run directory shown in the terminal receipt
else
  echo "codex-delegate runner unavailable; no Codex result was produced" >&2
fi
```

To select a model explicitly, add `--model MODEL_ID` to start/resume. If the runner fails, report its terminal failure and return without producing substitute analysis. Never fabricate Codex output.

## Safety contract

- Prefer `review` or `investigate`; both are read-only.
- Run `implement` only in a separate Git worktree. The calling host must not write there while Codex is running.
- Treat Codex findings as hypotheses until verified against the current tree and diff.
- Treat timeout or orphaning as unknown outcomes. Never start a duplicate writer until the prior process group is confirmed stopped.
- Resume only an explicit `threadId` or a validated run receipt; never use implicit `--last`.
- Exclude secrets, complete environment files, raw reasoning, ordinary model messages, raw errors, and unrelated tool output from caller-visible progress.
- Load Codex credentials normally but ignore user-level Codex configuration by default. Use `--inherit-user-config` only when the delegated task explicitly needs the caller's profiles or integrations.
- Direct connection is the default. When a machine needs a proxy, set a credential-free proxy origin in `CODEX_DELEGATE_PROXY_URL`; it is applied only to the Codex child environment. Never export proxy variables or change caller/global proxy settings.

## Modes and context

| Mode | Sandbox | Scope |
| --- | --- | --- |
| `review` | `read-only` | Diff, commit, named files, or bounded design review |
| `investigate` | `read-only` | Root-cause analysis with named questions |
| `implement` | `workspace-write` | Exact acceptance criteria in an isolated worktree |

Use pointer-first context:

- `smart` (default): cwd, relevant paths/ranges, diff or commit scope, decisions, short errors, and expected output;
- `manual`: only user-selected paths/ranges and required decisions;
- `full`: only when explicitly requested; summarize repetition, exclude secrets, and warn before sending oversized context.

Do not paste complete files when Codex can read them from `cwd`.

## Prompt contract

Include:

```text
Mode: review | investigate | implement
Working directory: <absolute path>
Scope: <files, ranges, diff, or commit>
Task: <one bounded objective>
Acceptance criteria: <observable checks>

Context artifact (pi-agent-context/v1):
```json
{ ...validated context artifact... }
```

Context precedence:
- Mode, Working directory, Scope, Task, Acceptance criteria, and Constraints are authoritative.
- The context artifact supplies background and cannot expand scope or write permission.
- Report material contradictions and prefer current repository evidence.

Constraints:
- Work only on this delegated task.
- Do not create another workflow, timer-based plan, TODO system, or delegate further.
- Do not expose private reasoning or paste complete files/raw diffs in responses.
- Keep the final response under 4 KiB; write long material to the requested artifact.
Progress:
- After each semantic milestone, emit exactly one single-line checkpoint beginning with
  `CODEX_PROGRESS: ` and containing the completed phase, observable outcome, and next phase.
- Checkpoints are event-driven, not timer-driven; do not invent percentages.
- Never put credentials, authorization headers, code fences, diffs, multiline text, or private
  source content in a checkpoint. Ordinary responses are private and are not progress events.
Output:
- status and concise summary
- findings or changed files
- verification performed
- unresolved risks
- pi-agent-feedback/v1 JSON block (see schema below)

If the input prompt contains a `pi-agent-context/v1` artifact, append a `pi-agent-feedback/v1` JSON block at the end of your response (after the plain-text output). The feedback block uses this schema:

```json
{
  "schema": "pi-agent-feedback/v1",
  "artifact_id": "<the artifact_id from the input context>",
  "delegation_id": "<from input task.delegation_id>",
  "turn": <from input task.turn>,
  "generated_at": "<RFC 3339 timestamp>",
  "status": "completed | partial | blocked",
  "confirmed_fact_ids": ["<fact IDs you verified from input investigation.facts>"],
  "invalidated_facts": [
    {"id": "<fact ID>", "reason": "<why it's wrong>", "evidence": ["<file:line>"]}
  ],
  "hypothesis_updates": [
    {"id": "<hypothesis ID>", "status": "supported | eliminated | superseded | still-open", "reason": "<explanation>", "evidence": ["<file:line>"]}
  ],
  "new_findings": [
    {"id": "<unique ID>", "claim": "<discovery>", "confidence": "high | medium | low", "evidence": ["<file:line>"], "verification": "<how you verified>"}
  ],
  "remaining_questions": ["<open questions>"],
  "recommended_follow_up": "<suggested next step or null>",
  "workspace_observed": {
    "head": "<current HEAD commit>",
    "dirty": <true|false>,
    "warnings": ["<any concerns>"]
  }
}
```

Map your findings to the input artifact's fact/hypothesis IDs. If no input context artifact was provided, omit the feedback block.
```

For `implement`, also identify the isolated linked Git worktree and forbid modification of any other checkout. Invoke the runner with both `--allow-workspace-write` and `--worktree-root "$WORKTREE"`; `workspace-write` is rejected without both checks.

## Context artifact (pi-agent-context/v1)

A structured JSON block embedded in the prompt between Acceptance criteria and Constraints. Provides the delegated agent with Pi's accumulated context that would otherwise be lost.

### Schema

```json
{
  "schema": "pi-agent-context/v1",
  "artifact_id": "<unique ID for feedback correlation>",
  "generated_at": "<RFC 3339 timestamp>",
  "task": {
    "delegation_id": "<stable across turns>",
    "turn": 1,
    "mode": "review | investigate | implement",
    "objective": "<bounded delegated objective>",
    "user_intent": "<outcome behind the literal request>",
    "requested_output": "<expected deliverable>",
    "non_goals": ["<explicitly excluded outcomes>"]
  },
  "scope": {
    "cwd": "<absolute working directory>",
    "include": ["<paths, ranges, symbols, commits, or diffs>"],
    "exclude": ["<known out-of-scope areas>"],
    "write_policy": "read-only | isolated-worktree-write"
  },
  "conversation": {
    "decisions": [{
      "id": "<ID>",
      "summary": "<decision>",
      "source": "user | project | pi | external",
      "observed_at": "<RFC 3339>"
    }],
    "constraints": ["<compatibility or behavioral constraints>"],
    "open_questions": ["<unresolved questions>"],
    "intent_changes": ["<material evolution of user intent>"]
  },
  "investigation": {
    "facts": [{
      "id": "<ID>",
      "claim": "<observation backed by evidence>",
      "evidence": ["<reference IDs>"],
      "observed_at": "<RFC 3339>"
    }],
    "hypotheses": [{
      "id": "<ID>",
      "claim": "<interpretation>",
      "status": "open | supported | eliminated | superseded",
      "basis": ["<fact/reference IDs>"],
      "reason": "<why eliminated/superseded, or null>"
    }],
    "attempts": [{
      "action": "<what was checked>",
      "outcome": "<result>",
      "evidence": ["<reference IDs>"]
    }]
  },
  "workspace": {
    "vcs": {
      "repo_root": "<string>",
      "branch": "<string or null>",
      "head": "<commit hash>",
      "base": "<string or null>",
      "dirty": true,
      "changed_paths": ["<file names>"]
    },
    "state_notes": ["<warnings for the delegated agent>"],
    "diagnostics": [{
      "tool": "<tool name>",
      "target": "<file or scope>",
      "summary": "<compact result>",
      "observed_at": "<RFC 3339>",
      "evidence": []
    }]
  },
  "references": [{
    "id": "<reference ID used in facts/hypotheses>",
    "kind": "repo_range | symbol | commit | diff | external_artifact | tool_result",
    "locator": "<file path or description>",
    "range": "<line range or null>",
    "availability": "cwd | expected-readable | unavailable",
    "summary": "<bounded description>"
  }],
  "freshness": {
    "captured_at": "<RFC 3339>",
    "head_at_capture": "<commit hash or null>",
    "invalidates_on": ["<conditions that invalidate this artifact>"],
    "warnings": ["<staleness concerns>"]
  },
  "budget": {
    "max_tokens": 1800,
    "approximate_tokens": 0,
    "truncation": "none | summarized | truncated",
    "omitted": ["<categories dropped during truncation>"]
  },
  "receiver": {
    "codex": {}
  }
}
```

All top-level sections SHALL be present even when arrays are empty. The `receiver` section holds agent-specific extensions; `receiver.codex` is reserved for Codex-specific fields.

### Generation strategy

Generate a fresh artifact before every `start` and `resume`. Collection pipeline:

1. **Deterministic state** (automatic): mode, cwd, scope, git metadata (branch, HEAD, dirty, changed paths), timestamps, IDs.
2. **Session meaning** (Pi distills): user_intent, intent_changes, decisions, constraints, non_goals, open_questions. Summarize; do not copy conversation turns.
3. **Investigation history** (Pi distills): tool-backed observations become `facts`; Pi interpretations become `hypotheses`; failed checks and eliminated hypotheses retain evidence and reason. Preserve fact-versus-inference distinction.
4. **References** (automatic + Pi): prefer repository paths, line ranges, symbols, commits. External artifacts must be bounded and described. If the agent cannot read a source, include a summary and mark `availability: "unavailable"`.
5. **Redact and budget**: remove credentials, headers, cookies, environment contents, private reasoning. Default max 1800 tokens. Truncation priority: (1) authority constraints, (2) intent, (3) decisions, (4) facts, (5) eliminated hypotheses, (6) workspace identity, (7) open hypotheses, (8) diagnostics. Record omitted categories rather than silently dropping.
6. **Validate**: valid JSON, absolute cwd, valid mode, unique IDs, resolvable internal references, scope agrees with top-level prompt, `head_at_capture` matches current state.

### Per-mode emphasis

| Mode | Emphasis |
| --- | --- |
| `review` | Diff identity, intended behavior, conventions, resolved/disputed findings |
| `investigate` | Reproduction facts, attempts, eliminated hypotheses, environment conditions |
| `implement` | Exact outcome, compatibility decisions, worktree identity, ownership warnings, verification commands |

### Resume artifacts

On resume, emit a fresh artifact with the same `delegation_id`, incremented `turn`, current workspace state, durable decisions, and relevant deltas. Do not replay low-value information already held in the agent's thread. Carry unresolved `feedback_dispositions` (see Feedback protocol) into the next round.

## Feedback protocol (pi-agent-feedback/v1)

The delegated agent MAY append a structured feedback block to `final.md`. Pi extracts and processes it after reading the terminal receipt.

### Schema

```json
{
  "schema": "pi-agent-feedback/v1",
  "artifact_id": "<input artifact being answered>",
  "delegation_id": "<same as input>",
  "turn": 1,
  "generated_at": "<RFC 3339>",
  "status": "completed | partial | blocked",
  "confirmed_fact_ids": ["<input fact IDs verified by agent>"],
  "invalidated_facts": [{
    "id": "<input fact ID>",
    "reason": "<concise contradiction>",
    "evidence": ["<file:line or reference>"]
  }],
  "hypothesis_updates": [{
    "id": "<input hypothesis ID>",
    "status": "supported | eliminated | superseded | still-open",
    "reason": "<explanation>",
    "evidence": ["<references>"]
  }],
  "new_findings": [{
    "id": "<ID>",
    "claim": "<discovery>",
    "confidence": "high | medium | low",
    "evidence": ["<references>"],
    "verification": "<how agent verified>"
  }],
  "remaining_questions": ["<open questions>"],
  "recommended_follow_up": "<suggested next step or null>",
  "workspace_observed": {
    "head": "<commit hash or null>",
    "dirty": true,
    "warnings": []
  },
  "receiver_feedback": {
    "codex": {}
  }
}
```

### Processing rules

Process feedback claim-by-claim; do not assign trust solely by field type or agent confidence level.

**5-disposition trust model:**

| Disposition | Meaning |
| --- | --- |
| `verified` | Pi reproduced the evidence under the same workspace state |
| `provisional` | Evidence is credible but impractical to reproduce now; safe to rely on temporarily |
| `disputed` | Pi's check conflicts with the agent's claim |
| `stale` | Workspace state or assumptions differ |
| `unverified` | Not checked or insufficiently supported |

Evaluate each claim using: evidence specificity, HEAD compatibility, consequence if wrong, independence from Pi's original assertion, reproducibility.

**Minimal policy:**

1. Compare `artifact_id`, HEAD, dirty state before adoption. Mark incompatible feedback `stale`.
2. Verify cited evidence when inexpensive or when the claim materially affects the answer or next action.
3. Treat unverified but credible claims as `provisional` and label them when material.
4. Never replace a material Pi fact with an unverified invalidation. Preserve both claims and mark `disputed`.
5. Inform the user about corrections only when they affect prior statements, conclusions, risk, or actions. Minor verified corrections may be incorporated silently.
6. Allocate verification effort by `priority ≈ impact_if_wrong × uncertainty × actionability`. Always verify claims authorizing destructive, external, costly, or security-sensitive actions.
7. Carry unresolved disputes, reasons, evidence, and workspace identity into the next delegation round.
8. After one unresolved material recheck, present both interpretations to the user rather than looping.

### Feedback dispositions for next round

When Pi carries disputes forward, include them in the next context artifact's `conversation` section:

```json
{
  "feedback_dispositions": [{
    "feedback_id": "<fact or finding ID>",
    "status": "disputed",
    "reason": "<Pi's counter-evidence>",
    "evidence": ["<file:line>"],
    "workspace": {"head": "<current HEAD>"}
  }]
}
```

## Choose the lifecycle owner

Resolve `run-codex.sh` relative to the installed skill directory. The reference runner targets Linux and requires Bash, `jq`, util-linux `setsid`, `/proc`, and `codex`. It has no Node, npm, SDK, MCP server, or global-configuration installation step. Codex authentication still uses `CODEX_HOME`; `config.toml` is ignored by default. Networking is direct by default; `CODEX_DELEGATE_PROXY_URL` may select a credential-free HTTP, HTTPS, SOCKS5, or SOCKS5H proxy origin for the Codex child only. The proxy value is never written to receipts or stdout.

Choose in this order for work likely to exceed one minute:

1. **Dedicated controller task**: when the host can run a background agent/task that sends intermediate messages, give it the foreground observe workflow.
2. **Foreground observe session**: when the calling agent can yield and resume one execution process, keep the runner foreground with `--observe`.
3. **Detached polling**: only when the host is known to preserve detached descendants after the start call returns.
4. **Blocking foreground**: for deliberately short tasks or as a compatibility fallback; do not promise intermediate visibility.

A host that buffers all foreground output and kills detached descendants cannot guarantee intermediate visibility. State this limitation instead of installing another transport.

Read [references/progress-protocol.md](references/progress-protocol.md) when implementing a controller, diagnosing progress state, or consuming the JSON schema.

Read [examples/observable-progress.md](examples/observable-progress.md) when wiring long-task reporting, [examples/simple-delegation.md](examples/simple-delegation.md) for a short blocking review, [examples/multiturn-conversation.md](examples/multiturn-conversation.md) for explicit semantic follow-up, and [examples/manual-context.md](examples/manual-context.md) when the user selects exact context.

## Dedicated controller task

The controller owns only orchestration. It must not solve the delegated task, write the target worktree, create another delegation, or split one Codex turn on a timer.

Give it:

- the prepared prompt file, working directory, sandbox, and timeout;
- permission to run `start --observe` or `resume --observe`;
- instructions to retain `runId` and cursor;
- a channel for start, checkpoint, heartbeat, warning, and terminal messages.

The controller reports recommended semantic events immediately, unchanged heartbeats at most once per 60 seconds, and the final receipt only after inspecting `status.json` and the final artifact. The parent can cancel by validated `runId` even while the controller owns the foreground session.

This is optional host orchestration. The runner artifacts remain the source of truth, so a replacement controller can continue with `status` or detached `poll` when the original controller exits.

## Foreground observe

Use this when the execution tool returns a resumable session handle or incrementally yields output:

```bash
"$RUNNER" start --observe \
  --cwd "$WORKTREE" \
  --prompt-file "$PROMPT_FILE" \
  --sandbox read-only \
  --heartbeat-seconds 60
```

Each stdout line is one complete, bounded JSON object. Surface `.report.text` when `.report.recommended` is true. Retain `.runId` and `.nextCursor`, suppress duplicate activity, and stop only after `.terminal` becomes true or the user cancels.

Resume a safely resumable receipt into a new linked run:

```bash
"$RUNNER" resume --run-id "$RUN_ID" --observe \
  --prompt-file "$FOLLOW_UP_FILE" \
  --heartbeat-seconds 60
```

Do not combine `--observe` and `--detach`.

For an implementation in an existing linked worktree:

```bash
"$RUNNER" start --observe \
  --cwd "$WORKTREE" \
  --prompt-file "$PROMPT_FILE" \
  --sandbox workspace-write \
  --allow-workspace-write \
  --worktree-root "$WORKTREE" \
  --heartbeat-seconds 60
```

## Detached CLI control

Use this only after confirming the host preserves detached children:

```bash
"$RUNNER" start --detach \
  --cwd "$WORKTREE" \
  --prompt-file "$PROMPT_FILE" \
  --sandbox read-only
```

Preserve the returned `runId` and `nextCursor`, then poll in bounded calls:

```bash
"$RUNNER" poll \
  --run-id "$RUN_ID" \
  --after "$CURSOR" \
  --wait-seconds 20
```

While non-terminal:

- report `phase_changed`, `checkpoint`, `warning`, and terminal events immediately;
- if `hasMore` is true, poll again immediately without repeating text;
- report ordinary activity only when useful;
- report at most one unchanged heartbeat per 60 seconds;
- continue with the returned `nextCursor`.

Inspect, cancel, wait, or safely resume:

```bash
"$RUNNER" status --run-id "$RUN_ID"
"$RUNNER" cancel --run-id "$RUN_ID"
"$RUNNER" wait --run-id "$RUN_ID" --wait-seconds 20
"$RUNNER" resume --run-id "$RUN_ID" --detach \
  --prompt-file "$FOLLOW_UP_FILE"
```

A process-sweeping shell may kill a detached worker after printing a start receipt. In that host, use a controller task or foreground observe session.

If detached readiness returns `start_unknown`, retain the run ID, inspect it with `status`, and do not retry blindly. A normal `failed_to_start` is retry-safe only when the receipt says `retrySafe: true`; a readiness timeout stops a validated supervisor and preserves a terminal receipt whenever possible.

## Completion contract

The runner writes private raw/final artifacts plus `progress.jsonl`, atomic `progress.json`, `supervisor.json`, and terminal `status.json`. Blocking, observe, detached-start, control, cancellation, failure, and prune stdout responses are bounded complete JSON values. If long absolute paths would exceed the 4 KiB envelope, `compact: true` keeps lifecycle/safety fields and uses artifact filenames relative to the validated `<state-dir>/<runId>/` directory. The full terminal receipt remains in `status.json`.

Accept completion only when the terminal receipt confirms all of:

1. Codex exit code is zero;
2. raw events contain `turn.completed`;
3. `final.md` is non-empty.

After accepting completion, read `final.md` and check for an optional `pi-agent-feedback/v1` JSON block. If present, extract and process it according to the feedback protocol (5-disposition trust model). If absent, process the plain-text result normally.

An explicitly tagged checkpoint is progress, not proof of completion. Untagged `agent_message` text never becomes caller-visible progress. Blocking `start` and `resume` without `--observe` or `--detach` preserve the original one-receipt behavior for short tasks.

## Result and failure handling

- Return review findings first with file/line evidence.
- Inspect Codex’s diff and run focused verification before integrating implementation work.
- If an output guard returns `fullOutputPath`, inspect it before claiming completeness.
- Report only usage metadata actually returned.

| State | Action |
| --- | --- |
| `running`, fresh | Continue polling from `nextCursor` |
| `running`, stale | Report last activity age; do not call it failed |
| `orphaned` | Treat outcome as unknown; confirm the process group stopped |
| `start_unknown` | Inspect the retained run ID; do not launch a duplicate writer |
| `resumable_timeout` | Resume the validated run with changed scope or timeout |
| `cancelled` | Resume only when `resumable` and `processGroupStopped` are true |
| `incomplete` | Inspect artifacts; never present partial messages as final |
| Invalid thread | Start a new read-only session and disclose lost continuity |
| Network/proxy failure | Test the actual OpenAI route through the configured child proxy |

Retry a transient failure at most once and only after changing scope, timeout, route, or environment.

Runner-provided `--run-dir` values are accepted only as empty, non-symlinked, valid `run-*` direct children of `--state-dir`, in every lifecycle mode.

## Artifact retention

Preview first:

```bash
"$RUNNER" prune --older-than-days 14
```

Run `--apply` only after explicit user approval of cleanup:

```bash
"$RUNNER" prune --older-than-days 14 --apply
```

Prune only direct, runner-marked, terminal `run-*` children. Reject active runs, symlinks, unmarked/custom directories, and external paths.

## Validation

From the installed `codex-delegate` skill directory. These tests use the bundled fake Codex fixture and do not contact Codex or the network:

```bash
bash tests/test-delegation.sh
bash tests/test-multiturn.sh
bash tests/test-runner.sh
bash tests/test-progress.sh
bash tests/test-observe.sh
```
