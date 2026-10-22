# Tasks: Configurable Workspaces

**Input**: Design documents from `specs/006-configurable-workspaces/`: [plan](plan.md), [specification](spec.md), [research](research.md), [data model](data-model.md), [contracts](contracts/configuration.md) and [quickstart](quickstart.md).

**Capability refinement**: The implementation review found no safe public atomic existing-branch mode in examined Git. T043–T050 validate new-branch success and existing-branch pre-dispatch refusal (5), retaining import of existing worktrees and the no-remote-guessing requirement. This narrows the original positive existing-branch checkpoint; it does not grant an unsafe exception. See the spec implementation refinement.

**Prerequisites**: Reviewed Phase 0/1 artifacts and constitution 2.4.0. This checklist records implementation progress; native acceptance is separate and is not claimed by checked items. The existing repository/worktree and prepared `.venv` are reused.

**Tests**: The specification explicitly requires independent tests and 37 acceptance scenarios. Write the listed isolated behavior tests before the corresponding implementation, observe the relevant failures, then make them pass. Use temporary HOME/DSH_HOME/XDG/state, synthetic Git repositories, blocked network, fake hosts/subprocesses and sentinels. Never inspect real credentials/sessions or start a third-party host in default tests.

**Organization**: Setup → Foundational → US1/US2/US3 (P1) → US4/US5 (P2) → US6 (P3) → Polish. Each story has an independently observable checkpoint. Shared-file ownership imposes the explicit serialization below.

## Format: `[ID] [P?] [Story] Description`

- `[P]` identifies an explicitly described pair of tasks with disjoint writable files and satisfied prerequisites; it never authorizes simultaneous writes to a shared module.
- `[USn]` appears only in story phases. Every checkbox starts unchecked.
- Paths are relative to the repository root; use the existing Python package and thin launchers, without a new service framework.
- At most two delegated tasks run together: one implementation owner and one independent test/evidence owner. Escalate changed design assumptions, unclear transaction/lock/recovery semantics, material scope expansion, or a failure surviving two substantive approaches to the main agent.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Admit only the dependencies and public-source fixtures needed by this existing CLI extension.

- [X] T001 Recheck official stable Herdr public source/schema and record the exact candidate tag/commit, protocol, source identities and capability boundary in `specs/006-configurable-workspaces/research.md`; use researched 0.9.5 as a starting candidate, retain its unsupported guarded close, and do not treat a version string as admission or run/install a host.
- [X] T002 [P] Admit the comment-preserving TOML dependency in `pyproject.toml` and `uv.lock`, recording exact version/source/integrity and license in `specs/006-configurable-workspaces/research.md`; use researched tomlkit 0.15.2 as a candidate and keep Python >=3.11. After explicit lock admission, prepare the feature-isolated repository `.venv` with `uv sync --locked` if needed; preserve an existing shared environment reached through a symlink. No system-Python replacement or startup installation.
- [X] T003 [P] Add exact tagged public request/result/metadata fixtures and provenance under `tests/fixtures/herdr-native/v2/` (`api-schema.json`, `responses.json`, `config.toml`, `source.json`, `LICENSE`) after T001; preserve `tests/fixtures/herdr-native/v1/` byte-for-byte for legacy tests and record the v2 fixture's bounded coverage in `specs/006-configurable-workspaces/contracts/native-api.md`.

**Checkpoint**: T001–T003 establish dependency and native schema inputs; no active runtime configuration has changed. T002 and T003 may overlap only after T001; their research/contract ownership is disjoint.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared strict configuration, private state, native proof and complete initial-launch payload must exist before story dispatch is enabled.

- [X] T004 [P] Extend `tests/work_helpers.py` with temporary private roots, fake single-executable editor/Agent/native dispatch, mutation-call recording, deterministic failure barriers and sentinel assertions; network and real host calls must fail, and fixture-only native v2 loading must leave v1 behavior intact.
- [X] T005 [P] Add strict public API contract cases in `tests/test_herdr_api.py` using v2 fixture files for ordinary workspace.create env, tab.create, pane.current, metadata, explicit focus/rename and reads; reject unsupported methods, malformed/oversized results, implicit caller focus, replacement sockets and mutation resend, while preserving v1 cases.
- [X] T006 Extend `schemas/local.schema.json`, `src/termcfg/work_config.py` and the non-secret loader integration in `src/agentcfg/config.py`: retain `schema_version = 1`; require explicit `model = "structured-v1"`, reject structured-only fields without it and unknown models without legacy fallback; new IDs match `^[A-Za-z][A-Za-z0-9_-]{0,63}$`, all nested unknown fields fail, Unicode paths/titles are literal with NUL/control/invalid-encoding rejection, existing profile IDs retain their rules, `herdr_binary`/`session` stay required and `codex_daemon` defaults to `false`.
- [X] T007 Implement protected v2 bindings, immutable authorized intents and receipt validation in `src/termcfg/work_state.py` using `src/agentcfg/storage.py` primitives: current-user 0700 directories/0600 files under the standard XDG state/HOME fallback, canonical socket namespace, endpoint generation evidence/random epoch, context kind/key, native IDs, fixed starts, template/origin and no terminal inventory/secrets; state/schema conflicts return 4 and unsafe I/O retains the established 4/6 distinction, with no implicit migration or deployment-state version change.
- [X] T008 Implement precise admitted public method/result and runtime capability checks in `src/termcfg/herdr.py` after T005: preserve O_PATH/procfs pinning and one request/connection, validate disk/server inputs and protected startup configuration observations separately, explicitly lacking a public effective-config attestation; detection/integration rules are not used for lifecycle authority, explicit pane.current caller membership and metadata capacity, and classify possibly sent mutations as unknown without reconnect/resend; existing servers must already have the prepared wrapper/no-auto-resume contract, with no active-server repair.
- [X] T009 Define v2 one-use JSON envelope parsing and complete non-secret normalized launch preparation for shell/editor/pi/dsh/codex in `src/termcfg/work_shell.py` and `src/termcfg/work_config.py`: <=16 KiB UTF-8, integer version 2, action workspace-initial/existing-workspace tab, kind default/extra (initial always default), random 32-hex op/instance/epoch, ASCII type key, existing-tab required workspace ID and initial caller-derived ID; include explicit local selection/session/trusted root/source and binding digests, fixed cwd/captured HOME/launch boundary (shared initial resolver handles omitted workspace_start, literal relative-to-fixed-workspace-start, ~/captured caller HOME and absolute existing directories without fallback, and freezes first type cwd/launcher), absolute protected intent reference, pinned socket/dev/inode and total monotonic deadline; reject duplicates/unknowns/non-finite values/type errors/expired or extended deadlines and never log raw payloads.
- [X] T010 Implement wrapper-side immutable-intent verification and ready/commit/accepted/failed protocol in `src/termcfg/work_shell.py` and `rotom-work-shell` after T007–T009: wrapper takes no parent operation lock and writes no private record; actual caller IDs, pane membership, workspace markers and parent commit must agree before exactly one accepted/exec path, strip ROTOM_WORK_LAUNCH_V2 without replacing HERDR identity variables, preserve v1 path, and enforce conservative failure/exec-failure reporting without an accepted fallback shell.
- [X] T011 Add parent-side shared v2 operation helpers in `src/termcfg/work.py` and `src/termcfg/work_state.py`: use the existing per-UID operation lock, never nest it with the config lock, preserve total 30-second ordinary/60-second managed-Agent budgets, persist intents before mutations and commit-issued before commit publication; enforce "There is at most one unresolved native-creation intent per workspace (including extras)." Keep uncertain receipts indefinitely, compact completed native receipts only after durable bindings, retain relevant completed Git outcomes until explicit reviewed archival, and let only an original authorized operation finalize uniquely proved bookkeeping without replay. Extend the existing `source_digest()` in `src/termcfg/work.py` to cover introduced safety-critical v2 state/launch modules and `schemas/local.schema.json` before their first launch use; later module-integration tasks extend the same manifest before enabling their dispatch.

**Checkpoint**: T004–T011 are ready. Complete launcher preparation/payload support already includes arbitrary initial editor/Agent types; US2 does not depend on US3. Native ownership still requires current proof rather than private records/environment/labels/cwd. T004 and T005 are the only foundation parallel pair, after T003.

## Phase 3: User Story 1 - Configure and discover projects through any entrance (Priority: P1) 🎯 MVP

**Goal**: Offline discovery and safe source/project/named registration share one TOML contract through selector, complete CLI input and manual edits.

**Independent Test**: Run `.venv/bin/python -m pytest tests/test_work_projects.py tests/test_work_config_edit.py tests/test_work_cli.py` with fake fzf/editor and zero host/native calls; cover scenarios 1.1–1.9 and equivalent valid/invalid inputs through all three entrances.

### Tests for User Story 1

- [X] T012 [P] [US1] Add discovery/validation tests in `tests/test_work_projects.py` for .git-file checkouts, depth/default/exclusions, directory boundaries/subdirectories, aliases/symlink escape/cycles, unreadable-source diagnostics, precedence/conflicts, duplicate labels, trusted executing-root changes and literal Unicode; include source/template/type/named ID and nested-field rejection, defaults/references, and disabled built-in cases (1.1–1.4, 1.8–1.9).
- [X] T013 [P] [US1] Add preservation/save/editor tests in `tests/test_work_config_edit.py` for source/project/named registration, no-effect cancel/dry-run/check, idempotent bytes, permissions/comments/unrelated content, unsafe links/read-only files/manual fragments, serialized cooperating writers, observed outside replacement, manual edits between saves and post-replace durability uncertainty; assert editor staging excludes all unrelated machine/secret fields and no whole-file digest/backup is produced (1.5–1.7, 1.9).
- [X] T014 [US1] Add CLI/selector/manual parity tests in `tests/test_work_cli.py` after T012–T013, using the same accepted/conflicting cases and fake opaque fzf choices; cover --machine/--local mutual exclusion/default selection, missing explicit input, absent/unsupported fzf, offline list/config check, preview/cancel/refresh, literal display text, hostile inherited FZF option overrides and config edit exit propagation (1.4–1.7). Verify complete explicit CLI still works when selector admission fails.

### Implementation for User Story 1

- [X] T015 [US1] Normalize source/template/type/project/named definitions in `src/termcfg/work_config.py`: source required id/path/mode/template, mode git/directory, depth integer 1–32 default 1, exclude_hidden true, exclude empty basename-glob array, follow_symlinks false; templates require duplicate-free order whose set exactly equals tab_types and one defined initial; type label is nonempty literal text, launcher exactly shell/editor/pi/dsh/codex, cwd omitted defaults to `{ from = "workspace_start" }` or exclusively `{ path = "literal" }` (nonempty), rejecting mixed/unknown selectors and arbitrary command/options; project kind=project requires existing path/explicit mode/template with no id/title, named kind=named requires id/nonempty title/template with optional existing start_path and no project path/mode.
- [X] T016 [US1] Implement pure boundary resolution and bounded discovery in `src/termcfg/work_projects.py`: TOML relative paths use selected file parent, ~/ uses caller HOME, CLI/TUI explicit paths use invocation cwd then reviewed canonical absolute paths; recognize Git checkout roots/.git files without external metadata traversal, preserve directory-mode boundaries, prune before descent, no default symlink following and contained cycle-safe opt-in, re-enumerate on entry/refresh and report unreadable sources without masking partial discovery.
- [X] T017 [US1] Add canonical precedence, duplicate diagnostics and trusted executing Rotom candidate to `src/termcfg/work_projects.py` and `src/termcfg/work_config.py`: explicit project > most-specific source > verified built-in, compatible repeats no-op/incompatible equal priority fail, distinguish duplicate titles by path/ID/origin; include_rotom defaults true and rotom_template defaults "development" without injecting templates, validate enabled/explicit references even when shadowed, disabled+omitted imposes no reference, and unverified executing root diagnoses without PWD/main guessing or blocking other candidates.
- [X] T018 [US1] Implement preserving source/project/named add and named-title proposal edits in `src/termcfg/work_edit.py` using the existing non-secret loader and storage primitives: stable lock keyed by canonical selected config path survives atomic replacement and is never unlinked live, bounded wait returns 4, re-read/compare identity/content in memory, full proposed config validation, owned machine.work edits only, same-directory private temporary publication and safe permissions/ancestor checks; no-op leaves bytes unchanged, observed outside changes refuse, post-replace uncertainty is reported truthfully and no universal CAS against lock-ignoring writers is claimed.
- [X] T019 [US1] Implement `work config edit` in `src/termcfg/work_edit.py`: hold the same config lock across private non-secret machine.work fragment editing via the explicitly configured single editor executable, then validate/review/merge; editor lifetime is separate from management timeout, unchanged/cancelled/invalid/failing edits leave original untouched, unsafe/read-only saves return diagnostic+manual fragment without success, no full-file editor copy/secret digest/generic backup and no config/native lock nesting.
- [X] T020 [US1] Route source/project/named add, offline list/config check/config edit and dry runs in `src/termcfg/work.py` and `work` after T015–T019; require complete explicit inputs, preview actual Git/directory boundary and source candidates, reuse one selected private TOML, save no snapshot/implicit selection, no clone/copy/move/init/mkdir/native/launcher effects from registration (except expressly requested fragment editor), and no new lock file/receipt on dry run or cancellation; propagate editor exit, manager 2/4/6 and direct-exec boundaries as contracted. Extend the T011 `source_digest()` manifest for the introduced `work_projects.py` and `work_edit.py` modules before US2 launch dispatch.
- [X] T021 [US1] Implement registration forms, explicit previews and refresh in `src/termcfg/work_ui.py` after T020. Admit the required public fzf interface using researched 0.74.5 as a candidate, record exact version/source/license and supported-option evidence in `specs/006-configurable-workspaces/research.md`, and diagnose missing/unsupported selection without installing it or blocking explicit CLI. Feed a bounded escaped list with single opaque in-memory IDs via argv/stdin, clear inherited FZF option overrides, and enable no shell preview/execute bindings. Show mode/template/origin/path and required inputs; save separately from entry through the same validator, cancel without mutation. Add `work_ui.py` to the T011 source manifest before US2 launch dispatch.
- [X] T022 [US1] Add ASCII public `examples/work-structured.toml` with development shell/edit/build/test/agent (initial shell) and investigation code/agent/problem (initial problem), explicit profiles and two named IDs sharing HOME; use fictitious paths, no injected default template and no numbered problem types; validate fixture-substituted example through `tests/test_work_projects.py`.
- [X] T023 [US1] Run the US1 isolated command above and record actual argv/exit/sanitized evidence plus no-effect and three-entrance comparison results in `specs/006-configurable-workspaces/quickstart.md`; record completed/in-progress/failed-pending-decision/environment-insufficient separately, and repair only affected US1 paths until its checkpoint passes.

**Checkpoint**: US1 is the offline directory-configuration MVP. It can discover/register/check without native readiness. It is not yet daily terminal entry. T012/T013 are the disjoint parallel pair; all implementation tasks are serial.

## Phase 4: User Story 2 - Enter independent directory and named workspaces (Priority: P1)

**Goal**: Enter/reuse independent verified contexts with one initial terminal, fixed workspace starts and read-only recovery reporting.

**Independent Test**: Run `.venv/bin/python -m pytest tests/test_work_lifecycle.py tests/test_work_cli.py` with fake endpoint/server/wrapper; cover scenarios 2.1–2.6, initial shell/editor/Agent, lost replies and zero replay.

### Tests for User Story 2

- [X] T024 [P] [US2] Add context identity/start/rename and initial handoff failure-window tests in `tests/test_work_lifecycle.py`: ordinary checkout/two worktrees/non-Git, two named IDs sharing HOME, project at same path, same ID on different endpoints, canonical socket aliases, mutable title/branch/runtime cwd, missing start, arbitrary initial editor/Agent, concurrent creators/lost replies/late phases/exec failure/marker loss/cold restore/moved or reused native IDs and zero blind retry (2.1–2.6).
- [X] T025 [P] [US2] Add CLI cases in `tests/test_work_cli.py` for named add→separate enter→rename, enter PATH uniqueness, open requiring confirmed context, outside attach versus inside caller, list --live never starting a server and read-only status/reconcile never changing receipt bytes or sending mutations, including rename saved-title/native-failure partial outcome (2.2–2.6).

### Implementation for User Story 2

- [X] T026 [US2] Resolve directory identity `(selected endpoint, canonical project boundary)` and named identity `(selected endpoint, "named", local ID)` in `src/termcfg/work_state.py` and `src/termcfg/work_projects.py`; retain the discriminator, canonical socket alias namespace and independent checkout boundaries, ignore title/branch/common Git directory/cwd/status, freeze workspace_start to boundary or first named caller HOME/explicit existing start with no creation/borrow/fallback, and preserve active starts across config/executing-root changes.
- [X] T027 [US2] Implement ordinary workspace initial creation/reuse in `src/termcfg/work.py` after T026 using T009–T011 handoff: resolve unique confirmed candidate first, prepare only initial launcher, persist intent then workspace.create with explicit cwd/label/focus=false/one-use env, verify unique caller-derived op/epoch and independent ordinary workspace, publish markers/commit and persist accepted default before focus; create exactly one initial instance, never grouped APIs, bootstrap replacement tab or implicit adoption of startup workspace.
- [X] T028 [US2] Enforce native metadata and late-event ordering in `src/termcfg/work_state.py` and `src/termcfg/work.py`: workspace "Four keys; digests 64 hex, epoch/op 32 hex" and managed root pane "Eight keys, each value <=80 characters"; "The type key is <=64 ASCII characters; kind is default/extra and phase is ready/accepted/failed." "Patches stay within the audited native 16-key limit and resource 32-key limit." Use rotom-work-v2/rotom-work-launch-v2 fixed keys, monotonic resource/source sequences and public null patch to clear commit; refuse capacity/conflict without clearing other sources or allowing late messages to undo terminal phases.
- [X] T029 [US2] Implement live proof and uncertain-result classification in `src/termcfg/work_state.py` and `src/termcfg/work.py`: match durable references with current workspace/pane/terminal membership and epoch before focus/control, retain unknown intents across timeout/crash/missing/multiple markers/replacement/cold restore, block dependent creates even --new, permit unrelated existing work, and finalize only uniquely proved original bookkeeping; no elapsed-time GC, automatic adoption/Agent resume or inference of absence from missing markers.
- [X] T030 [US2] Implement named rename in `src/termcfg/work.py` through `src/termcfg/work_edit.py`: save title under config lock first, release before native lock, retain ID/start/binding, rename only verified matching live workspace with epoch recheck, keep saved title on native failure/unknown and report partial presentation; configuration-only rename never starts/creates/attaches a server and other endpoints stay untouched.
- [X] T031 [US2] Route explicit enter/named enter/rename, offline versus --live list and status/reconcile in `src/termcfg/work.py`: status/reconcile inspect only receipts/live selected endpoint without writes/retry/cleanup; refuse absent/ambiguous/unverifiable targets before effects, outside entry alone may use existing protected session start/attach, inside entry verifies explicit caller with no global-focus fallback; preserve direct terminal/Agent/attach exec exits.
- [X] T032 [US2] Add context enter/rename and verified/stale/partial/unknown reporting to `src/termcfg/work_ui.py` after T031; label saved title versus pending native presentation accurately, keep selector display separate from identity, and make read-only candidate/list/status views usable without Agent extensions or implicit entry.
- [X] T033 [US2] Run the US2 independent command and affected existing `tests/test_work_identity.py`, `tests/test_work_context.py`, `tests/test_work_entry.py`, `tests/test_work_launch.py`, `tests/test_work_recovery.py` with the prepared `.venv`; record exact selected argv/exits and handoff mutation counts in `specs/006-configurable-workspaces/quickstart.md`, leaving native support explicitly unverified.

**Checkpoint**: US2 resolves all initial launcher kinds using the foundation; one verified independent workspace has one initial default, and ambiguous outcomes stop related creation. T024/T025 may run together; shared lifecycle modules remain one writer.

## Phase 5: User Story 3 - Open predictable terminal types and instances (Priority: P1)

**Goal**: Ordered types have fixed cwd/launcher contracts, safely reusable defaults and intentional extras without adopting native splits.

**Independent Test**: Run `.venv/bin/python -m pytest tests/test_work_templates.py tests/test_work_lifecycle.py tests/test_work_cli.py`; cover scenarios 3.1–3.8 with fake terminal/Agent/editor dispatch and advisory status only.

### Tests for User Story 3

- [X] T034 [P] [US3] Add type binding/launch tests in `tests/test_work_templates.py` for order/initial examples, every launcher's default+extras, extra-before-default, runtime cd/caller HOME changes, relative/~/absolute cwd, omission/default versus mixed/unknown cwd rejection, fixed launcher/profile/HOME, shell no-task behavior, unused-launcher preparation, drift/removed types and accepted zero-active rebind (3.1–3.6, 3.8).
- [X] T035 [P] [US3] Add lifecycle tests in `tests/test_work_lifecycle.py` for closed/moved defaults versus missing markers/reused IDs, no extra promotion, manual native tabs/splits including split managed tabs remaining unowned, complete proof of zero active instances, pending-op rebind refusal and advisory status never granting control/completion/recovery (3.2, 3.4–3.7).

### Implementation for User Story 3

- [X] T036 [US3] Extend the shared initial resolver from T009 with frozen TypeBinding/InstanceBinding resolution in `src/termcfg/work_config.py` and `src/termcfg/work_state.py`: resolve cwd omission/workspace_start, relative literals against fixed workspace_start, ~/ against first-type caller HOME and absolute unchanged; require existing resolved directories, record normalized shell/single editor/prepared explicit pi/dsh profile/independent Codex daemon policy and relevant declared env/HOME without credentials, plus random instance/op IDs, default/extra, native references, sequence and handshake phase; runtime cd does not drift and config reload does not rebind.
- [X] T037 [US3] Implement plain open/default focus and existing-workspace tab creation in `src/termcfg/work.py` using the common v2 handoff: ordered type selection, current verified context, explicit workspace ID, fixed cwd/launcher, focus verified defaults without re-preparing missing/changed executables or injecting input/restart; only complete native proof of closed/moved-out default permits a replacement, retain moved pane, never infer absence from lost markers.
- [X] T038 [US3] Implement structured --new extras for every type in `src/termcfg/work.py` and `src/termcfg/work_state.py`: always extra even before a default exists, never promote/change default, later plain open safely creates default with the same binding, render ordinals as instance labels rather than type keys and retain one unresolved creation intent across defaults/extras.
- [X] T039 [US3] Implement bound-type drift refusal and explicit rebind in `src/termcfg/work.py` and `src/termcfg/work_state.py`: new/uninstantiated types may use fresh settings, existing/removed verified defaults stay key-addressable/focusable, removed definitions cannot create; new contradictory instances refuse without touching active processes, and rebind requires complete zero-active proof, no unresolved operation, reviewed fresh contract and --accept/interactive acceptance; missing markers are not zero proof.
- [X] T040 [US3] Add ordered types/existing instances/extras/rebind review to `src/termcfg/work_ui.py` after T037–T039, routing through explicit CLI behavior without altering manual tab/split layouts; show native/Agent status as advisory only and supply no scheduler/task execution/input/automatic close/session recovery.
- [X] T041 [US3] Audit the already-active `source_digest()` manifest in `src/termcfg/work.py` and add temporary-source tamper regressions in `tests/test_work_templates.py` for introduced safety-critical launch modules and `schemas/local.schema.json`; assert parent/wrapper reject changed source/config selection before launch while preserving v1 behavior, without treating labels/environment/digests alone as ownership or exposing secrets. This verifies protection established before T027, rather than adding it after US2 acceptance.
- [X] T042 [US3] Run the US3 independent command and affected existing `tests/test_work_roles.py`, `tests/test_work_tools.py`, `tests/test_work_shell_fallback.py`, `tests/test_work_optional_status.py`, `tests/test_work_metadata.py`; record exact argv/exits/fixed-binding and unowned-split evidence in `specs/006-configurable-workspaces/quickstart.md` and repair only impacted paths.

**Checkpoint**: US1+US2+US3 form the usable daily terminal increment, independent of Agent extensions. T034/T035 are the parallel pair after T033; all shared implementation modules are serial.

## Phase 6: User Story 4 - Create a Git worktree with explicit effects (Priority: P2)

**Goal**: Distinct reviewed local Git creation preserves dirty originals and any partial successful outcome.

**Independent Test**: Run `.venv/bin/python -m pytest tests/test_work_git.py tests/test_work_cli.py` against disposable repositories and fake entry, covering scenarios 4.1–4.7 with no network/host execution.

### Tests for User Story 4

- [X] T043 [P] [US4] Add synthetic-repository tests in `tests/test_work_git.py` for registered-only import/create distinction, both exclusive branch modes, explicit local refs/ambiguity, occupancy/destination/ref/config races, source coverage/depth/exclusions, hooks/fsmonitor/filter sentinels, unchanged dirty/index/persistent-config bytes, timeout/nonzero/partial/unknown outcomes and checkout retention after failed entry (4.1–4.7).
- [X] T044 [P] [US4] Add CLI/selector tests in `tests/test_work_cli.py` for create-only default, explicit --enter/create-and-enter, missing/conflicting args, preview/cancel/dry-run no locks/receipts/branches/checkouts/native objects and separately confirmed parent-source save retained after later cancellation with a fresh preview (4.2–4.5, 4.7).

### Implementation for User Story 4

- [X] T045 [US4] Implement read-only Git preview/eligibility in `src/termcfg/work_git.py`: registered Git source/project only (built-in alone is insufficient), exactly new branch+explicit local base or unoccupied existing local branch without base; resolve local branch/tag/HEAD/commit to reviewed IDs and reject ambiguity/missing/duplicate/remote guessing, any existing destination and missing parent/visible configured-source coverage including depth/exclusions; show repository/common metadata, destination/template/config identities and dirty preservation without filters/fsmonitor or future project registration.
- [X] T046 [US4] Implement one-shot worktree dispatch in `src/termcfg/work_git.py` using the existing operation lock and durable reviewed intent: immediately recheck refs/occupancy/repo/path/parent/coverage/template/config, changed facts renew preview/refuse, use argv with -c core.hooksPath=verified-empty-private-directory, core.fsmonitor=false and worktree.guessRemote=false, strip caller Git repository/config overrides and detect executable checkout filters for pre-dispatch refusal; existing-mode dispatch is capability-gated before any add because a short branch can race into remote fallback; new mode uses -b and the resolved commit; no fetch/submodule/bootstrap/stash/force/reset/delete/copy/install/service effects or persistent config changes.
- [X] T047 [US4] Implement Git receipt retention and read-only observed-result reconciliation in `src/termcfg/work_git.py` and `src/termcfg/work_state.py`: a conflicting repository/destination receipt blocks further creation until reconciled, preserve partial branch/checkout/config outcomes after nonzero/timeout/concurrent Git change, return recovery-required 4 where appropriate and never auto-retry/cleanup; retain latest relevant completed outcome without command output until explicitly reviewed archival, and never let status/reconcile change receipts.
- [X] T048 [US4] Route worktree create and optional post-success ordinary entry in `src/termcfg/work.py` after T045–T047: complete explicit args authorize only reviewed creation, default create-only, --enter separately scopes entry after success, failed entry retains checkout and reports explicit enter guidance, import remains configuration-only and native worktree grouping APIs are unused. Extend the existing source-digest manifest to include `src/termcfg/work_git.py` before enabling this dispatch.
- [X] T049 [US4] Add worktree preview and create-only/create-and-enter choices in `src/termcfg/work_ui.py`, including separately confirmed Add parent source through `src/termcfg/work_edit.py`; finish/release config lock before a renewed Git preview/operation lock, retain earlier save on later cancellation and never silently register a nonexistent destination.
- [X] T050 [US4] Run the US4 independent command and inspect exact Git argv, mutation-call counts, original dirty/index/hooks/config sentinels and partial-retention outcomes; record exits and bounded evidence in `specs/006-configurable-workspaces/quickstart.md`, keeping host/native entry tests fake.

**Checkpoint**: New-branch creation works only within registered visible source coverage, with truthful retained partial outcomes. Existing-branch preview validates local facts, but creation refuses with 5 and zero add calls because the examined public CLI lacks the required guard; importing an existing worktree is unaffected. T043/T044 are disjoint; Git/state/dispatch/UI work is serialized after US3.

## Phase 7: User Story 5 - Close exactly one reviewed workspace (Priority: P2)

**Goal**: Provide exact read-only close scope and fail before mutation when the public guard is absent. Herdr 0.9.5 does not deliver successful close.

**Independent Test**: Run `.venv/bin/python -m pytest tests/test_work_lifecycle.py tests/test_work_cli.py tests/test_herdr_api.py`; scenarios 5.1–5.4 require exact preview or pre-dispatch refusal, zero close/group/pane substitutes and unchanged sibling/data/server sentinels.

### Tests for User Story 5

- [X] T051 [US5] Add close-scope tests in `tests/test_work_lifecycle.py` and `tests/test_work_cli.py` for all tabs/native splits/unowned panes/viewing clients, same-repository sibling and named contexts, authorization syntax/cancel/dry-run, scope/epoch/membership races and legacy groups; on the 0.9.5 fixture confirmed matching scopes still return 5 with zero close calls, changed/unprovable scope returns 4, and idle/status never authorize closure (5.1–5.4).

### Implementation for User Story 5

- [X] T052 [US5] Implement ephemeral ReviewedScope close preview in `src/termcfg/work.py` and `src/termcfg/work_state.py`: action/verified target+epoch/exact tabs-panes/normalized request/capability/scope digest only, no raw machine document or secret whole-file hash; include unowned native splits and the selected endpoint/context, and disclose that closure affects every client viewing this workspace. Client identity/count enumeration is not required or inferred from fake data; never infer complete tab/pane membership from managed bindings alone or persist a discovery inventory.
- [X] T053 [US5] Implement close authorization/recheck/refusal in `src/termcfg/work.py` and `src/termcfg/herdr.py`: dry-run only previews, noninteractive mutation requires both --scope TOKEN and --yes, reject mixed/partial authorization; recheck complete identity/membership and refuse legacy-group/unknown/drift, then return capability 5 before any close on 0.9.5; scope token is no server guard, do not invent public fields, pane-by-pane/group substitutes, upstream patches, server stop, data deletion or layout reconstruction.
- [X] T054 [US5] Present exact close review and missing-capability outcome in `src/termcfg/work_ui.py` and `docs/herdr-workspaces.md`, distinguishing detach (client only), fold (presentation where supported), close (process ending) and data deletion; document retained checkout/branch/config/server and unavailable guarded close, with future admission requiring a new exact-source/schema review and server-boundary race tests rather than enabling a hypothetical guard now.
- [X] T055 [US5] Run the US5 independent command; record exact zero-close-call evidence, current capability refusal and untouched sibling/checkout/branch/config/server sentinels in `specs/006-configurable-workspaces/quickstart.md`; explicitly leave successful guarded native close unavailable rather than marking that outcome passed.

**Checkpoint**: Scope review/refusal is delivered; successful close is unavailable on the examined candidate. Shared lifecycle/CLI test files and implementation are serial; no implementation parallel pair exists in US5 (only independent review of `docs/herdr-workspaces.md` alongside T055 evidence execution).

## Phase 8: User Story 6 - Adopt the model without taking over active work (Priority: P3)

**Goal**: Deliberate opt-in preserves legacy contracts, active layouts/accounts and truthful readiness boundaries.

**Independent Test**: Run `.venv/bin/python -m pytest tests/test_work_config.py tests/test_work_entry.py tests/test_work_lifecycle.py tests/test_work_cli.py`; scenarios 6.1–6.3 must leave v1 state/layout/account/config sentinels untouched and reject invalid structured fallback.

### Tests for User Story 6

- [X] T056 [US6] Add explicit-opt-in and active-preservation regressions in `tests/test_work_cli.py` and `tests/test_work_lifecycle.py`: legacy seven-role Git-only inputs/state/launches unchanged, structured-only fields never infer opt-in, invalid structured config never falls back, synthetic groups/accounts/layouts never adopted/ungrouped/stopped/rebuilt/rebound/resumed; assert proposal/fake/history/native readiness categories remain distinct (6.1–6.3).

### Implementation for User Story 6

- [X] T057 [US6] Complete compatibility routing and refusal diagnostics in `src/termcfg/work_config.py`, `src/termcfg/work.py` and `src/termcfg/work_shell.py`, preserving legacy v1 configuration/state/launch payload paths and explicit structured-v1 selection; add no automatic migration, active reconstruction, account access, primary-entry switch or implicit state-root adoption, and diagnose ownership/recovery requirements for any separately reviewed future migration.
- [X] T058 [US6] Update `docs/herdr-workspaces.md` and `docs/design/configurable-workspaces-interactions.md` with explicit opt-in/example, three entrances/manual editor-lock convention, no automatic active migration and recovery boundaries; distinguish proposed/implemented/historical/isolated/native evidence, current close refusal, selected exact combinations and separate authorizations for native execution, accounts, deployment and entry switching.
- [X] T059 [US6] Run the US6 independent command plus affected legacy `tests/test_work_client_contract.py` and `tests/test_work_review_boundary.py`; record argv/exits/sentinel results and unverified platforms in `specs/006-configurable-workspaces/quickstart.md`, without using feature 005 history or a repeated long-duration baseline as feature 006 acceptance.

**Checkpoint**: Legacy and structured workflows coexist only by explicit selection, with active work untouched. Shared code/test files are serial; an independent documentation reviewer can review T058 after its write completes while T059 runs, without modifying shared evidence.

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Complete bounded dataset acceptance, publication review and honest execution records, without deployment/merge/PR actions.

- [X] T060 Add and execute the cross-story acceptance dataset in `tests/test_work_lifecycle.py`: three directory projects, two additional worktree projects of one repository, two named contexts sharing start and 30 terminals across seven contexts; ten discovery/entry/default-open cycles must yield zero duplicate defaults/wrong focus/cross-workspace ownership changes, and exercise the complete cancel/dry-run/save-drift/Git-unknown/close-refusal tables with original/live/created sentinels preserved (SC-001–SC-005).
- [X] T061 Execute all six new test modules `tests/test_work_projects.py`, `tests/test_work_config_edit.py`, `tests/test_work_templates.py`, `tests/test_work_lifecycle.py`, `tests/test_work_git.py`, `tests/test_work_cli.py` plus `tests/test_herdr_api.py` and the affected existing work regressions selected in T033/T042/T059 using `.venv/bin/python -m pytest`; record actual argv/candidate/lock/source identities/exits/sanitized logs and same-input three-entrance/no-selector outcomes in `specs/006-configurable-workspaces/quickstart.md`, repair affected failures and rerun changed scope only.
- [X] T062 Reconcile implementation/readiness notes in `docs/design/configurable-workspaces.md`, `docs/herdr-workspaces.md`, `specs/006-configurable-workspaces/plan.md` and `specs/006-configurable-workspaces/quickstart.md`: distinguish completed/in-progress/failed-pending-decision/environment-insufficient, list exact isolated evidence and unsupported native combinations, preserve historical scope and state that no host/account/deploy/primary switch/merge/PR/server stop has been authorized by this checklist. Complete these writes before T064 final review.
- [X] T063 Prepare the separately authorized native acceptance recipe in `specs/006-configurable-workspaces/quickstart.md` for exact admitted Linux endpoint/client/filesystem combinations, initial shell/editor/prepared Agent handoff, independent same-repository identities, focus/extras/reconnect/selector and comparable p95 enter/reuse <=1s/new ordinary terminal <=3s with discovery separately measured; do not execute it without later authorization, keep real-account/model calls separately authorized, preserve active instances and 0.9.5 close refusal, and request no new historical long-duration baseline. Finish recipe writes before T064.
- [X] T064 Review the stable final diff only after T060–T063 and all implementation/documentation writes: check `src/termcfg/work.py` source-digest inclusion, all new safety-critical modules, `schemas/local.schema.json`, `examples/work-structured.toml`, `uv.lock`, native fixture/source consistency and `specs/006-configurable-workspaces/quickstart.md`. Run affected document/link/ASCII-example checks, `git diff --check` and bounded public-content inspection including untracked files. Report sanitized locations/categories without reading real secret/auth/session files; any subsequent correction requires affected verification and a new stable final review. No merge, commit or deployment is included.

**Checkpoint**: All applicable isolated checks and publication review have evidence; missing native/account authorization is an unverified state, not a passing result or a reason to block unrelated offline work. The controlled dataset is simulated acceptance, not proof of native behavior.

## Dependencies & Execution Order

### Phase Dependencies and DAG

Task ranges below mean every task in that closed range. Within a serial range, each task depends on its predecessor; explicit joins replace that default for the documented parallel pairs.

```text
T001 -> (T002 || T003) -> (T004 || T005) -> T006 -> T007 -> T008 -> T009 -> T010 -> T011
T011 -> (T012 || T013) -> T014 -> T015 -> T016 -> T017 -> T018 -> T019 -> T020 -> T021 -> T022 -> T023
T023 -> (T024 || T025) -> T026 -> T027 -> T028 -> T029 -> T030 -> T031 -> T032 -> T033
T033 -> (T034 || T035) -> T036 -> T037 -> T038 -> T039 -> T040 -> T041 -> T042
T042 -> (T043 || T044) -> T045 -> T046 -> T047 -> T048 -> T049 -> T050
T050 -> T051 -> T052 -> T053 -> T054 -> T055
T055 -> T056 -> T057 -> T058 -> T059
T059 -> T060 -> T061 -> T062 -> T063 -> T064
```

T003 explicitly requires T001's exact-source decision. T002/T003 write different evidence files. T004/T005 require T002+T003 and share no files. Other parallel pairs require the prior checkpoint and write their own test modules. Tests may use existing helper interfaces read-only; only T004 owns `tests/work_helpers.py`. The DAG is intentionally conservative about shared implementation modules; it does not claim all stories can be coded concurrently.

### User Story Dependencies

| Story | Required task IDs | Deliverable and ownership boundary |
| --- | --- | --- |
| US1 | T001–T011, then T012–T023 | Pure configuration/discovery MVP; work_config/work.py/UI/state foundations already owned serially |
| US2 | T023, then T024–T033 | Uses shared complete T009–T011 launch payload, not US3; common identity/native safety enables later type operations |
| US3 | T033, then T034–T042 | Adds instance/default/extra/drift/rebind behavior on proved entry; revises same modules only after US2 writes finish |
| US4 | T042, then T043–T050 | Uses saved coverage and ordinary entry; serial state/CLI/UI integration, dedicated work_git module |
| US5 | T050, then T051–T055 | Uses proved identities/read methods; only preview/refusal on current API, no positive-close dependency |
| US6 | T055, then T056–T059 | Compatibility/docs on completed dispatch surface, legacy protected throughout earlier phases |
| Polish | T059, then T060–T064 | Cross-story dataset and stable-diff review; native recipe is preparation, not authorized execution |

### Within Each Story

Test cases come first, followed by validation/model resolution, lifecycle services, CLI/UI integration and the checkpoint command. Capture initial relevant failures without weakening tests, then verify the implemented behavior. Any later edit invalidates affected prior evidence and requires the matching check again; unrelated passing checks are not repeated without new evidence. Config saves finish before fresh native/Git review; configuration and operation locks never nest.

### Parallel Opportunities and Examples per Story

| Phase/story | Safe example after prerequisites | Shared-file rule |
| --- | --- | --- |
| Setup | After T001, worker A T002 dependency/lock+research; worker B T003 fixture+native contract | No common evidence file; neither starts a host |
| Foundation | After T002+T003, A T004 helper fixtures; B T005 API test cases | B consumes the existing helpers read-only until join |
| US1 | After T011, A T012 `tests/test_work_projects.py`; B T013 `tests/test_work_config_edit.py` | T014 waits for both; one writer for all subsequent runtime modules |
| US2 | After T023, A T024 `tests/test_work_lifecycle.py`; B T025 `tests/test_work_cli.py` | Join at T026; no concurrent work.py/work_state.py edits |
| US3 | After T033, A T034 `tests/test_work_templates.py`; B T035 `tests/test_work_lifecycle.py` | Join at T036; work_config/work.py/UI/state edits remain serial |
| US4 | After T042, A T043 `tests/test_work_git.py`; B T044 `tests/test_work_cli.py` | Join at T045; shared receipt/CLI integration remains serial |
| US5 | No parallel code tasks; after T054, one independent reviewer reads `docs/herdr-workspaces.md` while owner executes T055 | Reviewer reports without writing quickstart/shared files |
| US6 | No parallel code tasks; after T058, an independent reviewer reads the completed guide while owner executes T059 | A requested correction waits for evidence execution to finish |

No `[P]` means sequential ownership, not permission to allocate another runtime writer. Do not exceed two sub-tasks; sub-agents do not delegate further.

## Requirement and Acceptance Traceability

These mappings name concrete behavior and evidence rather than claiming coverage from a checkbox alone. Scenario numbers refer to [spec.md](spec.md#user-scenarios--testing-mandatory).

| Requirement | Concrete implementation/evidence | Acceptance |
| --- | --- | --- |
| FR-001 | T006/T015 structured sources/templates/entries; T020/T021 shared entrances | 1.4, 2.2, 3.1; T012/T014/T024/T034 |
| FR-002 | T016 selected Git versus directory boundary, T026 independent checkout identity | 1.2, 2.1; T012/T024 |
| FR-003 | T026 endpoint+canonical boundary, not common repository/title/cwd | 2.1; T024 |
| FR-004 | T026 named discriminator+ID; T030 stable binding rename across endpoints | 2.2, 2.6; T024/T025 |
| FR-005 | T026 first HOME/explicit existing start without mkdir/borrow/fallback | 2.3; T024 |
| FR-006 | T016 first-level Git checkout/.git-file enumeration without root/external edges | 1.1–1.2; T012 |
| FR-007 | T015/T016 depth/exclusions/contained optional links/refresh | 1.1, 1.3, 1.5; T012/T014 |
| FR-008 | T017 explicit > specific source > built-in with incompatible conflict | 1.3; T012 |
| FR-009 | T018–T021 one validator/TOML for CLI/selector/manual | 1.4; T014/T061 |
| FR-010 | T006/T015 strict nested ASCII identifiers/literal Unicode; T022 ASCII example | 1.4; T012/T014/T064 |
| FR-011 | T020/T021 actual-boundary preview/required existing mode+template/complete CLI | 1.2, 1.5–1.6; T013/T014 |
| FR-012 | T020 registration-only effects, no clone/create/native launch | 1.5; T013/T014 mutation sentinels |
| FR-013 | T020/T049 cancel/dry-run zero current effects, earlier saves retained | 1.6, 4.4–4.5; T013/T044/T060 |
| FR-014 | T018/T019 cooperative stable lock/comment+permission preservation/outside-edit refusal | 1.7, 1.9; T013 |
| FR-015 | T019 diagnostic/manual fragment; T020 next-load offline validation | 1.7, 1.9; T013/T014 |
| FR-016 | T017 verified executing built-in origin/no PWD/write/open | 1.8; T012 |
| FR-017 | T017 shadowed/default/explicit/disabled references; T026 no active rebind | 1.8–1.9; T012/T024 |
| FR-018 | T027/T031 unique confirmed configured context before entry/open | 2.4; T024/T025 |
| FR-019 | T008/T010/T011/T027–T029 verified membership/one pending intent/no replay | 2.5; T024/T035 |
| FR-020 | T015 order+initial; T027 exactly one initial default | 3.1; T034/T024 |
| FR-021 | T022 development/investigation examples; T038 instance ordinals | 3.1; T034 |
| FR-022 | T037/T038 default focus/create and extras including extra-first | 3.2; T034/T035 |
| FR-023 | T015/T036 exclusive cwd source and fixed first binding | 3.3, 3.8; T034 |
| FR-024 | T039 uninstantiated freshness/removed focus/drift/explicit zero-active rebind | 3.4–3.5; T034/T035 |
| FR-025 | T037/T040 query native membership without adopting/restricting splits | 3.5; T035 |
| FR-026 | T009/T010/T036 official launcher/profile/cwd/HOME, no task commands/install | 3.6; T034/T042 |
| FR-027 | T032/T040 advisory status, no Agent extension/scheduler/control permission | 3.6–3.7; T035/T042 |
| FR-028 | T020 import only; T045 registered Git eligibility | 4.1; T043 |
| FR-029 | T045/T046 exclusive new+local-base/existing-no-base branch forms | 4.2; T043/T044 |
| FR-030 | T045/T046 complete identity/ref/config preview and final recheck | 4.3; T043 |
| FR-031 | T045/T049 visible coverage, separate parent save, no future-project catalog | 4.4; T043/T044 |
| FR-032 | T048/T049 create-only default and explicit entry choice | 4.5; T044 |
| FR-033 | T046 safe argv/hook+fsmonitor suppression/filter refusal/dirty preservation | 4.6; T043/T050 |
| FR-034 | T047/T048 no retry/cleanup, partial/unknown/entry-failure checkout retained | 4.7; T043/T044 |
| FR-035 | T052/T053 complete exact scope/all viewers/explicit authorization | 5.1; T051 |
| FR-036 | T053 scope recheck/legacy-group refusal, no public guard means no dispatch | 5.2; T051/T055 |
| FR-037 | T053 zero current-candidate close calls; sibling/data/server sentinel retention | 5.3; T051/T055; positive guarded close unavailable |
| FR-038 | T054 detach/fold/close/delete distinct effects, no substitution | 5.4; T051 |
| FR-039 | T006/T057 explicit opt-in/invalid no fallback/legacy path intact | 6.1; T056/T059 |
| FR-040 | T057/T058 no automatic migration/adoption/ungroup/restart/rebind | 6.2; T056/T059 |
| FR-041 | T058/T062/T063 evidence categories/exact native combination/separate authorization | 6.3; T056/T059/T064 |
| SC-001 | T060 seven contexts/30 terminals/ten cycles, assert zero duplicate/wrong-focus/ownership changes | Isolated dataset, record T061 |
| SC-002 | T014/T025/T044/T061 same valid/invalid entrance dataset and absent-fzf complete CLI | Compare accepted config/canonical identity/conflicts |
| SC-003 | T013/T044/T051/T060 all cancellation/dry-run points, no new lock/receipt/current effects | Earlier confirmed source survives |
| SC-004 | T051–T055/T060 complete shared-client/sibling/race/group scope matrix | Current 0.9.5 refuses before closure; zero unrelated mutations |
| SC-005 | T013/T024/T034/T043/T060 save/drift/Git partial/unknown matrix | Original bytes/live bindings/created checkout retained; truthful result |

## Original Implementation Strategy

The following delivery order records the original plan. T001–T070 are now complete within the admitted implementation scope; the Phase 11 task record below and [quickstart](quickstart.md) describe current isolated evidence and unverified native/deployment work.

### MVP First (User Story 1 Only)

Complete T001–T023, validate offline discovery/configuration and all three input entrances, then review its independent checkpoint. This is a useful offline directory-configuration MVP; it makes no terminal-entry or native-support claim.

### Incremental Delivery

Complete US2 and US3 next (T024–T042) for daily terminal entry/default/extra behavior using the shared foundation. Add reviewed local Git creation (T043–T050), exact close preview/current-capability refusal (T051–T055), then finish explicit legacy coexistence and documentation (T056–T059). Finish the isolated dataset and readiness notes, prepare later native acceptance without executing it, then review the complete stable final diff (T060–T064). Keep ownership and scope unchanged between increments; an unavailable guarded close is documented as unavailable, not a silently waived requirement.

### Verification and Task Record

Use `.venv/bin/python -m pytest` with the exact listed modules and isolation fixtures; never `uv run`, default third-party smoke or real account calls. Record actual commands, exits, candidate/source/lock identities and sanitized log references in `specs/006-configurable-workspaces/quickstart.md`. A passing fake/native-schema test is isolated evidence only. A failed/missing environment is not a pass. Future successful native guarded close requires a new public-capability design/admission, not an implementation shortcut in this checklist.

The following table records the historical pre-T064 checkpoint; it is retained separately from the later completion records.

| State | Scope at that checkpoint |
| --- | --- |
| Completed | T001–T063 implementation, isolated tests, capability refinements and native-recipe preparation; exact execution evidence is in quickstart |
| In progress | None within this implementation checklist |
| Failed, pending decision | None in the admitted scope; previous intermediate failures are retained historically in quickstart and resolved by fixes or explicit capability refusal |
| Environment insufficient / unverified | Actual changed Herdr/client/Agent/platform/account acceptance and deployment. Successful guarded close and existing-branch creation remain unavailable on examined capabilities; tested refusal is not a success claim for those operations. |

No task authorizes deployment, primary-entry switching, active layout migration, server stop, merge, remote update, publication or PR creation. Those remain separately scoped actions under repository policy.

## Phase 10: Convergence

At the Phase 10 checkpoint, read-only assessment identified four implementation gaps, now addressed below. Task descriptions retain the findings as observed before remediation. These tasks do not authorize native execution, deployment, migration, commit or merge. Existing task markers and capability refusals remain unchanged.

- [X] T065 CRITICAL [US4] Distinguish failed, partially successful and unknown Git outcomes in `src/termcfg/work_git.py` and `src/termcfg/work_state.py`, including read-only status/reconcile reporting. Current create paths at `work_git.py:288-297` collapse nonzero, timeout and mismatched observations into unknown, and report at lines 302-305 exposes no explicit outcome classification. Classify only what dispatch/result facts and read-only observations justify; absence after a possible still-running operation must remain uncertain. Preserve original facts, receipts and created branch/checkout outcomes, keep reconciliation read-only and retain the prohibition on blind retry, automatic cleanup and unsupported existing-branch dispatch. Extend `tests/test_work_git.py` and affected CLI/state tests for known nonzero failure without observed effects, branch-only partial effects, checkout creation followed by failure/timeout and unavailable observations; verify truthful classifications without claiming task completion or rollback. Per Constitution XI, FR-034, US4/AC7 and T043/T047 (partial; finding F2).
- [X] T066 [US1] Complete discovery and registration presentation in `src/termcfg/work_edit.py`, `src/termcfg/work_ui.py` and `src/termcfg/work.py`: retain and display actual source candidates and canonical registration boundaries before save, show candidate mode/template/origin/path, and surface discovery diagnostics in the selector and configuration check without blocking other valid candidates. Current `_proposal()` discards discovery results, registration previews show only TOML, and the selector/config check discard diagnostics. Reuse one validated proposal/discovery contract across CLI previews and TUI confirmation, including independently confirmed parent-source registration during worktree creation. Add isolated presentation assertions for source matches, zero matches, Git boundary canonicalization, unreadable sources and unverifiable built-in roots, preserving zero-effect cancellation/dry runs and separate save/entry authorization. Per FR-011, FR-017, US1/AC2, US1/AC5, US1/AC8 and T020/T021 (partial; finding F3).
- [X] T067 [US1] Provide the required safe manual configuration fragment when configuration is already read-only or safely uneditable at command entry. Address `src/termcfg/work.py`/`src/termcfg/work_config.py` early-load refusal and `src/termcfg/work_edit.py` pre-proposal read failures; do not weaken Constitution II private-file, ownership or link protections, read unsafe secret-bearing content, copy the whole local file, change permissions or claim a successful save. Derive any fallback fragment only from safe explicit inputs or already validated non-secret work data, and clearly disclose validation or editing limitations. Extend `tests/test_work_config_edit.py` and `tests/test_work_cli.py` to cover initial 0400/0444 files and safe 0600 files on an unwritable target, not only permission changes after a valid proposal; assert a diagnostic plus safe fragment, original-state preservation and no new configuration lock/receipt/host effects on early refusal. Per FR-015, US1/AC7 and T019/T020 (partial; finding F4).
- [X] T068 [US3] Select the structured operation deadline from the confirmed current workspace/type launch contract in `src/termcfg/work.py`, preserving the total 30-second ordinary and 60-second managed-Agent budgets. The scan at lines 1088-1090 currently lets a Pi/DSH launcher in an unrelated template extend an ordinary shell operation to 60 seconds. Preserve scoped identity checks, fixed bindings, removed-type focus and a shared deadline through actual preparation/dispatch rather than restarting its budget. Add isolated CLI tests with the same type key bound to shell versus Pi/DSH in different templates, including existing fixed bindings and focus-only paths; verify unrelated templates do not select the budget and no extra preparation occurs. Per T011 and plan: existing operation-budget preservation (partial; finding F5).

Phase 10 execution state:

| State | Evidence |
| --- | --- |
| Completed | T065-T068 implementation and isolated verification; 68/68 implementation tasks checked. The aggregate affected suite passed 728 tests; final CLI suite passed 64 after adding two focus-path cases. Exact commands and limits are recorded in quickstart. |
| In progress | None within the implementation checklist. |
| Failed, pending decision | None. Red tests and the initial sandbox metadata failure were resolved; they are not counted as passes. |
| Environment insufficient / unverified | Native/client/Agent/account/platform acceptance, deployment and primary-entry switching remain outside this pass. Guarded workspace close and existing-branch Git creation retain tested pre-dispatch refusal. |

## Phase 11: Convergence

At the Phase 11 checkpoint, the read-only assessment found two presentation gaps, now addressed below. Task descriptions retain the findings as observed before remediation. Backend creation checks remain enforced; this phase authorizes no native execution, deployment, migration, commit or merge.

- [X] T069 [US4] Complete the final interactive Git worktree creation preview in `src/termcfg/work_ui.py` before create-only/create-and-enter confirmation. The current seven-field summary omits relevant source/configuration and repository/common metadata already present in the reviewed `GitPlan`. Present the selected source and its relevant coverage rules, reviewed repository/common identity summary and selected non-secret configuration identity alongside the existing branch/base/commit/destination/template and suppression/preservation information. Reuse the existing plan facts without reading secrets, dumping the whole local file, requiring every internal timestamp/inode field to be shown, or weakening dispatch-time fact rechecks. Add isolated UI assertions for already configured coverage and independently saved parent-source coverage: the relevant information must appear before confirmation; cancellation must retain zero current-action effects and any earlier separately confirmed save. Per FR-030, US4/AC3 and T045/T049 (partial; finding F1, HIGH).
- [X] T070 [US3] Restrict the terminal-type selector in `src/termcfg/work_ui.py` so types removed from the current template are never offered for new default/extra creation or unsupported rebind. Keep their existing managed instances selectable through clearly labelled focus-only actions, preserving runtime identity checks, fixed startup bindings, removed-type focus budgets and the existing backend creation refusal. Add isolated selector/routing tests with a type retained only in private bindings: `open --new` must omit it, ordinary selection may focus an existing instance without preparation or creation, and a removed type without a usable existing instance must not imply that it can be created. Do not automatically delete bindings or alter native tabs/panes. Per FR-024, US3/AC5 and T039/T040 (partial; finding F2, MEDIUM).

Phase 11 execution state:

| State | Evidence |
| --- | --- |
| Completed | T069-T070 implementation and stable source review; the five affected isolated test modules passed 172 cases. All 70 implementation tasks are checked; exact commands and boundaries are recorded in quickstart. |
| In progress | None within the implementation checklist. |
| Failed, pending decision | None. Test-first failures are implementation evidence, not passes. |
| Environment insufficient / unverified | Native/client/Agent/account/platform acceptance, deployment and primary-entry switching remain outside this pass. Guarded workspace close and existing-branch Git creation retain tested pre-dispatch refusal. |
