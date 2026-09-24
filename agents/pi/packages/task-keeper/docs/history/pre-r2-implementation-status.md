# Implementation and acceptance status

> 2026-09-14：当前功能设计已重订为TK-R2，见[唯一实施进度](../../../../openspec/changes/add-pi-task-keeper/implementation-progress.md)。本页旧71/76和P0–P3覆盖数字仅对应现有代码基线，不是新版完成状态。包内源码与旧测试计划尚未迁移；此设计整理不赋予新运行信用。


This remains an implementation candidate. **Full P0–P3 acceptance is not complete.**
OpenSpec `add-pi-task-keeper` records **71/76 tasks completed**. The remaining tasks
are live Qwen acceptance (7.4), complete request-path certification (10.2), real utility
comparisons (11.6), full scenario/fault/variant audit (12.1), and complete Q1/Q2/Q3 await coverage (13.5).

## Latest complete package run

- Run `2026-09-14T01-50-24-884Z`: **822/822 passed; 17,928 assertions; zero failed, cancelled or skipped tests**.
- Current source digest: `f71bf637f0b69b9b4b14a5021990d73c651cb20d5a2d1b2f35a867de17068c81`.
- Minimum release evidence gaps: **91/707**. Original expanded matrix gaps: **301/436**. Full domain/oracle audit remains open.
- Typecheck, static plan, strict OpenSpec validation and frozen-design checks passed. The original bwrap namespace isolation ran successfully; the previous NETLINK blocker is historical.
- The [current evidence checkpoint](testing/runtime-progress.json) was generated from this run and independently checked against raw execution/discovery records and the current source. Previous checkpoints and failed runs remain in their original artifacts.

[Full report](../test-results/2026-09-14T01-50-24-884Z/report.json), [TAP](../test-results/2026-09-14T01-50-24-884Z/tests.tap), [remaining cases](testing/runtime-gap-cases.csv), [case evidence](testing/runtime-case-evidence.csv), [matrix evidence](testing/runtime-matrix-evidence.csv), [changes and audit history](testing/continuation-2026-09-14.md).

This run closes the verified local changes described in the dated audit. It does not establish live Qwen acceptance or complete the remaining offline request/crash/await and scenario obligations.

## Implemented and verified

- A confirmed native terminal now reconciles an undelivered continuation acknowledgement by its full durable identity and ends the old ACK listener. A real Pi regression and a failing cleanup mutation show that a subsequent quota incident can progress; missing/conflicting native identity still retains unknown claims.
- W3 lifecycle/process coverage additionally verifies real new/switch/fork/shutdown/PTY reload, protocol replies, distinct-PID restart and deadline preservation. Complete await/crash matrices remain pending.

- F01–F04 are connected and verified: fixed-workflow proposal admission, declared shared-directory resources, zero writer enforcement, and optional bounded diagnostic replanning. See the [dated execution record](testing/continuation-2026-09-10.md) and [scope audit](scope-audit.md).
- Invalid proposal JSON/authority fields are audited without changing semantic revision or acceptance. Stale queued proposals are retired, and explicit resume can retry a rejected baseline while preserving counters.
- W2's original 15 minimum-evidence gaps are filled. Online Advisor remains off: its accounting-cost scenario uses a declared upstream safety fixture and actual Pi consumer, not a certified online Advisor.
- Work continues against the [finite closure plan](../../../../openspec/changes/add-pi-task-keeper/closure-plan.md); full case/variant closure remains pending.

- Pre-dispatch SQLite BUSY/LOCKED now yields and retries admission without allocating an execution, retaining lastDispatchError. Deterministic lock contention beyond the five-second busy timeout made nine real Pi peers block before the fix and remain waiting afterward; deadlines, pause, other SQL errors and post-commit uncertainty keep their conservative behavior.
- Quota waiting now survives pause/resume and restart through quotaWaitPending. With an unchanged candidate, resume returns to stage admission instead of spawning another attempt on the last backup. A real four-backup quota run reproduced the extra execution, then passed after the fix with original timestamps and budgets retained.
- Managed model provenance now distinguishes actual client configuration from unobserved response model and unverified server weights. Real SSE mismatch/opaque responses and receipt/UI/tool projections verify the distinction.
- Actual OS spawn failure, blocked worktree creation and cancellation after confirmed file edits preserve original errors/candidates and cannot produce a successful task receipt. Native retry duplicate facts preserve two distinct request charges, and an unrecognized fetch chain prevents protected dispatch.
- Four independent workflow driver files retain all 68 cases and their original assertions while allowing the test runner to execute groups concurrently. Native retry/stream/tool recovery cases have dedicated per-ID and physical ledger assertions; project guard-disable reloads retain existing unknown work and budget.
- Ten real Pi RPC parents share one quota recovery permit, settle progressively, and preserve each original session/input/error. Holder cancellation releases only after native settlement; a killed parent with no durable terminal fact retains the permit while nine live peers recheck. A private capacity-10 mutation produced ten simultaneous recoveries and failed the receiver assertion.
- Remaining S tests retain route/failure identity after total redaction, show independent coordination roots through the registered doctor handler, reject unavailable SOCKS routes without direct fallback, and trap selector effects across critique/upgrade state sequences.
- Pure recovery eligibility, native terminal success, owner identity and intent dispatch predicates are used by production callers and covered by independent U counterexamples. Nine isolated guard-removal mutations are detected by the actual tests, with a passing original-source control.
- State campaigns cover elapsed owner loss, last-slot competition, long-context continuation identity, interrupted migrations and missing intent/budget facts. Six continuation C0-C5 cuts preserve original actions across unknown ack, interrupted settlement and lost notification; S is not native crash certification.
- The focused launcher now honors filtering flags placed after file names by placing validated targets after Node options. A failing unselected test reproduced the old behavior; prefix/suffix/equal-form filtering and target/isolation checks pass.
- Actual Pi baseline build environment failure preserves BLOCKED receipts and five-layer failure disclosure without starting a writer, upgrade or critic. Structural-only report success leaves runtime obligations unexecuted and code coverage unavailable.
- Actual child thinking drift is observed independently: requested/high-before-start versus effective off is rejected before HTTP, while legitimate high runs successfully. Removing thinking guards causes two real loopback requests and fails the control; configured thinking is never rewritten to hide the mismatch.

- Main recovery and canary share the unchanged pure network-failure counting rule. Fixed boundary tests prove that unlimited quota waiting does not bypass the network retry limit; state/timeout and actual network recovery/exhaustion regressions pass, and disabling exhaustion fails the control.

- Real successful execution now links native run identity, descriptor, reporter readiness, observed configuration and events through the existing receipt/UI/tool/parent checks. Separate forged-scope/fork/background input calls are rejected by the real host, while doctor limits the declared managed scope to foreground/fresh.

- Fixed TaskSpec/dependency validation now precedes job persistence and workspace creation. A configured check colliding with the writer step is rejected through the real Pi entrypoint without creating work; valid workflows and configured limits retain their behavior.

- All four stream-terminal variants now have explicit S and real Pi E witnesses: HTTP200 alone cannot certify completion, stream error/truncation retain diagnostics in the next model input, and a received partial stream still obeys finite request timeout and termination reconciliation before explicit resume.

- A real silent verifier remains RUNNING with no receipt while its actual PID is alive; the command UI agrees and no model request starts early. Releasing it allows empty-output build success and completion without additional writer work. Timeout and uncertain termination remain separately tested.

- Interrupted native results retain their backend status and exit code, with an explicit fallback reason when no detailed error is provided. An actual native ToolResult projection with interrupted=true/exit0 stays blocked across adapter, receipt, UI, tool and parent input. Required child-tool startup failures also retain the native failed/exit1 witness and zero-HTTP evidence.

- Native test cancellation/timeout is recorded as failed even after earlier assertions; actual reporter controls reject the resulting evidence. Owner-interleaving state tests start at their declared ready state and fail immediately if dispatch never occurs, removing unrelated real verifier startup from S coverage without extending the watchdog.

- The actual model tool rejects forged workScope input before creating any job/intent, and the next parent request contains its validation error. Child release uses the same pure termination/external-work rule covered by a handwritten truth table and real process/adapter regressions; deleting physical-stop evidence fails the control.

- A real worker cannot lower an acceptance threshold and reuse the original authorization: the wrong candidate stays blocked before checks, with unchanged spec/main tree and visible approval evidence. Skipping that guard makes the wrong candidate complete and fails the negative control. Public tool registration uses the same pure parameter schema tested against individual scope/budget/binding overrides.

- Independent review contract rejections now persist structured failure facts before blocking. A subsequent validated review explicitly resolves the original failure with its current artifact; a real resume re-runs only review, preserves history and completes without rewriting the candidate. Optional critique rejection is retained as nonrequired and does not weaken root acceptance.

- Actual Pi owner-probe tests reject duplicate recovery owners before child/HTTP admission, with a successful single-owner control and a failing count-check mutation. State ownership blocks a second live dispatcher. Lost reporter-channel evidence now records prior readiness and absent events while retaining unknown termination and resource claims.

- State tests keep failed independent gates blocked despite native completion or an authorized finish proposal. Registered terminal input remains unconsumed in both canary orders and cannot renew authority. Protected recovery candidates reject stale or mismatched telemetry while preserving the original incident and request ledger.

- Each canonical state directory atomically binds one configurable database filename before ledger creation. Conflicting first-open races cannot allocate independent last-slot ledgers; legacy ambiguity is refused without deletion. Maintenance resolves the bound filename, and default/custom databases pass all five process-crash cuts. Real Pi doctor states the actual database and independent-root boundary.

- Successful direct fix and repair runs compare native output, process-isolated checks, stored receipt, command UI, tool content/details and the next parent request; retained failure history and summary groups agree. Real verifier controls independently attribute zero/all-skipped/unknown-count rejection without treating exit zero as success.

- Recovery timing now uses shared pure rules for deadline precedence, wall rollback and shared cooldown, validated alongside actual Pi deadline/resume checks. Ten real controller processes compete for one quota permit; pausing every waiter prevents sends. Owner-death and uncertain-budget tests retain independently attributed state and physical-effect evidence.

- Long full runs emit progress every 30 seconds and persist TAP as it arrives; close waits for all child output before validation. Real two-parent Scheduler contention tests verify reverse resource order, canonical aliases and the last slot, retaining unknown claims until supervised death and explicit owner reconciliation.

- Verification/workspace operations use an independently checked PID namespace. Ordinary and detached descendants cannot yield a passing parent-only receipt. Final admission cancellation is proven not sent. A retained intermittent failure led to a deterministic Z→ENOENT regression: process identity/state now use one kernel record and terminal proof is latched.
- Native `find` can reject cancellation before its fd subprocess closes. Actual fd and Pi/subagents tests retain unknown and resource claims while it remains alive. Reporter exit alone cannot release pending grep/find external work; historical observations without explicit coverage remain unknown.
- Model-created replacement jobs, cancellation, forks and owner replacement retain workScope job/semantic/step ceilings. Actual kernel_task tests reject the second over-limit job without extra writes. Status includes cumulative usage.
- Runtime identity hashes the executable bundle as well as its CLI stub. Modified/missing/extra/symlinked chunks invalidate certification. Supervisor binary and implementation hashes participate in verification input identity.
- Upgrade/disable/restart/rollback × not-sent/terminal-confirmed/unknown use actual Pi loading and new database connections. All 12 basic combinations preserve business keys, used/reserved budget, claims, workspace and private configuration bytes. Interrupted migration and unsafe rollback controls remain tested.
- Source-tagged multi-service Q1/Q2 fixtures include a historical observed Qwen terminal sample. Classification preserves rule/source and independent Retry-After/reset evidence, with explicit uncertainty; actual Pi tests cover known/unknown windows, permanent/context/unknown failures and blocked resume. No Q3 service certification follows.
- Completed receipt queries validate required artifact identity/content and current acceptance inputs. Missing/corrupt files and runtime upgrades invalidate the current presentation while preserving the historical receipt. Restoring original evidence sends no model request.
- Current owners can independently validate a late verifier's kernel termination, intent/epoch/snapshot, binding and environment before adopting the same completed check without replaying its effects. Unmatched or missing evidence remains blocked; other requirements do not become accepted.
- Main recovery and managed workflows coexist through pinned extension identity and a verified fetch-delegate chain. Owned helper denials do not overwrite main request observations. A kernel_task-only parent can recover a quota failure while its original managed job completes.
- Mutating model tool replies use single-use IDs bound to genuine user-turn authority. Human pause/stop, input and session changes revoke old replies; internal messages cannot mint authority. Actual Pi tests deliver the stale reply after pause and verify rejection before a later user resume.
- The offline reporter rejects claimed L evidence, retaining the unqualified execution and a specific rejection reason. Report exit status includes evidence/recording validation, with the native child status recorded separately; labels alone cannot certify a live route.
- Fixed workflow construction and binding diagnostics share one root-requirements rule. Unit tests and a failing mandatory-check-removal mutation protect direct/inspect/critic boundaries. Actual local verification proceeds with exhausted or uncertain model budget, while missing required review keeps the task blocked.
- Doctor now lists static binding gaps by capability without credential lookup or requests. Known unimplemented Advisor modes return ADVISOR_NOT_IMPLEMENTED, while malformed values remain configuration errors; real Pi disabled/unbound/unsupported/off controls pass.
- Distinct quota pools retain independent progress and cancellation. Telemetry and launch-contract tests now carry specific adapter assertions; unsupported thinking/readonly requests cannot silently downgrade. Recorded state traces reproduce an explicitly injected duplicate-charge fault and validate the same trace without it.
- Real Pi command and model-tool entry points reject terminal-job resume without new managed execution or accounting changes. Explicit throttle resume during a server cooldown preserves the original floor and progresses only after it expires.
- Owner-replacement state tests preserve unknown writer claims and observed effects; cancellation reconciliation cannot reopen a cancelled job. Backup handoff is observed before the primary review response, preserving the open primary incident and charged/uncertain budgets across both shared and distinct quota groups.
- User scheduling settings now configure bounded workflow priorities and ready aging; the actual selector has pure boundary/fairness tests and the queued priorities are observed in real workflows. Defaults preserve legacy policy identity. The focused launcher validates every requested file before running, including snapshot-normalized absolute paths and scope/mode rejection controls.
- Successful worker results no longer clear a newer failed auxiliary HTTP request: known recoverable pressure updates the shared quota/transport cooldown while preserving completed code and semantic counts. Real workflow observers verify Retry-After and five-layer disclosure. The long-input canary false-positive case now observes the still-open incident between requests, with a failing early-close mutation.
- Dedicated event-loss/replay unit tests and input-origin state tests preserve observation gaps, failure identity and user control. Unacknowledged starts and registered proposal contracts retain their original identity and budget through owner replacement and late settlement; state evidence does not certify online Advisor execution.
- Queued stale timer callbacks cannot burst recovery requests or bypass a new cooldown; wall rollback extends the durable floor once. Quota parking releases repository capacity only after execution is confirmed ended, retaining unknown writers and original accounting.
- Final request authority is rechecked and committed before fetch is invoked outside the transaction, preserving v6 intent/commit/effect ordering. Admission records never prove sending; cancellation after admission can still settle not_sent. Actual compaction cancellation after recheck reproduced an extra request and now passes, with gate observer sidecars retained.
- Store resource admission uses an all-or-none pure claim plan inside the existing transaction, with unit/state mutation controls and real multiprocess regression. Native SDK retry cancellation now has four independently observed A/P windows, preserving one model input and exact sent/not-sent accounting.
- State regressions verify atomic reverse-order resource admission, aliased writer/verifier exclusion, persisted cooldown restart proofs, and repeated project policy reload with existing spent/unknown budgets retained. These state observations are distinct from physical process and HTTP certification.
- Receipt inspection reads current acceptance facts after awaited snapshot capture; concurrent TaskSpec revision, required artifact loss or receipt replacement cannot return a stale completion. R08 native-tail settlement has explicit state-layer reverse-order evidence. Legacy scheduler/recovery state tests no longer borrow unit-level credit.
- Request timeout revokes automatic ownership before abort callbacks. Late termination may settle the same intent but cannot restart automation; explicit resume preserves original accounting. Real Pi verifies continuation and canary cancellation independently, and local timeout abort provenance no longer replaces the original recoverable quota incident.
- Actual worker self-reported passing tests remain claims: trusted checks, receipts, UI and the next parent input preserve real failure. Progress completion and acceptance are independently projected; accounting updates recheck budget without mechanically expiring a valid proposal.
- Resume cannot turn an exhausted job/workScope step budget into an idle RUNNING state. It reconciles existing executions first, then refuses new work without changing counters; live Pi and late-verifier regressions cover this.
- Optional-strategy skips are now disclosed in receipts, status, text and parent context with persisted reasons. Real protected-budget and state boundary tests preserve required review and accounting while skipping an unaffordable critic.
- Actual PTY terminal-capability replies preserve recovery authority while genuine keys pause it. Reader profile boundaries and independent server/local/persisted cooldown floors have dedicated unit evidence.
- Release/report unit controls keep planning separate from execution, leave code coverage unavailable without instrumentation, and retain deferred Advisor obligations. Selector purity and explicit network-policy controls are tested with valid and rejecting alternatives.
- Review acceptance requires causal delivery: actual tool-result bytes must reach a successful model request before the matching structured verdict. Same-response read+PASS and post-callback payload stripping are rejected; ordinary review and exact reuse remain tested.
- workScope identity now checks canonical current-session files, parent/header/fork origin and branch markers together. Malformed references cannot select a fresh budget; actual Pi forking before the marker retains the original semantic cap.
- Host status coalesces duplicate updates, refreshes waiting countdowns and immediately publishes critical changes. Fractional monotonic clocks are rounded for the integer timer API. Real Pi verifies pause/disable/session cleanup without early retry; UI scheduling never changes task acceptance or budgets.
- A dedicated details-only-error campaign exercises the pinned native converter with Done content plus an error in execution details, then verifies adapter/state/real Pi propagation into the blocked receipt, tool content/details, UI and next parent request.
- Parent context is rebuilt from all managed jobs and native failures, including root TaskSpecs and grouped failure indexes. An explicit UTF-8 byte budget is rechecked at context compilation and the actual send gate, preserves legacy execution-policy identity, and fails closed; even an ineffective host abort cannot bypass it. Real lossy-compaction tests retain blockers and receipt identity in the next parent request and UI.
- Event-ledger state and real multiprocess tests cover duplicate completion, sequence gaps and producer restart, conflicting identities across scopes, and independent-scope progress. Filling an event gap cannot stand in for writer termination; duplicate delivery preserves one native identity and one charge. These do not certify the native adapter crash-cut matrix.
- Doctor/status expose the effective restricted policy without credentials or executable bindings. Real Pi rejects project correctness overrides, untrusted check commands and malformed numeric limits; attempted budget expansion stays capped. Repeated session-start state clears a prior policy on load failure, with a failing mutation control.
- State-level recovery-chain tests cover early primary recovery after reconciliation/server cooldown, the fourth sent or unknown backup permit, and persistent bounded-stage timestamps.
- Acceptance revisions retire the current receipt while retaining its historical artifact. Receipt queries verify the current root TaskSpec version/snapshot/policy before treating earlier evidence as current.
- Blocked workflows now persist an explicit BLOCKED TaskReceipt with missing checks, failure history, routes and unresolved execution. Real zero-test/all-skipped/unknown-count checks are compared across verification, ledger, receipt, command UI, tool content/details and the next actual parent request. Artifact storage failures retain the blocked database record; owner fencing prevents stale receipt publication.
- Service-bound classifier state tests preserve the original session/incident under renamed models, unknown-reset usage pressure, permanent failures and a successful canary followed by a still-limited long request.
- Coverage remains active in recorded test workers but is not inherited by fault-killed subprocesses. A malformed V8 coverage file makes the overall command fail even when test assertions pass; both positive and negative reporter controls are verified.
- Request settlement uses an explicit truth table: unknown reservations survive new incidents/owners, duplicate terminal facts charge once, and contradictory facts are rejected. Critique and cascade preserve shared semantic/step/request limits.
- Automatic threshold/overflow compaction retains current recovery authority and separately records completion or failure. Real split-turn summaries pass; summary quota failure pauses with its original error. Human compaction still revokes automatic control.
- Finalization refuses unresolved running/unknown steps even with old passing checks. Receipts separately record configured, selected, requested and natively observed route/model facts for failed and successful attempts.
- Expanded matrices now require explicit per-variant assertions. Report controls reject missing reverse orders, borrowed levels, zero assertions, failures, skipped/stale evidence and invented cases. Lifecycle, canary/continuation interleavings and complete/error/truncated/timeout stream variants have been registered individually.

Earlier verified work includes route/context/thinking hard admission, separate quota/transport incidents,
late credential/config/telemetry checks, exact review reuse, optional PARTIAL, failure indexing, durable
migration fences, independent start inventories and all-outcome evaluation reporting.
See [decisions](decisions.md), [request admission](request-admission.md), [state maintenance](state-maintenance.md)
and [Qwen fixture provenance](qwen-classifier-fixtures.md) for scope and original ADR/source links.

## Remaining acceptance

Minimum scenario/fault-layer gaps: **120 full / 114 P0–P3**, compared with 618 P0–P3 at the frozen baseline.
`releaseReady=false`. Positive per-ID assertions do not waive every planned variant or observer audit.
Expanded-matrix evidence: **123/436 credited; 313 missing**.
These are a separate detailed view, not an amount to add to the minimum scenario/fault gap count.

The pinned scope remains Pi 0.84.4 and locally patched pi-subagents 0.63.0, foreground/fresh managed
children, guarded tools and direct chat-completions transport. Unsupported background/fork modes,
main-session strict cross-model budgets and P4 online Advisor/learning/narration are not certified.
A Qwen acceptance binding and request ceiling are still needed for live testing. Offline request-path,
race and full case/variant work also remains; live configuration is not the only limitation.

All new runtime tests use private HOME/Pi/state/workspace and loopback-only namespaces. No real
Pi or Claude configuration was written in this continuation.

## Repository integration checks

The focused Task Keeper sync tests and the package, settings-policy, audit, resource-plan and safe sync-contract
suites total **173 passing tests**. They use an isolated Pi directory and the repository template root.
The old broad `pi_spec.lua` suite was also run and did not pass in full: it includes expectations for an old
package count/provider name and earlier merge semantics. It is not represented as a green suite here.

Sync integration required a small existing-code fix: `vim.NIL` must serialize as JSON `null`. This has a
round-trip test and a real isolated sync regression. The package declaration was added to the settings
template; generated model/auth files in the real Pi home were not deployed or edited.

## Test isolation incident

An old `contract_spec.lua` test called real cross-tool sync with `allow_in_tests=true` and wrote
`~/.claude/settings.json` at local time **2026-09-08 05:18:23**. The writer merges generated settings over
existing values, so permissions, sandbox/default environment settings and the appended prompt may have
changed. The exact pre-write contents were not captured, and no reliable immediately preceding backup
was found. **The file has not been claimed restored.**

The return-contract test now uses a fake sync target. The real Claude settings writer also rejects every
test-mode write, including callers that bypass the generic test guard. The corrected contract suite and
the new guard regression passed. Old dated backups, the available editor undo metadata and live editor
buffers were checked for a reliable recovery source without exposing credentials; none established the
pre-incident contents. A private post-incident snapshot is retained outside the repository at
`/tmp/task-keeper-test-incident-glo2tpsr/claude-settings-after.json`.
The user has been asked for a recent backup path or authoritative restoration source.
