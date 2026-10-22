# Data Model: Configurable Workspaces

**Status**: Implemented private model with isolated verification; no native acceptance or deployment claim. Existing-branch Git creation and guarded close remain unsupported.
**Inputs**: [specification](spec.md), [research](research.md), [configuration contract](contracts/configuration.md), [lifecycle contract](contracts/lifecycle.md).

## Ownership and storage boundaries

| Owner | Data owned | Excluded |
| --- | --- | --- |
| Machine-private TOML | Discovery rules, explicit directory/named entries, templates, launch selections | Discovered project snapshots, runtime terminals, task state |
| Herdr | Live workspace/tab/pane/terminal identities and layouts | Authoritative Rotom configuration or task completion |
| Rotom structured binding store | Managed identity references, fixed launch bindings and unresolved operation receipts | All-terminal inventory, screen text, shell history, Agent conversations |
| agentcfg / Agent | Prepared launch contracts, credentials and native sessions | Workspace organization or terminal lifecycle |
| Independent editor | Editing, review state and exports | Herdr control or project discovery |

Private state root: `$XDG_STATE_HOME/rotom/work/v2`, using the standard HOME fallback when XDG_STATE_HOME is absent. Use current-user 0700 directories and 0600 files, safe path/link checks and shared storage primitives. Do not write state into the public repository. This is a separate schema from termcfg deployment state; no changes to its state version are implied.

A directory in private state is an endpoint namespace derived from the canonical discovered socket address. Selecting the same endpoint through another local-config spelling does not create another workspace identity. Records also carry the observed endpoint generation and random workspace epoch. State may remember references but cannot authorize control without current native evidence.

## Entities

| Entity | Fields / validation | Relationships and lifetime |
| --- | --- | --- |
| WorkConfiguration | `model`, native binary/session, explicit launcher/profile selections, include_rotom/rotom_template, templates, sources, workspaces | One selected private TOML; no automatic opt-in |
| Template | ASCII key, ordered exact type-key set, valid initial key | Referenced by sources and explicit/built-in entries |
| TerminalType | ASCII key, display label, launcher enum, exclusive cwd source | Local to a template; not an Agent adapter or task definition |
| DiscoverySource | ASCII id, existing canonical root, git/directory mode, bounded depth, template, exclusions, symlink policy | A rule, re-enumerated on load/refresh |
| ExplicitProject | Existing canonical boundary, explicit mode and template | Directory identity; no extra configuration ID needed |
| NamedContext | ASCII local id, mutable title, template, optional existing start path | Identity does not depend on path or title |
| Candidate | Kind, canonical boundary or local ID, template, origin and precedence, display path/title | In memory only; save does not open it |
| EndpointObservation | Selected session, canonical discovered socket address, pinned O_PATH fd, dev/inode, observed version/protocol | FD lives for one operation; no invented persistent boot UUID |
| WorkspaceBinding | Version, endpoint namespace/generation evidence, random epoch, context kind/key, directory boundary or named ID, fixed workspace_start, native workspace ID, selected template, configuration origin | One managed context at one verified endpoint; cold-restore records can become stale |
| TypeBinding | Workspace epoch, type key, resolved start cwd, normalized launcher contract, default instance reference, sequence counter | Frozen at first instantiation, shared by default and extras |
| InstanceBinding | Random instance ID/op ID, type key, default/extra, native pane/terminal references, last observed workspace/tab, handshake phase | Managed references only; tab/workspace membership must be queried again after native moves |
| OperationReceipt | Random op ID, action, reviewed non-secret input subset, endpoint/epoch, native references when known, dispatch/handshake/result state | Written before a permitted mutation; uncertainty prevents replay |
| ReviewedScope | Action, verified target/epoch, exact relevant identities, normalized proposed change, capability result, scope digest | Ephemeral review; contains no raw machine document or secret-bearing whole-file hash |

Configuration identifiers newly introduced here use `^[A-Za-z][A-Za-z0-9_-]{0,63}$`. Existing shared machine/profile identifiers keep their current validation. Paths/titles are Unicode data; reject NUL/control characters and invalid encodings with fixed diagnostics, never shell evaluation.

## Identity and discovery

Logical directory identity is `(selected endpoint, canonical project boundary)`; named identity is `(selected endpoint, "named", local ID)`. The kind discriminator keeps a named context distinct from a directory project at the same start path. Branches, titles, current cwd and Agent status do not participate.

The selected source/entry chooses the boundary policy. Git mode resolves to the actual checkout root, including a worktree's .git file. Directory mode preserves the selected canonical directory even inside a larger repository. Entering a subdirectory resolves within that configured boundary. Never substitute a common Git directory for a checkout.

Discovery examines only configured roots and depth, applying hidden/basename-glob exclusions before descent. Git mode lists checkout roots, not ordinary children inside one checkout. Do not follow external worktree metadata as discovery edges. Default symlink policy is no traversal; explicit following remains confined to the source's canonical root with visited-directory cycle detection. Explicit aliases can still canonicalize to a project.

Canonical duplicates resolve in order: explicit project, most specific source root, built-in Rotom candidate. Compatible duplicates coalesce; equal-priority incompatible modes/templates fail. For equal canonical source definitions, a compatible duplicate registration is a no-op; an ID collision or incompatible policy is an error. Duplicate titles remain distinguishable by path/ID and origin.

Sources that become unreadable produce explicit diagnostics, not a complete-looking partial success. A requested candidate whose boundary cannot be established is unusable. Other verified candidates may remain selectable with the affected-source warning visible. An unverifiable built-in root does not block other entries.

## Configuration and explicit path resolution

Relative source/project paths and named start_path values written in TOML resolve against the selected local file's parent directory. Home-relative values use the caller HOME. CLI/TUI explicit path input resolves against the calling directory and saves the reviewed canonical absolute path. No path input is inferred when missing.

Type cwd literals have a different explicit base: relative values use the workspace's fixed workspace_start. Omitted named start uses the caller HOME captured at first entry; type-level ~/ resolution captures caller HOME at first type binding. Neither caller changes nor config reloads rebind an active start.

## Fixed startup bindings

A directory workspace starts at its canonical boundary. A named context starts at the caller's HOME captured on its first creation, or its explicit existing start path. Re-entry and a different caller HOME never rebind the live workspace. A changed named start is drift for future creation, not a request to move processes.

A type uses either `cwd = { from = "workspace_start" }` or `cwd = { path = "literal" }`; omission selects the former. Relative literals resolve against fixed workspace_start, `~/` against the caller HOME captured when first binding the type, and absolute paths retain their meaning. Record the resolved existing directory. No other expansion or fallback applies.

The normalized launcher contract includes launcher kind, selected single editor executable or prepared Agent profile/runtime contract, independent Codex selection/daemon policy where applicable, and the relevant declared environment/HOME boundary. Do not retain credential values. The launch source digest is a per-operation integrity check; it does not make titles or environment ownership proofs.

Runtime cd does not create drift. Changing a bound type's resolved cwd or launch contract preserves active instances and refuses contradictory creation. Existing verified defaults remain focusable without re-preparing a changed/missing executable. Uninstantiated types can use new settings. A removed type's existing default remains addressable by key for focus; new instances require a current valid definition.

`--new` always creates an extra in structured mode, including when no default yet exists. It never promotes an extra. A later plain open creates the default only if its absence is proved. All instances share the type binding. Ordinals are display conveniences; problem1/2/3 are not type keys.

Explicit rebind requires zero active instances of the type, complete native verification, no unresolved operation and acceptance of a fresh contract. A missing marker is not proof of zero instances. Native tabs/splits not registered by Rotom remain unowned; splitting a managed tab does not make every new pane a managed instance.

## Native evidence and metadata

Proposed metadata sources are `rotom-work-v2` and `rotom-work-launch-v2`; v1 markers remain untouched. Use fixed keys rather than one workspace key per configurable type.

| Resource | Proposed keys | Bound |
| --- | --- | --- |
| Workspace | rw2_owner, rw2_epoch, rw2_model, rw2_pending | Four keys; digests 64 hex, epoch/op 32 hex |
| Managed root pane | rw2_owner, rw2_epoch, rw2_type, rw2_instance, rw2_kind, rw2_op, rw2_phase, rw2_commit | Eight keys, each value <=80 characters |

The type key is <=64 ASCII characters; kind is default/extra and phase is ready/accepted/failed. A cleared commit is represented by the public metadata null patch. Patches stay within the audited native 16-key limit and resource 32-key limit. Refuse capacity/conflict instead of clearing another source's metadata. Use monotonic sequence ordering for each owned resource/source; late messages may not undo terminal phases.

Private records contain full canonical identities and fixed starts; native tokens contain only bounded non-secret references. Both must agree with native pane/terminal/workspace membership before control. Neither private records alone, an environment variable, a matching label nor a matching cwd is sufficient.

Cold restore clears or invalidates relevant markers. Socket dev/inode without live epoch agreement cannot prove a resumed server identity or authorize reuse. Stop automatic control with stale/unknown status; do not adopt restored layouts, resume Agents, infer “absent”, or recreate against the same unresolved binding. New-server/new-workspace migration is explicit and preserves old state.

## State transitions and retention

Detailed transitions and failure windows are in [lifecycle.md](contracts/lifecycle.md).

| Current evidence | Event | Next state |
| --- | --- | --- |
| No binding and unique configured context | Accepted enter | Intent persisted; creation may dispatch once |
| Durable intent, unique matching ready pane | Verified parent/child agreement | Commit issued, then accepted/registered |
| Possible dispatch, missing/contradictory result | Timeout/failure | Unknown; read-only reconciliation required |
| Known accepted live instance | Plain open | Focus only, no new launch |
| Complete query proves default closed/moved out | Subsequent open | Absent default; original moved pane retained |
| Native ID reused, marker missing or multiple matches | Any control | Unknown/conflict, never adopt |
| Config contradicts active type binding | Create/rebind request | Drift refusal; live focus stays available |
| Known Git checkout creation, failed entry | Entry failure | Created checkout retained |
| Close capability missing | Close request | Refused without native close dispatch |

There is at most one unresolved native-creation intent per workspace (including extras). A Git creation receipt blocks another conflicting creation for its repository/destination until facts are reconciled. This does not prevent unrelated configuration checks or use of existing terminals.

Do not expire or garbage-collect uncertain receipts by elapsed time. A completed native operation can compact its transient receipt only after the matching durable binding is committed; preserve an unresolved record on any bookkeeping uncertainty. Keep the latest completed Git outcome for each still-relevant operation until an explicit reviewed archival action, without storing command output. Archival is not automatic cleanup of checkouts, branches or native objects.

`status` and `reconcile` inspect only; they do not change receipts. The original operation may subsequently finalize bookkeeping for a uniquely proved completed result, without replaying create/exec. A failed/partial Git operation is not converted into a retry. State/schema conflicts return 4; unsafe I/O returns the established 4/6 distinction. No migration is implicit.

## Implementation observations

Endpoint namespaces also contain protected startup observations (`server.json`) that distinguish explicitly observed startup inputs from a nonexistent public effective-config attestation. Native lifecycle authority still requires current endpoint/process/marker agreement. Git intents and receipts live separately under the v2 git directory, retaining non-secret reviewed refs/path/config metadata and unknown/completed outcomes without command output. Config locks/editor fragments are private siblings of v2; full machine files and secret-bearing digests are never staged there. Existing-branch Git preview is read-only and dispatch returns 5 until an admitted public guard exists.
