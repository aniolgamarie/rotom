# rotom / agentcfg

**Project principle: do not modify any agent's upstream source.** Integrations use official configuration, public extension APIs and official CLIs. Historical deviations and migration status are recorded in the [architecture](docs/architecture.md#基本原则上游宿主保持原样) and [migration inventory](docs/follow-ups/upstream-agent-source-migration.md).

**English** | [中文](README.zh-CN.md)

Personal Agent configuration management repository: shared rules, complete skill packs, tool templates, and dependency locks live in Git; per-machine overrides and API keys stay outside. A single entry point generates, validates, deploys, and launches isolated instances; each instance keeps only the previous round of managed-configuration backup.

The first release implements **DSH + ccch1mneyyy/dsh-TUI**. The Pi migration spec is complete within its agreed scope: software integration and Linux x86_64 mock/native validation, including cold rebuilds of all four profiles in two fresh HOME/checkout paths each. The accepted candidate is `9d6a9270`; other platforms and real-account/service validation remain unverified and are tracked as [separate follow-up work](docs/follow-ups/pi-platform-and-live-validation.md). Pi delegates to the official Codex CLI through model-delegate; the migration retires codex-delegate. See the [Pi guide](docs/pi.md), [support matrix](docs/acceptance/pi-support-matrix.md), and [spec completion report](docs/acceptance/pi-spec-closure-20260924/README.md) for configuration and verification status.

The getting-started steps below cover DSH. Their Codex/Cursor subscription references describe authentication/provider access within DSH. Pi uses separate profiles and instance logins.

The Pi closure report applies to the historical lock candidate `9d6a9270…`. Changes to the lock or source require matching native/cold evidence; historical completion does not establish native validation of the current checkout. See the [current support boundary](docs/acceptance/pi-support-matrix.md#当前-checkout-与历史证据).

OMP integration is tracked separately in the [OMP guide](docs/omp.md) and [support status](docs/omp-support.md). It uses fixed OMP v18.4.5 standalone packages, a separate HOME and native profile for each recipe, and fresh logins. `omp-default` is a bootstrap recipe; the nine-row fictional validation recipe is installed only in a temporary validation checkout. The Linux x64 no-account native smoke has passed. Other platform and real-account checks are tracked as [separate follow-ups](docs/follow-ups/omp-platform-and-live-validation.md), outside the completed OMP spec.

Terminal and proxy configuration is managed separately by [`./termcfg`](docs/termcfg.md). It previews and backs up selected zsh, tmux, and mihomo public files before copying them; core and plugin downloads and mihomo service actions are explicit commands. See the guide for private configuration, recovery, and isolated verification status.

Use [`omp-kernel`](docs/omp-kernel.md) to reproduce the reviewed kernel configuration, including models, approval policies, theme, native agents, and complete skills. The guide includes WSL setup; `omp-default` inherits the shared DeepSeek, Kimi and GLM defaults. All profiles inherit these official providers, with profile-specific models and roles layered on top. Use `model status` for credential guidance and `model key deepseek|kimi|glm` to enter a shared key without echoing it; see [local configuration](docs/local-config.md).

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
./agentcfg profiles
./agentcfg init-local

./agentcfg setup
./agentcfg run --cwd /path/to/worktree
```

The default recipe selects the Codex/Cursor subscription entry. It contains no fabricated OAuth endpoints or model IDs, and does not require a DeepSeek key. `setup` previews, syncs locked dependencies (possibly using the network), and deploys. Stage progress and failure locations appear on stderr. Log in through the native TUI before making model calls. `model presets` summarizes the official DeepSeek, Kimi, and GLM models inherited by every profile; add `--verbose` for endpoints and sourced pricing. `model status` shows missing URL/key fields, role bindings, and the files to edit; add `--verbose` for the full model catalog and individual filling commands. `model key` fills shared credentials; `model enable` remains available to add another protocol route. A missing model API key warns at launch but does not block the host; that model and fallbacks using it remain unavailable until the key is supplied. Use `model add` for a new private API-key model; other custom configurations can be edited in the private TOML file.

Public selectors precede subcommands: `--machine NAME` or `--local PATH` (mutually exclusive), `--profile ID` optional. Default machine is `default`; default profile comes from the local file, falling back to `dsh-default`. `init-local --machine NAME --profile ID` creates or checks the private machine and shared credential files, adding only missing URL/key placeholders while preserving values and comments. An explicit profile does not change an existing machine's default profile. Repeating the command without missing fields does not rewrite either file.

Structured commands such as `validate`, `plan`, and `doctor` now show readable summaries in a terminal and retain the original single-line JSON when piped or redirected. Select a format after the subcommand: `./agentcfg plan --format json` or `./agentcfg doctor --format human`. Progress and errors remain on stderr. `setup`, `init-local`, and `model` keep their text output; `profiles` keeps TSV when piped. `run` and `usage` pass through native output.

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
| `profiles` | Lists registered profile IDs and their agents without loading local configuration |
| `init-local [--machine NAME] [--profile ID]` | Creates or checks private configuration and adds missing URL/key placeholders for the selected profile without replacing existing values |
| `setup` | Initial deployment or update of existing configuration: redacted preview, locked dependency sync, and deployment; stops on conflicts, drift, or pending recovery |
| `validate` | Offline schema, reference, adapter, and full-lock validation |
| `render` | Offline generation; writes only to private cache — field intent is not a full native settings file |
| `plan` | Offline redacted diff with location IDs; private cache stores concrete field positions, not targets |
| `lock --agent dsh` | Explicit online resolution of the full dependency lock; review lock & vendor diffs on upgrade |
| `sync` | Consumes the existing lock; stages installs or repairs damaged packages — does not update the lock, start, or log in |
| `apply` | Offline re-plan, backup, and deploy — does not install dependencies |
| `run [dsh] --cwd PATH` | Launches the current deployment; the agent can be inferred from the profile; no implicit sync/apply |
| `usage <native-args>` | Passes through to PATH's `omp usage` without loading local configuration; a preceding explicit OMP `--profile` selects the managed instance ([details](docs/omp-usage.md)) |
| `doctor` / `doctor --live` | Default: offline diagnostics; `--live` adds declared-service reachability checks — never auto-logs-in or calls models |
| `model add` | Interactively adds a private API-key provider, model, and role binding; atomically writes the private machine file after confirmation |
| `model presets` | Summarizes official models; `--verbose` shows endpoints, pricing, and sources |
| `model status` | Shows missing URL/key fields, roles, and edit locations; `--verbose` adds the full catalog and filling commands |
| `model url PROVIDER` | Reads a service URL without echo and saves it to the private machine file; public providers can use `base_url_ref = "local:NAME"` |
| `model enable deepseek\|kimi\|glm` | Enables a shared model for the selected profile after securely entering its API key; unselected presets never block startup |
| `doctor --input` | All agents: caller terminal and offline interaction readiness; OMP also reports structured event-loop stalls, without recording keystrokes |
| `capture` | Captures previews, supported themes, and declared model selections; generates a legal local proposal; does not export auth data |
| `rollback` | Restores the previous managed configuration; consumes that backup on success |
| `project init openspec --path PATH` | Initializes a specific project with the locked CLI; pre-checks conflicts |

Optional native parameters are passed via `run dsh --cwd PATH -- <native-args>` — `--` is the separator and is not forwarded to DSH. Exit codes: 0 success, 2 argument/config/lock error, 3 required MCP/service credential missing, 4 conflict/active lock/recovery pending, 5 dependency or native check failure, 6 IO/internal failure. Missing model API keys produce a warning; after a successful launch the native process exit code is preserved.

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
- [OMP Configuration](docs/omp.md), [Profiles](docs/omp-profiles.md), [Dependencies](docs/omp-dependencies.md), and [Usage](docs/omp-usage.md): fixed standalone runtime, isolated native profiles, resource mapping, and transparent usage queries.

## Testing

```sh
.venv/bin/python -m pytest -q
```

Default tests use a temporary HOME/DSH_HOME/XDG, network blocking, and fake processes; no third-party hosts are run. The native no-account smoke is a separate explicit step; real model calls require separate user authorization and login state. Test counts, actual run environments, untested platforms, and live status are recorded in [Acceptance Records](docs/acceptance.md).

Full npm locks and vendor patches for DSH/TUI/plugins/OpenSpec live in `locks/dsh/`. TUI bundled-manifest fixes keep runtime code unchanged; Cursor patches disable automatic account import, background updates, and package stamping, and provide a terminal login entry. Sources and modification records are in [Upstream Verification Records](docs/upstream-verification.md). Superpowers is not installed; ModSearch, Memento, ModLens, and MCPLens are not in the default install list.
