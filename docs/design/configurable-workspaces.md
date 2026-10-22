# Configurable workspace design and current boundaries

The structured workspace implementation uses explicit `machine.work.model = "structured-v1"`. It extends the existing `work` entry with configured discovery, named contexts, on-demand tab types and reviewed Git creation. It does not replace Herdr or the existing Agent adapters.

This document records implemented behavior and current capability limits. It is not a deployment record. This iteration has not completed native Herdr/client/Agent acceptance and has not switched production entry points. Earlier [legacy implementation evidence](../../specs/005-herdr-project-workspaces/implementation-evidence.md) applies only to its recorded candidate and environment. Daily examples are in the [usage guide](../herdr-workspaces.md); selector behavior is in [interaction flows](configurable-workspaces-interactions.md).

## Context and terminal model

A project or named context owns one ordinary Herdr workspace. A workspace contains tabs; tabs contain actual terminal panes. Rotom starts one managed instance in a new tab and records its native identity. Native layout changes, hand-created tabs and splits remain Herdr operations and do not automatically become managed types.

| Object | Identity and behavior |
| --- | --- |
| Project | Verified endpoint and canonical project boundary; each Git checkout is independent |
| Named context | Verified endpoint and stable local ASCII ID; no directory or problem binding required |
| Tab type | Key in the selected template; label and launcher are configuration |
| Instance | Recorded operation plus verified native workspace/tab/pane/terminal identity |
| Default | One explicitly recorded default instance of a type |
| Extra | Another instance of the same fixed launch contract; never promoted automatically |

Git common directories, branches, display titles and runtime cwd do not merge identities. Named contexts sharing HOME remain distinct from each other and from directory projects. Rename retains the named ID. Native ID reuse or missing markers is a conflict, not proof that an old instance has closed.

## Configuration and discovery

The [complete structured example](../../examples/work-structured.toml) defines these templates:

| Template | Ordered types | Initial type |
| --- | --- | --- |
| `development` | `shell`, `edit`, `build`, `test`, `agent` | `shell` |
| `investigation` | `code`, `agent`, `problem` | `problem` |

These are configuration examples, not fixed public-code roles. Type keys, IDs, comments and labels in published examples use ASCII; real paths and titles can contain Unicode data. An editor or Agent may be the initial type. Creating the workspace launches exactly that one default; remaining types are on demand.

`launcher` is one of `shell`, `editor`, `pi`, `dsh`, `codex`. A shell type name does not encode a build/test task. The editor is one configured executable. Pi and DSH require explicit profiles with existing deployment and runtime preparation. Codex uses its explicit independent CLI and defaults to `--no-daemon`. Unused launchers do not need preparation just to focus or start another type.

Configuration comes from the existing private machine file through three compatible entrances: selector registration, complete CLI commands, and manual TOML or `config edit`. All share strict validation, unknown-field refusal and canonical duplicate/conflict checks. `config edit` stages only the non-secret `machine.work` fragment. Atomic saves preserve unrelated fields/comments and do not start native terminals. A confirmed save finishes before any later lifecycle action; config and lifecycle locks are not nested.

Configured sources save rules, not discovery snapshots. Depth 1 enumerates visible direct children, excluding the root itself. Git mode recognizes `.git` directories and valid `.git` files; directory mode preserves independent directory boundaries inside or outside Git. Hidden/basename exclusions prune traversal. Optional symlink traversal remains within the canonical source root and detects cycles.

An explicit project wins over source discovery. Among sources, the most specific matching rule wins. The built-in Rotom candidate comes from the trusted executing checkout and is lower priority; it is not a persisted registration or parent coverage grant. Discovery refresh is explicit, without a daemon or a whole-HOME scan.

Source/project paths and explicit named start paths in TOML resolve relative to the selected machine file; `~/` uses caller HOME. CLI paths resolve from invocation cwd. All registered paths must exist. Git project import resolves a subdirectory to its checkout root; directory import retains its exact selected boundary. Importing a checkout or worktree does not create or modify Git state.

## Fixed launch contracts

The workspace records its initial start directory. Project contexts use the resolved project boundary. Named contexts use explicit existing `start_path`, or capture caller HOME on first entry. Named contexts therefore require no dedicated directory.

Each type fixes its launch contract on first instantiation:

- cwd resolves to an existing canonical directory.
- Captured HOME and standard XDG path selections preserve the Agent deployment boundary.
- Launcher argv and relevant prepared runtime identity determine whether later creation would drift.
- Default, sequence and instance records remain private state tied to native proof.

The cwd default is `cwd = { from = "workspace_start" }`. The alternate form is exclusively `cwd = { path = "..." }`: relative values resolve against fixed workspace start, `~/` against captured HOME, absolute values directly. No shell evaluation, mkdir or silent fallback occurs. Runtime `cd`, later caller cwd and later HOME do not move the fixed contract or extras.

Ordinary open focuses a proven default without preparing or re-executing its tool. `--new` always creates an extra, even before any default exists. Closed/moved default references can only be corrected after complete native proof; marker loss cannot establish absence. Extras are never promoted. A removed type may retain a verified focusable default, but creation needs a current definition.

Changed relevant configuration preserves existing focus and refuses contradictory creation. Explicit rebind requires zero active instances and no unresolved operation. Its preview is read-only; acceptance replaces only that type's launch contract, leaving other types intact. It does not terminate programs to become eligible.

## Ownership and one-shot launch

Structured contexts use ordinary workspace and tab creation, not Herdr's native Git grouping ownership. The current endpoint generation, workspace owner/epoch/model and complete pane identity must agree with durable private records. Environment IDs locate a caller; actual current native membership authorizes it. Titles, hashes, environment and private state alone do not grant ownership.

The parent stores immutable intent before one creation request, waits for a uniquely proven ready pane, stores commit-issued before publishing the matching commit, waits for accepted, then saves the binding and compacts the completed operation. A wrapper verifies the intent, source/config selection, actual caller, paths and deadline before exec. It does not hold the parent's operation lock or write lifecycle records. No shell history injection or command replay is used.

Pending state is per owner, and uncertain mutations are not resent. Missing replies, ambiguous readiness, changed identities and incomplete proof remain unknown. In particular, an initial workspace create with a lost reply cannot prove birth from a pane that may have moved; it is not silently adopted. Read-only status/reconcile report observations without clearing receipts or granting a retry.

The source manifest covers the entry/wrapper, lifecycle/config/state/native modules, introduced projects/editor/UI/Git modules and local schema. Source changes during handoff are refused. Digests are integrity checks, not ownership proof; they do not include secret-bearing whole files, credentials or raw Agent runtime configuration.

## Reviewed Git creation

Only an explicit Git project or configured Git source authorizes a repository. The built-in Rotom candidate is insufficient. A new destination must be absent, its parent present, and its exact location covered by a visible configured Git source under depth, exclusion and traversal rules.

The form can separately save a missing parent source after confirmation, then read fresh settings and renew the Git preview. Later cancellation retains that save but creates no future-project entry, checkout or branch. Save is not authorization for a later dispatch without review.

New-branch mode requires an explicit local base. Preview resolves local branch/tag/HEAD/commit identity without remote guessing or network access and rejects ambiguity. The reviewed plan records repository/common metadata, destination/parent, references, template, source policy and relevant configuration. Dispatch rechecks these facts under the existing operation lock and publishes durable intent before one `git worktree add`. Default behavior is create-only; explicit `--enter` scopes subsequent ordinary workspace entry.

**Existing-local-branch dispatch is currently unavailable and returns 5.** Read-only preview remains possible, and existing checkouts can be imported. Git's public short-branch form can create a local branch from a remote-tracking ref if an external actor deletes the reviewed branch just before dispatch; `--no-guess-remote` does not close this path. A full ref form changes checkout semantics and does not meet the existing-branch contract. This release treats existing-branch dispatch as unsupported; there is no claim that both creation modes succeeded. Future enablement requires a public atomic guard and explicit review.

Per invocation, Git receives a verified empty private hooks directory, disabled external fsmonitor, remote guessing and recursive submodule actions, and sanitized repository/config overrides. Executable checkout filters are detected and refused before dispatch. The original dirty worktree, index and persistent config stay in place. No fetch, stash, reset, force, cleanup, dirty-file copy, bootstrap, package installation or service start is authorized.

Nonzero exit, timeout or lost response can have partial effects. Receipts retain observations; conflicting operations are blocked without blind retry or deletion. Git success followed by failed workspace entry keeps the checkout and offers explicit entry retry. Read-only reconciliation does not rewrite receipts or claim rollback.

## Close is a capability limit

A workspace-wide close would affect every tab/pane in that workspace, including manual members and all viewers. A preview inventories and rechecks the complete scope and produces a token. Config, checkout, branch, sibling workspaces and the server are outside that reviewed scope.

The admitted native API lacks an atomic membership guard. `close --dry-run` is available, but actual `close`, including a reviewed `--scope TOKEN --yes`, returns 5 without a destructive native request. A token and repeated client-side reads do not substitute for native atomic protection. Full-project closing is not claimed as completed or accepted.

Detach only disconnects a viewer while processes remain running. Folding/collapsing a UI item changes display. Neither is a close operation or evidence that tasks ended.

## Legacy coexistence and readiness

Omitting `model` preserves the legacy Git-only seven-role behavior. Structured-only fields without opt-in fail rather than silently migrating. Existing legacy metadata, tasks and tmux sessions are not adopted, terminated or converted. Explicit configuration/session choices separate new work from old work; rollback of configuration or code is not permission to stop a process.

The implementation uses unmodified official hosts and public APIs/CLIs only. The normal entry uses the prepared repository Python environment and performs no dependency download, `uv run`, host installation or implicit login. fzf is optional; selector inputs are data, caller `FZF_*` settings are removed, and no candidate-driven shell actions are installed.

Isolated tests exercise fake native handshakes, private filesystem state and narrowly allowed synthetic local Git commands. They do not establish real SSH/Ghostty behavior, Agent login, terminal input fidelity, concurrent native-client behavior or deployed readiness. Native acceptance, deployment, migration and any destructive host operation require separate scope and evidence. The current status is implemented with stated capability limits, native-unaccepted and undeployed.
