# Feature Specification: Configurable Workspaces

**Feature Branch**: `design/configurable-workspaces`

**Created**: 2026-10-22

**Status**: Implemented with isolated verification; native acceptance and deployment remain unverified. Guarded workspace close and existing-branch Git creation remain capability-gated.

**Input**: User description: "Replace fixed project-terminal roles with locally configurable directory projects and independent named contexts; provide equivalent interactive, command-line and manual configuration, predictable terminal instances, explicit worktree creation and safely scoped workspace close. Preserve existing launchers, active work and configuration ownership."

## Clarifications

### Session 2026-10-22

- Q: How should concurrent manual edits and configuration-saving commands be coordinated? -> A: CLI/TUI saves and `work config edit` share one lock. Direct manual TOML editing remains supported between save operations; users avoid doing it concurrently with a configuration save. Observed outside edits cause refusal, but an editor ignoring the lock cannot be excluded in the final replacement window.

## User Scenarios & Testing *(mandatory)*

This specification defines the requested user outcomes. The confirmed [proposal](../../docs/design/configurable-workspaces.md) and [interaction companion](../../docs/design/configurable-workspaces-interactions.md) supply background and design detail. Those documents now describe implemented behavior and current capability limits; executed isolated evidence is recorded in quickstart. They do not establish deployment or native verification. Concrete command spellings, configuration fields, components and storage layout remain design and planning concerns.

### User Story 1 - Configure and discover projects through any entrance (Priority: P1)

As a user, I want to configure search roots, templates and individual workspaces locally, so I can organize ordinary terminal work without changing public code or depending on an interactive selector.

**Why this priority**: Predictable discovery and one configuration contract are the foundation for every subsequent action.

**Independent Test**: Use temporary directories and configuration to register sources and projects through interactive, command-line and manual entrances; compare candidates, validation and identities without opening terminals.

**Acceptance Scenarios**:

1. **Given** a Git search root containing direct child checkouts, a worktree with a `.git` file, non-Git children, deeper checkouts and an externally referenced worktree, **When** the user previews the default search, **Then** only direct child checkout roots appear; the root itself, non-Git children, deeper roots and external metadata targets do not appear.
2. **Given** a directory-mode source or explicit directory inside a larger checkout, **When** the user previews or enters it or a subdirectory within its boundary, **Then** the selected directory remains the project boundary; Git mode instead resolves a selected checkout subdirectory to its checkout root and shows that actual registration path before save.
3. **Given** exclusions, hidden children, symlinks, overlapping sources and explicit entries, **When** candidates are enumerated, **Then** configured bounds and exclusions apply, symlinks are not traversed by default, aliases resolve to one canonical candidate, explicit entries outrank the most specific source and sources outrank the built-in fallback; incompatible equal-priority rules fail, and duplicate titles show distinguishing paths.
4. **Given** equivalent local configuration entered interactively, by complete explicit command-line input, or manually, **When** it is validated and loaded, **Then** all entrances produce the same accepted configuration, candidates, identities and conflicts; unknown fields or values, invalid references, duplicate identifiers and ambiguous rules are rejected. Stable configuration identifiers use ASCII; published configuration keys, identifiers and comments use ASCII. Literal Unicode paths and titles remain valid data, and existing local comments are preserved.
5. **Given** a proposed source or single-directory project registration, **When** the user saves after interactive preview or supplies complete explicit command-line input, **Then** single-directory registration requires an existing path, an explicitly selected Git or directory mode and a valid template; missing inputs or a nonexistent path fails before save, and valid input saves only configuration; no directory is cloned, copied, moved, initialized or created, no native workspace/tab/pane is opened, and no interactive shell, editor or Agent is launched. A source remains a discovery rule and is enumerated again on picker entry or explicit refresh.
6. **Given** a proposed registration, **When** the user cancels before save, requests a dry run, or checks configuration, **Then** the current action changes nothing; checking is offline and launches no host. Missing noninteractive inputs fail, and complete explicit operations remain available when the selector is unavailable.
7. **Given** existing comments, unrelated fields and file permissions, **When** configuration is saved, **Then** they are preserved, compatible canonical duplicates are idempotent and incompatible entries are not overwritten. CLI/TUI saves and `work config edit` coordinate through the same lock so cooperating edits cannot be lost; direct external editing is supported when it does not overlap a save, and observed concurrent outside changes cause refusal. A refusal or failure before atomic publication leaves original content intact; a read-only or safely uneditable file yields a diagnostic and a manual configuration fragment without claiming success. The fragment uses only explicit inputs or previously validated non-secret work data and discloses unverified references/conflicts; when neither is available, it consists of commented editing guidance without invented configuration or unsafe file reads. A failure after replacement, including parent-directory fsync failure, retains the observed published/uncertain state and reports that uncertainty without claiming rollback or unconditional success.
8. **Given** structured configuration with the built-in Rotom candidate enabled, **When** the picker loads, **Then** it shows the verified executing trusted Rotom checkout and its origin, never the caller's working directory or a guessed main checkout; higher-priority matches deduplicate it, and no configuration is written or workspace opened. Users can disable it or choose a defined template; enabled inclusion and explicit template choices are reference-validated. If the trusted checkout cannot be verified, a diagnostic appears and other valid entries remain usable.
9. **Given** a manual configuration change or a different executing Rotom checkout, **When** configuration is next checked or loaded, **Then** the change is validated without restarting existing terminals; the built-in candidate may change, but active workspace bindings and other projects' start directories do not.

---

### User Story 2 - Enter independent directory and named workspaces (Priority: P1)

As a user, I want to enter a checkout, non-Git directory or directory-free named context with a stable identity, so unrelated work remains independent even when names, branches or process directories change.

**Why this priority**: Reliable ownership prevents accidental reuse or control of the wrong terminals.

**Independent Test**: Enter synthetic directory and named contexts, rename them and change process directories; verify distinct identities and refusal of unresolved targets using simulated native observations.

**Acceptance Scenarios**:

1. **Given** an ordinary checkout, two worktrees of one repository and a non-Git project, **When** each is entered, **Then** each owns an independent workspace identified by its verified endpoint and canonical project boundary; branch, title and process-directory changes do not merge or rebind them.
2. **Given** two named contexts without project or problem bindings, **When** they are created at one selected endpoint with distinct stable local identifiers and the same default HOME start directory, **Then** each identity combines that endpoint and its identifier; they remain independent of each other and of a directory project at that path, and renaming either changes only its display title and retains its native binding.
3. **Given** a named context with an explicit existing start directory, **When** it is entered, **Then** that directory is used without borrowing another pane's directory. Missing or unusable start directories fail without directory creation or fallback; omission uses the caller's HOME.
4. **Given** structured configuration and an unmatched, ambiguous or unverifiable project/context, **When** entry or terminal opening is requested, **Then** it fails with corrective guidance before side effects; it does not guess a template, create another workspace, adopt an arbitrary layout or fall back to legacy rules. Opening a terminal requires an already confirmed workspace context.
5. **Given** concurrent requests, contradictory ownership, a missing managed default or a timeout after possible creation, **When** an operation is attempted or resumed, **Then** verified native identity and operation state determine whether it can proceed; duplicate creation, ownership inferred from titles/environment alone, and blind retry are refused. Potentially successful operations are reconciled before another creation.
6. **Given** the same stable local named-context identifier registered at two distinct verified endpoints, **When** either context is entered, focused or renamed, **Then** only that endpoint's context is affected and the other context remains independent, even if titles and start directories match.

---

### User Story 3 - Open predictable terminal types and instances (Priority: P1)

As a user, I want configurable purposes such as shell, edit, build, test, problem and Agent, so I can find existing terminals or intentionally add another without disrupting running work.

**Why this priority**: Ordinary terminal work must be useful independently of Agent extensions.

**Independent Test**: Configure two templates, enter each, open defaults and extras, change running directories and configuration, and observe launch/focus requests through simulated terminals.

**Acceptance Scenarios**:

1. **Given** locally defined ordered types and one valid initial type, **When** a new workspace is entered, **Then** exactly one default instance of the initial type opens and others remain on demand. The development example offers shell, edit, build, test and agent with only shell initially; investigation offers code, agent and problem with only one problem initially. Invalid, duplicate or incomplete ordering and invalid initial selection fail validation.
2. **Given** a verified default instance, **When** its type is opened normally, **Then** it is focused without input injection, restart or directory change; when safely absent it is created. An explicit extra instance does not replace the default. Labels such as problem1, problem2 and problem3 denote instances of one problem type; every type permits extras.
3. **Given** a type first opened in a workspace, **When** later instances are created after any shell changes directory or focus/caller changes, **Then** they reuse its fixed start directory and launcher binding. Each type selects exactly one start-directory source: workspace start, which is the default when omitted, or one literal path. Different types and workspaces may differ. Relative paths resolve against workspace start, home-relative paths use the caller's HOME, absolute paths remain absolute, and unusable directories fail without fallback or command evaluation.
4. **Given** configuration changes affecting an already bound type, **When** existing verified instances are focused or contradictory new instances requested, **Then** live bindings remain intact and existing instances remain focusable, while contradictory creation is refused with drift information. Explicit rebind requires no active instance of that type and acceptance of the new binding, or the user chooses a new workspace. Changes for uninstantiated types may apply without changing existing terminals.
5. **Given** manually created native tabs or splits, removed configured types, or further splits inside a managed tab, **When** Rotom loads or opens a type, **Then** native layout remains usable, manual objects are not automatically adopted, and verified instances of removed types remain focusable without being offered for new creation.
6. **Given** shell, editor and existing managed Agent launch choices, **When** a type is opened, **Then** existing editor and Agent preparation, profile, start-directory and HOME boundaries are preserved; shell-purpose types start interactive shells without automatically executing build, test or investigation work. No arbitrary command evaluation, implicit profile choice, dependency installation, generic Agent framework or scheduler is introduced.
7. **Given** visible Agent or terminal status, **When** it is displayed, **Then** it is advisory and cannot establish task completion, ownership, permission to inject input, automatic closure or session recovery.
8. **Given** a type definition with mixed start-directory sources or an unknown source selector, **When** configuration is validated or the type is opened, **Then** it is rejected before creation; no directory is guessed and no existing binding changes.

---

### User Story 4 - Create a Git worktree with explicit effects (Priority: P2)

As a user, I want to create a new checkout separately from importing or entering existing work, so I can review the branch, destination and entry choice before anything changes.

**Why this priority**: This extends existing project entry with a distinct action that can create persistent Git state.

**Independent Test**: Use disposable local repositories and simulated workspace entry to cover previews, cancellation, local ref changes, conflicts and partial outcomes without launching a host.

**Acceptance Scenarios**:

1. **Given** an existing worktree, **When** it is imported as a project, **Then** registration creates no branch or checkout. New worktree creation only accepts a registered Git project, never a non-Git project or an unregistered repository.
2. **Given** an eligible repository, **When** creation is requested, **Then** the user chooses either a new branch with an explicit local base or an existing unoccupied local branch; the modes are mutually exclusive and existing-branch mode rejects a base. Missing local refs, duplicate new names, occupied branches and any existing destination fail without force or remote guessing. A mode whose public CLI cannot preserve these constraints remains capability-gated: the examined Git existing-branch mode is preview-only and creation refuses with exit 5 before dispatch; importing existing worktrees remains available.
3. **Given** complete creation inputs, **When** reviewed, **Then** the preview discloses repository identity, branch mode, branch/base and resolved local ref identities, destination, template and relevant source/configuration, plus hook/bootstrap suppression and preservation of dirty work. Immediately before dispatch these are rechecked; changed refs, occupancy, destination, template or configuration require a new preview or refusal before creation.
4. **Given** a destination outside a source's visible range, **When** the user requests creation, **Then** creation is blocked until the user changes destination or independently previews and confirms adding a parent search root. The built-in Rotom candidate grants no parent coverage. After a source save the creation preview is refreshed; cancelling creation retains that separately saved source but creates no branch, checkout or workspace. Future project registrations are not created.
5. **Given** a valid preview, **When** the user selects create only or create and enter, **Then** only the explicitly selected effects occur. Complete explicit command-line input authorizes creation and defaults to create only; entry requires an explicit choice. Dry run and cancellation before dispatch have no creation effects.
6. **Given** a dirty original checkout and project hooks/bootstrap, **When** Rotom creates a worktree, **Then** original dirty changes remain intact and are not copied or stashed; checkout hooks/bootstrap do not execute, persistent Git configuration is unchanged, and no reset, force, deletion, dependency installation, secret copying or service startup occurs.
7. **Given** creation failure or timeout with possible partial effects, **When** the result is reported or retried, **Then** the outcome distinguishes failure, partial success and unknown, and read-only reconciliation precedes another attempt without blind retries or automatic cleanup. If checkout creation succeeds but entry fails, the checkout is retained and explicit entry can be retried.

---

### User Story 5 - Close exactly one reviewed workspace (Priority: P2)

As a user, I want to close the complete selected workspace with clear scope, so other workspaces and repository data remain safe.

**Why this priority**: Ending terminal processes requires stronger scope evidence than selecting or focusing them.

**Independent Test**: Simulate multiple workspaces, two checkouts of one repository and multiple viewing clients; confirm, cancel and race close requests and compare affected identities.

**Acceptance Scenarios**:

1. **Given** a selected workspace with multiple tabs, split panes and viewing clients, **When** close is reviewed, **Then** the preview identifies the workspace, every affected tab/pane and the effect on all clients viewing it; closing requires confirmation or explicit noninteractive authorization for that complete scope. Process idleness never supplies authorization.
2. **Given** a reviewed scope, **When** identity or membership changes before dispatch, scope cannot be proven, or legacy grouping could affect another workspace, **Then** close is refused or returns to a fresh review; no group-wide close or reconstruction is substituted.
3. **Given** an authorized independently verified workspace, **When** it closes, **Then** only its tabs/panes and processes end; another checkout of the same repository, named contexts and other clients' unrelated work remain intact. Checkout directories, branches, configuration and the server are retained.
4. **Given** detach, fold and close choices, **When** the user selects one, **Then** detach disconnects only the client, fold changes presentation where supported, and close explicitly ends the selected workspace's processes; none implies checkout, branch or configuration deletion.

---

### User Story 6 - Adopt the model without taking over active work (Priority: P3)

As an existing user, I want to opt into the configurable model deliberately and retain my current setup, so trying it does not rebuild or interrupt active work.

**Why this priority**: Migration is independently useful once the new model has been implemented and verified.

**Independent Test**: Load old configuration and synthetic active state, opt into the new contract explicitly, and verify that invalid new configuration never causes silent fallback or active-state takeover.

**Acceptance Scenarios**:

1. **Given** current Git-only seven-role configuration without opt-in, **When** it is loaded, **Then** existing behavior is retained; enabling the built-in candidate does not independently opt it in. New structured configuration and migration require explicit selection, and invalid structured configuration fails rather than using legacy fallback.
2. **Given** active layouts, native Git groups, accounts and managed configuration, **When** new configuration is introduced or migration is offered, **Then** nothing is automatically adopted, ungrouped, terminated, rebuilt or rebound; migration has a separately reviewed ownership and recovery boundary.
3. **Given** the proposal, historical verification or simulated tests, **When** readiness is reported, **Then** each is distinguished from current implementation, exact supported native combinations and actual native evidence; no deployment, primary-entry switch, real-host execution or real-account use is implied. New native execution requires separate authorization and evidence for the changed behavior, without reopening the historical long-duration baseline merely to claim this feature passed.

### Edge Cases

- A source becomes unreadable, a path disappears, or a symlink target changes between preview and action: report the affected candidate and refuse unsafe dispatch rather than widening discovery or guessing a directory.
- The same canonical path appears through aliases, multiple sources and the built-in candidate: apply explicit precedence; incompatible equal-priority results fail rather than duplicating or silently choosing.
- Multiple native workspaces appear at one project path without a unique verified registration: require explicit selection or report a conflict before creation or control.
- A terminal is waiting for input, has changed its title or cwd, or appears idle: none changes its binding, proves completion or permits input or closure.
- Configuration changes or a concurrent operation occurs after review: preserve active bindings and original file contents, revalidate the intended scope and report conflict or unknown when proof is incomplete.
- A separately confirmed source save precedes worktree cancellation: the source remains; cancellation affects only the unconfirmed creation action.
- Git may have created a branch or checkout before returning failure or timing out: inspect read-only and report observed/unknown effects without automatic retry, reset or deletion.
- A checkout exists after entry failure: retain it for explicit re-entry; do not report that all effects were rolled back.
- Selector, native identity or independent-close capability is unavailable: keep explicit configuration operations available, diagnose the missing capability and refuse unsupported control rather than widening scope or patching upstream.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to configure discovery sources, templates and explicit directory or named workspaces locally without public-code changes.
- **FR-002**: Directory projects MUST support ordinary Git checkouts, Git worktrees and non-Git directories; Git mode MUST use the checkout boundary, while directory mode MUST retain its selected canonical boundary even inside a repository.
- **FR-003**: Directory workspace identity MUST combine the verified selected endpoint and canonical project boundary, independent of title, branch and process cwd; checkouts of one repository MUST remain independent.
- **FR-004**: Named context identity MUST combine the verified selected endpoint and a stable local identifier separate from mutable titles, without requiring a project directory or problem identifier; same-cwd contexts and projects, and the same local identifier at different endpoints, MUST remain independent and rename MUST retain the binding.
- **FR-005**: Named starts MUST default to the caller's HOME or an explicit existing directory; resolving any start MUST neither create directories nor borrow another pane's cwd or silently fall back on failure.
- **FR-006**: Default Git discovery MUST enumerate first-level child checkout roots including `.git` files, excluding the root itself, non-Git/deeper children and externally referenced worktrees; directory-mode children MUST remain independent candidates.
- **FR-007**: Discovery MUST obey configured bounds and exclusions, avoid whole-HOME scans and external metadata traversal, and not follow symlinks by default; re-entry or explicit refresh MUST re-enumerate saved source rules.
- **FR-008**: Canonical candidates MUST deduplicate with explicit entries above the most specific source above the built-in candidate; incompatible equal-priority rules MUST fail, and identical display names MUST be distinguishable by path.
- **FR-009**: Interactive, command-line and manual entrances MUST share the same private configuration, validation, references, identities, precedence and conflict rules without a second project database.
- **FR-010**: Validation MUST reject unknown fields/values, invalid references, duplicate identifiers and ambiguous definitions and require ASCII stable configuration identifiers, while accepting literal Unicode paths/titles as data without command evaluation. Published configuration keys, identifiers and comments MUST use ASCII; existing local comments MUST remain preserved regardless of their language.
- **FR-011**: Interactive registration MUST preview the proposed configuration and actual candidates/registration boundary before save. Single-directory project registration MUST require an existing path, an explicitly selected Git or directory mode and a valid template, refusing missing inputs or nonexistent paths before save; complete explicit command-line inputs MUST authorize the same save without requiring the selector, and incomplete noninteractive input MUST fail.
- **FR-012**: Configuration registration MUST remain separate from entry and MUST NOT clone, copy, move, initialize or create directories, create native terminal objects, or launch interactive shells, editors or Agents.
- **FR-013**: Cancellation before confirmation and dry runs MUST have no current-action side effects; configuration checks MUST be read-only and offline without host launch. Previously confirmed independent actions MUST not be reported as undone.
- **FR-014**: Saves MUST preserve comments, unrelated fields and existing permissions. Refusals and failures before atomic publication MUST leave original content intact; failures after replacement MUST retain the observed state and report published/uncertain durability without claiming rollback or unconditional success; compatible canonical duplicates MUST be idempotent and incompatible registrations MUST be refused. CLI/TUI saves and `work config edit` MUST share one configuration lock and protect cooperating edits from lost updates. Direct manual editing remains supported between save operations; users MUST avoid overlapping it with a configuration save. Observed outside changes MUST cause refusal, without claiming exclusion of an uncoordinated writer in the final replacement window.
- **FR-015**: Read-only or safely uneditable configuration MUST produce a diagnostic and a manual fragment without partial writes or false success. Fragment values MUST come only from explicit inputs or previously validated non-secret work data, with unverified references/conflicts disclosed. Without either safe source, the fragment MUST consist of commented editing guidance without invented configuration; private-file protections MUST NOT be weakened to obtain its content. Manual changes MUST be validated at the next check/load without terminal restart.
- **FR-016**: Structured mode MUST offer an enabled-by-default, disableable Rotom candidate from the verified trusted executing checkout, disclose its path/origin and allow template selection; it MUST neither infer PWD/main nor save configuration or open a workspace implicitly.
- **FR-017**: Enabled built-in inclusion and explicit template choices MUST validate defined-template references, even if a higher-priority candidate wins; disabled inclusion with no explicit choice MUST impose no implicit default-template reference. Unverifiable roots MUST be diagnosed without blocking other valid entries, and executing-checkout changes MUST not rebind active workspaces.
- **FR-018**: Entry MUST resolve a unique confirmed configured or verified built-in context before side effects; terminal opening MUST require an existing confirmed context and MUST NOT guess ownership, templates or legacy fallback.
- **FR-019**: Managed control MUST rely on verified scoped native identities and operation outcomes, not titles or environment alone; concurrent creation, missing defaults and unknown outcomes MUST be reconciled before further creation without blind retry or arbitrary layout adoption.
- **FR-020**: Templates MUST define an explicit duplicate-free ordering covering exactly their local types and one valid initial type; new workspaces MUST start only one default initial instance, with other types on demand.
- **FR-021**: The development example MUST provide shell/edit/build/test/agent with only shell initially; investigation MUST provide code/agent/problem with only one problem initially, and numbered problem labels MUST denote instances rather than extra type definitions.
- **FR-022**: Normal type opening MUST reuse its verified default or create it when safely absent; explicit extras MUST be supported for every type without replacing that default, and focus MUST inject no input or restart.
- **FR-023**: Each workspace/type MUST select exactly one start-directory source, either workspace start (the omission default) or one literal path; mixed sources and unknown source selectors MUST fail validation. It MUST retain one fixed resolved start directory and launcher binding from first instantiation; later instances MUST reuse it regardless of runtime cd, focus or caller cwd. Relative starts MUST resolve against workspace start, home-relative starts against caller HOME and absolute starts unchanged.
- **FR-024**: Configuration changes MAY affect uninstantiated types but MUST preserve live bindings; contradictory bound-type creation MUST fail with drift information, while verified existing instances, including removed types, remain focusable. Rebind MUST be explicitly accepted with no active instance of that type, or use a new workspace.
- **FR-025**: Native tabs and splits MUST remain available without automatic managed adoption or restrictions to single-pane layouts.
- **FR-026**: Launching MUST preserve existing managed Agent and independent editor entry points, preparation, profiles, cwd and HOME boundaries; shell purposes MUST not execute tasks automatically or introduce arbitrary commands, implicit profiles or installation.
- **FR-027**: Workspace organization MUST work without Agent extensions and MUST NOT introduce a generic Agent framework or scheduler; visible status MUST NOT establish completion, control permission, automatic close or session recovery.
- **FR-028**: Importing an existing worktree MUST create no branch/checkout; new worktree creation MUST be a distinct action restricted to registered Git projects.
- **FR-029**: Creation MUST require exactly one of a new branch with explicit local base or an unoccupied existing local branch without a base; missing refs, duplicate new branch names, occupied branches and existing destinations MUST be refused without remote guessing or fetch. A mode lacking the necessary public guard MUST refuse before dispatch; examined existing-branch creation remains unsupported (5), while reviewed new-branch creation and existing-worktree import remain available.
- **FR-030**: Creation MUST preview repository, branch mode and branch/base resolved identities, destination, template, relevant configuration, hook/bootstrap suppression and dirty-work preservation; these MUST be rechecked immediately before dispatch and changes MUST require renewed preview or refusal.
- **FR-031**: A new destination MUST not exist and MUST fall within configured visible source coverage; missing coverage MUST require an independently confirmed parent-source save or destination change before renewed preview. Built-in inclusion MUST not authorize parent coverage, and no future project state MUST be registered.
- **FR-032**: Command-line creation MUST default to create only and require explicit entry selection; interactive creation MUST offer explicit create-only/create-and-enter choices, with complete explicit inputs authorizing only their reviewed scope.
- **FR-033**: Creation MUST preserve dirty original checkouts without copying changes or stashing, disable checkout hooks/bootstrap for that invocation and leave persistent Git configuration unchanged; force, reset, deletion, dependency installation, secret copying and service startup MUST NOT occur implicitly.
- **FR-034**: Failure/timeout MUST distinguish failed, partially successful and unknown outcomes and require read-only reconciliation before further creation without blind retry or automatic cleanup; successful checkout creation followed by entry failure MUST retain the checkout for explicit re-entry.
- **FR-035**: Close MUST review exactly one selected workspace's stable identity, complete tabs/panes and impact on all viewing clients, and require confirmation or explicit noninteractive authorization for that scope; idleness MUST NOT authorize it.
- **FR-036**: Close MUST recheck identity and complete scope before dispatch; changed, unprovable or legacy-group scope MUST require renewed review or refusal without group-wide substitution or active reconstruction.
- **FR-037**: Close MUST affect only the selected workspace's tabs/panes/processes and preserve other workspaces, including same-repository checkouts, checkout directories, branches, configuration and the server.
- **FR-038**: Detach, fold, close and data deletion MUST remain distinct: detach leaves processes running, fold is presentation where supported, and close MUST NOT imply deletion.
- **FR-039**: Existing seven-role Git-only configuration MUST retain its contract until explicit structured opt-in/migration; invalid structured configuration MUST fail without silent fallback, and built-in inclusion MUST not trigger opt-in.
- **FR-040**: Migration MUST preserve active instances, native layouts/groups, accounts and configuration ownership without automatic adoption, ungrouping, termination, recreation or rebinding; ownership and recovery boundaries MUST be reviewed explicitly.
- **FR-041**: Readiness reports MUST distinguish proposals, implementation, historical results, isolated checks and current native support/evidence; deployment, primary-entry switching, native-host and real-account execution MUST require separately authorized work, and historical long-duration acceptance MUST NOT stand in for this feature's evidence.

### Key Entities *(include if feature involves data)*

- **Discovery source**: A local rule describing a bounded search root, mode, exclusions and template choice; it is not a stored snapshot of discovered projects.
- **Directory project**: An existing canonical project boundary with Git or directory semantics and a selected template; each endpoint/project pair has independent workspace ownership.
- **Named context**: A directory-independent identity combining the verified selected endpoint and stable local identifier, with a mutable display title, template and optional process start directory. The same local identifier at different endpoints denotes independent contexts.
- **Workspace template and type**: A locally defined ordered set of terminal purposes with one initial type and launch/start choices; a purpose can have a default instance and explicit extras.
- **Managed binding**: Verified workspace/type/instance ownership, native identity, fixed launch/start choices and operation outcome; runtime titles, cwd and status do not redefine it.
- **Reviewed action scope**: The identities and effects authorized for one save, creation, entry or close, including any separately completed prior action and any unknown result requiring reconciliation.

### Acceptance Traceability

Story/scenario references below identify the acceptance evidence required for every functional requirement; they do not claim that it has been executed.

| Requirements | Acceptance scenarios |
| --- | --- |
| FR-001 | 1.4, 3.1, 2.2 |
| FR-002 | 1.2, 2.1 |
| FR-003 | 2.1 |
| FR-004 | 2.2, 2.6 |
| FR-005 | 2.3 |
| FR-006 | 1.1, 1.2 |
| FR-007 | 1.1, 1.3, 1.5 |
| FR-008 | 1.3 |
| FR-009, FR-010 | 1.4 |
| FR-011 | 1.2, 1.5, 1.6 |
| FR-012 | 1.5 |
| FR-013 | 1.6, 4.4, 4.5 |
| FR-014, FR-015 | 1.7, 1.9 |
| FR-016, FR-017 | 1.8, 1.9 |
| FR-018 | 2.4 |
| FR-019 | 2.5 |
| FR-020, FR-021 | 3.1 |
| FR-022 | 3.2 |
| FR-023 | 3.3, 3.8 |
| FR-024 | 3.4, 3.5 |
| FR-025 | 3.5 |
| FR-026 | 3.6 |
| FR-027 | 3.6, 3.7 |
| FR-028 | 4.1 |
| FR-029 | 4.2 |
| FR-030 | 4.3 |
| FR-031 | 4.4 |
| FR-032 | 4.5 |
| FR-033 | 4.6 |
| FR-034 | 4.7 |
| FR-035 | 5.1 |
| FR-036 | 5.2 |
| FR-037 | 5.3 |
| FR-038 | 5.4 |
| FR-039 | 6.1 |
| FR-040 | 6.2 |
| FR-041 | 6.3 |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a controlled local dataset containing three directory projects, two additional worktree projects of one repository, two named contexts sharing a start directory and 30 terminal instances across them, ten repeated discovery/entry/default-open cycles produce zero duplicate managed defaults, wrong-workspace focus events or cross-workspace ownership changes.
- **SC-002**: Every equivalent valid and invalid configuration case in the acceptance dataset produces the same accepted settings, canonical identities or conflict outcome through all three entrances; explicit command-line configuration, validation, entry, terminal opening and authorized lifecycle actions are fully usable without the selector.
- **SC-003**: Across every cancellation and dry-run point in the acceptance scenarios, 100% leave no side effects from the current unconfirmed action; independently confirmed earlier saves remain correctly reported and retained.
- **SC-004**: Across all close-scope acceptance cases, including shared clients, same-repository checkouts, concurrent membership changes and legacy groups, 100% either affect exactly the explicitly authorized workspace or refuse before closure; zero unrelated workspace or repository-data changes occur.
- **SC-005**: Across all save, binding-drift and worktree failure cases, 100% preserve original content before publication, running instances and successful checkout outcomes as specified; after a replacement has occurred, any durability uncertainty retains the observed state without compensating overwrite. None reports unknown or partial effects as complete rollback or unconditional success.

## Assumptions

- The user controls the relevant local configuration and explicitly selects the endpoint; a named context requires process cwd but its identity requires neither a directory project nor a problem object.
- Existing editor and managed Agent launch preparation remains a dependency. This feature organizes terminals and does not replace their account, credential, profile or installation contracts.
- Public native capabilities must prove scoped identity, independent workspace ownership and close effects. If the selected official combination cannot do so, the operation remains unsupported pending design revision; upstream patches and private interfaces are not authorized alternatives.
- Stable configuration identifiers use ASCII. Published configuration keys, identifiers, comments and examples use ASCII; this does not restrict real user paths or display titles, which may be Unicode, or authorize rewriting existing local comments in any language. Public examples, diagnostics published as evidence and configuration guidance must remain free of private paths, credentials, session content and arbitrary environment dumps; local previews may show the user's chosen paths.
- Ordinary project registration requires an existing directory. Worktree creation is the only covered action creating a new checkout; cloning, future project registration, deletion and remote lifecycle management are outside scope.
- This specification supersedes fixed-role/Git-only requirements only for users who explicitly opt into the new model after implementation; it does not retroactively change legacy behavior or historical acceptance scope.
- Existing user-approved terminal performance budgets remain governed by their original acceptance scope and applicable upgrade regression requirements; this specification adds no selector latency threshold and does not restart the historical long-duration baseline.
- Default verification uses isolated local data, temporary HOME/state, blocked network and simulated host behavior. Real hosts, accounts, deployment and primary-workflow switching require separate authorization and evidence for the exact changed scope. This document requests no execution or repetition of historical long-duration baselines.

## Implementation capability refinement (2026-10-22)

Official Git source and an isolated synthetic Git 2.43.5 reproduction showed that an existing short branch deleted after review can be recreated from a same-name remote-tracking ref even with `--no-guess-remote`. A full `refs/heads/...` argument can instead detach HEAD. The implementation therefore applies the existing unsupported-capability assumption and preserves FR-029 rather than weakening its no-remote-guessing constraint: existing-branch preview remains read-only, creation returns 5 with no add call, and new-branch mode uses the resolved local commit. This is a conservative implementation boundary under the user's instruction to finish remaining work except unavailable/high-risk actions; it is not a claim that the user answered the optional preference question. Enabling existing-branch dispatch requires a separately reviewed capability or explicit requirement revision.
