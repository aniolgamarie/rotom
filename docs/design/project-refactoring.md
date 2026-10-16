# Project review and refactoring plan

Status: concurrency, terminal-scope and review fixes were verified in the Linux
scope below on 2026-10-15. The execution-environment follow-up is also implemented;
its separate 2026-10-16 acceptance and review record appears at the end. This record
distinguishes implemented contracts, executed tests and remaining native/platform evidence.
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


### Whole-project review fixes, 2026-10-15

This repair follows base `4610678` and preserves the existing software pins. It
fixes the OMP reviewer endpoint join for custom OpenAI-compatible paths and rejects
explicit Bash startup inputs before raw permission commands, including a change
while approval is pending. Normal native shell execution is unchanged.

Pi now uses official loader configuration, public session events and stable
Rotom-owned method delegates. It no longer changes SDK methods/prototypes, calls
private request/session methods, imports private MIME helpers, or instruments Node
HTTP/2 for Cursor delegates. Model routes exposed by the adapter are immutable
snapshots. Activity and resource-digest checks run before the managed TUI calls
native reload; the injected resource loader also checks content before and after
reload. Worker registries contain only their granted tools, with built-ins and
resource discovery disabled. These are managed adapter boundaries, not isolation
from malicious trusted extensions or same-user processes.

Two capabilities remain explicitly unavailable pending upstream public APIs:
native Pi `/import`, whose pre-switch event does not expose the source before
copying, and Cursor read-only `model_delegate`, whose plugin has no public transport
audit injection. Cursor delegation fails before reading credentials or spawning a
worker. Current-format session resume/fork and ordinary Cursor main sessions are
retained; DSH Cursor is outside this change.

Ignored Pi asset files are optional verified download caches. Offline lock reading
succeeds without them; explicit installation downloads only absent entries and
checks the locked URL, size and digest. Existing damaged or unsafe cache entries
fail without network fallback. The lock recipe and installed launcher now share
one source inventory, including model-delegate wrappers and public schemas.
Maintenance instructions distinguish private configuration changes from public
OMP/Pi source changes requiring an explicit complete-lock rebuild.

| Component | Final identity |
| --- | --- |
| DSH lock, unchanged | `bbd0cbc2f4c80d7b6422a2879837f82f701ed06dba730360904623a46cceea7b` |
| OMP full lock | `90357d838801ddab2d3ebe54d57f8cdc49ca31870b9c1e9615409ab58be592ca` |
| Pi full lock | `471b0da5230b29e25e8a7fc06706437f872d2f2979e62ac6e6daff704c47fa46` |
| Pi recipe | `c2f13e81882270e5d111a895eb1bfeaee4a82d9b83b4b953e00b3355cfc436d7` |
| Linux pi-default sealed runtime | `9bc1722cade725a15b743745a8f099bcbe840425e84d2ae12b7d33b3b1bcaff7` |
| Native concurrency source digest | `7a7643bdcf5bd0c955118c2238a98b5e263544c0226c888391df2ab188681e9e` |

Both locks were generated by the actual fixed-version resolvers. A private source
snapshot was used because the development mount's ancestors permit other-user
writes and are unsuitable for the private publication journal. No permission
checks were weakened. Source inventories were compared before copying the public
lock outputs back, then checked with the ordinary readers. Pi's four complete
profile slices were rebuilt; direct pins did not change. The pi-default resolution
changed only the root record and the local runtime archive. Intermediate unreferenced
archives created by this repair were removed; pre-existing fallback material remains.

| Validation | Result and scope |
| --- | --- |
| Full offline pytest coverage | PASS: 3,820 passed, 7 skipped, 7 subtests passed; all 3,827 collected cases covered after file-level deduplication |
| Pi runtime mocks | PASS: 278 tests through the official temporary-HOME, network/process-blocked Node entry |
| OMP focused checks | PASS: 90 pytest tests, including 487 Bun tests and 12 official-wrapper checks |
| Pi dependency/asset/delegate focused checks | PASS: 59 tests |
| Public source-only reconstruction | PASS: DSH, OMP and Pi locks read with downloads blocked and zero Pi asset cache entries; metadata validation, not a cold install |
| Real SDK, controlled driver | PASS: 12 checks, zero model calls; selected extension/model, old-session preservation, import refusal, active-task refusal, content drift, reload, resume, fork, worker tool registry, new session and unchanged host methods |
| Two native Pi TUIs | PASS: independent live owners/endpoints, cross-owner rejection, maintenance exit 4 while either runs, both exit 0 with terminal restored, final maintenance exit 0; zero model requests |
| Native host resources and OS sandbox | PASS: real SDK, guarded file read, loopback simulated-model round trip, task/role/tool registration, source preservation and confirmed process termination |
| Independent final review | PASS: executor and scout closed all findings on the stable sources and final locks |
| Real accounts; non-Linux platforms; remaining profile/Bun native builds | NOT RUN; no acceptance transferred from historical candidates |

Commands used for the native checks (all exit 0) were:

```sh
node scripts/smoke-pi-public-api.mjs --allow-host <final-runtime> <private-sdk-report.json>
.venv/bin/python scripts/smoke-pi-concurrency.py --allow-host --runtime <final-runtime> --evidence <new-private-directory>
.venv/bin/python scripts/verify-pi.py --tier native --case host-resources --allow-host --runtime <final-runtime> --output <private-native-report.json>
```

The matching runtime was materialized with explicit `PiBackend.sync` in a new
private fixture, exact Node 24.14.0/npm 11.19.1, a fresh npm cache and a shared,
SHA-verified public asset cache. The TUI/resource checks copied that sealed runtime
to their fresh fixtures. This is not a fully cold download or four-profile native
acceptance. Raw commands, exits, XML, PTY logs and hashes remain in the private
repair evidence directory; they contain synthetic configuration only.

The isolated repair acceptance did not inspect accounts, migrate sessions, switch
local deployments, or update remote refs. Authorized integration and deployment
are recorded in the final follow-up below. Existing Perry limitations and the remaining source,
platform, lifecycle and development-tooling issues listed in the issue register
remain separate from these fixes.


Offline coverage used the recorded complete-file results from the initial serial
run (1,506 cases) and three independent remaining-file shards (774, 774 and 773
cases). The serial process was deliberately interrupted with SIGINT (exit 2) to
parallelize continuation; its partially executed file was rerun in full. All three
shards exited 0. Raw XML and the collected-node manifest were reconciled by file;
partial and duplicate results were not added to the final count. The commands used
`pytest -q`, the explicit locked-Bun option, separate temporary roots, with pytest cache disabled and
only failed fixtures retained for the shards. This preserved the default network,
HOME, credential and third-party-host boundaries. Offline uv lock validation,
public-document validation, changed-text privacy checks and `git diff --check`
also passed.

## Execution-environment follow-up

Status: Linux acceptance and final review passed within the scope below. The
reviewed changes were integrated into local `main` at `de43346`, followed by the
authorized local deployment recorded at the end. The reviewed main snapshot was `4610678`
and the preceding repair base was `93cac69`; evidence for that earlier repair
remains scoped to its original changes.
GPT-6.1 catalog support is deferred by maintainer decision and is not a prerequisite.

### Goal and invariants

Ordinary development tools should use the caller's development environment while
each adapter locates native configuration, authentication and sessions through
supported public interfaces. Keep one DSH recipe and the existing physical
instance identities. Do not create environment-specific user profiles, an
environment daemon, an OAuth replacement, or a general tool interception layer.

The common implementation must distinguish the following purposes:

| Purpose | Environment and ownership |
| --- | --- |
| Manager storage | Existing declared machine paths and private-file protections; independent of child HOME |
| Ordinary host and developer tools | Caller HOME/XDG where the adapter can preserve native ownership; declared developer variables and explicit machine overrides |
| Native configuration and authentication | Adapter-owned public directory/file settings and stable instance binding; no automatic adoption of global accounts |
| Restricted helper or delegate | Explicit minimal environment and grants; no automatic inheritance of ordinary development capabilities |
| Dependency installation and default tests | Isolated staging or temporary HOME/XDG; no real native account discovery |

HOME/XDG lookup is separate from filesystem permission. Restoring a developer
HOME does not grant writes outside the workspace. Preserve `workspace-write + ask`,
existing approval behavior and sandbox failure handling. An external build-log
directory needs a supported output setting or an explicit native per-action
approval; it must not trigger default Full access or a broad directory grant.

Do not automatically source shell startup files, copy the complete parent
environment, or treat nonsecret variables as harmless. Loader paths and runtime
options can execute code. Retain existing preload, credential and identity guards.
Native shell functions and aliases are not promised by environment inheritance.
Native state isolation is not general credential, network or same-user isolation.

### Adapter feasibility and adoption order

| Adapter | Confirmed baseline | Implementation and gate |
| --- | --- | --- |
| OMP | Caller HOME/XDG is restored after the generic builder, with explicit native storage binding. Some guides still describe the old isolated execution HOME. | Preserve behavior and storage guards while moving shared environment policy into the common launch contract. Correct the contradictory guides. |
| Pi | Main sessions bind instance HOME although native agent/session paths are explicit. Restricted workers and delegates have separate minimal environments. | Verify native discovery and authentication fallback with synthetic sentinels, then adopt caller HOME for the main development path. Keep restricted paths unchanged unless their own contract requires a change. |
| DSH | RC2 standard Bash derives HOME from the host process. TUI 0.15 preferences use `homedir()/.dsh-tui`; launch snapshots are not a subprocess boundary. Public subprocess providers and per-server MCP environment configuration offer separate candidate integration seams. | Prototype replacement of the existing host subprocess provider through the official composition overlay, preserving TUI HOME. Validate MCP separately, including variable deletion. Keep the current deployment until these paths pass native tests; diagnostics alone do not complete compatibility. |
| termcfg | Shell configuration overwrites NVM_DIR and private hooks use a fixed HOME-relative config directory. | Preserve explicit NVM_DIR, including empty values; load NVM only from a nonempty selected path. Define XDG-aware hook selection with a reviewed legacy fallback and an explicit conflict when both locations are ambiguous. Never source both automatically. |

The DSH gate must inventory settings, model preferences, history, authentication
and sessions separately. Public provider composition must cover the actual
enabled channels, rather than proving only a replacement Bash command. Moving UI
preferences into caller HOME changes ownership and is not a transparent fix.
Do not modify upstream modules, change process HOME around module imports, create
redirection symlinks, or force a host upgrade to bypass this gate. Record the
remaining limitation if the locked public interfaces are insufficient; proceed
with independent common, OMP, Pi and terminal work, but keep the unresolved DSH
compatibility item open.

### Explicit overrides and visible environment differences

The earlier plan did not define a complete repair interface. Add the following
small contract using the existing machine schema, launch contract and CLI:

| Source | Semantics |
| --- | --- |
| `machine.environment.inherit` | Keep the existing name list. Resolve values from the caller on every run; an absent optional inherited name stays absent. |
| `machine.environment.values` | Keep literal nonsecret strings, including empty strings. Machine declarations require plan/apply; do not expand shell syntax or environment references. |
| `machine.environment.unset` | Add an explicit deletion list. Remove the variable rather than setting an empty string. Reject a name also declared in machine inherit/values. |
| `run --inherit-env NAME` | Ordinary-run option: explicitly use this invocation's caller value after machine values. Missing input fails before credentials or host startup. Only names enter manager argv. |
| `run --unset-env NAME` | Ordinary-run option: delete the variable for this run; deleting an absent variable is idempotent. Reject conflicting or repeated one-shot declarations. |

These CLI options and the unset field are implemented. Keep literal one-shot
values out of the manager CLI; callers
can supply nonsecret values through their shell environment. This avoids putting
values in manager arguments, not the caller shell's own history. Neither interface
is a credential channel. Native arguments after `--` remain untouched.

Precedence is caller baseline, deployed machine inherit/values/editor, machine
unset, explicit one-shot changes, then final validation. Machine unset removes
EDITOR after machine.editor has set it, without implicitly removing VISUAL. A
one-shot inherit clears an earlier deletion marker and uses the caller value;
a one-shot unset creates the final deletion marker. Protected identity, credential and preload
bindings are not ordinary overrides. HOME/XDG select a supported execution policy
and stable identity, not an unrestricted alternate account directory. An adapter
must reject an incompatible override before resolving SecretRefs or spawning;
it must not accept a value and then silently clear or replace it. Preserve the
existing Pi Cursor proxy restriction until a supported separate route exists,
and report conflicting explicit proxy overrides as unsupported. This does not
deliver the deferred per-route network redesign.

Deletion markers must survive every builder and adapter layer: OMP must not refill
a deleted TOOL_ENVIRONMENT variable, and package PATH assembly must not undo an
explicit selection. If environment declarations differ from the saved deployment,
fail with the existing conflict exit 4 and an actionable plan/apply instruction.
Do not reject changes to unrelated model declarations through this check. Values
of inherited variables remain dynamic and need no apply.

Ordinary overlays must not propagate implicitly into restricted workers. At the
review baseline, `PiHost.worker_command` called `environment(home=root)`, which
inherited BASE_ENV from its already-overlaid parent. The implementation replaces
that dependency with an explicitly scoped restricted environment and the frozen
engine executable. Installers retain only their declared toolchain and
network inputs and temporary HOME, and default tests retain their isolated fixtures.

Warnings are a required behavior, not an optional doctor feature. Capture original
caller names and only permitted values before constructing host environments;
do not persist a full parent snapshot or read unknown credential values for this
comparison. Before launch, compare that caller basis with the effective environment
for the declared path, using the platform's environment-name semantics.
An originally present variable that is omitted or changed produces a visible,
bounded stderr summary, including changes explicitly requested by configuration.
List ordinary names and fixed reason categories, never values or value hashes.
Summarize credential-shaped variables without exposing their values or individual
names. Empty-but-present differs from absent. An identical value with a different
source is provenance, not a false changed-value warning.

Provide details through an explicit environment view in the existing doctor
interface: variable name where allowed, source, inherited/overridden/removed/
unsupported status, purpose and reason. It must use the same resolution path,
avoid credential files and never claim that a host preview proves downstream
propagation. Warn once per relevant launch/channel rather than on every model
turn. A child policy change discovered at a later boundary needs its own scoped
notice; unobservable boundaries are reported as unverified. Do not suppress the
default warning merely because a change is intentional.

### DSH public integration and coverage gates

Further locked-source review found a more specific public path than a missing
single HOME setting. `SubprocessRuntime` supports an independent provider;
`LocalSubprocessRuntime` exposes public executable resolution, spawn and terminal
methods. `runProfile` composes official bundle/profile/overlay rows. The adapter
replaces the existing `subprocess` row through that composition and uses a thin
public subclass of the official local provider, retaining its managed process
lifecycle. Do not register a second provider, mutate the original instance, use
test hooks or implement another process supervisor. Native composition, standard
Bash and dual-TUI checks passed on the matching final lock.

The public subprocess spawn environment accepts undefined deletion markers;
the shell request environment has a narrower type. Keep that distinction.
Cover executable resolution and PTY shell selection as well as spawn, and retain
native sandbox arguments, cancellation, signals and termination behavior. Do not
let caller values replace managed DSH facts or gain reviewer tool capabilities.

MCP stdio bypasses this service and has its own public per-server string env map.
It can override HOME/XDG when supplied a trusted nonsecret caller context, but
cannot express a deletion marker. Prove an exact public launch/configuration
solution for removal as well as assignment before claiming general MCP support;
empty strings are not a substitute for removal. A small argv-only environment
launcher may be evaluated if required, using declared inputs and unchanged MCP
transport; it must not become a general plugin framework or bypass the sandbox.
HTTP MCP has no local child HOME. File tools resolve paths through their fs service,
not through the subprocess provider, and require a separate path-behavior test.
PTC/direct Node and external agents are separate channels; do not infer coverage
from Bash or a parent delegation. Unsupported channels must be explicitly reported
or unavailable for this override feature. The current DSH deployment remains until
this coverage gate passes.

### Ordered work packages

The packages below define the implemented scope and acceptance conditions.
Retain earlier repair evidence without transferring it to changed source.
Use one writer for shared files and independent read-only reviews at boundaries.

| Package | Scope and prerequisites | Completion condition |
| --- | --- | --- |
| ENV-0: Freeze the contract | Review `adapter.py`, `process.py`, `runtime.py`, `config.py`, adapter bindings and CLI diagnostics. Prototype the DSH public subprocess/MCP paths before promising adoption. | Document variable precedence, deletion, visible warnings, operation scope, native identity paths and per-channel capabilities. No new user profile or unsupported configuration fields. |
| ENV-1: Common launch construction | After ENV-0, extend the existing launch contract minimally and version saved semantics. Keep explicit isolated-HOME construction for installers and restricted operations. | New contracts do not infer all XDG changes from one HOME binding. Construct the nonsecret basis once per invocation, resolve required executables consistently for preflight/spawn, and inject only selected secrets afterward. Old contracts retain their recorded behavior until apply. |
| ENV-2: Adapter adoption | After ENV-1, migrate OMP policy without changing behavior, then Pi main sessions after native-state tests; close the restricted-worker inheritance gap. DSH adopts only after the ENV-0 prototype passes. | Caller tool paths and explicit overrides work, native storage stays in the same instance, deletion is not undone, restricted helpers retain separate environments, and each channel advertises only verified capabilities. |
| ENV-3: Terminal consistency | Independent after ENV-0; update `terminals/zsh`, its catalog digests, relevant tests and guide. | Custom and empty NVM_DIR cases work as specified; XDG/legacy hooks are selected once, ambiguity is reported without private content, and repeated deployment preserves user drift. Test new shells separately from an existing tmux server's environment. |
| ENV-4: Migration and diagnostics | Design with ENV-1 and implement before promoting ENV-2. Reuse plan/apply/doctor and existing deployment journals. | Default run warnings identify omitted/changed caller variables with redacted reasons; doctor distinguishes execution HOME, storage and variable provenance. Stale environment declarations fail explicitly. Apply requires exclusive maintenance; failures and rollback preserve synthetic state. |
| ENV-5: Acceptance and delivery | Stable implementation, matching complete locks, then final diff review. | Affected offline and native no-account checks pass; remaining limitations have explicit states. Merge/deploy only the reviewed supported scope through the normal manager path. |

Precedence must be explicit: declared caller inheritance, then allowed machine
values/editor settings, then machine unset, one-shot ordinary changes and final validation of
adapter-owned identity bindings, with selected credential references resolved for
the required consumer. Contradictory reserved
controls fail instead of being silently repaired. Keep caller development values
fresh on each run while native identity remains bound to the saved deployment.
Preserve the distinction between absent, empty and invalid path values; preserving
an input does not require accepting an invalid native path.

Do not prepend runtime directories to the business PATH without accounting for
their effect. Use explicit host entry points where possible and inventory shebang
interpreters and helper subprocesses as well. Required checks and execution must
select the same tools. Optional project tools are not universal host prerequisites.
An upstream host may filter shell environments or forward variables to MCP; test
those actual boundaries and document any propagation that public APIs cannot limit.
An in-process reviewer is not a separately isolated process.

### Acceptance and evidence

Extend existing test families rather than adding tests that merely mirror a new
environment dictionary. All default tests keep temporary HOME/XDG, fictional
credentials, blocked network and fake subprocesses. Required scenarios include:

- A synthetic caller HOME containing a build launcher, custom Git configuration,
  developer PATH, virtual environment and library paths. Check declared inheritance,
  explicit overrides and unknown-variable exclusion for each adopted adapter.
- Custom, absent and empty XDG states; native discovery/authentication sentinels;
  unsafe paths and symlinks; forbidden preload and credential controls. No global
  account import and no default shell-startup loading.
- A PATH collision that proves preflight and spawn use the same required tool,
  including a host helper. Check that runtime packaging does not replace the
  developer toolchain unexpectedly.
- Legacy/current launch contracts, environment-only apply and rollback, active
  runs, interrupted maintenance, drift and repeated apply. Configuration rollback
  must not be described as a native data or software downgrade.
- Restricted workers, reviewers where applicable, delegates, installers and test
  fixtures retain their own grants and environment boundaries.
- NVM and private-hook selection, legacy ambiguity, catalog integrity, and terminal
  environment behavior without reading or sourcing real private hook files.
- Persistent and one-shot precedence, missing explicit inheritance, deletion versus
  empty values, conflicting names, protected controls and native `--` passthrough.
  Prove that OMP refill and Pi fixed proxy policy cannot silently undo an override.
  Include machine.editor with EDITOR unset, and machine unset followed by one-shot
  inheritance, so deletion precedence has one explicit result.
- Caller variables omitted or changed produce a default warning with a reason;
  unchanged values do not produce a false difference. Use synthetic credential
  canaries to prove no value, hash or credential name leaks through errors,
  warnings, diagnostics, saved contracts or one-shot records. Warning generation
  must not read credential files. Verify ordinary overrides do not reach restricted
  worker/delegate or installer environments through a parent process.

After offline checks, extend the existing explicit native smoke entries only as
needed. Use exact locked hosts, two fresh synthetic HOME trees, a fake provider,
and controlled workspace/external sentinels. Exercise the native Bash/file/MCP
channels actually enabled; record unsupported channels rather than implying
coverage. Verify an allowed build launcher and a denied external write independently.
No business compiler, real account files, production endpoints or global shell
changes are acceptance inputs. Distinguish shared-cache rebuilds from cold installs.
Require one matrix row for each enabled execution channel and each supported
override operation: inherit, set, empty and unset. Record actual child observations
from controlled fixtures, not only the dictionary passed to the host. Channels
without a child environment need an explicit not-applicable rationale and their
own path-behavior check. A missing DSH channel or failed deletion case keeps the
corresponding capability open. All supported explicit overrides must either reach
their declared consumer or fail before the action starts; accepting and silently
ignoring an override is an acceptance failure.

The design-review baseline ran `tests/test_isolation.py`, `tests/test_runtime.py`
and `tests/test_omp_execution_contract.py`: 79 passed on Linux. A UID-mapped
sandbox attempt was rejected by ownership checks; rerunning as the host user
passed without weakening guards. The implementation baseline subsequently passed
321 affected offline tests before source changes. Neither baseline transfers
acceptance to the new implementation; matching native results are recorded below.

Use the existing [test entry points and isolation rules](../testing.md). Starting
families are `test_config_policy.py`, `test_config_secret_loading.py`, OMP's
`test_omp_execution_environment.py` / `test_omp_pipeline.py`, Pi's
`test_pi_pipeline.py` / `test_pi_test_boundaries.py` / migration families, DSH's
`test_dsh_pipeline.py` / `test_dsh_upgrade.py`, and termcfg's security/status/apply
families. Extend these with the new scenarios; their current coverage is not proof
of the proposed semantics. Native entry points include
`scripts/smoke-pi-public-api.mjs`, `scripts/smoke-pi-concurrency.py`,
`scripts/smoke-dsh-concurrency.py`, `scripts/smoke-dsh-environment.py` and
`scripts/verify-pi.py`; inspect their actual
arguments and extend only where the new behavior requires it. Do not add native
host execution to default pytest.

Bind final evidence to source and lock identities, exact commands, exits, platform
and redacted reports. Rebuild only locks whose declared source inputs changed,
using the actual resolver and existing publication protocol; never edit digests to
claim freshness. Record dependency changes and rerun their affected tests. Repeat
the final review after writes stop. Existing privacy, commit identity and clean
history merge gates remain mandatory.

### Delivery boundary and deferred work

The deliverable is a small common execution contract, verified per-adapter adoption,
terminal fixes, migration diagnostics and updated guides. Before local deployment,
review the selected machine's nonsecret plan, preserve native ownership, wait for
active leases to release, and use ordinary sync/apply/doctor. Do not copy real
accounts or sessions into fixtures, stop user processes, reset branches, or clean
unowned worktrees. Configuration rollback restores the saved environment contract;
it does not authorize old hosts to consume newly written native data.

Defer GPT-6.1 catalog additions and the associated alpha-stack evaluation. Retain
the current model IDs, default model and official runtime pins. A future ordinary
upstream upgrade can reevaluate the catalog; no model alias, OAuth replacement,
forced override or vendor edit is part of this work. Per-route network redesign,
LEASE-01 descriptor lifetime, Perry DSH-AR-01–04, and unrelated Task Keeper or
vendor/source migrations remain separately tracked. This plan does not change the
maintainer's existing auto-review deployment choice or its accepted limitations.


### Implemented environment boundary

New deployments save environment version 1, caller HOME/XDG identity and the
existing native bindings. A changed declaration or caller path requires explicit
plan/apply before credentials or preflight. Legacy contracts keep their saved
behavior until apply; rollback restores configuration/contract state and does not
promise software or native database downgrade. Synthetic migration and native
state preservation are tested separately from authenticated accounts.

DSH disables the original subprocess row and inserts one public
`LocalSubprocessRuntime` subclass. RC2 patch `name` is a matching guard, so changing
that field alone does not select a replacement. Cordis service proxies also
require ordinary immutable properties instead of JavaScript private-field brands.
No upstream module or binary is modified. Ordinary and PTY process lifetime,
termination and containment remain owned by the inherited provider.

MCP stdio uses its separate public command/args configuration and `/usr/bin/env`
to exec directly, without an extra relay process. Assignment-like commands are
rejected before launch; bare commands require a selected nonempty PATH. The
platform env executable is checked before credentials. Internal AGENTCFG_ names,
including hashed MCP credential destinations, are removed from subprocesses and
MCP children by name-only tombstones; their values never enter the development
payload or argv. Explicit HTTP MCP authorization remains scoped to that client.

| Channel | Environment behavior | Permission boundary |
| --- | --- | --- |
| DSH host/TUI/auth/settings | Instance HOME and native storage unchanged | Trusted host and selected plugins; no general same-user isolation |
| Ordinary subprocess and PTY | Caller development HOME/XDG, declared values and final deletions | Original provider containment; a direct spawn is not itself an OS sandbox |
| standard Bash | Same public provider; real tool and sandbox result tested | Original workspace-write sandbox and native approval policy |
| stdio MCP | Separate direct exec with matching assignment/deletion and internal-variable filtering | Existing MCP/approval behavior; no additional OS sandbox is claimed |
| HTTP MCP | No local child environment | Explicit configured headers stay with the selected client |
| File tools | Native workspace/path semantics, not shell tilde expansion | Original fs service and native policy; subprocess overlays do not redirect files |
| Native in-process subagents | Shared host services; ordinary tool boundary where used | Per-action native policy; parent permission is not blanket child approval |
| PTC/direct Node/trusted plugins | Isolated host environment | Separate existing boundary; caller overlay is not promised |
| External agents | Only a public subprocess boundary receives this overlay | No new external-agent permission or account adoption |

Linux native acceptance uses temporary state, synthetic internal credentials and
MCP servers, and zero account/model calls. The sandbox probe lives outside /tmp
and /dev because upstream bwrap remounts those locations; changing that fixture
preserves rather than weakens the real sandbox. Live accounts, business builds,
other platforms and other Pi profile-native combinations remain unverified.

### Environment acceptance results

The implementation is based on `93cac69`. Linux x86_64 acceptance uses Node
24.14.0 and npm 11.19.1. Upstream pins remain DSH `0.2.0-rc.2`, TUI `0.15.0`,
Cursor subscription `0.6.12`, Perry auto-review `0.12.17`, Pi SDK `0.84.4` and
official OMP `18.8.6`; DSH remains a prerelease host. The new repository-owned
public extension is `rotom-dsh-execution-environment@0.1.0`.

| Candidate | Complete lock identity | Scope |
| --- | --- | --- |
| DSH | `f9da5fd8538eeee6d3526ac5cb160095f0c3d1ff36e3bde072f04441ce208d15` | Matching local extension source archive and complete pnpm resolution |
| Pi | `632795dddc4484e4b220814f013c6da724a9aae02f2e6863b6784e341d7d5125` | Rebuilt runtime archive and all four profile resolutions; native acceptance selects pi-default |
| OMP | `90357d838801ddab2d3ebe54d57f8cdc49ca31870b9c1e9615409ab58be592ca` | Upstream runtime lock unchanged; common launch integration tested offline |

The DSH resolver also refreshed transitive loader/include/group, cosmokit,
undici and build-tool packages. This is not a package-only lock edit. Approval,
session and subagent packages remain RC2; realpath checks confirm that the new
extension and host share the same subprocess/Cordis runtime. Native DSH evidence
below uses the new lock rather than inheriting the former lock's results. Both
local archives match the exact source inventories; Pi's four npm graphs change
only the local runtime archive reference. No force or peer-range bypass was used.

| Check | Result | Evidence scope |
| --- | --- | --- |
| DSH real environment and sandbox | PASS, 6 checks | Public provider composition, ordinary/PTY children, standard Bash, real configured stdio MCP and actual external-write rejection; zero model calls |
| DSH dual native TUI | PASS, 8 checks | Separate sessions, collision refusal, maintenance leases, clean exit and terminal restoration; synthetic loopback model only |
| Pi public SDK | PASS, 13 checks | Instance model/resource selection, synthetic caller-global sources not adopted, sessions, worker registry and unchanged host methods; simulated supervisor, zero model calls |
| Pi native resources | PASS | Real SDK guarded read, todo and role-resource round trips through the existing outer sandbox; synthetic model only |
| Pi dual native TUI | PASS, 8 checks | Independent live supervisors/endpoints, cross-owner refusal, maintenance leases, exit and terminal restoration; zero model calls |
| DSH/Pi rebuilds | PASS, two fresh HOME trees per lock | Actual locked installation and unchanged repeated sync; shared verified public vendor/toolchain and large Pi asset cache, not fully cold downloads |
| termcfg | PASS | 115 affected offline tests and 18 actual isolated zsh cases; synthetic hooks only |
| Node contract suites | PASS | 340 Pi mock-runner cases and 50 DSH environment helper cases; no native or account claim |
| Full Python coverage | PASS, 3,886 passed, 9 skipped, 7 subtests passed | All 3,895 collected node IDs reconciled without gaps; complete-file reruns cover the final Pi plan repair |
| Final independent review | PASS, no unresolved findings | Runtime/lock and terminal/documentation reviews; necessary fixes re-reviewed against the final 60-file source manifest |
| Live accounts, business compiler, other OS, nondefault Pi native profiles | NOT RUN | No account or business-environment access; no cross-platform inference |

The explicit native commands are documented in [testing](../testing.md).
Private evidence retains commands, exit codes, sanitized reports and source/lock
digests. The changed code/configuration/lock/test manifest relative to `93cac69`
has SHA256 `6f4c223e6c25889e8a29195e7e6b22bdcfb35df33fc85a28a1a8d3b48637800c`;
documentation result metadata is excluded from that digest. DSH's native source
manifest contains 159 source files and matches the
current implementation. Native checks do not establish a same-user credential
boundary, a fully cold download, Perry's deferred safety properties, or permission
to write external build logs. At the isolated acceptance boundary, main and daily
deployments were unchanged. The later authorized integration below updated
managed deployment artifacts without inspecting credentials or native sessions.

The first complete Python run exited 1 with 12 obsolete assertions/fixtures
(3,867 passed, 9 skipped); those files were corrected and rerun. The final offline
suite was split into three disjoint complete-file groups. The third initially
hit the existing Unix socket path-length guard because its
explicit temporary prefix was too long. All six cases in that file then passed
with a short prefix, and a full retry of that group exited 0. Final group results
were 1,295 passed/2 skipped, 1,297 passed/7 subtests, and 1,289 passed/7 skipped.
All three complete groups exited 0. The subsequent real CLI check uncovered an
existing Pi upgrade-preview bug: it read plan-only `desired` from saved state,
which actually retains `baseline`. The strict baseline repair and deployed-plan
regression passed 22 cases across three complete files, including five additional
corruption cases. File-level reconciliation replaces older results for those
files: the 22-case rerun replaces 17 existing results and adds 5 new cases.
Thus the original groups cover 3,890 cases, and the final collection contains
3,895 unique cases (3,886 passed, 9 skipped); the 7 subtests are counted separately.
Duplicate results are not added. Actual two-HOME plan/apply/doctor checks
also passed on the final lock, and both saved launch identities match it.
No socket, owner or sandbox guard was
weakened. Raw logs retain superseded failures rather than representing them as
successful commands.

### Authorized local integration and deployment

The user authorized integration after final review. Local `main` fast-forwarded
from `4610678` through four reviewed, single-parent commits to `de43346`; no remote
push or history rewrite was performed. Commit identities, introduced history,
public content, final source/lock consistency and the existing acceptance evidence
passed the merge gates. The initial review summaries remain historical evidence;
their findings were closed by the follow-up commits rather than deleted.

The existing DSH `dsh-default` and OMP `omp-kernel` deployments were updated with
`agentcfg setup` on the integrated checkout. DSH maintenance initially returned
4 because a process still held the instance lease after the visible TUI closed.
After separate user authorization, one SIGINT was sent to the verified DSH child;
the child and manager exited normally, and setup then returned 0. No lock was
deleted or bypassed. The `dsh` and `dsh-proxy` wrappers still reach the same
main-checkout entry point and instance.

| Local check | Result |
| --- | --- |
| DSH and OMP `setup` | Exit 0; normal frozen dependency installation and deployment |
| DSH and OMP `doctor --environment --format json` | Exit 0; dependencies installed, deployed runtime matches current lock, no pending declarations or recovery, offline-ready |
| DSH and OMP `plan --format json` | Exit 0; changes 0, drift 0, conflicts 0 |
| DSH and OMP repeated `apply --format json` | Exit 0; changes 0, drift 0, conflicts 0 |
| termcfg apply | Exit 0; two managed zsh files updated with private backups; tmux targets unchanged |
| termcfg `doctor --strict`, plan and repeated apply | Exit 0; ready, all targets unchanged, no repeated file changes |

The terminal manager required its explicit plan-bound `.zshenv` confirmation;
the authorized deployment supplied the same reviewed plan ID and retained the
normal backup/transaction mechanism. Existing shells and tmux servers were not
restarted, and private hooks were not sourced for acceptance. Start a new shell
to use the updated initialization. No managed Pi instance was present, so no
additional Pi deployment was created.

These local checks verify managed deployment and offline readiness, not live
account access, the business compiler, non-Linux platforms, or deferred Perry
safety properties. Credential and native-session files were not read for this
follow-up. Configuration rollback remains distinct from software or session
database downgrade. Remote publication remains a separate authorized operation.
