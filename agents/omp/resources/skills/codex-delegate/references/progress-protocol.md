# Codex Delegate Progress Protocol v1

Use this reference when implementing or consuming observable, asynchronous Codex delegations. The protocol is host-neutral; a Pi status bar is not part of it.

## Contents

1. Run lifecycle
2. Private artifacts
3. Normalized event schema
4. Snapshot schema
5. Control response schema
6. Cursor and polling rules
7. Reporting policy
8. CLI execution mappings
9. Safety and compatibility

## 1. Run lifecycle

An observable delegation has one stable `runId` and one private run directory. Its state is one of:

- `running`
- `completed`
- `incomplete`
- `failed`
- `failed_resumable`
- `resumable_timeout`
- `timed_out`
- `cancelled`
- `orphaned`
- `start_unknown` (startup-only, non-terminal)

`orphaned` means the recorded supervisor is gone and no terminal receipt exists. It is not success and must not be resumed until the prior process group is confirmed stopped.

A safe resume creates a new run and records `resumedFromRunId`. It always uses the explicit thread ID from the prior terminal receipt; it never selects an implicit last session.

## 2. Private artifacts

Each run keeps:

| File | Purpose |
| --- | --- |
| `.codex-delegate-run.json` | Ownership marker and run identity |
| `request.txt` | Delegated prompt |
| `events.jsonl` | Complete raw Codex JSONL |
| `final.md` | Final Codex message |
| `stderr.log` | Codex diagnostics |
| `progress.jsonl` | Normalized, append-only progress events |
| `progress.json` | Atomically replaced current snapshot |
| `supervisor.json` | Supervisor identity, readiness, and process group |
| `status.json` | Atomically replaced terminal receipt |

Run directories use mode `0700`; artifacts use mode `0600`. Raw JSONL, full diffs, raw command output, ordinary agent messages, raw error diagnostics, and reasoning remain private and are never copied into a progress response.

## 3. Normalized event schema

Every persisted event contains:

```json
{
  "schemaVersion": 1,
  "seq": 4,
  "runId": "run-Ab12Cd34",
  "timestamp": "2026-07-17T08:00:00Z",
  "timestampEpoch": 1784275200,
  "kind": "checkpoint",
  "state": "running",
  "phase": "implementing",
  "summary": "Investigation completed. Next: implementation.",
  "reportable": true,
  "sourceLine": 12,
  "milestones": {
    "completed": 1,
    "total": 3
  }
}
```

Event kinds:

- `started`
- `phase_changed`
- `checkpoint`
- `activity`
- `warning`
- `terminal`

Phases:

- `starting`
- `investigating`
- `planning`
- `implementing`
- `verifying`
- `finalizing`
- `waiting`
- `working`

Use `working` when the evidence does not justify a more specific phase. Only include milestone totals when Codex supplied an explicit finite plan. Do not invent percentages.

Checkpoint text is deny-by-default. Only a completed `agent_message` whose text begins exactly with `CODEX_PROGRESS:` is eligible. The payload must be single-line and is rejected when it resembles credentials, authorization headers, private keys, code fences, or diffs. Rejected checkpoints and raw failures become generic summaries; their original text remains only in `events.jsonl`/`stderr.log`.

## 4. Snapshot schema

`progress.json` contains:

```json
{
  "schemaVersion": 1,
  "runId": "run-Ab12Cd34",
  "runDir": "/private/state/run-Ab12Cd34",
  "state": "running",
  "phase": "verifying",
  "startedAt": 1784275200,
  "updatedAt": 1784275260,
  "lastActivityAt": 1784275255,
  "elapsedSeconds": 60,
  "lastActivityAgeSeconds": 5,
  "stale": false,
  "threadId": "thread-id",
  "resumable": false,
  "latestSeq": 8,
  "processGroupId": 1234,
  "processGroupStopped": false,
  "milestones": null,
  "lastSummary": "Verification command completed.",
  "artifacts": {
    "progressPath": "/private/state/run-Ab12Cd34/progress.json",
    "progressEventsPath": "/private/state/run-Ab12Cd34/progress.jsonl",
    "statusPath": "/private/state/run-Ab12Cd34/status.json",
    "eventsPath": "/private/state/run-Ab12Cd34/events.jsonl",
    "finalMessagePath": "/private/state/run-Ab12Cd34/final.md",
    "stderrPath": "/private/state/run-Ab12Cd34/stderr.log"
  }
}
```

A valid terminal `status.json` always supersedes an earlier running or stale snapshot.

## 5. Control response schema

CLI control commands and foreground observe records use the same compact JSON:

```json
{
  "schemaVersion": 1,
  "operation": "poll",
  "runId": "run-Ab12Cd34",
  "state": "running",
  "phase": "verifying",
  "terminal": false,
  "stale": false,
  "elapsedSeconds": 60,
  "lastActivityAgeSeconds": 5,
  "cursor": 8,
  "events": [],
  "nextCursor": 8,
  "hasMore": false,
  "report": {
    "recommended": true,
    "reason": "heartbeat",
    "text": "Codex is verifying; elapsed 60s; last activity 5s ago."
  },
  "nextPollAfterSeconds": 20
}
```

The default and minimum serialized response budget is 4096 bytes. When unread events exceed the budget, return only whole events, set `hasMore: true`, and return the last included sequence as `nextCursor`.

If repeated absolute artifact paths make the response envelope itself too large,
the runner switches to a complete compact envelope instead of cutting JSON. A
compact response sets `"compact": true` and keeps the normalized events, cursor,
report, liveness, and terminal fields. Its `artifacts` values are short filenames
with `"relativeToRunDir": true`; resolve them below the validated run directory
identified by the caller's state directory and `runId`. This fallback applies to
foreground observe records, blocking terminal receipts, detached startup,
`status`, `events`, `poll`, `wait`, `cancel`, startup failures, and prune output.
Full terminal data remains in `status.json`.

## 6. Cursor and polling rules

- Cursors are client-owned and are never consumed globally.
- Requesting events after `N` returns only events with `seq > N`.
- A heartbeat is ephemeral and does not advance the cursor.
- `poll` returns on a new event, terminal receipt, or bounded wait expiry.
- Poll waits are capped at 30 seconds.
- If `hasMore` is true, poll again immediately with `nextCursor`.
- Stop polling only after a terminal state or explicit user cancellation.

## 7. Reporting policy

The calling agent:

1. Acknowledges a successful asynchronous start and retains `runId` and cursor.
2. Reports phase changes, checkpoints, warnings, blocked states, and terminal states immediately.
3. Reports no more than one unchanged heartbeat per 60 seconds.
4. Suppresses duplicate and low-value activity.
5. Never exposes raw reasoning, full diffs, full command output, or raw JSONL.
6. Reads the terminal receipt and final artifact before claiming completion.

Codex checkpoints are semantic, not timer-based. A checkpoint states the completed phase, observable outcome, and next phase. Do not split one task into new turns merely because time elapsed.

## 8. CLI execution mappings

| Lifecycle | Start | Resume | Progress |
| --- | --- | --- | --- |
| Foreground observable | `start --observe` | `resume --run-id ... --observe` | One bounded JSON object per stdout line |
| Detached | `start --detach` | `resume --run-id ... --detach` | `poll --run-id ... --after ...` |
| Blocking compatibility | `start` | `resume --thread-id ...` | Terminal receipt only |

Both observable lifecycles use the same runner-owned state and normalized cursor. `status`, `events`, `wait`, `cancel`, and `prune` are CLI-only control operations.

A dedicated controller agent/task is preferred when the host can run it in the background and deliver intermediate messages. The controller owns the foreground observe session and reporting cadence, not a second state model. It does not perform the delegated work or create timer-driven Codex turns.

Agent tools that kill every descendant when a shell call returns must keep `--observe` in a resumable foreground execution session. Detached mode is valid only when the host is known to preserve background children. A host that buffers foreground output and kills descendants cannot guarantee intermediate visibility.

## 9. Safety and compatibility

- Accept control targets by validated run ID, never an arbitrary path.
- Require a direct child of the selected state directory, a valid ownership marker, and no symlink.
- Apply the same direct-child valid-`run-*` rule to caller-provided `--run-dir` in foreground and detached modes.
- Validate the recorded supervisor identity before signaling it.
- Preserve full process-group termination and cancellation receipts.
- Resume only when `resumable` and `processGroupStopped` are both true.
- Use a direct Codex child connection by default. When explicitly configured, inject only the
  credential-free `CODEX_DELEGATE_PROXY_URL` origin into the Codex child environment and never
  include its value in receipts or stdout.
- Never export or persist proxy variables for the caller, terminal, controller task, or supervisor host.
- Pass `--ignore-user-config` by default and record `configMode: isolated`; use `--inherit-user-config` only as an explicit compatibility override.
- Require `--allow-workspace-write` plus an existing linked-worktree `--worktree-root` whose canonical root contains the start `cwd`.
- Treat `start_unknown` as possible live-writer state: retain the run ID, inspect it, and do not retry blindly.
- Keep blocking foreground CLI available for deliberately short tasks, but do not promise intermediate visibility for those calls.
- Target Linux and require Bash, `jq`, util-linux `setsid`, `/proc`, and `codex`; do not require Node, npm, an SDK, or an MCP server.
- Keep prune preview-first and reject active, external, unmarked, symlinked, and non-terminal runs.
