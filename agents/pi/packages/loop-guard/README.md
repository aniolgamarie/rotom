# starter-pi-loop-guard

Local Pi package that places a deterministic, fail-closed execution bound around repeated tool calls. Response similarity and short action cycles are retained as bounded diagnostics, but are observe-only by default.

## Safety contract

The guard scopes exact action counts to a real user task. An exact action includes the tool name, all canonical arguments, and the effective working directory. The shipped quota is two executions:

| State | Exact action request | Result |
| --- | --- | --- |
| Ready | First request | Execute and record attempt 1 |
| Seen once | Second request | Execute and record attempt 2 |
| Quota exhausted | Third request | Block before execution; leave one recovery turn |
| Block challenged | Same action requested again | Block, terminate, and latch the task |
| Latched | Any later tool request | Block and terminate without execution |
| Internal uncertainty | Guard, checkpoint, or blocking UI path fails | Fail closed with a terminal block |

After the third request is blocked, a genuinely different action still has its own quota, but it does not clear the original challenge. The quota-block result names the stable session-local `action:<digest>`, explains that the challenge lasts for the task epoch, and warns that requesting that action again terminates the task.

The exact quota is not reset by success, failure, changed output, timestamps, assistant text, tool output, compaction, or extension-generated messages. Only accepted `interactive` or `rpc` input, a new session, or an explicit `/loop-guard reset` opens a fresh task epoch.

## Session recovery

Recovery state is stored as versioned Pi custom entries. Custom entries are excluded from model context. Only task-boundary, quota-block, terminal-latch, internal-failure, reset, and incompatible-state transitions are checkpointed; ordinary allowed calls do not add session entries.

Reload, resume, fork, and session-tree navigation restore the latest compatible checkpoint on the active branch. Ordinary allowed executions after that checkpoint are reconstructed from correlated session tool-call/result entries, so reloading after two executions cannot reset the quota. Missing or contradictory replay evidence fails closed. A fork inherits the checkpoint and digest scope of its ancestor. Malformed or newer checkpoint schemas produce a visible compatibility latch instead of silently clearing safety state.

Persisted records contain reason codes, counters, task epochs, incident IDs, and session-scoped digests. They do not contain raw prompts, assistant text, tool arguments, output, credentials, or unredacted paths. Terminal checkpoints double as the durable diagnostic source: TUI renders them as expandable cards, RPC exposes them as structured `entry_appended` events, and they remain excluded from model context.

## Incident attribution and terminal reports

Quota, terminal, status, and explanation surfaces use one canonical session-local action reference:

```text
action:0123456789abcdef01234567
```

The reference permits correlation inside the current session without storing or displaying the raw command, arguments, working directory, or output.

### Two diagnostic layers

LoopGuard provides two levels of diagnostic output, each with a different audience and information scope:

**1. Direct output (model-visible tool result)**

When a tool call is blocked or terminated, the model receives a concise reason string:

```text
LoopGuard [exact-quota-exhausted]: action:5da27e4e08ee35c03ec5f6da already executed 2 times in task epoch 10. It remains blocked until trusted interactive/RPC input or /loop-guard reset opens a new epoch; different actions do not clear this challenge. Requesting it again will terminate the current task. Incident: lg-10-325-quota-block.
```

This output contains:
- Reason code (`exact-quota-exhausted`, `block-defiance`, `task-latched`, etc.)
- Action reference (`action:<24-hex-digest>`)
- Execution count
- Task epoch
- Incident ID

It intentionally **excludes** the tool name and raw command text. This is a design decision: the direct output is the model-facing contract, and including tool names or command previews would require either raw value exposure (privacy risk) or regex-based redaction (unreliable for arbitrary shell text). The action digest is sufficient for the model to understand that a specific action is blocked.

**2. `/loop-guard explain` (operator-facing full diagnosis)**

For human operators who need to understand *which* tool and *what* happened, use the explain command:

```text
$ /loop-guard explain lg-10-325-quota-block

Loop guard incident explanation
incident: lg-10-325-quota-block
reason: exact-quota-exhausted
task epoch: 10
action: action:5da27e4e08ee35c03ec5f6da
executions: 2
result evidence: stable
status: complete
timeline:
- branch#123 matching-execution tool=bash action:5da27e4e08ee35c03ec5f6da result=stable input={command:string(length=120,lines=1)}
- branch#124 matching-execution tool=bash action:5da27e4e08ee35c03ec5f6da result=stable input={command:string(length=120,lines=1)}
- branch#125 quota-block tool=bash action:5da27e4e08ee35c03ec5f6da input={command:string(length=120,lines=1)}
- branch#126 intervening-action tool=read action:abc123def456 result=stable input={path:string(length=45)}
- branch#127 terminal-defiance tool=bash action:5da27e4e08ee35c03ec5f6da input={command:string(length=120,lines=1)}
scanned entries: 50
```

The explain output includes:
- **Tool name** (`tool=bash`, `tool=read`, etc.)
- **Timeline** with branch ordinals
- **Observation kinds**: `matching-execution`, `quota-block`, `intervening-action`, `terminal-defiance`, `unpaired-request`
- **Result evidence**: `stable` (same fingerprint), `changed` (different fingerprints), `insufficient`, `unavailable`
- **Structural input summary**: field names, value types, string lengths, line counts (no raw values)
- **Completeness**: `complete`, `partial`, `unavailable`, or `not found`

### Explain command variants

```text
/loop-guard explain              Explain the latest explainable incident
/loop-guard explain latest       Same as explain with no selector
/loop-guard explain <incident>   Explain one retained incident by exact ID
```

The explainer scans only a bounded slice of the active branch (controlled by `PI_LOOP_GUARD_CHECKPOINT_SCAN_LIMIT`), recomputes session-scoped action digests, correlates results by tool-call ID, and reports a safe chronology.

### Explanation completeness

An explanation is one of:
- `complete`: all matching executions, quota block, intervening actions, and terminal defiance were found
- `partial`: some events are missing (e.g., compaction removed matching calls, or a correlated result is unavailable)
- `unavailable`: the incident has no valid challenged-action digest
- `not found`: the incident is unknown, belongs to another branch, or is outside the bounded scan

The explainer never fabricates missing events and never mutates enforcement state.

Each `terminal-latch`, `internal-failure`, or `incompatible-state` checkpoint renders at most one expandable TUI card. Its collapsed form shows the stable reason, incident, epoch, and action reference when available. Its expanded form adds the cause, execution count, effect, recovery, exact explain command, and the multi-tool limitation: Pi termination was requested, later calls observing the latch are blocked, but an already-started sibling may still finish.

Presentation is mode-aware:

| Mode | Automatic terminal diagnostics |
| --- | --- |
| TUI | Durable checkpoint card, terminal tool-result row, and latch status; the redundant generic terminal notification is suppressed |
| RPC | Complete terminal tool result, structured checkpoint event, and one concise notification |
| JSON / print | Complete terminal tool result and native session events when available |
| Reload / resume / fork / tree | Restored latch status and one notice per branch activation; the original card is reused |

Later `task-latched` calls reference the original incident without creating more cards or notifications. Trusted interactive/RPC input, explicit reset, or navigation to a clean branch clears the active status while retaining historical incident entries. Automatic reports use plain custom entries and UI/RPC presentation only; they never use a custom message or synthetic user message and therefore never add a new model turn.

## Advisory observation

The advisory layer records but does not enforce:

- Period-one through period-three action/result cycles, including A-B-A-B.
- Repeated English and other whitespace-delimited responses using word n-grams.
- Repeated CJK and compact-script responses using character n-grams.

Only assistant-visible text is analyzed. Provider-hidden thinking is not available and status reports that coverage explicitly. Tiny acknowledgements below the configured minimum are treated as insufficient evidence.

Repeated tool history is compacted without adding synthetic user-role warnings. Compaction preserves the first occurrence, first failure, latest occurrence, and tool-call/result pairing, and bounds retained repeated-result text.

## Install

From the repository root:

```bash
pi install ./pi/packages/loop-guard
```

The main installer also installs the local package:

```bash
./scripts/install-pi-dev.sh
```

## Commands

```text
/loop-guard                 Show effective modes, quotas, epoch, latch, counters, restoration, and incident status
/loop-guard explain         Explain the latest explainable incident on the bounded active branch
/loop-guard explain latest  Same as explain with no selector
/loop-guard explain <id>    Explain one retained incident by exact incident ID
/loop-guard reset           Explicitly open a fresh task epoch and persist a reset checkpoint
/loop-guard off             Explicitly disable deterministic enforcement
/loop-guard on              Enable deterministic enforcement
/loop-guard response-off    Disable advisory response and cycle observation
/loop-guard response-on     Enable observe-only response and cycle diagnostics
```

Assistant output or tool results containing these strings do not execute the commands and cannot reset a latch.

### Status output fields

The `/loop-guard` command displays:

```text
Loop guard status
deterministic mode: enforce
advisory mode: observe
exact execution quota: 2
legacy failure threshold (diagnostic compatibility): 2
response repeat threshold: 1
response similarity threshold: 0.82
legacy observation window: 900000ms
task epoch: 10
latch: open | terminal
latest reason: exact-quota-exhausted | block-defiance | task-latched | internal-failure | checkpoint-incompatible | none
latest incident: lg-10-325-quota-block | none
challenged action: action:5da27e4e08ee35c03ec5f6da | none
challenge executions: 2 | none
challenge phase: ready | quota-exhausted | block-challenged | none
restored state: no | yes (restored from session-tree)
tracked actions: 5/200
pending calls: 0/64
incidents: 3/32
requests/executed/blocked/terminal: 154/152/2/1
result updates: 152
already-started sibling results: 0
checkpoint writes: 11
response observations/findings: 0/0
cycle findings: 0
response coverage: full | partial | none
degraded subsystems: none | incident-explanation, ...
configuration warnings: none | PI_LOOP_GUARD_REPEAT_LIMIT=5 (out of range), ...
allow-repeat annotation: recognized, never bypasses the exact quota or latch
commands: /loop-guard explain [latest|<incident-id>] | reset | on | off | response-on | response-off
```

### Active latch status

When the task is terminally latched, a persistent status indicator is shown:

```text
LoopGuard: terminal · block-defiance · action:5da27e4e08ee35c03ec5f6da · lg-10-343-terminal-latch
```

When enforcement is disabled but a latch is retained:

```text
LoopGuard: OFF · retained terminal latch · lg-10-343-terminal-latch
```

The latch status persists until trusted interactive/RPC input, explicit reset, or navigation to a clean branch clears it.

## Environment

Existing settings remain accepted. New mode settings take precedence when present.

```bash
# Deterministic layer: enforce (default) or off
PI_LOOP_GUARD_MODE=enforce

# Advisory layer: observe (default) or off
PI_LOOP_GUARD_ADVISORY_MODE=observe

# Legacy enable switches (still supported)
PI_LOOP_GUARD=1
PI_LOOP_GUARD_RESPONSE=1

# Deterministic execution quota; validated range 1-4, default 2
PI_LOOP_GUARD_REPEAT_LIMIT=2

# Legacy/advisory thresholds. FAILURE_LIMIT and WINDOW_MS remain parsed and
# visible for configuration compatibility; task-scoped exact enforcement no
# longer expires or grants retries from a time window or failure-text count.
PI_LOOP_GUARD_FAILURE_LIMIT=2
PI_LOOP_GUARD_RESPONSE_REPEAT_LIMIT=1
PI_LOOP_GUARD_RESPONSE_SIMILARITY=0.82
PI_LOOP_GUARD_WINDOW_MS=900000

# Bounded state and context controls
PI_LOOP_GUARD_MAX_ENTRIES=200
PI_LOOP_GUARD_MAX_PENDING_CALLS=64
PI_LOOP_GUARD_MAX_INCIDENTS=32
PI_LOOP_GUARD_MAX_RESPONSES=12
PI_LOOP_GUARD_CYCLE_HISTORY=18
PI_LOOP_GUARD_MIN_RESPONSE_CHARS=24
PI_LOOP_GUARD_CONTEXT_MAX_MESSAGES=64
PI_LOOP_GUARD_CONTEXT_MAX_CHARS=24000
PI_LOOP_GUARD_CHECKPOINT_SCAN_LIMIT=256
```

Invalid numeric values use the documented safe default or nearest safe bound. `/loop-guard` prints the normalized effective values and warnings.

## Legacy allow-repeat annotation

The existing annotation is still recognized:

```bash
# loop-guard: allow-repeat
```

It is removed before fingerprinting so annotated and unannotated forms share the same count. Because the annotation can be authored by the model, it never grants an additional execution, clears a block challenge, resets a task, or bypasses a latch.

## Polling and multi-tool batches

Changing output does not provide an unbounded polling lease. Prefer Pi's existing observe workflow for long-running monitoring instead of repeatedly issuing the same tool call. If more probes are genuinely required, provide new interactive or RPC input after reviewing the current evidence.

The extension commits a terminal latch synchronously. Later callbacks in the same multi-tool batch are blocked as soon as they observe it. Pi may already have started a sibling before the latch existed; the extension cannot roll back that side effect and reports any such result in status. Once the batch settles, the latch prevents another provider-driven tool turn in the same task.

## Reason codes and direct output formats

| Reason | Meaning | Recovery |
| --- | --- | --- |
| `exact-quota-exhausted` | The named exact action reached its task quota and remains challenged | Use a different diagnostic or answer; other actions do not clear the challenge |
| `block-defiance` | The named challenged action was requested again | Inspect `/loop-guard explain <incident>`; then use trusted new input or explicit reset after review |
| `task-latched` | The task remains latched by the original terminal incident | Follow the original incident recovery; repeated calls do not create new reports |
| `internal-failure` | The guard could not make or persist a trustworthy decision | Inspect `/loop-guard` and logs; fix the guard or checkpoint path before reset |
| `checkpoint-incompatible` | Saved safety state cannot be restored safely | Load a compatible extension or explicitly reset after reviewing the branch |

### Direct output examples

**exact-quota-exhausted** (third request for the same action):

```text
LoopGuard [exact-quota-exhausted]: action:5da27e4e08ee35c03ec5f6da already executed 2 times in task epoch 10. It remains blocked until trusted interactive/RPC input or /loop-guard reset opens a new epoch; different actions do not clear this challenge. Requesting it again will terminate the current task. Incident: lg-10-325-quota-block.
```

**block-defiance** (challenged action requested again, triggers terminal latch):

```text
LoopGuard [block-defiance]: challenged action:5da27e4e08ee35c03ec5f6da was requested again after an explicit quota block. Task epoch 10 is terminally latched and Pi termination was requested. Review /loop-guard explain lg-10-343-terminal-latch; then use trusted interactive/RPC input or /loop-guard reset after review.
```

**task-latched** (any tool request after terminal latch):

```text
LoopGuard [task-latched]: task epoch 10 remains terminally latched by block-defiance. No tool observed after the latch may execute. Original action:5da27e4e08ee35c03ec5f6da; incident: lg-10-343-terminal-latch. Review /loop-guard explain lg-10-343-terminal-latch, then use trusted interactive/RPC input or an explicit reset.
```

**internal-failure** (guard could not make a trustworthy decision):

```text
LoopGuard [internal-failure]: the guard could not make or persist a trustworthy decision for task epoch 10, so this tool was blocked and the task was terminally latched. Incident: lg-10-350-internal-failure. Inspect /loop-guard status and the degraded subsystem before resetting.
```

**checkpoint-incompatible** (saved state cannot be restored safely):

```text
LoopGuard [checkpoint-incompatible]: saved safety state for task epoch 10 cannot be restored safely. Incident: lg-10-360-checkpoint-incompatible. Load a compatible extension or review the incident before an explicit reset; reopening or forking does not clear this latch.
```

### TUI terminal card

In TUI mode, each terminal checkpoint renders as an expandable card:

**Collapsed**:

```text
LoopGuard terminal latch
block-defiance · action:5da27e4e08ee35c03ec5f6da
incident: lg-10-343-terminal-latch · epoch: 10
```

**Expanded** (adds cause, evidence, effect, recovery):

```text
LoopGuard terminal latch
block-defiance · action:5da27e4e08ee35c03ec5f6da
incident: lg-10-343-terminal-latch · epoch: 10

Cause
A previously quota-blocked exact action was requested again.

Evidence
action: action:5da27e4e08ee35c03ec5f6da
completed executions: 2
task epoch: 10
incident: lg-10-343-terminal-latch

Effect
The task is terminally latched and Pi termination was requested.
Later tool calls that observe this latch are blocked before execution.
Tool calls already started in the same batch may still finish; no rollback is claimed.

Recovery
Review the incident, then send trusted interactive/RPC input for a new task epoch,
or run /loop-guard reset explicitly after review.
Details: /loop-guard explain lg-10-343-terminal-latch
```

Do not work around a latch by changing whitespace, adding the allow-repeat annotation, reloading, forking, or injecting extension messages. Those paths preserve or conservatively lock safety state.

## Development verification

```bash
npm test --prefix pi/packages/loop-guard
npm run typecheck --prefix pi/packages/loop-guard
node --test tests/pi/
```

The behavior suite includes pure state transitions, action references, bounded incident explanations, collapsed/expanded terminal cards, Pi adapter and presentation failures, session lifecycle branches, CJK and cycle observation, context compaction, raw-secret exclusion, mixed batches, and sanitized incident replays.
