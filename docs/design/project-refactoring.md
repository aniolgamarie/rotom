# Project review and refactoring plan

Status: design and staged implementation plan, 2026-10-15; runtime changes are not delivered.
The reviewed source baseline is `6e9513a`. This review covers agent configuration,
launch and supervision, dependency publication, credentials, and terminal management.
It does not renew native-host, live-account, or cross-platform acceptance.

## Intended boundaries

Make concurrent runs of different native sessions the normal Rotom contract, with
exclusive maintenance. Include DSH, Pi, and OMP; do not equate multiple TUIs with
permission for uncontrolled writers in the same Git worktree. Keep configuration,
runtime packages, credentials, native sessions, and execution evidence distinct.

Retain one `dsh-default` recipe. Do not introduce core/full/proxy profile families;
`dsh-proxy` selects process environment, not a second deployment or proxy service.
Narrow `termcfg` to zsh/tmux and remove its mihomo management through an explicit
migration. A future independent proxy project has not been created or handed control.
This planning stage changes no runtime, service, or private data.

Use unchanged upstream hosts and public APIs. Do not add a universal plugin,
approval service, audit database, or instance daemon to achieve these changes.
`workspace-write + ask`, accepted auto-review limits, and native ownership remain
separate constraints. OMP network routing is a separate project.

## Review findings and confidence

Severity describes implementation priority, not a claim of an observed incident.
Confirmed means current code or locked-source behavior; static risk still needs a
race or failure test. Native behavior remains unverified unless separately recorded.

| ID / severity | Evidence and finding | Required response |
| --- | --- | --- |
| RUN-01 / High | [runtime.py](../../src/agentcfg/runtime.py) defaults `shared_run_lease` to false, calls `prepare_runtime` inside admission, and passes lease FDs to the host. [omp.py](../../src/agentcfg/omp.py) explicitly enables shared lifecycle/state access. DSH and Pi remain exclusive. | Split maintenance preparation from ordinary-run validation before changing defaults. |
| DSH-RUN-01 / High | [profile_runtime.py](../../src/agentcfg/profile_runtime.py), `prepare`, writes pending/final ownership and module projections during each run. Confirmed shared mutation. | Prepare and migrate under exclusive maintenance; run verifies prepared resources. |
| PI-RUN-01 / High | [pi_lifecycle.py](../../src/agentcfg/pi_lifecycle.py) locks the physical instance inode exclusively. [pi_host.py](../../src/agentcfg/pi_host.py) creates a fresh activation/nonce and supervisor per run; [activity.py](../../src/agentcfg/activity.py), `allocate`, rejects protected executions from another activation. | Design run namespaces and instance-wide maintenance admission together; changing to a shared flock alone is unsafe. |
| PUB-01 / High | [dependencies.py](../../src/agentcfg/dependencies.py), `resolve_lock`, uses fixed per-file temporary names and publishes the manifest last; [omp_dependencies.py](../../src/agentcfg/omp_dependencies.py), `resolve_lock`, also publishes multiple files without repository publisher coordination. Static concurrency risk; no race reproduced. | Serialize publishers and protect readers from mixed generations; test two writers and lock-versus-sync. |
| CFG-01 / Medium | [config.py](../../src/agentcfg/config.py), `load_local`, invokes `load_secrets`; [commands.py](../../src/agentcfg/commands.py) and [workspace.py](../../src/agentcfg/workspace.py) share preparation paths used by non-launch operations. | Separate nonsecret loading from explicitly required credential reads; runtime-only resolution is not the same as avoiding early file reads. No disclosure is claimed. |
| TERM-01 / High | [cli.py](../../src/termcfg/cli.py) dispatches mihomo operations and reads its lock for general operations; [preview.py](../../src/termcfg/preview.py) always includes its output. State and recovery also encode proxy effects. | Remove the full dependency and recovery coupling, with a migration path for existing machines. |
| LEASE-01 / High | Existing [lease lifecycle issue](../known-issues.md): descendant processes can retain inherited descriptors after foreground exit. | Preserve active-host protection while defining descriptor/process lifetime; do not delete locks or kill unrelated holders. |

### DSH native-source evidence

The [locked DSH recipe](../dsh.md#packages-and-reproducibility) and
[manifest](../../locks/dsh/manifest.json) identify Core RC2, TUI `0.15.0`, and
Perry `0.12.17`. The following package-relative source evidence is not a new native
acceptance result; no pair of real TUIs was launched for this review.

- TUI `lib/types/sessionMounts.js` (530–573, 614–631, 678–705) uses a cross-process
  mount ledger; Core RC2 `@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js`
  (614–624, 666–704) uses an OS writer lease per session and rejects two writers.
- TUI `lib/types/tuiSettingsFile.js` (1–16, 51–90) and `tui-settings.js` (146–180)
  reread under `withFileLock` and write atomically; initial creation is exclusive.
  Core RC2 `@deepseek-ai/dsh-credentials-local/lib/index.js` (541–565, 604–629) and
  TUI `lib/types/dsh-adapter/oauth/credentials.js` (34–40, 113–125, 150–158, 196–203)
  also use cross-process locks. These distinct stores must retain their boundaries.
- The default base `session-query-sqlite` plugin has `openAt: never`; do not assume
  an always-open shared SQLite writer conflict from the plugin's presence.
- Perry `src/runtime.ts` (177–212, 262–289) keeps per-mount runtime state and a
  `WeakMap` keyed by Session. `src/cache.ts` (121–163) has a process-local map; TTL
  zero disables reuse. This does not prove cross-session reviewer isolation.
- The repository-owned [cursor-terminal adapter](../../agents/dsh/packages/cursor-terminal/index.mjs)
  publishes a fixed `cursor-login-url.txt` at lines 131–141 and 165–168. Concurrent
  login publication can collide even though the credential store itself is locked.
- TUI `0.15.0`, `lib/types/dsh-adapter/inject-channel.js`, lines 127–140 and
  217–236, updates `inject/servers.json` with unlocked whole-file read/modify/write.
  Concurrent updates can lose discovery records; this is not evidence of session
  JSONL corruption. Seek an upstream fix or explicitly document a supported
  degradation; do not patch the upstream package or silently claim full support.

## Identity and operation model

| Identity | Scope and owner | Must not be used as |
| --- | --- | --- |
| Deployment / instance / profile | Stable native HOME, binding, configuration generation and recovery journal | A single TUI or execution ID |
| Runtime package | Immutable lock/source/platform identity, reusable by deployments | Mutable native session storage |
| Run invocation | One admission, supervisor/control channel and foreground host lifetime | A shared activation impersonated by unrelated processes |
| Native session | Host-owned conversation identity and persistence lease | A Rotom deployment or unrestricted workspace writer |
| Pi execution attempt | Owner, task/attempt, generation, child process and termination evidence | An entire instance or another run's recovery authority |
| Git worktree | Canonical repository/worktree inode identity and write arbitration | A session name or mere path string |
| Credential provider | Operation-specific secret references and native authentication store | A generic configuration field or copied session store |

### Target lock and operation matrix

This is the target contract, not the current DSH/Pi behavior. Preserve OMP's
physical-instance → state → runtime-package nesting. The common acquisition order
is repository publication, when needed, then physical instance, deployment state,
runtime package, run records, and canonical sorted workspace leases. Take only
required locks; never acquire an earlier lock while holding a later one. Publication
and terminal-operation locks keep their own scope, not one global Rotom mutex.
Implementation must map every affected existing path to this order before coding;
if a path requires a reversal, stop for design review rather than weakening protection.

| Operation | Instance / state | Package / publication | Session / worktree / credential boundary |
| --- | --- | --- | --- |
| Ordinary run | Shared stable deployment admission | Shared verified package; no publication | New private run allocation; native session writer lease; Pi workspace arbitration |
| Prepare or migrate launch resources | Exclusive maintenance | Verified package; no implicit dependency resolution | Preserve native account/session data and managed-file ownership |
| Apply / rollback / recovery | Exclusive maintenance; inspect all active or unknown runs | Hold required package protection in order | Recovery is scoped; never erase another run's activity evidence |
| Sync / repair | Exclusive affected maintenance where activation changes | Exclusive affected package; coordinated publication reader | Do not replace a package used by active runs |
| Lock resolution | No native-session takeover | Exclusive repository publisher, staged generation and reader protocol | No account or model calls; failed publication preserves prior usable lock |
| Login / key operations | Explicit selected operation | Use prepared runtime if required | Serialize or isolate auth publication; no raw link/code/token reporting |
| Pi workspace write | Shared run admission | Existing package guard | Cross-run canonical workspace lease; same-worktree conflict remains enforced |

Ordinary run validates existing prepared resources and performs only necessary
private per-run allocation. It must not repair module links, migrate shared files,
or invoke implicit sync/apply. Missing preparation fails with an actionable
maintenance command. Unknown or unverifiable activity continues to block maintenance.

Pi's managed execution paths use canonical worktree writer leases. DSH and OMP
interactive tool actions do not acquire those Rotom leases. Parallel admission may
allow different interactive sessions in the same directory; it does not serialize
their writes. Use separate worktrees or explicitly coordinate writers. This plan
does not add universal interception of native file or shell actions. Tests must
record this boundary rather than imply that a session lock protects project files.

## Pi design decision and implementation gate

Prefer an independent supervisor and execution namespace for each run in the same
instance, with instance-wide aggregation for maintenance. Reuse existing records,
owner identities, Linux/macOS process backends, workspace leases, and generation /
termination evidence. One current supervisor already handles multiple children;
that does not establish support for multiple independent activations in one store.

Before implementation, specify the run namespace schema, registry/aggregation
protocol, atomic allocation and cleanup, owner authority, and migration from current
records. Define which records are read-only compatibility inputs and how incomplete
registration is detected. Keep cross-run worktree arbitration and canonical lock
ordering. Do not allow unrelated processes to pretend to share an activation.

Stop/recovery must address one run and its proven descendants. Instance maintenance
must consider every run, including unknown legacy owners; no deletion of old records
or assumed-dead PID may substitute for termination evidence. Retain grant generation,
nonce and process identity checks, cancellation boundaries, and failure recovery.

A central supervisor with attach/multiclient support is an alternative only if public
interfaces and lifecycle evidence establish it. That evidence is currently missing;
do not introduce a daemon or choose that architecture by assumption. The preferred
option remains a design direction, not a finalized runnable state schema.

## Dependency publication and credential loading

Use unique staging plus a publisher lease and a documented reader/snapshot protocol
for DSH/OMP lock publication. Review Pi's publication path as part of the same
inventory without assuming identical implementation. [termcfg packages](../../src/termcfg/packages.py)
already use `repository_lease` and snapshot rechecks and provide a local reference.
A manifest-last write alone does not provide atomic multi-file publication. Preserve
previous valid generations and recovery evidence across interruption; never silently
refresh digests or conflate source changes with publication fixes.

Separate configuration-only parsing/validation from SecretStore creation/loading.
Inventory `validate`, `render`, `plan`, and `doctor` call paths and state explicitly
which operations need credentials. Preserve backward-compatible inline-secret
conflict rules and strict unknown-field rejection. Key/status/login commands retain
explicitly required reads; neither a blanket ban on credentials nor broad eager reads
is the target. Tests use fictional stores and sentinels, not real account files.

## Removing mihomo from termcfg

Target: `termcfg` owns zsh/tmux configuration and their selected public dependencies.
Proxy lifecycle, subscriptions, effective configuration and service control belong
to a future independent project. The configured proxy endpoint and environment values
remain an external-service contract; agentcfg and `dsh-proxy` may consume that
contract without starting or managing the service.

Removal inventory includes:

- [mihomo.py](../../src/termcfg/mihomo.py), CLI imports/service/lock/sync dispatch,
  unconditional `_read_lock_raw` in components/plan/doctor/apply/rollback, and
  `preview.py`'s unconditional `mihomo.json` output.
- [packages.py](../../src/termcfg/packages.py)'s mixed core/plugin paths,
  [config.py](../../src/termcfg/config.py)'s component list,
  [machine/catalog/state schemas](../../schemas/termcfg/), and
  [state.py](../../src/termcfg/state.py) / [transaction.py](../../src/termcfg/transaction.py)
  fields `pending_core_effect`, `pending_config_effect`, `public_config_identity`.
- [catalog](../../terminals/catalog.json) entries `mihomo-base`/`mihomo-mgr`,
  [public assets](../../terminals/mihomo/), required licenses and provenance,
  [machine example](../../examples/termcfg-machine.toml), service/sync/catalog tests,
  README/guides, and specification references. Preserve historical records as scoped
  records; they must not advertise a still-supported removed command.

Retain generic plugin download, integrity verification, repository leases, and
transaction machinery needed by zsh/tmux. Resolve dependencies by current selection;
removing mihomo must not require its lock or break unrelated terminal operations.

Provide an explicit migration entry point before tightening schemas. Existing machine
components and state/journals containing mihomo must not be silently dropped or
render zsh/tmux recovery impossible. Design versioned legacy-schema validation,
read-only archival and a documented recovery path; unknown fields still fail.
Record a private handoff manifest of paths and metadata only. Do not read subscription,
secret, or effective-configuration bodies, automatically copy private data, stop/delete
an active proxy, or modify business HOME directories. Keep unresolved active ownership
as a blocker to destructive removal. Reversal must preserve old state and supported
recovery inputs without pretending an external proxy service has been transferred.

## Independently reviewable work packages

| Stage / state | Owned scope and prerequisite | Acceptance and recovery gate |
| --- | --- | --- |
| 0 / Review completed | This design and linked architecture/issues; source baseline `6e9513a` | Findings, scope and operation matrix reviewed; nine-file offline baseline: 189 passed, exit 0; scope below. No runtime or service changes. |
| 1 / Planned | Shared admission/preparation contract; `runtime.py`, adapter hooks, DSH profile preparation | Fake-process tests show parallel distinct runs and exclusive maintenance; interrupted preparation, drift and unknown ownership fail safely. Test descendant descriptor retention, foreground exit and active delegated work before releasing protection. Preserve OMP behavior and fixed lock order. |
| 2 / Planned | Pi namespace/schema and owner migration design, then lifecycle/activity/supervisor implementation | Design approval first; two independent runs, children and cross-run worktree conflicts, targeted stop/recovery, stale generations, PID reuse, crash and unknown legacy records. Maintain old evidence and test rollback compatibility. |
| 3 / Planned | Repository lock publication in DSH/OMP, with Pi path inventory | Two writers, lock-versus-sync, interruption at each publish boundary, reader recheck, and previous-lock restoration. No mixed generation accepted; no lock/source mismatch hidden. |
| 4 / Planned | Nonsecret loading and explicit credential operation paths | Sentinel tests prove configuration-only operations avoid secret bodies; inline conflict/error behavior and required key/status/login access remain compatible. No real credential reads. |
| 5 / Planned | termcfg legacy-state migration, then mihomo removal across inventory | Old machine, state and pending-journal fixtures migrate or recover explicitly; zsh/tmux-only operations work without a mihomo lock; generic plugin integrity and rollback remain tested. Check concurrent distinct machine IDs targeting the same canonical HOME before claiming cross-machine exclusion; that case is unverified. No service/secret migration. |
| 6 / Not run | Authorized native and platform validation after implementation and matching locks | DSH distinct-session parallel use, same-session refusal, settings merge, auth serialization/isolation, inject discovery outcome and reviewer separation; Pi true lock closure before current native/cold tests; OMP regression. Test missing/corrupt/unwritable mount ledgers and their recovery, distinguishing existing mounts from new-session reservations. Verify canonical path/alias handling and Pi cross-run worktree conflicts; record DSH/OMP's manual writer-coordination boundary. Record every untested platform. |

Keep each stage as focused commits with affected offline tests and stable final review.
Run shared-infrastructure regression for all adapters when its contract changes.
Do not flip the global default until the applicable adapters satisfy their gates;
intermediate releases must state adapter-specific support rather than imply parity.
If native public APIs cannot meet a gate, escalate the limitation and choose an explicit
supported scope; do not ship a host patch or weaken an ownership check.

## Evidence, migration and non-goals

Nine existing offline test files were executed against unchanged candidate
`6e9513af16932bce98b3a930a7f662ccf412cf83` on Linux x86_64, CPython 3.11.11:
**189 passed**, exit 0, pytest duration 153.12 seconds (runner 153.42 seconds),
2026-10-15 03:56:51Z–03:59:24Z. The invocation used `pytest -q -p no:cacheprovider`
and `--basetemp=<temporary>/pytest`, with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, isolated
HOME/DSH_HOME/XDG, network guards and fake processes. The retained log SHA-256 is
`80dfe00df7d34feb7c02ccbf7fd64f492cc9fadc296959925252819240679e0c`.
The selected files were `tests/test_runtime.py`, `tests/test_deployment.py`,
`tests/test_review_hardening.py`, `tests/test_omp_runtime_foundation.py`,
`tests/test_pi_host.py`, `tests/test_pi_activity.py`, `tests/test_pi_workspace_leases.py`,
`tests/test_pi_supervisor.py`, and `tests/test_termcfg_service.py`.
This is a regression baseline, not evidence that planned concurrent runs work.
Documentation checks cover links, selected public paths and whitespace. Native hosts,
real account data, network calls and new race tests were not executed.

Preserve PI-LOCK, PI-SOURCE/RM-001, REVIEW-F02, DSH-AR-01–04, LEASE-01/RM-002,
and platform/live gaps as independent issues. Pi requires real source/lock closure,
not a hash-only repair. OMP-NET is not part of this concurrency change.

The cleaned `main` has since been manually pushed by the user and anonymously
verified; this does not rewrite the original local-cleanup evidence or authorize
other ref changes. The retained remote Pi feature branch has old lineage: replay
reviewed changes from clean `main`, never ordinarily merge it. All worktrees retain
[the same integration gates](../worktrees.md), including privacy and public identity.
No historical acceptance is renewed by this plan, and no unrelated user work,
credential state, runtime service, or upstream source may be changed implicitly.
