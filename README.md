# Rotom

**Reproducible configuration and isolated instances for coding agents.**

[Getting started](docs/getting-started.md) · [Documentation](docs/README.md) · [Roadmap](docs/roadmap.md) · [Known issues](docs/known-issues.md) · [简体中文](README.zh-CN.md)

Rotom keeps shared model definitions, rules, complete skill packages, native configuration templates, and dependency locks in Git. Machine overrides, credentials, native logins, and sessions stay private. `agentcfg` validates, previews, installs, deploys, and launches DSH, Pi, and OMP through their own adapters. `termcfg` separately manages selected zsh/tmux configuration and pinned plugins. Proxy service management is outside its scope.

Integrations use official configuration, public extension APIs, and official CLIs. Rotom does not modify agent host source or official binaries. Historical deviations remain documented as migration work; they are not permission to build new patched hosts.

## Current status

This repository is preparing its first public release. The manager package version is `0.1.0`; no release tag is implied by that value. See [versions and release scope](docs/releases.md) and the [changelog](CHANGELOG.md).

| Integration | Locked host | Status and boundary |
| --- | --- | --- |
| DSH | Core `0.2.0-rc.2`, TUI `0.15.0` | One `dsh-default` recipe; Cursor Provider and Perry auto-review `0.12.17`. Core is a prerelease. Auto-review has accepted, unresolved upstream limitations. |
| OMP | `18.8.6` | Unmodified official runtime with an independent Rotom permission plugin. Platform and operation coverage is recorded separately. |
| Pi | Official `1.3.0` | `pi-base` / `pi-pro` use the official CLI and complete npm locks. Linux evidence is limited to manager rebuilding and isolated contracts; native/account acceptance remains not run. Pro collaboration and status-information parity remain unavailable. See [support and limits](docs/pi-support.md). |
| termcfg | Component-specific locks | Explicit terminal configuration and plugin downloads; independent of agent profiles. Legacy metadata has an explicit migration path. |

Read [known issues](docs/known-issues.md) before selecting an integration. Python tests, native smoke, and authenticated model calls provide different evidence; [testing and support](docs/testing.md) explains the distinction.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and the selected agent's locked toolchain. DSH was tested with Node `24.14.0` and npm `11.19.1`; accepted compatibility ranges and installation requirements are in the [DSH guide](docs/dsh.md).

```sh
git clone <repository-url> rotom
cd rotom
uv sync --locked
./agentcfg profiles
./agentcfg init-local --machine workstation --profile dsh-default
./agentcfg --machine workstation --profile dsh-default model status
./agentcfg --machine workstation --profile dsh-default setup
./agentcfg --machine workstation --profile dsh-default run --cwd /path/to/workspace
```

`init-local` creates private machine and shared credential files and adds missing placeholders without overwriting existing values. Use `model key kimi-code`, `model key glm-code`, or `model key deepseek` for hidden key entry. OAuth accounts are logged in through the selected native instance. Missing model credentials do not prevent startup; that route remains unavailable. Rotom never imports another application's login automatically.

`setup` previews, consumes the existing dependency lock, and deploys. For separate reviewable steps, use `validate`, `plan`, `sync`, and `apply`. Daily `run` launches the deployed contract without implicitly installing or applying changes. Public selectors such as `--machine` and `--profile` precede the command.

## What Rotom manages

- Shared model and provider references, with independent credentials, protocols, routes, and billing.
- Deterministic native configuration and complete declared rules, skills, agents, and resources.
- Locked runtime packages, integrity checks, staged installation, and drift diagnostics.
- Stable instance HOME directories, active leases, field ownership, conflict detection, and interrupted-write recovery.
- One previous generation of managed configuration. Configuration rollback does not downgrade software or migrate session databases.

Files that mix native and managed settings use field-level ownership. Initialization-only UI preferences respect later native edits; unknown native fields are preserved. Unknown fields in Rotom input fail validation.

## Documentation

| Goal | Start here |
| --- | --- |
| Install and launch | [Getting started](docs/getting-started.md) |
| Configure shared keys and models | [Local configuration](docs/local-config.md), [model catalog](docs/model-catalog.md) |
| Use a specific integration | [DSH](docs/dsh.md), [OMP](docs/omp.md), [Pi](docs/pi.md), [termcfg](docs/termcfg.md) |
| Diagnose, update, or recover | [Operations](docs/operations.md), [known issues](docs/known-issues.md) |
| Understand the design | [Architecture](docs/architecture.md), [approval boundaries](docs/design/approvals.md) |
| Contribute or report a security issue | [Contributing](CONTRIBUTING.md), [security policy](SECURITY.md) |

English is the authoritative documentation language. The Chinese landing page is a supplementary translation. Project specifications and historical governance material may retain their original language and scope; they do not override current implementation and support statements.

## License

Rotom is distributed under the [MIT license](LICENSE). Bundled third-party material retains its own licenses, notices, and source records. Those records are intentionally preserved.
