# Manage Pi with agentcfg

The Pi adapter implements isolated instances, configuration deployment, Task Keeper, and model-delegate. **The Pi 0.84.4 full lock has been rebuilt through the real resolver for this change.** Source/lock closure and an isolated pi-default sync/apply succeeded; matching native and platform evidence is recorded separately. Existing deployments are not automatically migrated. Do not bypass lock checks or regenerate a lock as an incidental setup step.

Historical candidate `9d6a9270…` passed the agreed Linux x86_64 mock/native and two-path rebuild checks for four recipes. Those results belong to that candidate and do not certify this checkout. Other platforms, actual accounts, and real services retain their unverified status. See [known issues](known-issues.md), [testing](testing.md), and [releases](releases.md).

## Configuration ownership

| Content | Location |
| --- | --- |
| Reusable skills and rules | `shared/skills/`, `shared/content.toml` |
| Pi roles, prompts, themes, plugin declarations | `agents/pi/` |
| Machine-independent capabilities | `profiles/pi-*.toml` |
| Paths, exact model bindings, services, check programs | Private machine TOML `overrides` |
| API keys | Private shared SecretStore; legacy inline `secrets` remains supported |
| Native OAuth, sessions, task data | Isolated instance; no automatic import of an old HOME |
| Rebuildable dependencies and source identities | `locks/pi/`; fixed sources, integrity and per-profile complete npm locks |

Private files require mode 0600. Most arrays replace the complete selection, so retain all plugins you need when editing a list. See [local configuration](local-config.md) for the provider/model selection exception and secret storage.

## Choose a recipe

| Recipe | Host | Purpose |
| --- | --- | --- |
| `pi-default` | Node | Parent-session implementation, read-only scout/reviewer cooperation, Pi-backend delegation |
| `pi-managed` | Node | Task Keeper candidate worktrees, checks, reviews, and budgets |
| `pi-codex` | Node | Ordinary cooperation and official Codex CLI delegation through model-delegate |
| `pi-cursor` | Bun | Separate Cursor-provider sessions and read-only Pi-backend delegation |

Ordinary recipes select Todo, loop protection, and a status bar. Todo is separate from Task Keeper tasks and budgets. `agent_options.todo` can explicitly set `locale`, `maxWidgetLines`, `collapseKey`, and guidance without scanning old Todo settings.

The declared baseline is Pi 0.84.4, Node 24.14.0, npm 11.19.1, Bun 1.4.0, Codex 0.154.0, and pi-cursor 1.4.29. These declarations do not prove installation or platform support. Cursor/Bun and Task Keeper are mutually exclusive. The Cursor route currently requires explicit direct connectivity, has zero delegation retries, and rejects proxy configuration.

On Linux, all four recipes use the locked bwrap helper in a separate PID namespace. Host exit causes the kernel to terminate descendants; the supervisor verifies collection before releasing protection. The helper comes from the fixed Codex distribution with source/license metadata. Installing it does not enable Codex delegation. Host gating preserves original stdin, and file authorization remains governed by instance policy.

## Preparation and deployment sequence

The following is the intended sequence **after maintainers repair and verify the current lock**. It is not a claim that a fresh deployment works today.

1. Prepare Python 3.11+, uv, and the exact Node/npm/Bun required by the recipe. The manager does not alter the system toolchain.
2. Run `uv sync --locked` in `/path/to/rotom`. Use `./agentcfg` directly afterward.
3. Prepare a private machine file from [pi-workstation.toml](../examples/pi-workstation.toml) or [pi-managed.toml](../examples/pi-managed.toml). Replace fictional providers, exact remote IDs, and workspace paths; keep real keys private.
4. Validate and preview before explicitly synchronizing and deploying the reviewed lock.

```sh
./agentcfg --machine workstation --profile pi-default validate
./agentcfg --machine workstation --profile pi-default plan
./agentcfg --machine workstation --profile pi-default sync
./agentcfg --machine workstation --profile pi-default apply
./agentcfg --machine workstation --profile pi-default doctor
./agentcfg --machine workstation --profile pi-default run pi --cwd /path/to/workspace
```

Only sync downloads dependencies and performs approved preparation/build steps. npm lifecycle scripts are disabled by default. Official Codex native assets are checked for SHA256, entry points, and architecture. Failed installation preserves the prior runtime. Downloads accept standard lower/uppercase HTTP proxy variables without embedded credentials and retain CA validation; those download proxies are not injected into the model host. Model routes use explicit machine configuration. Validate, render, plan, and apply do not install missing dependencies.

## Models and accounts

Roles such as main, scout, reviewer, and managed roles reference logical model IDs selected by the recipe. Every `remote_id` must be exact. An ordinary configuration that truly resolves without main may open bootstrap login but cannot dispatch tasks. Current recipes inherit public Kimi Code main when no role overrides it. Selecting the Cursor plugin alone does not bind the main model to Cursor; configure that role explicitly.

Keys use `secret:<name>` and become runtime environment references. Native OAuth is established inside the target instance. The manager does not read system Cursor accounts, old Pi auth.json, or global CODEX_HOME. Codex login and explicit control are covered by [model-delegate usage](../shared/skills/model-delegate/USAGE.md).

## Task Keeper and delegation

The [managed example](../examples/pi-managed.toml) binds reader, writer, and reviewer, plus `second_view` when enabled; it declares project roots, permission policy, routes, trusted foreground check programs, fixed argv, parsers, and minimum test counts. Writes occur in a separate candidate worktree and are not automatically merged into the original checkout. A skill or purpose template does not grant a read-only role write permission.

All execution shares one AgentManager and supervisor. Accepted cancellation does not prove the physical process has stopped. Ordinary mode keeps implementation in the parent session with a fresh reviewer; use `kernel_task` for managed work rather than creating a hidden managed writer.

`model_delegate` is the unified entry point and requires an explicit backend. The old codex-delegate is not retained. The general/context/challenge/plan/research/review/scout purpose templates add task requirements, not another permission layer. Codex uses the official CLI and native tools with execution-bound grants, sandbox, workspace, and supervision; Pi-backend delegation is read-only. Advanced Codex writes require an explicitly authorized separate worktree. See the [skill](../shared/skills/model-delegate/SKILL.md) and [API](../shared/skills/model-delegate/API.md).

Codex file operations require a projectable policy such as `agent_options.permissions.policy_ref = "delegate-worktree"`. Read-only grants and mounts still prohibit writes; writes additionally require `explicit-write`, `implement`, and user CLI worktree authorization. The default `project-default` denies operations. Selecting Codex does not open access. Linux rejects project roots broad enough to contain private instances and runtimes; use the actual business project root.

Codex admission checks require absent/empty system configuration, absent managed preferences on macOS, and a recognized personal OAuth or explicit API-key identity. Organization, mixed, unknown, or unverifiable sources fail without rewriting account/admin state. These checks assume a trusted machine/account and are not an atomic configuration guarantee. See [Codex admission](pi-codex-admission.md).

## Daily maintenance

- **Add a skill:** copy its complete directory, relative resources, scripts, and license into `shared/skills/`; register it in `shared/content.toml` and select the ID in the recipe. External skills require explicit paths. Validate/plan/apply.
- **Adjust roles:** edit role sources in `agents/pi/roles/` or logical model bindings. Managed name collisions fail; ordinary scout/reviewer stay read-only. Generated `pi-home/agents/` is not the source.
- **Switch models:** register the provider and exact remote ID, select the logical model, and update roles. Prior route evidence becomes stale and needs applicable revalidation.
- **Disable a plugin:** remove its selection from plugins or `agent_options.resources.extensions` and resolve dependent plugins/options. Stop or recover active hosts/children/unknown leases before deploying.

## Optional capabilities

| Capability | Scope |
| --- | --- |
| [Agent state](pi-agent-state.md) | OSC titles or explicitly bound agent-report service |
| pi-rules | Explicit `root_refs`; no HOME scanning |
| OpenSpec | Optional fixed 1.11.0 CLI and 12 complete skills; explicit project target with conflict checks. See [OpenSpec](openspec.md). |
| Superpowers | Fixed-commit 14 skills and Pi bootstrap, loaded only when selected; helper services need explicit bindings. |
| [Review/editor](pi-review.md) | Diff/annotation UI with supervised Git/file/editor access; interactive editor uses a bound private PTY. Real terminal behavior remains separately unverified. |
| [MCP](pi-mcp.md) | Supervised stdio, explicit HTTP/SSE routes, Bearer/OAuth, sampling, input, scripts, Apps, direct tools; historical synthetic Linux results do not establish real service/account access. |
| [ReadSeek](pi-readseek.md) | Nine-tool contract, supervision, Git/rg selection, submission, visual assets. Historical Linux native evidence applies to pi-default/codex/cursor; managed uses Task Keeper. macOS x86_64 source-build support lacks machine verification. |
| [Web](pi-web.md) | Explicit providers, routes, credentials, and tools; historical synthetic SearXNG evidence is separate from real service validation. |

Selected but unverified Codex, Cursor, MCP, web, proxy, and terminal services remain selected and unverified. Historical spec closure did not turn those into passes or remove them from scope.

## Concurrent runs

New protocol-2 deployments admit independent supervisors in the same instance.
Each run retains a unique activation/nonce and control endpoint; execution IDs and
recovery evidence remain in the existing global store. Child/service capacity is
per run. The default recipes disable project-resource discovery. Explicit
`discovery.project_resources=true` retains exclusive physical admission because
the current native role projections depend on cwd and are shared within an instance.
The saved launch binding includes this policy; changing it requires apply before
another run can start. Stop, cancellation, delegation and status use the exact saved owner and
cannot borrow another run's endpoint. Managed workspace writers still conflict across
runs using canonical worktree leases; parallel readers remain allowed.

Old saved launch contracts fail with a migration instruction. Stop/recover old runs,
rebuild through the complete lock workflow, then sync and apply before using the new
shared contract. Do not overwrite a frozen supervisor or update only a recipe hash.
Native UI preferences remain instance-wide; concurrent preference editing has no
new cross-process transaction guarantee. Avoid simultaneous settings edits.
Legacy or unknown protected owners block admission/maintenance until explicit
recovery establishes their outcome. A temporary busy activity snapshot is retried by
the host loop; it does not authorize abandoning live work or deleting evidence.

On Linux, the supervisor verifies its private control directory before entering a
PID namespace. Runtime clients receive that directory's exact device/inode/UID
binding as an opaque string. This permits a fixed, read-only `control.json` lookup
when namespace UID mapping hides root ancestry. Wrong or malformed bindings fail
without fallback; file, socket, peer-UID and capability checks still apply. Ordinary
CLI requests retain the original strict ancestor checks. This mechanism grants no
general filesystem access and changes no upstream host or sandbox implementation.

## Recovery and diagnostics

Plan reports dependency, role, policy, route, resource, and configuration changes plus historical runtime locations. Pi sessions and Task Keeper stores accept only declared v3 data; incompatible state is rejected without downgrade or rewrite.

Rollback restores managed configuration and saved runtime references, preserving accounts, sessions, and task databases. Changing HOME cannot bypass active write leases on a shared worktree. See [migration and explicit recovery](pi-migration.md) for stop/recovery commands, 300-second plan validity, and unknown activity handling.

Doctor diagnostics and release acceptance are distinct. `report-only` success means a report was generated; `check-release` requires all applicable evidence in its fixed scope to match and pass. See [diagnostics](pi-diagnostics.md) and [testing](testing.md). Neither historical reports nor a working old deployment substitutes for current native/cold evidence.
