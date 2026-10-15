# Architecture

Rotom separates shared intent, native translation, dependency installation, configuration deployment, and process launch. DSH, Pi, and OMP implement distinct adapters; Codex is an authentication route or a delegated official CLI, not a fourth configuration adapter. `termcfg` has its own command and transaction model.

## Upstream hosts remain unmodified

Use official configuration, public plugins and extension APIs, official CLIs, and repository-owned adapters. Do not patch agent source, official binaries, cached distributions, or private host interfaces. Historical patch material is retained only for provenance and migration analysis. Its presence does not authorize rebuilding a patched host.

OMP now uses an official standalone runtime and an independent permission plugin. Current DSH uses unmodified Core/TUI and public extension points. Pi retains historical derived plugin and build material that still needs a source-by-source audit; it must not be described as fully migrated solely because it has a source URL. See [Roadmap](roadmap.md).

## Data flow

```mermaid
flowchart LR
  Public[Registry, resources, profiles] --> Resolve[Strict validation and merge]
  Local[Private nonsecret overrides] --> Resolve
  Resolve --> Render[Deterministic artifacts and field intent]
  Render --> Plan[Baseline / current / desired comparison]
  Plan --> Apply[Managed write and recovery journal]
  Apply --> State[Stable instance and deployment contract]
  Lock[Complete dependency lock] --> Sync[Staged install and verification]
  Sync --> Package[Runtime identified by lock]
  State --> Run[Launch deployed contract]
  Package --> Run
  Secret[Private credential store] --> Run
  Run --> Native[Native HOME, login, sessions]
```

| Subsystem | Code entry points in `src/agentcfg/` |
| --- | --- |
| Commands and selection | `cli.py`, `commands.py`, `workspace.py` |
| Input and rendering | `config.py`, `schema.py`, `merge.py`, `render.py` |
| Ownership and recovery | `deployment.py`, `native_projection.py`, `storage.py` |
| Dependencies and launch | `backends.py`, `runtime.py`, `process.py`, `execution_environment.py` |
| Native adapters | `dsh.py`, `pi.py`, `omp.py` and related modules |
| Pi supervision and evidence | `pi_supervisor.py`, `pi_delegate*.py`, `pi_validation*.py` |

`src/termcfg/` separately implements zsh/tmux previews, transactions, pinned plugins, and explicit legacy metadata migration. Proxy service control has been removed. It does not run implicitly from agent setup or launch.

## Configuration and secrets

Objects merge recursively; arrays normally replace wholesale, including empty arrays. `false` remains meaningful. The shared default model layer adds deduplicated provider/model choices and lets explicit role bindings take precedence. Stable local model IDs are separate from remote IDs and protocol routes.

SecretStore is separate from ordinary configuration. Renderers and digest builders receive no secret values. Shared secret files and legacy inline entries may coexist only under the documented conflict rules. Launch resolves the deployed references for the required operation; capture reads a narrow nonsecret allowlist. Workspace loading defers shared credential-file reads until an operation resolves a SecretRef. Configuration-only validate/render/plan/doctor paths do not read those bodies. Direct callers of `load_local` retain its eager default unless they explicitly request deferred loading.

Native authentication, trust, sessions, and logs remain native-owned. A user interface preference may be initialized once without becoming continuously managed. Unknown native fields survive field-level merges; unknown Rotom input fields fail validation.

## State, installation, and execution

A deployment has a stable owner, current field baselines, at most one previous configuration generation, and a pending journal during interrupted multi-file work. Three-way comparison preserves user drift and detects conflicting edits. Single-file replacement is atomic; the system does not claim atomicity across files or external processes.

The dependency backend consumes a complete lock and verifies staged output before activation. DSH/OMP publishers use an exclusive repository lease and recoverable manifest-last journal; sync holds a reader lease for the full consumption period. Interrupted publication blocks readers until explicit lock recovery. Pi publication is separately inventoried and still requires a single publisher. `apply` installs nothing. `run` uses a saved deployment contract and performs no implicit sync or apply. A stale repository lock can block new deployment while an earlier deployed runtime remains launchable under its saved contract; preserve that distinction during source upgrades and recovery.

Private storage uses directory handles, no-follow traversal, ownership and ancestor checks, and rechecks before writes. Leases protect managed instance, state, and runtime operations. Ordinary DSH, Pi and OMP runs use shared admission; maintenance requires exclusive access. Pi's opt-in project-resource discovery remains exclusive because its native projections depend on cwd. DSH prepares shared profile projections during journaled apply/rollback and only verifies them during run. Pi retains separate supervisors and full owner identities, with short serialized execution-record mutations and per-run control endpoints. Background descendants may inherit lease descriptors; the unresolved lifecycle issue is tracked in the Roadmap.

These controls are not an OS sandbox against arbitrary same-user processes. Host sandbox and approval coverage must be assessed independently. See [state and recovery](design/configuration-state.md), [approval design](design/approvals.md), [adapter contract](adapters.md), and [testing](testing.md).

## Runtime and terminal boundaries

The [project refactoring record](design/project-refactoring.md) implements concurrent admission
of different native sessions with exclusive maintenance across all three adapters.
Deployment/profile, runtime package, run invocation, native session, Pi execution
attempt, Git worktree and credential provider have separate identities. Shared run
admission does not authorize uncontrolled writers in the same worktree or alter
native sandbox and approval boundaries.

The versioned execution-environment contract separately controls ordinary caller
variables and native instance storage. OMP/Pi main sessions retain caller HOME/XDG;
DSH retains its TUI HOME and applies the caller environment at public subprocess
and stdio MCP boundaries. Restricted workers and installers keep their own minimal
environments. Explicit deletion and name-only one-shot controls share precedence
and value-free diagnostics; they neither expand filesystem permissions nor promise
credential or network isolation. See the [machine guide](local-config.md) and
[environment channel matrix](design/project-refactoring.md#implemented-environment-boundary).

Shared resources must be prepared or migrated under maintenance; ordinary run then
validates them and allocates only necessary private run state. Pi keeps its existing
global execution/evidence store and unique lease IDs. Version 2 owner markers prove
concurrent supervisors; activation-specific endpoints prevent cross-run routing.
Legacy, dead or unknown protected owners require explicit recovery. Maintenance
checks all owners; stop/cancel is scoped to the exact owner. A new protocol-2 launch
contract and matching lock/runtime are required before Pi shared admission.

`termcfg` now manages zsh/tmux. Its [explicit migration](termcfg.md#retiring-an-existing-mihomo-selection)
retires mihomo ownership metadata while preserving old targets, backups and private
proxy data. Strict v1 recovery remains available before migration to v2 state.
A future independent proxy project has not been created. Proxy environment values
remain an external-service contract consumed by agentcfg; `dsh-proxy` does not own
service startup. No existing proxy service is stopped or transferred by this change.
