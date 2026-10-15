# Project review and refactoring plan

Status: implemented and verified within the Linux scope below, 2026-10-15. This record distinguishes
implemented contracts, executed tests and remaining native/platform evidence.
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
Implementation preserves existing deployments, running services and private data.

Use unchanged upstream hosts and public APIs. Do not add a universal plugin,
approval service, audit database, or instance daemon to achieve these changes.
`workspace-write + ask`, accepted auto-review limits, and native ownership remain
separate constraints. OMP network routing is a separate project.

## Review findings and confidence

Severity describes implementation priority, not a claim of an observed incident.
The findings table describes the reviewed baseline, before implementation.
Confirmed means baseline code or locked-source behavior; completion is listed below. Native behavior remains unverified unless separately recorded.

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
acceptance result; native concurrency results are recorded separately below.

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

This is the implemented admission and maintenance contract; native coverage is separately recorded. Preserve OMP's
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

The implementation retains the existing globally unique execution IDs and evidence
store. Each run has its own supervisor, activation, nonce and endpoint at
`activity/control/<activation>/control.json`; no new daemon or registry is introduced.
Version 2 owner markers permit coexistence only when the exact peer process and owner
are proven live. Legacy, dead, malformed or unknown protected records fail closed.

A short instance-wide mutation lease serializes allocation and updates; readers reject
in-flight snapshots. Supervisors defer transient busy reads rather than abandoning
children. Capacity remains per run. Project-resource discovery still takes exclusive physical
admission: cwd-dependent native role projections have not been separated by run.
Instance-wide native UI preferences have no new transaction guarantee across processes;
concurrent settings editing is not validated. Workspace writer leases remain instance-wide and
use canonical worktree identity. Every control, parent/child and summary lookup is
scoped to the complete owner. Legacy fixed endpoints are accepted only for an exact
matching owner; endpoint discovery never scans for a convenient live peer.

Maintenance considers all records. Targeted recovery retains generation/termination
proof and may address a dead owner while another proven run remains active. Recovery
of version 2 records preserves interrupted recovery evidence. Unknown records cannot
be discarded to admit a launch. The saved launch contract declares supervisor
protocol 2: old contracts must be explicitly rebuilt, synced and applied with matching
source. Old sealed runtimes are retained; the new manager refuses to launch an old
exclusive supervisor through shared admission.

DSH preparation participates in the deployment journal before any shared projection
changes. Recovery selects the persisted current launch and restores its projections
before removing the journal. Repeated interruption retains the observed owned link
values; external drift remains a conflict. Ordinary run only validates these resources.
This restores configuration and launch preparation, not native account/session data.

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

The removal inventory describes baseline `6e9513a`; runtime and asset removal is
implemented. [Migration](../../src/termcfg/migration.py) owns metadata compatibility.

The baseline inventory includes:

- former `src/termcfg/mihomo.py`, CLI imports/service/lock/sync dispatch,
  unconditional `_read_lock_raw` in components/plan/doctor/apply/rollback, and
  `preview.py`'s unconditional `mihomo.json` output.
- [packages.py](../../src/termcfg/packages.py)'s mixed core/plugin paths,
  [config.py](../../src/termcfg/config.py)'s component list,
  [machine/catalog/state schemas](../../schemas/termcfg/), and
  [state.py](../../src/termcfg/state.py) / [transaction.py](../../src/termcfg/transaction.py)
  fields `pending_core_effect`, `pending_config_effect`, `public_config_identity`.
- [catalog](../../terminals/catalog.json) entries `mihomo-base`/`mihomo-mgr`,
  former `terminals/mihomo/` public assets, required licenses and provenance,
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
| 1 / Implemented and tested | Shared admission/preparation contract; `runtime.py`, adapter hooks, DSH profile preparation | Offline tests cover parallel distinct runs, exclusive maintenance, interrupted preparation, drift, unknown ownership and repeated recovery interruption. Descendant descriptor retention remains LEASE-01; protection is preserved rather than removed. |
| 2 / Implemented; native evidence separate | Pi namespace/schema and owner migration design, then lifecycle/activity/supervisor implementation | Existing global store with version 2 owner markers and per-run endpoints; two independent runs, children and cross-run worktree conflicts, targeted stop/recovery, stale generations, PID reuse, crash and unknown legacy records. Maintain old evidence and test rollback compatibility. |
| 3 / Implemented for DSH/OMP | Repository lock publication in DSH/OMP, with Pi path inventory | Two writers, lock-versus-sync, interruption at each publish boundary, reader recheck, and previous-lock restoration. No mixed generation accepted; no lock/source mismatch hidden. |
| 4 / Implemented; 220 targeted tests passed | Nonsecret loading and explicit credential operation paths | Sentinel tests prove configuration-only operations avoid secret bodies; inline conflict/error behavior and required key/status/login access remain compatible. No real credential reads. |
| 5 / Implemented; 106 isolated tests passed | termcfg v1 metadata migration and mihomo removal across inventory | Old machine, state and pending-journal fixtures migrate or recover explicitly; zsh/tmux-only operations work without a mihomo lock; generic plugin integrity and rollback remain tested. A bounded test confirms different machine IDs sharing HOME are not serialized; use one machine ID per HOME. No service/secret migration. |
| 6 / Linux native concurrency passed; extended scopes separate | Authorized native validation after implementation and matching locks | DSH distinct sessions and simultaneous-resume refusal; Pi independent live supervisors, owner-specific control, namespace and terminal restoration; Pi sandboxed resource round trip. Settings/auth stress, other profiles/platforms and reviewer isolation retain their explicit unverified scope. OMP regression uses the offline suite. |

Keep each stage as focused commits with affected offline tests and stable final review.
Run shared-infrastructure regression for all adapters when its contract changes.
Shared admission is the base adapter default. Native validation and deployment remain
adapter-specific; do not infer platform or authentication parity from that default.
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

Track PI-LOCK separately until real materialization/native evidence is recorded; preserve PI-SOURCE/RM-001, REVIEW-F02, DSH-AR-01–04, LEASE-01/RM-002,
and platform/live gaps as independent issues. Pi requires real source/lock closure,
not a hash-only repair. Pi publication still has dynamic vendor/profile paths and no
new multi-publisher protocol; serialize explicit Pi lock resolution. OMP-NET is not part of this concurrency change.

The cleaned `main` has since been manually pushed by the user and anonymously
verified; this does not rewrite the original local-cleanup evidence or authorize
other ref changes. The retained remote Pi feature branch has old lineage: replay
reviewed changes from clean `main`, never ordinarily merge it. All worktrees retain
[the same integration gates](../worktrees.md), including privacy and public identity.
No historical acceptance is renewed by this plan, and no unrelated user work,
credential state, runtime service, or upstream source may be changed implicitly.

## Implementation and acceptance record

The runtime implementation is committed as `3720067`, following focused terminal,
credential, publication and shared-admission commits. At implementation acceptance,
target `main` was `6e9513a`; no merge, push or real-machine deployment had been
performed. Runtime code was frozen before the final offline rerun. Later documentation and smoke-harness
changes do not modify the managed host or package inputs.

The user subsequently authorized integration into `main` and local redeployment.
The local integration and deployment results are recorded below; no remote push
was performed or authorized by that integration.

Platform: Linux x86_64, CPython 3.11.11, Node 24.14.0 and npm 11.19.1. The isolated
toolchain uses the exact declared npm tarball and integrity; no global tool was
replaced. DSH and OMP retain their original locks. Pi's final complete lock is
`f9ed17268271f5f0565604f71791d3c74d88b1d1a477b4dc1784f45f69e8e08c`.
All four npm slices were resolved through the real backend. Direct pins remain
unchanged; resolution updates 70 transitive versions in each Node slice and 71 in
the Cursor slice, adding one transitive package in each. Only pi-default was
materialized and exercised natively. Downloads and large public assets reused
verified caches: this is not four-profile or cold-download acceptance.

Native commands use the explicit entries in [testing](../testing.md#concurrent-run-validation).
Raw results retain exact argv, configuration/lock/source digests, exit codes and
private log hashes. They are not published with machine paths or account data.

| Evidence | Result and scope | Private result SHA-256 |
| --- | --- | --- |
| DSH CLI/TUI, including same-session refusal | PASS: independent results, explicit occupied-session refusal, no collision requests, original session remains responsive, maintenance `4/4/0`, both original exits 0, terminal restored, source unchanged; five loopback requests, zero live calls | `2f5867431046c56205ddc6f104813f28ab588c92a461522aeff55af451aae643` |
| Pi concurrent CLI/TUI | PASS: two complete live owners, unique endpoints/activations, cross-owner refusal, verified PID namespaces, maintenance `4/4/0`, exits 0 and terminal restored; zero model requests | `e4e1505821c5d14056b7d9042bdae4b3e047d3f52d58930bca6fd87e53153c2d` |
| Pi native host-resources | PASS: unchanged outer filesystem sandbox, real SDK, guarded read, two synthetic model requests, exit 0 and confirmed termination | `ecac1e199421d3bd11992bb606be641f8abef7c2566aefd3ef877425626394c3` |
| Pi control directory and OS mapping | PASS: unanchored and incorrect-directory requests fail before opening a socket; the exact parent-verified directory completes real RPC under the unchanged PID namespace flags | `0a615036439c5cfe2db2bde84ee5dc9449f2c400ae9fb2d36ad1bc4300c58634` |

Pi's first interactive launch failed because namespace UID mapping hid trusted root
ancestry. The fix preserves ordinary path validation and passes only an exact
parent-verified control-directory identity to runtime clients. It exposes a fixed,
bounded, read-only control record, retaining socket, peer and capability checks.
It does not trust unmapped UIDs or alter the upstream host. The fix passed 84 related
offline cases, 12 isolated Node mocks, independent review and the native checks above.

A later Pi concurrency attempt hit the original 180-second harness budget after
the first TUI became ready. The final bounded harness records stage timings:
preparation/copy/apply/sync consumed 106.7 seconds, and both TUIs became ready at
139.3 and 175.2 seconds. A 600-second total budget permits the remaining checks;
readiness, ownership, sandbox, execution-count and exit criteria were not relaxed.

An earlier full run exposed 16 regressions in legacy probe preparation, a test
publisher operating on the actual repository, and OMP drift-injection hooks after
preparation moved to maintenance. Those paths were corrected and retested before
the final run. The publisher test now uses its own copied repository.

One superseded full-suite attempt exhausted temporary storage and is recorded as
an environment failure. Its output is not counted as passing evidence. Closed
task-owned fixture inputs were retired after private log preservation; the final
rerun retains failed pytest fixtures and promptly removes passed ones. No system
permissions, sandbox, proxy service or real account state were changed.

The final full offline run covered all **3,813 collected cases in 204 files**,
partitioned into two disjoint groups with the unchanged network/host/account guards:

| Group | Actual result | Exit | Retained log SHA-256 |
| --- | --- | --- | --- |
| 102 files | 2,226 passed, 13 skipped, 7 subtests passed; 986.54 seconds | 0 | `858d57eb452c8dce5028859ab6ca13973f28809fc47d2f52eba7d393e7f1b3c0` |
| 102 files | 1,574 passed; 1,027.22 seconds | 0 | `fbb3f2b545df38e571db3128be52b2f3824db2bafd1f8e58cbbaf2297b513e8b` |

Combined: **3,800 passed, 13 skipped, 7 subtests passed**. A separate explicit
Node/rg toolchain run passed all five ReadSeek binding tests, covering four of the
skipped cases without starting a third-party host. The remaining nine skips are
seven retired OMP host-patch fixtures and two unavailable locked-Bun standalone
checks; they are not passes. The 12 restricted Node mocks, public-document checker,
whitespace check and Python offline lock check also passed. The ordinary pytest
entry and its isolation contract are unchanged.

| Work state | Scope |
| --- | --- |
| Completed | Implementation and Linux validation above; fast-forward integration into local `main` at `de2201b`; local DSH apply and deployment/admission checks; termcfg v2 migration and terminal apply; local OMP apply, doctor, plan and repeated apply below |
| In progress | None within the authorized local integration and deployment scope. Release and remote publication remain separate |
| Failed pending decision | No unresolved implementation failure in the recorded scope; superseded failures and fixes remain documented above |
| Environment unavailable or not run | Other operating systems; Pi Cursor/Bun and other profile native/cold builds; real accounts, concurrent login/refresh and UI-preference stress; broader MCP/PTC/reviewer coverage |

### Local integration and deployment follow-up

The reviewed candidate was fast-forwarded from cleaned `main` to `de2201b` locally,
without a push. The existing Linux DSH `dsh-default` deployment then passed official
apply with zero changes. Doctor reported offline-ready, installed dependencies, no
pending transaction, and zero changes, drift or conflicts; repeated apply was
idempotent. Checks against the deployed resources and two simultaneous shared
admissions passed, with exclusive maintenance refused while admission was held.
These are deployment and lease checks, not a new dual-TUI or live-account test.
The `dsh` and `dsh-proxy` shortcuts still select the same main-checkout deployment;
the latter's loopback port 10808 setting changes only the launched process environment.

The termcfg legacy state had no pending transaction. Explicit `migrate --drop-mihomo`
completed, v2 status and strict doctor passed, and apply succeeded with all four
terminal targets unchanged. The existing proxy service was not operated on.
No managed Pi instance was present, so no additional Pi deployment was created.

For `omp-kernel`, the initial apply returned exit 4 because a native process held
the activity lock. That process was not terminated. After the user exited OMP,
the maintenance lease was available and official apply, doctor, plan and repeated
apply all returned exit 0. Doctor reported offline-ready, installed dependencies,
a matching deployed runtime and no pending transaction. Plan and both applies
reported zero changes, drift or conflicts. This follow-up did not start a host,
inspect credential/account files or call a model.

The command selections below use a generic machine name; private paths and native
account state are not part of this public record. Replace `<reviewed-plan-id>` with
the plan ID from the preceding termcfg plan after reviewing that plan:

```sh
./agentcfg --machine workstation --profile dsh-default apply
./agentcfg --machine workstation --profile dsh-default doctor
./agentcfg --machine workstation --profile dsh-default apply
./termcfg --machine workstation migrate --drop-mihomo
./termcfg --machine workstation status
./termcfg --machine workstation doctor --strict
./termcfg --machine workstation plan
./termcfg --machine workstation apply --plan-id <reviewed-plan-id>
./agentcfg --machine workstation --profile omp-kernel plan
./agentcfg --machine workstation --profile omp-kernel apply
./agentcfg --machine workstation --profile omp-kernel doctor
./agentcfg --machine workstation --profile omp-kernel plan
./agentcfg --machine workstation --profile omp-kernel apply
```

Existing deployments remain available. Stop their sessions before explicit
`plan`/`sync`/`apply`; old Pi launch contracts require migration rather than implicit
reinterpretation. termcfg v1 state uses `recover` when necessary, followed by
`migrate --drop-mihomo`. That operation retires ownership metadata and does not
transfer a service to a new project. Configuration rollback is not a software or
session-database downgrade. Preserve matching old software and data separately;
do not hand new session data to an older host and claim recovery.
