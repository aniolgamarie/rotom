# rotom / agentcfg

**English** | [中文](README.zh-CN.md)

Personal Agent configuration management repository: shared rules, complete skill packs, tool templates, and dependency locks live in Git; per-machine overrides and API keys stay outside. A single entry point generates, validates, deploys, and launches isolated instances; each instance keeps only the previous round of managed-configuration backup.

The first release implements **DSH + ccch1mneyyy/dsh-TUI**. Pi, Codex CLI, and other tools are not yet adapted — they can reuse the shared core via new adapters. "Codex subscription" and "Cursor subscription" in this project refer to authentication / provider access *within* DSH, not to standalone Codex or Cursor configuration sync.

**First-time users: start with the [Getting Started Guide](docs/getting-started.md).** It walks through environment setup, local file creation, installation, deployment, login, daily startup, and backup/restore in actual operation order, and explains command output. When using only Codex/Cursor subscriptions, you can leave `[secrets]` empty — no need to copy the private-gateway example below.

Existing first-release users: see [Upgrade & Repair Notes](docs/operations.md#审查修复后的升级). Local files now enforce strict permission and link checks; old deployment packages without a file receipt can be rebuilt by running `sync` after exiting DSH — account home directories are preserved.

Three commands cover the basics: `sync` installs software, `apply` deploys configuration, `run` starts DSH. Run them in order the first time; afterwards `run` is usually all you need. In the examples below, `workstation` is the local machine config name and `dsh-default` is the recipe name — both can be used as-is.

## Prerequisites

- **Manager:** Python 3.11+, uv. Run `uv sync --locked` once; the entry point then uses the repo `.venv` directly — offline commands install nothing.
- **DSH toolchain:** The lock was generated and smoke-tested with **Node 24.14.0, npm 11.19.1**. `sync` accepts Node **24.x from 24.2.0** and npm **11.x**; `run` checks the same Node requirement. Node 24.1 cannot execute the `import.meta.main` entry used here. Generating a lock still requires the exact locked versions. Prepare Node/npm with your own version manager; agentcfg does not install them. Other accepted versions have not been smoke-tested.
- **First-release platforms:** Linux, macOS. Native Windows is not supported. Linux has been isolation-verified; macOS acceptance status is tracked in [Acceptance Records](docs/acceptance.md).

## From Clone to Running

```sh
git clone <your-repo-url> rotom
cd rotom
uv sync --locked
./agentcfg init-local --machine workstation

# Edit ~/.config/agentcfg/machines/workstation.toml with your editor.
# When XDG_CONFIG_HOME is set, the file lives under $XDG_CONFIG_HOME/agentcfg/machines/.
./agentcfg --machine workstation validate
./agentcfg --machine workstation plan
./agentcfg --machine workstation sync
./agentcfg --machine workstation apply
./agentcfg --machine workstation doctor
./agentcfg --machine workstation run dsh --cwd /path/to/worktree
```

The default recipe selects the Codex/Cursor subscription entry. It contains no fabricated OAuth endpoints or model IDs, and does not require a DeepSeek key. You can complete validate → render → sync → apply first, then log in via the native TUI; actual model calls still need a user account.

Public selectors precede subcommands: `--machine NAME` or `--local PATH` (mutually exclusive), `--profile ID` optional. Default machine is `default`; default profile comes from the local file, falling back to `dsh-default`. `init-local --machine NAME` is the reserved initialization form — repeating it does not overwrite files.

## Local File

Below is **framework TOML, not native DSH config**. Addresses and models are fictional examples; when using a private API, replace them with values your service actually supports, and fill in keys by hand.

```toml
schema_version = 1
[machine]
id = "workstation"
default_profile = "dsh-default"
editor = "nvim"

[overrides.providers.private_gateway]
protocol = "openai-compatible"
base_url = "https://gateway.example.invalid/v1"
auth_kind = "api-key"
credential_ref = "secret:private_gateway_key"

[overrides.models.private_main]
provider = "private_gateway"
remote_id = "fictional-private-chat"
input = ["text"]

[overrides.profiles.dsh-default]
providers = ["private_gateway"]
models = ["private_main"]
mcp = []

[overrides.profiles.dsh-default.roles]
main = "private_main"

[secrets]
private_gateway_key = ""
```

Files are 0600, private directories 0700. Objects merge recursively; arrays are replaced wholesale; empty arrays and `false` are valid. Unknown fields, invalid references, and authentication ownership conflicts fail. For more fields, machine paths, environment variables, and multi-profile usage see [Local Config Reference](docs/local-config.md); `examples/` contains explicitly fictional format examples that must not be treated as callable services.

## Commands & Side Effects

| Command | Behavior |
|---|---|
| `init-local --machine NAME` | Creates an empty-secrets local file; does not overwrite |
| `validate` | Offline schema, reference, adapter, and full-lock validation |
| `render` | Offline generation; writes only to private cache — field intent is not a full native settings file |
| `plan` | Offline redacted diff with location IDs; private cache stores concrete field positions, not targets |
| `lock --agent dsh` | Explicit online resolution of the full dependency lock; review lock & vendor diffs on upgrade |
| `sync` | Consumes the existing lock; stages installs or repairs damaged packages — does not update the lock, start, or log in |
| `apply` | Offline re-plan, backup, and deploy — does not install dependencies |
| `run dsh --cwd PATH` | Launches the current deployment, preserves the working directory, injects secrets on demand; no implicit sync/apply |
| `doctor` / `doctor --live` | Default: offline diagnostics; `--live` adds declared-service reachability checks — never auto-logs-in or calls models |
| `capture` | Captures previews, supported themes, and declared model selections; generates a legal local proposal; does not export auth data |
| `rollback` | Restores the previous managed configuration; consumes that backup on success |
| `project init openspec --path PATH` | Initializes a specific project with the locked CLI; pre-checks conflicts |

Optional native parameters are passed via `run dsh --cwd PATH -- <native-args>` — `--` is the separator and is not forwarded to DSH. Exit codes: 0 success, 2 argument/config/lock error, 3 required key missing, 4 conflict/active lock/recovery pending, 5 dependency or native check failure, 6 IO/internal failure; after a successful launch the native process exit code is preserved.

## Backup & Runtime State

Default instance path: `~/.local/share/agentcfg/instances/dsh/<profile>/`; its `dsh-home` and isolated `user-home` remain fixed. State/backup live in XDG state, artifacts in XDG cache. The manager does not take over `~/.dsh`, Pi, or other tool account directories by default.

After a successful apply A→B, A is kept; after a subsequent successful apply C, only B is kept. No-change or failed operations do not rotate backups. Multi-file writes use a temporary recovery record; single files are atomically replaced; restore re-checks conflicts. Backups contain only managed files/fields — not OAuth, sessions, mixed settings, or local key files. Software downgrade and database migration are not covered by config rollback.

A running managed instance blocks apply/sync/rollback; the manager does not kill user processes. External processes started or modified outside the manager are not fully constrained by the active lock, but pre-write re-checks still run. A read-only trusted repository may reside under a shared mount ancestor, but private deployment directories continue to require secure ancestors, ownership, and permissions.

## Authentication, Project Integration & Maintenance

- [DSH Authentication, Parameters & Verified Limits](docs/dsh.md): Codex native companion `/auth login openai-codex`; Cursor community package adds `/cursor-login` — accounts are held by native plugins.
- [OpenSpec Project Operations](docs/openspec.md): Uses the upstream `agents` integration as a custom DSH integration; initializes the Git worktree root, does not auto-modify all business repos.
- [Daily Maintenance & Adding Shared Content](docs/operations.md): Includes examples for rules, skills, provider/model additions.
- The `maintain-agent-config` skill ships with the default profile, guiding Agents to write legal local TOML, modify templates, and validate generated results; deployment still goes through the manager's backup/conflict flow.
- [Adding a Second Tool](docs/adapters.md): Interface, ownership, native encoding, and acceptance boundaries.

## Testing

```sh
.venv/bin/python -m pytest -q
```

Default tests use a temporary HOME/DSH_HOME/XDG, network blocking, and fake processes; no third-party hosts are run. The native no-account smoke is a separate explicit step; real model calls require separate user authorization and login state. Test counts, actual run environments, untested platforms, and live status are recorded in [Acceptance Records](docs/acceptance.md).

Full npm locks and vendor patches for DSH/TUI/plugins/OpenSpec live in `locks/dsh/`. TUI bundled-manifest fixes keep runtime code unchanged; Cursor patches disable automatic account import, background updates, and package stamping, and provide a terminal login entry. Sources and modification records are in [Upstream Verification Records](docs/upstream-verification.md). Superpowers is not installed; ModSearch, Memento, ModLens, and MCPLens are not in the default install list.
