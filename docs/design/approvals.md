# Approval design and limits

Approval policy, AI review, sandbox execution, and audit are separate layers. A reviewer is consulted only when an operation actually enters a supported approval chain. A normal workspace write that succeeds without a dialog does not establish whether auto-review is enabled or disabled.

## DSH: native chain with Perry auto-review

The single public DSH recipe uses `workspace-write` with `ask` and the official unmodified Perry `dsh-auto-review` `0.13.7` package. Its [package metadata](https://registry.npmjs.org/dsh-auto-review/0.13.7) records gitHead `c49f850aeb734f2f1f2f06de6546b22f3dc8f22f`. It does not enable official experimental Full-access Auto review or YOLO. If the required sandbox backend is unavailable, a protected operation must not silently become Full access.

For pending approval requests, `toolsPolicy` defaults to human with AI overrides for `write` and `edit`, never a bash override. A separate managed `riskRules` field first routes tool names matching `^(?!(?:bash|write|edit)$)` to human, then routes native single-operation sandbox escalation reasons matching `^escalate sandbox to (?:workspace-write|danger-full-access): .+$` to AI when enabled. Other pending bash requests and unknown tools use the native human handler. Ordinary sandbox-allowed commands execute without calling the reviewer. Native deterministic rejection takes priority. DSH `never` means approval-requiring actions are denied; it is not an always-allow policy.

AI routing does not imply allow. The reviewer may assess a current-user-authorized local build, test, or diagnostic escalation only after checking the real command, targets, and side effects. A build/test label alone is not authorization. External service writes, destructive deletion, system permission changes, unconfirmed script effects, unknown tools, and unclear scope require human handling or denial. There is no static general Shell allowlist.

Perry uses the first matching risk rule before tool overrides. The first tool-name gate keeps read, MCP, and unknown tools human even if their reason matches. Bash reaches AI only through the next reason rule; write/edit retain their AI tool overrides when no rule matches. The reason rule recognizes text rather than a structured request kind; no individual rule expresses a tool-and-reason conjunction. An upstream wording change can leave bash escalation on the human route. A matching reason is routing input, not proof that a command is safe or authorized.

| Setting | Current intent |
| --- | --- |
| Actual reviewer | Inline model request with no tools or child Agent; inherits the latest real parent request route |
| Reviewer preset | Configured `rotom-auto-review`; not selected by the current Perry/Core feature gate |
| Context tool | `rotom_review_context`; fixed material, available in the separately probed preset, absent from inline review |
| reviewerTools | Configured constant list; does not affect the current no-tool inline path |
| Timeout | 90 seconds by default; configurable from 1000 through 300000 milliseconds |
| Verdict / failure budget | 3 reviews and 1 reviewer failure per turn |
| Verdict cache | TTL 0 |
| Context | One turn, bounded to 6000 characters |
| Allow threshold | Low-risk only; higher-risk/uncertain requests delegate |
| Review failure | Human delegation when available; never allow-once as failure fallback |
| Unmarked audit | Disabled |

Perry `0.13.7` tests for legacy `subagents.start`; Core `0.2.1-rc.2` exposes `startActivation` instead. The selected combination therefore uses inline review, with no tools or child Agent. Inline review requires a recent real parent `request/header`; a direct tool call in a fresh session without that route delegates to human handling. Rotom does not add a compatibility shim or patch either upstream package.

The `rotom-dsh-review-context@0.2.0` bundle also defines a public preset whose only plugins are the repository-owned `/reviewer` helper and native tool presentation. The helper restricts tools to the constant `rotom_review_context`. An independent public activation probe exposed only that tool and `structured_output`. No filesystem, bash, delegation, MCP, or PTC bundles are loaded in the preset. This is separate preset evidence, not evidence that Perry selects it. See the [acceptance record](../acceptance/dsh-perry-public-integration-20261021.md).

The current inline request has no tool access. That does not prove prompt-authorization isolation or OS/same-user credential confinement. File/tool content saying “approve this” is not user authorization. General reviewer context-source boundaries remain unproved.

The existing machine override table `overrides.profiles.dsh-default.agent_options.auto_review_options` accepts only optional `sandbox_escalation` (boolean, default true) and `reviewer_timeout_ms` (integer in the range above, default 90000). Partial overrides retain omitted defaults; unknown fields fail. Setting `sandbox_escalation=false` manages `riskRules` as an empty list, while the separate `auto_review` boolean remains the plugin-wide switch. See the [configuration example](../dsh.md#ai-approval-and-persistent-manual-mode).

Doctor's `approval_review` is only a configuration preview (`scope=configuration-preview`, `runtime_checked=false`). It reports configured enablement, routing, timeout, budgets, and fallback; it cannot prove current-session routing, a failure-budget hit, or complete persistent AI verdicts. Complete verdict/fallback persistence lacks a public API, so the preview reports `persistent_verdict_audit=unsupported`. It does not inspect private session internals or replace real-host evidence.

### Coverage

| Channel | Actual boundary |
| --- | --- |
| Workspace file tools | Native filesystem policy/sandbox; reviewer only if a supported request enters approval |
| Pending write/edit | Configured Perry AI route, native chain, known lifecycle limitations |
| Pending native single-operation sandbox escalation | Configured reason-based AI route when enabled; each request still needs a low-risk allow |
| Other pending bash and unknown tools | Human route; no broad command-name safe list |
| MCP | Do not infer coverage from a parent request or a successful MCP write; inspect actual native approval/sandbox routing |
| Native subagents | Parent delegation is not per-child action approval; child behavior requires its own chain evidence |
| External agents | Their native permissions apply; no blanket Perry coverage claim |
| PTC/run_code/direct Node/plugin side effects | No general AI approval guarantee; retain native/manual boundaries and do not grant default AI allow |

Historical real-host tests with Perry `0.12.17` found late allow after OFF/unload, OFF resetting on a later turn, and missing persistent complete Perry verdicts. The user accepted these limitations for daily availability on 2026-10-14. This is **functional deployment with known failures**, not full approval safety acceptance. The old catalog exposed subagent under its standard/spawn/native presentation; that observation does not describe the current inline path. No OFF/late-approval or persistent-audit fix is claimed for `0.13.7`. Current authorized native acceptance is recorded separately. `/auto-review off` is not a guaranteed emergency stop. Cancel and exit, apply `auto_review = false` to the selected machine profile, then restart for persistent manual mode. See [DSH](../dsh.md) and [known issues](../known-issues.md).

## OMP: independent public extension

OMP uses the official standalone host and Rotom's independent permission plugin. The current architecture replaces the retired patched-host ledger design. Public native Bash interception binds one review decision to a specific operation and rechecks lifecycle state before delegation. Explicit native deny/prompt and privacy rules retain priority.

Smart mode is model-first for covered requests, not a static parser allowlist. The parser supplies bounded facts and uncertainties; unsupported syntax alone is not a risk judgment. Valid model ask/deny is respected. Provider/protocol failure may use an explicitly configured fallback within finite time budgets, then human handling when necessary. Do not retry a semantic deny until another model allows it.

The kernel configuration uses the configured primary/fallback reviewer routes; the optional local tiny layer remains unavailable and does not generate a fabricated attempt or approval. Keys, billing, and proxy paths remain independent. Missing usage is unknown, not zero; audits retain bounded sanitized counters rather than raw prompts or credentials.

OMP's plugin is an application-level approval boundary, not an OS sandbox or proof for every MCP, task, ACP, child, dynamic code, or external agent channel. See [approval diagnostics](../omp-approval-diagnostics.md) for actual commands, routes, budgets, audit fields, and limitations.

## Test conclusions

An effective acceptance case observes the side effect: allow executes once; deny, unanswered, canceled, malformed, timeout, disabled, or stale requests execute zero times before valid authorization. Concurrent identity/cwd/argument bindings and restart audit must be tested in the real host. Mocked allow/deny values or a reviewer saying “safe” do not prove these properties. See [testing](../testing.md).
