# DSH ecosystem upgrade — 2026-10-21

This records the original development-base implementation. The later [current-main integration acceptance](dsh-main-integration-20261021.md) preserves its source/lock scope and reruns affected offline and native checks on clean main, including main's existing Pi fixture revisions.

This record follows the whole-ecosystem review and the explicit implementation authorization. Work is confined to the dedicated `feat/dsh-ecosystem-upgrade` worktree, based on `b18da6d`. The existing Perry candidate is retained. No production deployment, Git integration, or publication is included.

## Selected inputs and boundaries

| Component | Decision |
| --- | --- |
| Core and official optional packages | Keep the `0.2.1-rc.2` cohort and the existing independently versioned foundational packages |
| TUI | Use official published `0.16.1`, source `73ff99fbed56563bf154d719effd09f9f9725349`, replacing the `e709863` source build |
| Cursor subscription | Keep official `0.6.12` |
| Own OAuth adapters | Repack compatible peer metadata and verify the public `./oauth` exports; preserve credential/session ownership |
| Perry | Keep official `0.13.7`, workspace-write + ask, bounded single-call escalation review, and configuration diagnostics |
| Official Full-access Auto review | Keep disabled and outside the default composition |
| Agent Teams | Explicit optional plugin, absent from defaults; use official public configuration and packages only |
| Deployment and lifecycle | Keep existing exclusive maintenance and shared run admission; do not terminate active instances |

The actual TUI source delta is seven commits. The old source already includes rc.2 compatibility, scroll anchoring, background compaction, paged history, plugin management, and asynchronous Codex questions. New functionality is Teams and official Auto review presentation; standalone-launch and platform-SDK-update fixes have limited applicability to Rotom's Core `runProfile` launcher. Sources: [exact comparison](https://github.com/ccch1mneyyy/dsh-TUI/compare/e709863019d56897e64495699c3a945cce194d00...v0.16.1), [TUI release](https://github.com/ccch1mneyyy/dsh-TUI/releases/tag/v0.16.1), and [Core release](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.1-rc.2).

Perry on the selected Core uses a no-tool inline request; the conditional reviewer preset is not its active review path. Historical OFF/late-approval and persistent verdict-audit limitations remain open. The earlier [Perry acceptance](dsh-perry-public-integration-20261021.md) does not validate the new TUI composition.

## Implementation and acceptance plan

1. Update official TUI selection, own OAuth package peers/archives, public runtime checks, and the complete dependency lock as one consistent input set.
2. Expose Teams through the existing explicit optional-plugin selection. Preserve default ordinary delegation, existing profile ownership, and journaled managed-patch updates. No native package-manager mutation is part of apply/run.
3. Test strict selection, SSH rejection, on/off configuration transitions, native drift/conflict, interruption recovery, and default invariance with isolated fake state.
4. Prepare a frozen official runtime, check public module identities, then run the authorized isolated native Perry, TUI, OAuth-interface, and Teams fixtures. Use fictional models and synthetic files; real accounts and remote endpoints remain separate.
5. Review the stable final source/lock delta and public content. Record actual argv, exit codes, lock/source identities, and verification limits.

Teams uses named teammates, direct inbox messaging, and a persistent task board in one shared workspace. It does not provide file locking, cross-process coordination, exactly-once delivery, or automatic task release after member failure. Native message acceptance must not be reported as model processing. See the [official Team contract](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/experimental/agent-team/README.md).

## Task status

| State | Scope |
| --- | --- |
| Completed | Source/release review and migration; official TUI/own archives/full lock; explicit Teams integration; isolated tests and authorized native acceptance below; stable source/lock and public-content review |
| In progress | No remaining implementation work in this scope |
| Historical baseline failures | Seven pre-existing Pi environment-fixture failures were reproduced on the original base; that command remains failed. The current-main integration separately preserves main's existing fixture revisions and validates the resulting combination. |
| Environment insufficient / unverified | Real accounts and external model services; SSH/tmux clients; other platforms; crash/reboot/multiple-writer Teams recovery; historical Perry OFF/late-approval cases and complete persistent verdict audit |
| User-deferred operational issue | Daily launcher rejects a Pi machine option during whole-machine schema validation; no live configuration, launcher, or deployment repair was performed |

## Frozen inputs

The complete lock identity is `e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d`; recipe digest is `76cb4d64f9b225d312f95dd1ef8ffbcf8cc11dc89bfcb221fc4883ebe6b8839f`. The root manifest has 155 direct dependencies. All four official Teams packages are exact `0.2.1-rc.2` pins. Own package sources match their fixed archives; old TUI provenance remains historical and is no longer an input to the npm-based recipe.

The final uncommitted code/dependency/test digest is `02968c4025d0f91d8faced1a1d1b405fb854e7d16d9fe6fe01491fc4c8ead6c0`. It hashes the sorted changed paths under `src/`, `agents/`, `locks/`, `scripts/`, and `tests/` as `path + NUL + SHA256(bytes) + newline`; documentation is outside that digest. The private candidate manifest lists every file hash and six native report/source comparisons. The sealed runtime was rechecked as `installed`. This identifies the reviewed worktree bytes; it is not a published commit or permission to merge old-lineage history.

The normal resolver/publisher required trusted ancestor permissions, so it ran in a private temporary mirror. Its output was transferred byte-for-byte, manifest last, and both copies passed `read_lock`. The independent frozen installation, official spawn-helper preparation, public imports/version/realpath checks, and formal runtime sealing all exited 0. No path guard, peer declaration, or upstream package was patched. Installation did not modify package or pnpm-lock bytes. The actual commands used the pinned Node `24.14.0`, npm `11.19.1`, and pnpm `11.19.0`:

```text
node <runtime>/.tooling/pnpm/package/bin/pnpm.cjs install --frozen-lockfile --ignore-scripts --node-linker=hoisted --package-import-method=copy --store-dir <private-store>
node agents/dsh/templates/check-runtime.mjs <runtime>
```

New own archive SHA-256 values are:

| Archive | SHA-256 |
| --- | --- |
| cursor-terminal `0.1.3` | `fbcc7767c0f850b002f6e088a5861042d29e1e494762d6fc9c566c9821a9a280` |
| ssh-subscription-auth `0.1.1` | `4d5451622d13f46183bf33a017a611f146d03fe902e8728c4e4c35ba8645d97e` |

## Deployment selection and recovery

`agent-teams` is absent from defaults and rejected by the headless SSH composition. Local rendering adds a private managed `dsh-home/.agentcfg-agent-teams.json` containing a schema version and boolean selection. Profile preparation and verification read that deployed file, rather than an unapplied machine override. Older deployments without it select Teams OFF. The official Team profile bundle is appended only when the deployed flag is true; Rotom does not reproduce its service implementation or invoke a package installer during apply/run.

The existing transaction remains journal → prepare → managed writes → deployment-state commit → final preparation/recovery → journal removal. The transaction implementation and shared/exclusive admission were not changed. A pre-commit preparation failure recovers the previous selection; a post-commit preparation failure completes the committed selection. Owner metadata retains observed/pending bundle values so an interrupted preparation remains recoverable. Unknown native manifest mutations conflict. This is recoverable journal behavior, not a claim of one atomic filesystem transaction.

Tests cover unapplied ON and OFF edits, enable, rollback using current machine options, pre/post-commit interruptions, invalid deployed metadata, external bundle drift, active-run refusal, and deletion/toggling of the guarded selection before `runtime.run`. The run-drift cases spawn no subprocess and leave the manifest unchanged. Existing account/session sentinels remain untouched. No active process is stopped or reconfigured.

## Isolated checks

| Check group | Result |
| --- | --- |
| Dependency and lock-publication contracts | 156 passed; exit 0 |
| Existing optional-profile, profile ownership and preparation/recovery checks | 54 passed across the selected files |
| Teams selection/lifecycle/drift checks | 16 passed; exit 0 across the initial 14-case run and two added run-drift cases |
| Explicit Teams native-entry refusal checks | 2 passed; exit 0 |
| Broader affected manager/DSH/runtime/presentation group | 354 passed, 7 failed, 0 skipped; exit 1 |
| Own DSH extension Node checks | 76 passed; exit 0 in a fresh HOME with no host or network |
| Public Cursor protocol and synthetic authentication APIs | Exit 0; cold/checkpoint/tool-result protocol, redaction, expiry, cancellation, late refresh and prepared-generation cases passed |
| Syntax and final diff/public-content checks | Passed |

The seven failures are in `test_execution_environment_runtime.py`: six Pi reserved-environment parameter cases and one fixed-Bun-options case fail because a minimal Pi fixture omits `resolved.data.plugins`. The same selected tests on unchanged base `b18da6d` produced **7 failed, 4 passed, 11 deselected**, exit 1, at the same `PiAdapter.adjust_launch_environment` lookup. Neither Pi source nor that test was changed. This establishes a baseline failure, not a successful full suite or a new DSH regression. The earlier source-only Perry record's counts are not added to these results.

The first shared-mount pytest attempts hit existing ancestor-owner/path protections. Successful reruns used private system-temporary test bases with real metadata; the guards were retained. An initial combined public-API/Node harness leaked its own smoke-only variable names into an exact environment assertion; rerunning Node tests with a fresh finite environment passed. Early fixture failures are retained privately and are not counted as passes.

Actual isolated argv used the following forms; logs record the exact selected files and exits:

```text
.venv/bin/python -m pytest -q --tb=short -o tmp_path_retention_policy=failed tests/<selected-file>.py --basetemp <private-test-base>
node --test tests/node/dsh_*.test.mjs
node scripts/smoke-dsh.mjs <sealed-runtime> --protocol-only
```

## Authorized native acceptance

All runs used unmodified sealed packages, new HOME/DSH/XDG directories, synthetic files and fictional model routes. TUI HTTP traffic was limited to a local fake model service. The final scripts' recorded source fingerprints match the executed tree. Raw evidence remains in ignored private directories; reports and logs are mode `0600`, evidence roots `0700`.

| Native fixture | Observed result |
| --- | --- |
| Perry formal / manual / timeout | All three profiles and outer command exit 0. Allow/deny, high-risk/error fallback, budgets, unknown tools, ordinary bypass, cancellation and manual mode passed. The same outside-workspace Bash command was denied, explicitly granted once, and denied again with only one appended marker. Session remained workspace-write + ask. |
| TUI session-resume | New and resumed PTY processes exit 0, route/history restored, terminal settings restored |
| TUI settings-migration | First import, native user preference and effort persistence, model cancel and repeated apply passed; both processes exit 0 and terminal restored |
| Real agentcfg CLI → TUI | Apply/sync/run exit 0; welcome empty Enter, Chinese paste, narrow layout, real file write, active-stream cancellation, exit and lease release passed |
| TUI + Perry + Teams | `/team status` positively reports bundle ON/service running; `/auto-review status` reports ON; subsequent write, cancel and exit passed; status commands made zero model requests |
| Teams OFF → ON → new-host resume → OFF | Four separate host processes exit 0. Ordinary delegation returns when OFF. A genuine model tool call creates a fresh teammate; public service API creates a fork. Inbox acceptance and subsequent model processing are checked separately. Task claim/complete, stale-revision rejection and retained assignment after interrupt pass. A new host restores the lead roster and task state. |
| Teams + actual Perry pending-write flow | A real lead `followup` produces a native write tool call; a public test-only handler makes that synthetic request pending. Perry receives no tools, returns one low-risk allow, and one native fixture write succeeds. |

The Teams fixture uses real current Agent identities from the public registry and genuine Agent-produced logs. A continuation can replace its inactive Agent object; tests use the current live identity rather than fabricating a caller. Task claims remain assigned after interrupt. The clean shutdown/resume test does not prove crash recovery, cross-process multiwriter coordination, automatic task release, message deduplication, or exactly-once processing. The pending-write handler is fixture-only; ordinary workspace writes do not inherently enter AI review. Real model judgment and account entitlement were not tested.

```text
.venv/bin/python scripts/smoke-dsh-formal-review.py --allow-host --runtime <sealed-runtime> --evidence <private-persistent-evidence>
.venv/bin/python scripts/smoke-dsh-ui.py --allow-host --runtime <sealed-runtime> --evidence <private-evidence> --session-resume
.venv/bin/python scripts/smoke-dsh-ui.py --allow-host --runtime <sealed-runtime> --evidence <private-evidence> --settings-migration
.venv/bin/python scripts/smoke-dsh-ui.py --allow-host --runtime <sealed-runtime> --evidence <private-evidence> --agentcfg-cli
.venv/bin/python scripts/smoke-dsh-ui.py --allow-host --runtime <sealed-runtime> --evidence <private-evidence> --agentcfg-cli --agent-teams
.venv/bin/python scripts/smoke-dsh-agent-teams.py --allow-host --runtime <sealed-runtime> --evidence <private-evidence>
```

Execution used executor (`gpt-6.1-sol`, medium) for frozen dependencies, TUI fixtures and documentation, and scout (`gpt-6-luna`, high) for source/lock and API evidence. The main agent owned Teams preparation/recovery decisions, native Perry/Teams acceptance, baseline-failure comparison and final review. No upstream host, vendor source, cache code, private API, or monkey patch was used.

## Daily-entry schema finding

The reported daily launchers still target the original checkout. They reject the machine file before DSH starts because both Pi profile overrides contain `agent_options.discovery.project_trust`, while that checkout's closed Pi discovery schema accepts `project_resources`. Local validation covers every profile before resolving the selected one, so this also blocks a DSH command. This finding used field names and schema constraints only; it did not resolve credentials or inspect real sessions.

The evidence does not establish who wrote the field or when it first blocked startup, and does not establish a new-runtime deployment as its cause. The user deferred restoration. No live configuration, wrapper, account or session repair was made. [Worktree gates](../worktrees.md#preserve-daily-launchers-during-worktree-changes) now require inspecting launcher code targets and validating the full machine schema before and after migration. Passing isolated fixtures does not establish daily-entry compatibility. Production deployment, Git integration and remote publication remain outside this completed implementation scope.
