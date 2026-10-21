# DSH Perry public integration — 2026-10-21

This record covers repository configuration, dependency preparation, public-source review, and explicitly authorized isolated native acceptance for the selected integration candidate. Formal, manual, and timeout native profiles passed. It does not record a production deployment or account acceptance. Earlier configuration-test counts are not a substitute for the final candidate validation below.

This is the preceding Perry-only candidate, identified by lock `51e2ac0e…` below. The later [whole-ecosystem acceptance](dsh-ecosystem-upgrade-20261021.md) supersedes its TUI selection and lock and separately validates optional Teams. Historical counts and limitations in this record retain their original scope.

## Selected scope

| Area | Decision |
| --- | --- |
| Perry | Upgrade the official package and add targeted pending sandbox-escalation routing, bounded review timing, and configuration diagnostics; native acceptance gates readiness |
| Official Full-access Auto review | Keep disabled; choose and accept separately rather than stacking two permission mechanisms |
| Agent Teams | Keep disabled; any later integration is explicitly optional with separate acceptance |
| Core / TUI / Cursor | Keep the existing selected versions in this change |
| Deployment semantics | Keep existing behavior; process/deployment separation is deferred |
| Upstream implementation | Use official unmodified packages and public interfaces only |

## Candidate and public interfaces

| Component | Selected input |
| --- | --- |
| Perry | Official unmodified `dsh-auto-review@0.13.7`; npm gitHead `c49f850aeb734f2f1f2f06de6546b22f3dc8f22f` |
| Core public APIs | `0.2.1-rc.2` tools, preset registry, and native tool presentation |
| Repository integration | `rotom-dsh-review-context@0.2.0`; preset ID `rotom-auto-review` |
| Default execution | Native workspace-write + ask |

Public package references: [Perry metadata](https://registry.npmjs.org/dsh-auto-review/0.13.7), [tools metadata](https://registry.npmjs.org/@deepseek-ai/dsh-tools/0.2.1-rc.2), [preset metadata](https://registry.npmjs.org/@deepseek-ai/dsh-agent-preset/0.2.1-rc.2), and [presentation metadata](https://registry.npmjs.org/@deepseek-ai/dsh-agent-tool-presentation/0.2.1-rc.2). Upstream implementation, vendor copies, and installed caches are not patched.

Perry `0.13.7` selects structured review only when legacy `ctx.subagents.start` exists. Core `0.2.1-rc.2` exposes `startActivation` instead, so this combination selects `runReviewInline`: a model request without tools or a reviewer child. It resolves the route from the latest real parent session `request/header`; a fresh session with a direct tool call and no header returns unavailable and delegates to human handling. Rotom does not patch this feature gate or add a compatibility shim.

The repository bundle separately defines `rotom-auto-review` through the public preset registry. It loads only the repository-owned `/reviewer` helper and native tool presentation. The helper uses public `ctx.get("tools").restrict({allow: ["rotom_review_context"]})`. An independent public `startActivation` probe completed at depth 1 and exposed exactly `rotom_review_context` and `structured_output`. It loaded no filesystem, bash, delegation, MCP, or PTC bundles. This validates that preset separately, not its use by the current approval chain. Configured `reviewerProvider`, `reviewerPreset`, and `reviewerTools` do not change the selected no-tool inline path. Neither result proves OS filesystem confinement or same-user credential isolation.

## Configuration boundary

`toolsPolicy` defaults to human with AI overrides only for write/edit. The separately managed `riskRules` first matches `^(?!(?:bash|write|edit)$)` on `toolName` and routes those tools to human. The next rule matches `^escalate sandbox to (?:workspace-write|danger-full-access): .+$` on `reason` and routes matching requests to AI. Perry uses the first matching rule before tool overrides. Read, MCP, and unknown tools therefore remain human even with a matching reason; bash needs the matching reason, while write/edit retain their AI tool overrides when no rule matches. There is no structured request-kind check or single-rule tool-and-reason conjunction; the ordered gate limits eligible tool names, and a matching reason still does not prove the command or authorization. Ordinary sandbox-allowed commands do not call the reviewer; other pending bash requests remain human. There is no general Shell allowlist.

The reviewer must check the real command, target, and side effects against the current user's explicit authorization for one local build, test, or diagnostic. Naming a command “build” or “test” does not authorize it. External writes, destructive deletion, system permission changes, unconfirmed script effects, unknown tools, and unclear scope require human handling or denial. AI routing is not an allow verdict.

The strict optional `agent_options.auto_review_options` object accepts only `sandbox_escalation` (boolean, default true) and `reviewer_timeout_ms` (integer 1000–300000, default 90000). Disabling escalation routing writes an empty rule list. `auto_review` remains the plugin-wide boolean. Budgets remain three reviews and one failure per turn, cache TTL zero, low-risk automatic allow only, and failure fallback to human delegation.

The inline timeout aborts the model request. Current Perry can classify a standard terminal `aborted` stream chunk as `unavailable`; it labels timeout only when the timed-out operation throws into its catch path. Acceptance therefore checks the finite deadline, cancellation, human fallback, and absence of side effects rather than requiring a particular timeout label. Budget exhaustion delegates before a new reviewer attempt. Process-local status counters can observe these limits but do not establish persistent verdict history.

Doctor's `approval_review` reports `scope=configuration-preview`, `runtime_checked=false`, and `persistent_verdict_audit=unsupported`. It cannot establish current-session routing, a failure-budget hit, or complete persistent verdict/fallback audit. No private session inspection or fabricated complete audit is introduced.

## Complete lock and package preparation

The complete lock was generated with Node `24.14.0`, official npm `11.19.1`, and the pinned official pnpm `11.19.0`. Its validated identity is `51e2ac0eaf36a333a6e837996e04b4262c52caf6a9f9a96f2f7cdd9ae56b980e`. The normal publisher rejected the checkout's ancestor permissions; the same generator and recoverable publisher then succeeded in a private temporary checkout. The generated bytes were transferred unchanged under the repository writer lease, manifest last, and `read_lock` revalidated the identical identity. No path safety check was weakened.

The resolver reduced package entries from 847 to 772. Perry no longer depends on the old tsdown/TypeScript build chain, which accounts for the rolldown, yuku, and associated platform-package removals. Complete resolution also updated AWS SDK internals through Bedrock, execa `10.1.1` → `10.2.0` through plugin-manager, and fast-uri `3.1.8` → `3.1.9` through Ajv. Core, base, preset, and presentation package integrity values stayed unchanged. Preset and presentation were already in the old graph and are now explicit direct dependencies. The TUI source archive and integrity stayed unchanged.

Both old and new Perry dependency snapshots retain some `0.2.1-alpha.1` production dependencies. They were not introduced by this change; passing the selected public module identity checks does not prove that every upstream transitive module has one identity or that all native behavior is compatible.

Frozen installation and `check-runtime.mjs` both exited 0 in an isolated HOME/XDG/cache scope. Installed versions were Perry `0.13.7` and Rotom review-context `0.2.0`; package and installer lock SHA-256 values stayed unchanged. The check imported public modules and checked their selected versions and realpath identities without starting a host, model, account, TUI, or service. The actual commands, with generic temporary paths, were:

```text
node <runtime>/.tooling/pnpm/package/bin/pnpm.cjs install --frozen-lockfile --ignore-scripts --node-linker=hoisted --package-import-method=copy --store-dir <validation>/pnpm-store
node agents/dsh/templates/check-runtime.mjs <runtime>
```

Initial installation and pytest attempts encountered ENOSPC on the temporary filesystem. Those attempts are not passing evidence. Only task-owned temporary data was moved or removed; frozen installation then passed on the workspace filesystem. The affected pytest files subsequently passed with pytest's built-in successful-case temporary-directory cleanup and a separate temporary base per file. No application safety check or test isolation guard was disabled.

## Isolated validation

All 22 affected pytest files exited 0, with **724 passed** and no skipped cases. They cover Perry configuration and first-match routing, dependency locks, doctor/readiness and CLI presentation, the dependency backend, DSH render/upgrade/optional/SSH/TF compositions, historical smoke-entry refusal and experience ownership, configuration schema/resolution/policy/examples/credential reads, deployment ownership, native fixtures, and rendering. The actual argv for each selected file was:

```text
.venv/bin/python -m pytest -q --tb=short -o tmp_path_retention_policy=failed tests/<test-file>.py --basetemp <temporary>/cases
```

The file stems were `test_dsh_auto_review_config`, `test_dependencies`, `test_readiness_evidence`, `test_presentation`, `test_cli_presentation`, `test_dependency_backend_contract`, `test_dsh_pipeline`, `test_dsh_upgrade`, `test_dsh_optional`, `test_dsh_ssh`, `test_dsh_tf`, `test_dsh_auto_review_experience`, `test_dsh_cli_smoke`, `test_dsh_codex_device_smoke`, `test_config_schema`, `test_config_resolution`, `test_config_policy`, `test_config_examples`, `test_config_secret_loading`, `test_deployment`, `test_native_fixtures`, and `test_render`.

`node tests/node/dsh_review_context.test.mjs` exited 0 with **3 passed**, covering the constant context boundary, the exact restriction request, and activation failure without a weaker retry. These are tests of repository-owned code with a fake context, not proof of native scoped activation. `node --check agents/dsh/templates/check-runtime.mjs` also exited 0. Frozen installation and public module identity results are recorded above. The initial complete pytest run remains incomplete after ENOSPC and is not promoted to a full-suite pass.

After adapting the repository-owned smoke to the public Agent loop, `test_dsh_auto_review_config.py` was rerun with **66 passed**, exit 0. This replaces its earlier 63-case result; it is not 66 additional cases on top of 724. The new cases reject changed sealed-runtime inputs and memory-backed evidence directories before host creation. JavaScript syntax and `git diff --check` passed.

Execution used the tool-declared role configurations: executor (`gpt-6.1-sol`, medium) for bounded implementation, documentation, and frozen-package validation; scout (`gpt-6-luna`, high) for public API and lock-graph evidence. The main agent decided the interfaces and tool-name guard, integrated the public preset, and ran candidate acceptance. No upstream fork or patched host was used.

## Authorized native acceptance

The unchanged sealed runtime was started in isolated HOME/DSH/XDG directories on Linux with Node `24.14.0`. A fictional public LLM adapter supplies deterministic verdicts; a public human responder supplies controlled allow/reject/error outcomes. Real accounts, real model requests, and the interactive TUI were not exercised. These tests establish routing, cancellation, and side effects for the fixtures, not the quality of a real model's safety judgment.

Parent Agents start through public `agents.create` and `followup`. The fake parent stream emits genuine tool calls, so the Agent loop produces its own request headers and executes tools during a real open turn. The fixture does not append synthetic headers, turns, or internal owner markers. Pending file requests are deliberately created through a public test-only `tools/pre-execute` handler; native workspace writes normally bypass that handler. Bash escalation uses the actual tool's public arguments and native approval reason, without a synthetic ask.

The selected approval path made no reviewer child and supplied no tools to its inline model requests. A separate earlier public activation probe verified the conditional preset; it is not counted as a Perry approval-chain result.

| Profile / case | Observed result |
| --- | --- |
| Formal pending file allow | One native write; one reviewer call; no human call |
| File deny / hard never | Zero writes; native never did not call reviewer or human |
| High-risk allow / model error / attempted reviewer tool call | Zero writes; delegated where required; the inline tool-call response did not execute a read |
| Review budget | First three allowed writes reviewed; fourth delegated without another reviewer attempt and did not write |
| Failure budget | First reviewer error delegated; next pending request delegated without another reviewer attempt and did not write |
| Unknown tool with forged sandbox reason | Human once, reviewer zero, tool body not executed |
| Ordinary workspace file and Bash | Executed once without reviewer or human calls |
| Outside-workspace Bash before grant | Zero appended markers; exit 1; workspace-write; native denied=true |
| Same Bash with explicit single grant | One appended marker; reviewer once, human zero; exit 0; danger-full-access for that call |
| Same Bash again without grant | Marker count stayed one; exit 1; workspace-write; native denied=true |
| Bash deny / high risk / reviewer error | Zero appended markers; high risk and error delegated to the human responder |
| Persistent manual profile | Perry service/command absent; reviewer zero; human approval executed one file write |
| 1000-ms timeout profile | File and Bash reviewer requests observed cancellation at about one second, delegated once each, and executed zero actions |

The three same-command Bash attempts had identical command SHA-256 values and distinct call IDs. After each attempt, the session remained `workspace-write + ask`. Targets were precreated empty files with mode `0600` inside a private evidence directory outside the workspace on a persistent filesystem. Temporary namespace paths such as `/tmp` and `/dev` are unsuitable for measuring host-visible outside-workspace writes; the entry point also rejects memory-backed evidence directories. The result proves the tested local write boundary and one-call grant; it is not a blanket OS confinement, network, credential-isolation, or concurrency claim.

The formal profile used 13 inline reviewer requests and 35 parent model requests; manual used zero reviewers and two parent requests; timeout used two reviewers and five parent requests. Every actual inline reviewer catalog was empty. All three profile processes and the outer smoke exited 0; the final formal/manual/timeout process durations were 4.226 / 2.221 / 4.782 seconds. The invocation, with private paths normalized, was:

```text
.venv/bin/python scripts/smoke-dsh-formal-review.py --allow-host --runtime <sealed-runtime> --evidence <private-evidence-on-persistent-filesystem>
node <repository>/scripts/smoke-dsh-formal-review.mjs <sealed-runtime>
```

The entry point checks sealed-runtime package/lock bytes against the selected lock. Private evidence records the lock identity, lock hash, nonce, source hashes, actual normalized child argv, exit codes, bounded durations, request correlations, and file counts. The final source hashes matched the executed candidate. Evidence directories are `0700` and reports/logs are `0600`; only synthetic target content is retained. Early fixture failures are not passing evidence: a direct tool call without a real request header correctly fell back to human; the Bash fixture initially omitted a required argument; and the first outside target used a temporary namespace path. The final native run used the corrected fixtures without weakening expected denial or execution-count assertions.

## Evidence and remaining work

| State | Scope |
| --- | --- |
| Completed | Configuration mapping and public-source review; complete lock and independent lock-delta review; frozen installation and selected public module identity checks; 724 initial affected pytest cases, latest 66-case approval rerun, and 3 Node cases; independent preset probe; formal/manual/timeout native acceptance; final stable-diff and publication-content review |
| In progress | None within the selected change |
| Failed / pending decision | No failing final isolated checks; historical native failures below retain their own unaccepted scope |
| Environment insufficient / unverified | Full-suite run after ENOSPC; real account/model round trips; real TUI interaction; broader platform, network, concurrency, restart, and OS/same-user credential isolation |
| Historical failures retained for revalidation | OFF resetting on a later turn, late approval after OFF/unload, and missing complete persistent verdict audit |

The previous Perry `0.12.17` daily deployment limitations were accepted on 2026-10-14. Its standard/spawn/native catalog exposed subagent; depth-limited delegation and file tests were historical observations for that candidate. They neither describe the new preset's actual child tool surface nor validate the new reason routing and 90-second timeout. This integration claims no fix for those lifecycle or audit failures.

The user explicitly authorized isolated real-host smoke on 2026-10-21. Native fixtures use the unchanged sealed runtime, fictional provider/model, synthetic files, and private temporary HOME/DSH/XDG directories. They do not use existing accounts or sessions. Default tests continue to block real host subprocesses and network. No real account/model or TUI result is asserted here. See [DSH configuration](../dsh.md#ai-approval-and-persistent-manual-mode), [approval design](../design/approvals.md), and [testing](../testing.md).
