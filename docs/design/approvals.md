# Approval design and limits

Approval policy, AI review, sandbox execution, and audit are separate layers. A reviewer is consulted only when an operation actually enters a supported approval chain. A normal workspace write that succeeds without a dialog does not establish whether auto-review is enabled or disabled.

## DSH: native chain with Perry auto-review

The single public DSH recipe uses `workspace-write` with `ask` and Perry `dsh-auto-review` `0.12.17`. It does not enable official experimental Full-access Auto review or YOLO. If the required sandbox backend is unavailable, a protected operation must not silently become Full access.

For pending approval requests, the Rotom configuration restricts AI handling to `write` and `edit`; other pending tools delegate to the native human handler. Native deterministic rejection takes priority. DSH `never` means approval-requiring actions are denied; it is not an always-allow policy.

| Setting | Current intent |
| --- | --- |
| Reviewer | Independent spawned reviewer; explicit route when configured, otherwise the supported selected parent route |
| Exposed context tool | `rotom_review_context`; fixed contextual material, not a general filesystem reader or Shell |
| Subagent depth | Maximum depth 1 |
| Timeout | 30 seconds |
| Verdict / failure budget | 3 reviews and 1 reviewer failure per turn |
| Verdict cache | TTL 0 |
| Context | One turn, bounded to 6000 characters |
| Allow threshold | Low-risk only; higher-risk/uncertain requests delegate |
| Review failure | Human delegation when available; never allow-once as failure fallback |
| Unmarked audit | Disabled |

The independent reviewer and context-tool restriction reduce exposure but do not prove full filesystem or prompt-authorization isolation. File/tool content saying “approve this” is not user authorization. General reviewer directory/context boundaries remain unproved.

### Coverage

| Channel | Actual boundary |
| --- | --- |
| Workspace file tools | Native filesystem policy/sandbox; reviewer only if a supported request enters approval |
| Pending write/edit | Configured Perry AI route, native chain, known lifecycle limitations |
| Pending Shell and unknown tools | Human route under this configuration; no broad command-name safe list |
| MCP | Do not infer coverage from a parent request or a successful MCP write; inspect actual native approval/sandbox routing |
| Native subagents | Parent delegation is not per-child action approval; child behavior requires its own chain evidence |
| External agents | Their native permissions apply; no blanket Perry coverage claim |
| PTC/run_code/direct Node/plugin side effects | No general AI approval guarantee; retain native/manual boundaries and do not grant default AI allow |

Historical real-host tests found late allow after OFF/unload, OFF resetting on a later turn, and missing persistent complete Perry verdicts. The user accepted these limitations for daily availability. This is **functional deployment with known failures**, not full approval safety acceptance. `/auto-review off` is not a guaranteed emergency stop. Cancel and exit, apply `auto_review = false` to the selected machine profile, then restart for persistent manual mode. See [DSH](../dsh.md) and [known issues](../known-issues.md).

## OMP: independent public extension

OMP uses the official standalone host and Rotom's independent permission plugin. The current architecture replaces the retired patched-host ledger design. Public native Bash interception binds one review decision to a specific operation and rechecks lifecycle state before delegation. Explicit native deny/prompt and privacy rules retain priority.

Smart mode is model-first for covered requests, not a static parser allowlist. The parser supplies bounded facts and uncertainties; unsupported syntax alone is not a risk judgment. Valid model ask/deny is respected. Provider/protocol failure may use an explicitly configured fallback within finite time budgets, then human handling when necessary. Do not retry a semantic deny until another model allows it.

The kernel configuration uses the configured primary/fallback reviewer routes; the optional local tiny layer remains unavailable and does not generate a fabricated attempt or approval. Keys, billing, and proxy paths remain independent. Missing usage is unknown, not zero; audits retain bounded sanitized counters rather than raw prompts or credentials.

OMP's plugin is an application-level approval boundary, not an OS sandbox or proof for every MCP, task, ACP, child, dynamic code, or external agent channel. See [approval diagnostics](../omp-approval-diagnostics.md) for actual commands, routes, budgets, audit fields, and limitations.

## Test conclusions

An effective acceptance case observes the side effect: allow executes once; deny, unanswered, canceled, malformed, timeout, disabled, or stale requests execute zero times before valid authorization. Concurrent identity/cwd/argument bindings and restart audit must be tested in the real host. Mocked allow/deny values or a reviewer saying “safe” do not prove these properties. See [testing](../testing.md).
