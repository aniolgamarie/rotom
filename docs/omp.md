# Manage OMP with agentcfg

The OMP adapter uses the **unmodified official OMP 18.12.6** runtime and repository-owned plugins, including the permission plugin. Integration uses public configuration and extension APIs. Historical host patches are not a supported deployment path. See [release status](releases.md), [known issues](known-issues.md), and [testing](testing.md) for current evidence and unverified platforms or account routes.

## Recipes and native profiles

A rotom recipe selects shared models, roles, rules, skills, and OMP resources. Each recipe receives a separate native OMP profile for configuration, login, and sessions. Its name is derived from the first 24 hexadecimal characters of the recipe ID's UTF-8 SHA256; the full ID and hash are also checked.

Ordinary sessions preserve the caller HOME/XDG and use an explicit, instance-bound PI_CONFIG_DIR. Native configuration remains under `<instance>/user-home/.omp/profiles/<native-name>/agent`; information/login operations retain their declared native-state scope. The manager rejects arbitrary profile names, old agent directories and settings paths, and does not copy existing logins or sessions. See [environment controls](local-config.md) for name-only inheritance/deletion and value-free warnings.

Managed startup and modifications share the physical instance lock. Concurrent sessions use shared leases; configuration changes require an exclusive lease. Moving the state directory does not authorize takeover. Switching recipes changes the account/session scope and leaves the old scope intact.

## Configuration sources

| Content | Source |
| --- | --- |
| Shared providers, models, MCP | `shared/` registry, using exact IDs and references |
| Rules and complete skills | `shared/`, including skill resources, scripts, and executable intent |
| OMP defaults, prompts, themes | `agents/omp/` |
| Extensions and local MCP packages | `agents/omp/packages/`, with content identities in the dependency lock |
| Capability selection | `profiles/omp-*.toml` |
| Machine paths and nonsecret overrides | Private machine TOML |
| API keys or complete Authorization headers | Private SecretStore, referenced through `secret:<name>` |
| Native login and runtime state | Explicit instance-bound native directories; excluded from capture and configuration backups |

Objects merge recursively. Most arrays replace; provider/model selections append with deduplication as described in [local configuration](local-config.md). Explicit false and empty arrays retain their meaning. Unknown fields, undeclared references, ambiguous model IDs, and credential-bearing URLs fail validation. The shared `main` role maps to native `default`; supported role combinations are documented in [model presets](omp-model-presets.md). Static custom models require verified capacities; do not invent prices.

## Setup and daily startup

`omp-kernel` is the daily recipe; `omp-default` provides the base configuration and the three official API service providers. Prepare the repository `.venv` and a private 0600 machine file first:

```sh
./agentcfg init-local --machine workstation --profile omp-kernel
./agentcfg --machine workstation --profile omp-kernel model status
./agentcfg --machine workstation --profile omp-kernel setup
./agentcfg --machine workstation --profile omp-kernel run --cwd /path/to/workspace
```

Fill required private gateway URLs and keys before setup. `setup` previews offline and stops on conflicts or drift, then syncs the reviewed lock, verifies again, and deploys. For separate review, use validate, plan, sync, apply, and doctor. `render` only prepares cached output. `./agentcfg lock --agent omp` is a deliberate maintenance operation. `run` neither installs/deploys implicitly nor falls back to an OMP on PATH.

Custom API providers use private keys without native account login. For an explicitly selected native Codex account, login uses the same managed identity:

```sh
./agentcfg --machine workstation --profile omp-default run omp -- login openai-codex
```

Login does not require unrelated service keys. Real login and model calls are explicit user operations outside default tests.

## Source discovery and native arguments

External discovery, project skills/MCP, and automatic updates are disabled by default. Where native settings cannot completely disable a source, startup checks the cwd and ancestors, isolated HOME, active/default profiles, dotenv, and direct-helper paths. Other providers' `.agents/.agent/.claude/.codex/.gemini` directories and top-level AGENTS.md/CLAUDE.md/GEMINI.md may exist without their contents being read. Native OMP sources such as `.omp`, dotenv, SYSTEM, TITLE, and APPEND_SYSTEM remain checked. Undeclared sources produce a path/category error without exposing authentication details.

Project resources require `agent_options.discovery.project_resources=true` and nonempty absolute `project_roots` in private configuration. This allows validated read-only project skills and MCP within those roots; it does not admit project rules, prompts, extensions, arbitrary settings, or permissions. Redeploy policy/root changes; source contents are checked on every startup.

Pass native arguments after `run omp --`. The managed entry rejects identity/configuration overrides, extra extensions, secret/broker controls, install/update commands, and additional cwd sources. Model arguments must select an exact declared model. Ordinary sessions add `--no-title`; information and login commands use the instance HOME as cwd.

Session recovery can internally change cwd, so managed startup rejects `--continue/-c`, `--resume/-r`, `--session`, `--fork`, cross-tool session imports, and `--add-dir`. Saved sessions remain intact. Prompt text after native `--` remains text even if it contains flag names.

Source checks are not an operating-system sandbox. The repository permission plugin's scope and limitations are separate from model selection; switching a model preset does not change its permission sidecar. See [known issues](known-issues.md).

## Drift, rollback, and diagnostics

Plan compares the current value, previous deployment baseline, and desired intent, preserving unmanaged native fields. A no-change apply does not rewrite targets or rotate backups. Conflicting edits to the same managed field stop deployment. Capture only proposes nonsecret theme, declared shortcut, and uniquely mapped model-role changes in private storage.

Rollback restores one prior configuration and consumes that backup. It does not downgrade OMP or migrate authentication databases. Pending recovery is handled by explicit apply/rollback; run and usage return 4 while pending.

| Code | Manager meaning before native startup |
| --- | --- |
| 0 | Success, possibly with drift or login notices |
| 2 | Arguments, configuration, or lock invalid |
| 3 | Required runtime secret missing |
| 4 | Ownership, active instance, pending recovery, or source conflict |
| 5 | Missing runtime, unsupported platform, or dependency verification failure |
| 6 | Filesystem or internal operation failure |

After startup, native streams and exit codes pass through. See [operations](operations.md) for recovery, [local configuration](local-config.md) for secrets and gateway URLs, and [model presets](omp-model-presets.md) for role storage and fallback boundaries. Test fixtures are not evidence that a real host or account works.

Additional guides cover [kernel and WSL](omp-kernel.md), [profile/source boundaries](omp-profiles.md), [dependency maintenance](omp-dependencies.md), [usage](omp-usage.md), and [approval diagnostics](omp-approval-diagnostics.md).
