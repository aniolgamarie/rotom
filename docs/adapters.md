# Adapter contract

DSH, Pi, and OMP reuse configuration merging, SecretStore, deterministic artifacts, safe storage, deployment transactions, backups, and active leases. A new adapter must provide real native mappings and separately validated support claims.

## Interfaces

`src/agentcfg/adapter.py` defines the adapter declarations and hooks:

| Interface | Responsibility |
| --- | --- |
| `declaration` | Agent ID, data schema version, adapter version |
| `validate` | Capabilities, references, and native mapping validation |
| `managed_targets` | Whole-file, field, initialization-only, runtime, and package-manager ownership |
| `render` | Deterministic artifact bytes; field artifacts contain desired field intent, not the current native document |
| `render_with_context` | Explicit RenderContext for locked absolute resource paths; delegates to render by default |
| `dependency_plan` | Declared requirements without installation or implicit resolution |
| `launch_spec` | Arguments, cwd, environment literals or SecretRefs, and lock identity |
| `prepare_runtime` | Exclusive maintenance only; recoverable preparation, no implicit install |
| `validate_runtime` | Read-only launch-resource checks during shared run admission |
| `capture` | Valid local override proposal from an allowlisted native projection |
| `doctor` | Diagnostics from nonsecret status projections |

Adapters may also provide schemas and validated authentication claims, `capture_projection`, `launch_preflight`, and lifecycle hooks. `shared_run_lease` defaults to true for declared adapters; lifecycle hooks must use shared physical admission for runs and exclusive admission for maintenance. Legacy duck-typed adapters without the declaration retain the fail-closed exclusive fallback. Empty hooks do not imply native concurrent support has been validated. Use the existing concrete adapters as references rather than embedding one host's paths in the public configuration model.

`DependencyBackend` supplies `read_lock`, `resolve_lock`, `sync`, `root`, `status`, `executable_paths`, and `toolchain`. Commands dispatch through the selected backend rather than assuming a node_modules layout. An optional `resolve_lock_for(workspace)` hook lets explicit lock generation consume effective local dependency selections; otherwise commands use `resolve_lock(repository)`. Pi uses the hook for the selected profile and public defaults for the other profile. No current public project-init route is registered; generic project-generation helpers retain their separate protection tests.

## Integration procedure

1. Inspect the selected upstream version, configuration schema, authentication ownership, discovery paths, resource loading, and writes outside its HOME.
2. Declare `agents/<id>/agent.toml`, real bindings/resources, and strict schemas. Do not invent remote IDs or unsupported protocol mappings.
3. Implement and register the adapter in `workspace.ADAPTER_TYPES`; reject unsupported operations explicitly.
4. Implement the dependency backend, source receipts, integrity checks, staging, and failure recovery for its package format.
5. Register a safe field codec if needed. Keep unknown native fields and runtime/secret data outside managed projections and backups.
6. Use explicit native environments and launch preparation; never source or evaluate private configuration files.
7. Run shared contract tests and adapter-specific isolated tests, then separately authorized native/platform/account acceptance.

## Invariants

Tool/profile instances have independent state, previous configuration, and leases. Ownership conflicts, overlapping selectors, unsafe paths, unadopted nonempty files, and pending recovery must block unsafe writes. Preserving drift does not accept it as a new baseline.

`shared_files` declares future native-shared files during first empty-instance deployment; it is not permission to adopt arbitrary existing files. After a plan succeeds, common deployment also retains paths of files actually managed by selectors, so later deselection does not discard provenance. It never preclaims a new candidate path, imports native values, or overwrites an existing new managed field. The owner update is journaled even when no target bytes change, and does not rotate the previous configuration backup. Nonsecret location variables `AGENTCFG_REPOSITORY`, `AGENTCFG_LOCAL_FILE`, and `AGENTCFG_PROFILE` locate configuration sources, not the business cwd or a credential resolver.

OMP's native secret fields use bare environment variable names, unlike DSH/Pi `$VAR` references. The `omp-env-name` classification applies to current, baseline, backup, pending, and rollback projections. Removing a historical guard must not remove secret classification.

Fake adapters and backends under tests demonstrate contract reuse only. They do not prove a new host can load extensions, authenticate, or execute tools. See [testing](testing.md).

Pi reuses these shared contracts through a thin official-CLI adapter. Its profile-specific recipe
contains actual dependency selections and source identities, not the whole manager tree, other
profiles, model/editor/UI values or generated locks. Runtime packages and original npm files remain
separate from stable native home/session state.

The common `run_owners.Registry` records distinct main runs; Pi wires it to physical SH admission
for registration and physical EX for maintenance. Owner identity includes process birth identity.
Active/unknown records block maintenance. On Linux, a manager armed as a child subreaper before
spawn releases only its current run after the kernel confirms no children remain. Unsupported or
incomplete observation preserves unknown; earlier unknown records are never cleared by a new run.
