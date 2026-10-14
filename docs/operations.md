# Operations and maintenance

Start with [getting started](getting-started.md). This guide covers configuration changes after installation. Read the [DSH migration boundaries](dsh.md) before upgrading a legacy instance: current prerelease configuration must not be applied blindly over an old home. Configuration rollback is separate from software, session-format, or database downgrade. The [Pi lock blocker](pi.md) also applies before any new Pi deployment.

## Ask an agent to help

The default DSH recipe includes `maintain-agent-config`. For example:

> Use the maintain-agent-config skill to update this machine's preferences: keep terminal image previews disabled and use nvim as the editor. Preserve other configuration and secrets, run validate and plan, and explain the changes.

Specify whether a rule/skill is for all machines or only this machine. The skill helps locate sources and validate framework TOML. An active DSH cannot deploy changes to its own instance; exit it, apply from the shell, then restart. Never paste keys into chat.

## Change configuration

Edit shared Git sources or the private machine override, then:

```sh
./agentcfg --machine workstation validate
./agentcfg --machine workstation plan
./agentcfg --machine workstation apply
```

Explicit lock/sync is needed for dependency changes, not ordinary configuration edits. Rendering does not install software; installing does not start an agent. Shared rules cannot remove differences in upstream system prompts.

DSH uses pinned original pnpm 11.19.0 with its frozen pnpm-lock.yaml. Sync accepts Node 24.x from 24.2.0 and npm 11.x; run has the same Node floor. Lock generation requires exactly Node 24.14.0/npm 11.19.1. Node 24.1.0 cannot execute the selected entry point. See [toolchain preparation](getting-started.md).

## Add a shared rule or complete skill

Create `shared/rules/project-style.md` as ordinary Markdown. Literal `{{example}}` is not evaluated. Register it in `shared/content.toml`:

```toml
[rules.project-style]
path = "shared/rules/project-style.md"
```

Select it in the recipe's complete rules array, retaining required entries:

```toml
rules = ["chinese", "terminal", "cpp-local-search", "project-style"]
```

Only text explicitly marked `template = true` uses StrictUndefined templating. Structured JSON/YAML uses serializers.

For a skill, place the full SKILL.md package, scripts, references, and assets under `shared/skills/build-context/`. Preserve relative references and executable script intent. Frontmatter needs a valid name and description. Record authorship or the upstream URL/version and customization details.

```toml
[skills.build-context]
path = "shared/skills/build-context"
```

Select the complete package in the skills array. Copying does not execute scripts or follow source symlinks. For a DSH-specific replacement of a shared package, declare the exact old path in `agents/dsh/content.toml`:

```toml
[skills.build-context]
path = "agents/dsh/skills/build-context"
override = "shared/skills/build-context"
```

Undeclared replacements, mismatched old paths, and duplicate overrides fail.

## Add a provider/model

Shared definitions belong in the shared registry; private definitions use matching `overrides` fields. These are fictional framework examples:

```toml
# shared/providers.toml
[providers.team_gateway]
protocol = "openai-compatible"
base_url = "https://api.example.invalid/v1"
auth_kind = "api-key"
credential_ref = "secret:team_gateway_key"
```

```toml
# shared/models.toml
[models.team_chat]
provider = "team_gateway"
remote_id = "fictional-chat"
input = ["text"]
```

Use verified service values, select the provider/model in the recipe, and bind `roles.main` to the logical model ID. Omit unknown capacities; adapters requiring capacities will reject incomplete definitions. Users enter real keys privately. OpenAI API keys are not Codex subscription login. See [local configuration](local-config.md) and the [model catalog](model-catalog.md).

## Native preferences and capture

```sh
./agentcfg --machine workstation capture
```

DSH capture uses an allowlist for terminalImages, the isolated user-home `.dsh-tui/theme.json`, and model.json selection. It creates private cached `capture.json` intent, not a whole machine file or native YAML. Unsupported themes and ambiguous/unknown dynamic models fail and preserve the old proposal. The theme allowlist is `rotom-catppuccin`, `rotom-poimandres`, `auto`, `dark`, `dark-ansi`, `light`, `claude-dark`, `claude-paper`, `codex-lavender`, and `codex-paper`; other native themes are not automatically capturable.

The proposal passes schema, merge, adapter, and render validation. Review and merge only relevant nonsecret fields into the private TOML, then validate/plan/apply. Capture does not export auth, sessions, or dynamic OAuth catalogs and does not modify Git. UI/theme preferences are initialized once; repeated apply preserves native changes. Backend, preset, and Core default-model fields remain managed by three-way comparison. See [DSH settings ownership](dsh.md#settings-and-preference-ownership).

## Locate conflicts and missing credentials

Plan assigns each difference, drift, and conflict a `target-…` ID. Its diagnostics path points to a private locations.json mapping IDs to paths/selectors. It contains no field values, but paths may include private names; inspect locally.

Missing required service/MCP secrets use `credential-…` IDs. Run doctor with the same machine/profile, find the reference in diagnostics, and fill only that private entry. Missing model API keys produce startup warnings rather than blocking the host; use model status and fill them before making a request. Diagnostics include both current intent and deployed references, so unapplied changes do not obscure the deployed credential requirement. OAuth contents are not inspected.

## Update or repair a managed runtime

1. After updating the checkout, run `uv sync --locked`. If validation reports private-file permissions, inspect ownership, regular-file status, and link boundaries. The user can correct the specific file to 0600 and its private directory to 0700; do not change an entire HOME or system directory.
2. Stop the instance and sync the reviewed lock. A damaged runtime or missing file receipt is rebuilt in staging while preserving the account home. Repairing the same lock does not require regenerating it.
3. Plan, apply, doctor, then run. Doctor's dependencies refer to the repository lock; deployed_dependencies refer to the actual deployed version and may differ after rollback.

Missing files or changed critical entry digests mark a runtime damaged and block run. Sync repairs only manager-owned packages; it does not adopt an unknown nonempty directory. Checks cover directory shape, link targets, package manifests, and required entries on each invocation. This is not an audit of every transitive file. Matching size/timestamps or a marker alone do not prove unchanged content.

A repair activates only after staging succeeds. Interrupted repair uses `.repair-<lock-identity>` recovery slots, which are separate from configuration backups and contain no account/session backup. Pending configuration recovery blocks installation; follow doctor's apply/rollback recovery instructions first.

## Backups, drift, and interrupted deployment

For baseline B, current C, and desired D: update when C=B; preserve/report native drift when D=B; do not rewrite when C=D; otherwise conflicting edits fail. Preserved drift does not become a new baseline.

Only an actual successful change rotates the single previous managed version. No-change apply leaves it intact. Failure attempts to restore written managed items; subsequent external changes retain pending recovery and block unsafe continuation. Resolve conflicts and explicitly retry apply/rollback.

```sh
./agentcfg --machine workstation rollback
```

Successful rollback consumes the backup. First-deployment rollback removes only newly created, still-unmodified managed files, preserving later sessions and unknown data. Rollback does not restore software/databases; prepare missing runtime dependencies separately. Active instances block configuration/dependency modification. Do not bypass path checks, copy whole homes, or edit runtime packages to force progress.

## Maintain dependencies

Verify exact upstream commits, public fields, packaging, and platform requirements before changing dependency inputs and locks. Review source identity, archive integrity, and the full lock diff. Integration must use unmodified upstream agents and public APIs; do not patch host source, vendor copies, caches, or binaries. Repository-owned plugins can have their own reviewed build process.

Generate locks explicitly, for example `./agentcfg lock --agent dsh`, with the required toolchain. Run relevant isolated checks before separately authorized native smoke tests. Ordinary users should consume reviewed locks rather than follow floating branches or unversioned npx. Plugins such as Memento, ModLens, MCPLens, and ModSearch are not installed by default; catalog presence alone does not establish adapter support.

## Pi maintenance boundaries

The current stale Pi lock is a pre-existing new-deployment blocker; the historical `9d6a9270…` rebuild/native results are not current checkout evidence. See [Pi](pi.md) and [migration](pi-migration.md) for adoption, drift, credentials, rollback, and recovery.

Pi project policy denies by default. `permissions.policy_ref = "task-keeper-candidate"` explicitly allows the candidate's tk_* reads/write while retaining role roots, task grants, secret exclusions, and supervisor write leases.

Ordinary read/write/edit/rename/ls/find/grep use the instance supervisor. Writes and renames acquire a common workspace lease immediately before action. Interactive approval binds the session, directory, and input; unused authorization expires after five minutes. Rename authorizes both endpoints without replacing the destination, using Linux `renameat2(RENAME_NOREPLACE)` or macOS `renameatx_np(RENAME_EXCL)`; unsupported platforms/filesystems fail. See the [Linux](https://github.com/torvalds/linux/blob/master/include/uapi/linux/fs.h) and [Apple](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h) headers. Directory search excludes Git metadata and links; basic ignore handling does not claim complete Git parity.

Commands/editors need an exact binding such as `agent_options.external_tools.build`, with executable, version, fixed args, project/read/write roots, and timeout. Select it as `agentcfg:build`; the policy must separately allow bash execute with command_ref=build. Raw shell fragments, added arguments, excessive timeouts, and read-only-role execution fail. Foreground commands use private temporary storage and a network-disabled sandbox; native platform/editor behavior still needs its own evidence.

Session switch/fork/reload/handoff is blocked while protected children or unconsumed controlled results remain. Consume results or explicitly cancel/recover and establish termination first; clearing UI does not release workspace protection.

`agent_options.ui.notifications` accepts auto/osc99/osc777/bell/off. Auto selects OSC 99 for Kitty, bell for Windows Terminal, and OSC 777 otherwise. Sending bytes does not prove desktop delivery; no detached PowerShell toast is launched. See [agent state](pi-agent-state.md), [testing](testing.md), and [known issues](known-issues.md).
