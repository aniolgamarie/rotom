# Implementation Plan: Configurable Workspaces

**Branch**: `design/configurable-workspaces` | **Date**: 2026-10-22 | **Spec**: [spec.md](spec.md)
**Feature ID**: `006-configurable-workspaces`
**Input**: `specs/006-configurable-workspaces/spec.md`
**Status**: Runtime, isolated verification and stable final review complete. Native acceptance and deployment remain unverified. Existing-branch Git creation and guarded workspace close are capability-gated before dispatch.

## Summary

Extend the existing `work` entry with configurable discovery sources, directory projects, independent named contexts, ordered terminal types and fixed per-type startup bindings. Keep one machine-private TOML contract for selector, CLI and manual input. Herdr owns terminals/layouts, agentcfg owns managed Agent execution, and the independent editor launcher remains the editor entry. Add no daemon, second project catalog or generic Agent scheduler.

The user confirmed the configuration-editing convention: CLI/TUI saves and `work config edit` coordinate through one lock. Direct manual editing remains supported between save operations. Observed outside changes cause refusal; no universal compare-and-swap guarantee is claimed. This is encoded in [spec clarification](spec.md#clarifications), story 1.7 and FR-014.

Herdr 0.9.5 is the current stable candidate researched on 2026-10-22. Its public close request lacks a server-enforced membership guard. Therefore the current candidate supports a read-only close preview and explicit capability refusal, but not safe mutating Rotom close under FR-036. Keep that operation unavailable until a verified public guard exists; do not report successful close as delivered. This is a known capability boundary permitted by the spec, not an unresolved design choice.

## Technical Context

**Language/Version**: Python >=3.11 using the prepared repository `.venv`; observed 3.11.11 is evidence, not an exact compatibility gate. Preserve Bash launchers without replacing system Python.

**Primary Dependencies**: Existing PyYAML, jsonschema, Jinja2 and pytest; admitted tomlkit 0.15.2 for comment-preserving edits; optional fzf (reviewed candidate 0.74.5); Git >=2.36 public CLI and Herdr public socket API. Dependency/source admission and isolated preparation are recorded in research; startup performs no installation.

**Storage**: Existing selected machine-private TOML is the only project/source/template catalog. Minimal private v2 binding/operation receipts live under the normal XDG state root, independently of terminal deployment and Agent state. No stored discovery inventory, screen history, conversations or credentials.

**Testing**: pytest, synthetic repositories, temporary HOME/XDG/state, blocked network, fake hosts and file sentinels. Cover strict validation, file preservation, unsafe paths, cooperating-writer serialization, uncertain outcomes and lifecycle boundaries. Native support is a later separately authorized acceptance layer.

**Target Platform**: Linux server first, retaining the existing O_PATH/procfs endpoint protection. Exact architecture/filesystem/client combinations need evidence. Earlier macOS/Ghostty acceptance belongs to feature 005, not this changed workflow. Other combinations remain unverified.

**Project Type**: Existing Python CLI extension and thin native adapter; fzf supplies selection only.

**Performance Goals**: Preserve previously approved comparable enter/reuse p95 <=1 second and new ordinary-terminal p95 <=3 seconds. Record discovery cost separately without inventing selector thresholds. Select affected upgrade regressions; do not restart the historical long-duration baseline.

**Constraints**: Reject unknown fields/references; ASCII new identifiers/published examples; literal Unicode paths/titles; no shell evaluation, startup downloads, upstream patches or private APIs. Preserve active processes, credentials, layouts and configuration ownership.

**Scale/Scope**: Three directory projects, two additional worktree projects, two named contexts sharing one start path, 30 terminals and ten repeated cycles. Local-only worktree creation with explicit refs and configured coverage. Close never deletes data or stops the server.

**Clarification status**: No unresolved requirement/design clarification. Configuration concurrency is confirmed; unsafe close is explicitly capability-gated.

## Constitution Check

Evaluated against constitution 2.4.0 before research and again after Phase 1. All applicable design gates pass with the unsupported-operation boundary retained; no exception is requested.

| Gate | Principles | Before research | After design |
| --- | --- | --- | --- |
| Shared core / strict configuration | I, XI | Reuse existing entry/schema | Pass: one selected TOML, common non-secret loader, explicit opt-in, strict nested validation |
| Secrets / ownership / preservation | II, III, VII, VIII | No private-state inspection/mutation | Pass: only work fragment in editor staging, no secret-bearing receipts/whole-file digest, safe publication, no Git history/deploy action |
| Save concurrency / truthful recovery | III, XI | Research required | Pass: confirmed cooperating-writer contract; bounded external-edit detection; partial/unknown outcomes are not rollback claims |
| Explicit effects / dependencies | IV, IX, X, XI | Source/capability research | Pass: separate save/create/enter/close scopes, explicit dependency/lock admission later, no implicit install |
| Isolated versus native evidence | V, VIII, IX, X | Default fakes/temp HOME | Pass: quickstart separates proposed tests, historical evidence and later native execution |
| Public upstream interfaces | VI, IX, XI | New methods need inspection | Pass: public env handoff; precise adapter admission; close refuses without a proven server guard |
| Upgrade / compatibility scope | X | Current stable verification | Pass: minimum runtime differs from exact evidence; current candidate not a permanent version gate; affected regression only |
| Terminal-first identity / lifecycle | XI | Need stable scoped binding | Pass: canonical/named endpoint identity, frozen type contracts, native/manual pane distinction, advisory Agent state |
| Unrelated Agent rebuild requirements | I, technical constraints | Out of feature scope | Not applicable: no Agent rebuild, host patch retirement, status-bar replacement or new adapter |

The existing unknown ratification-date TODO is preserved and grants no exception. This plan makes no commit/merge/deployment claim.

## Project Structure

### Documentation (this feature)

```text
specs/006-configurable-workspaces/
├── spec.md
├── checklists/requirements.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
└── contracts/
    ├── configuration.md
    ├── cli.md
    ├── native-api.md
    └── lifecycle.md
```

The generated `tasks.md` records implementation progress and current capability refinements.

### Source Code (repository root)

Implemented responsibility map; native execution and deployment are separate:

```text
work
rotom-work-shell
src/agentcfg/config.py          # reuse non-secret local loading
src/agentcfg/storage.py         # reuse safe file operations, not arbitrary-writer CAS
src/termcfg/work.py             # CLI routing and lifecycle dispatch
src/termcfg/work_config.py      # legacy/structured settings, references and launcher selection
src/termcfg/work_shell.py       # v1 compatibility and v2 one-use handoff
src/termcfg/work_projects.py    # boundaries, discovery, precedence and built-in origin
src/termcfg/work_edit.py        # preserving work-fragment edits and configuration lock
src/termcfg/work_state.py       # minimal v2 bindings/receipts and reconciliation facts
src/termcfg/work_git.py         # reviewed local worktree lifecycle
src/termcfg/work_ui.py          # optional fzf selection and explicit forms
src/termcfg/herdr.py            # precise public method/result and capability checks
schemas/local.schema.json
examples/
tests/test_work_projects.py
tests/test_work_config_edit.py
tests/test_work_templates.py
tests/test_work_lifecycle.py
tests/test_work_git.py
tests/test_work_cli.py
tests/test_herdr_api.py
tests/fixtures/herdr-native/
docs/herdr-workspaces.md
docs/design/configurable-workspaces*.md
pyproject.toml
uv.lock
```

**Structure Decision**: Retain the existing package and launcher boundaries. New modules have bounded responsibilities; no generic service/repository framework. Share storage and non-secret loading, not termcfg deployment journal semantics. Include all safety-critical launch modules/schemas in the source digest. Schemas/locks/tests/docs change together only in implementation.

## Phase 0 Outcome

[Research](research.md) records the decision, rationale and alternatives for each question:

- Reuse existing preparation and pending/ready/commit/accepted launch handoff.
- Explicit `model = "structured-v1"` opts in; structured-only fields without it fail.
- Bounded discovery defaults to depth 1. Explicit entries outrank the most specific source, then the unsaved verified Rotom candidate.
- Directory identity is endpoint plus canonical boundary; named identity is endpoint plus local ID. No title/cwd/status inference.
- tomlkit 0.15.2 was admitted and installed only in the isolated prepared environment; fzf remains an optional external selector and was not installed or executed.
- Configuration edits use the confirmed shared-lock convention and non-secret fragment staging.
- Private state stores only managed references and uncertain operations, with live native proof still required.
- Ordinary workspace.create passes env to the prepared wrapper for one initial instance; no grouped worktree API or bootstrap tab replacement.
- Git owns local worktree creation. Hooks/bootstrap are suppressed per invocation; executable checkout filters cause refusal. New-branch mode uses a resolved local commit. The examined existing-branch CLI can race into remote fallback, so its creation returns 5 before dispatch; import remains available. Linux directory-FD pinning and pre/post identity checks retain uncertain outcomes rather than claiming an atomic transaction against unrelated Git writers.
- Close has no public exact-membership guard in the examined candidate and therefore cannot mutate.

## Phase 1 Outcome

[Data model](data-model.md) defines configuration versus runtime ownership, endpoint evidence, workspace/type/instance identity, fixed startup contracts, bounded metadata, stale restoration and receipt retention.

[Configuration contract](contracts/configuration.md) defines strict structured TOML, explicit legacy opt-in, defaults/references, path resolution, discovery bounds and preserving save behavior. It includes a complete ASCII example with five development purposes and three investigation purposes.

[CLI contract](contracts/cli.md) defines selector/CLI/manual parity, explicit source/project/named registration, enter/open/extras/rebind, config check/edit, local worktree creation and close preview/refusal. Ordinary save never implies entry; complete CLI actions need no fzf.

[Native contract](contracts/native-api.md) defines public-method admission, pinned endpoint/caller proof, versioned initial-pane handoff and the close capability boundary.

[Lifecycle contract](contracts/lifecycle.md) fixes operation ordering, non-nested locks, write-ahead intents, late/unknown-result reconciliation, checkout retention and destructive-scope refusal.

[Quickstart](quickstart.md) records executed isolated checks and a separate future native recipe. It preserves historical baseline scope and makes no deployment claim.

## Implementation Ordering

1. Extend strict schema/normalization and explicit opt-in, preserving all legacy input/launch contracts.
2. Implement pure discovery/built-in origin/precedence and one save/edit path; wire explicit CLI before selector actions.
3. Add v2 minimal state and exact native method fixtures/admission, retaining Linux endpoint protection and v1 state untouched.
4. Implement ordinary workspace creation and configurable default/extra bindings through the complete handoff; cover every uncertain-result window before enabling dispatch.
5. Add separately authorized local Git worktree creation and read-only reconciliation; preserve partial successes and original dirty work.
6. Add complete close preview and unavailable-capability refusal. Successful close remains gated pending a verified public guard; never substitute group/pane close.
7. Integrate fzf forms, legacy regression, migration guidance and evidence records. Enable native support only after separately authorized exact-combination tests.

These are planning dependencies, not a generated task checklist. Real-account work, deployment, primary-entry switching and active-layout migration remain separate.

## Requirements and Acceptance Mapping

| Requirements | Design coverage | Planned validation |
| --- | --- | --- |
| FR-001–002, FR-006–010 | Configuration / data model discovery | Source depth, .git files, exact directory boundaries, aliases, Unicode, exclusions, precedence and invalid definitions |
| FR-003–005 | Data model / lifecycle identity and starts | Independent checkouts/named IDs/endpoints, same HOME, rename, missing starts |
| FR-011–015 | Configuration / lifecycle save | Three-entrance parity, zero-effect dry run/cancel, shared-lock serialization, external drift, preservation, safe-input manual fragment or commented guidance when no safe values are available |
| FR-016–017 | Trusted built-in candidate | Executing-root proof, opt-out/default references, deduplication, diagnostic without PWD fallback |
| FR-018–019 | Native / lifecycle control | Explicit caller, concurrent creation, response loss, marker/endpoint replacement, zero blind replay |
| FR-020–025 | Type model / CLI / handoff | Initial-only type, order, default versus extras, fixed starts, drift/rebind, removed types and native splits |
| FR-026–027 | Existing launcher and state boundaries | Correct profile/cwd/HOME, no install/tasks/status-driven completion or permission |
| FR-028–034 | Git lifecycle / CLI | Import versus create, local branch modes, coverage/ref drift, hooks/filter refusal, dirty preservation and partial results |
| FR-035–038 | Close/native capability contract | Exact preview, shared impact, stale/legacy-group refusal, zero close calls on current candidate, no deletion/server stop |
| FR-039–040 | Opt-in / state boundary | Legacy unchanged, no invalid fallback, no active adoption/ungroup/restart |
| FR-041 | Quickstart / task record | Proposed, implemented, historical, isolated and native evidence remain separate |
| SC-001 | Cross-workspace synthetic dataset | Seven contexts, 30 terminals, ten cycles, zero duplicate defaults/wrong focus |
| SC-002 | Common input contract | Equivalent valid/invalid cases through CLI, selector and manual TOML; no-selector completeness |
| SC-003 | Lifecycle cancellation table | Every cancel/dry-run point has no current-action effects; prior confirmed saves retained |
| SC-004 | Close capability and scope | Correct exact closure or pre-dispatch refusal; current candidate exercises refusal, not positive native closure |
| SC-005 | Save/drift/unknown-result tables | Preserve original/live/created outcomes; no unknown-as-success or false rollback |

## Complexity Tracking

No constitution violation or exception. The comment-preserving TOML dependency and minimal receipt store serve concrete preservation/recovery requirements. No generic project platform, second catalog, full TUI toolkit, extra lifecycle manager or permission proxy is added.

## Task Record and Readiness

| State | Work |
| --- | --- |
| Completed | Strict configuration/discovery and preserving saves, ordinary independent entry, fixed type/default/extra/rebind, new-branch Git creation, legacy preservation, capability refusals and isolated tests; T065-T068 add explicit Git outcomes, complete previews/diagnostics, safe initial-refusal fragments and current-type operation budgets; T069-T070 complete interactive Git review facts and removed-type focus-only selection |
| In progress | None within this implementation checklist; see quickstart execution log |
| Failed, pending decision | None |
| Environment insufficient / unverified | Changed native/client/Agent execution, other platforms and deployment. Guarded close and existing-branch creation remain unavailable on examined public capabilities, with tested refusal only. |

Local and upstream evidence used scout roles configured as gpt-6-luna/high. A bounded contract/quickstart documentation package used executor configured as gpt-6.1-sol/medium. The primary agent decided concurrency, identity and lifecycle semantics. Implementation isolated results are recorded in quickstart; no native host or real account was run.

## Historical Phase 1 Document Validation

Independent general and native-contract reviews found no remaining substantive findings. Validation exited 0 for all ten feature Markdown documents: relative links/anchors, fence/whitespace/template checks, 41-requirement plan coverage, six stories/37 scenarios/five success criteria, 16 checked specification-quality items, one TOML example parsed with the repository Python, and two shell blocks checked with bash -n only. Bounded public-content inspection reported zero findings in those ten files; this is not a comprehensive secret-history audit.

At the planning checkpoint, protected-input hashes confirmed the constitution, active feature selector and committed source proposals are unchanged. Reconstructing the prior spec/checklist confirms only the approved clarification and its provenance changed. git diff --check passed; new untracked documents also received explicit whitespace checks. Before/after-plan extension hooks are absent because .specify/extensions.yml does not exist. That planning checkpoint executed no runtime test, shell example, third-party host, dependency installation, deployment, commit or merge. Later implementation dependency preparation and isolated tests are recorded separately in quickstart.
