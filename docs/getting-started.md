# Getting started with agentcfg

`agentcfg` prepares software and deploys configuration; DSH is the agent that talks to you and works on your project. This tutorial uses the single `dsh-default` recipe. Pi and OMP have separate [Pi](pi.md) and [OMP](omp.md) guides. Read the [DSH guide](dsh.md) before migrating an existing instance: the current Core is a prerelease, and the default AI approval integration has accepted, unresolved limitations.

The examples call this machine `workstation`. If you choose another name, use it consistently in every command. `--machine`, `--local`, and `--profile` are global selectors and go **before** the subcommand.

## 1. Prepare the repository and toolchain

Open your checkout:

```sh
cd /path/to/rotom
uv --version
node --version
npm --version
```

You need Python 3.11+ and uv. DSH's recorded native checks used Node **24.14.0** and npm **11.19.1**. Command requirements differ:

| Command | Accepted toolchain |
| --- | --- |
| `sync` | Node 24.x, at least 24.2.0; npm 11.x |
| `run` | Node 24.x, at least 24.2.0 |
| `lock --agent dsh` | Exactly Node 24.14.0 and npm 11.19.1 |

Node 24.1.0 lacks the `import.meta.main` support required by the entry point and may exit successfully without starting DSH. [Node documents its availability from 24.2.0](https://nodejs.org/download/release/v24.3.0/docs/api/esm.html#importmetamain). Other accepted versions have not all received native smoke testing. Prepare a compatible toolchain using your normal version manager; `agentcfg` does not install Node/npm or change global versions.

```sh
uv sync --locked
./agentcfg --help
```

`uv sync` may download Python dependencies. The entry point then uses the repository `.venv` directly; you do not need to activate it or use `uv run`. Changes committed only in a local checkout are not automatically available on another machine.

## 2. Initialize this machine

```sh
./agentcfg init-local --machine workstation
./agentcfg --machine workstation model status
```

Initialization reports the private machine and shared secret file locations. It creates missing URL/key placeholders required by the selected recipe, preserving existing values and comments. A repeat invocation with nothing missing does not rewrite the files. Use `./agentcfg profiles` to list recipes; `init-local --profile ID` prepares that recipe's fields without changing an existing machine's default recipe.

A minimal machine file for native subscription login is:

```toml
# agentcfg framework configuration, not native DSH YAML.
schema_version = 1

[machine]
id = "workstation"
default_profile = "dsh-default"
editor = "nvim"
```

`editor` is optional and belongs inside `[machine]`. New machine files contain no keys. Shared secrets default to `$HOME/.config/agentcfg/secrets.toml`, or the corresponding XDG configuration directory. These files stay outside Git, with file mode 0600 and private directory mode 0700.

The public model pool includes Kimi Code and GLM Coding Plan subscriptions and the metered DeepSeek API. Unless a role explicitly selects another model, the main model remains Kimi Code `kimi-for-coding`. Missing model keys allow startup but leave those routes unusable. To enter matching service keys without putting them in command history:

```sh
./agentcfg --machine workstation model key kimi-code
./agentcfg --machine workstation model key glm-code
./agentcfg --machine workstation model key deepseek
```

Entering a key does not switch roles. Use the matching Coding Plan credentials, rather than an old general Kimi/GLM API key. Codex/ChatGPT subscription login is separate from an OpenAI API key.

For another API service, `./agentcfg --machine workstation model add` interactively collects a provider, exact model ID, role, and hidden key, validates the proposal, and asks you to confirm the redacted summary before writing. Obtain actual addresses, IDs, and capacities from your service. See [local configuration](local-config.md) for manual configuration and private gateway examples; `example.invalid` and `fictional-*` values are deliberately unusable.

## 3. Preview, install, and deploy

```sh
./agentcfg --machine workstation setup
```

`setup` previews first and stops before installation on conflicts, drift, or pending recovery. It then synchronizes locked dependencies, checks again, and deploys. Installation may use the network. The individual commands remain available:

| Command | Effect and interpretation |
| --- | --- |
| `validate` | Offline configuration and lock checks; success does not verify login. |
| `plan` | Preview without writing the instance. Initial changes are expected; conflicts should be zero. `sync-required` means dependencies still need installation. |
| `sync` | Install or repair from the existing lock; no login, host startup, or lock update. DSH does not install OpenSpec. |
| `apply` | Deploy configuration after checking ownership and conflicts; retain one previous managed version. |
| `doctor` | Offline deployment, dependency, and backup diagnosis for DSH, Pi, and OMP; readiness reports blockers and next commands. |
| `doctor --input` | Also diagnose terminal flags and offline input readiness. OMP reports managed event-loop blocking logs; DSH/Pi report no managed event source and do not read keys. |

Progress goes to stderr, including elapsed-time updates during long installations. Final summaries go to stdout. Installer logs, raw arguments, and keys are not printed. Authentication marked `not-inspected; use native auth status` means account data was not inspected.

Structured commands accept `--format auto|human|json` **after** their subcommand. In `auto`, a terminal receives readable output and a pipe receives single-line JSON. This applies to validate, render, plan, lock, sync, apply, inventory, doctor, capture, rollback, recover, and project init.

```sh
./agentcfg --machine workstation plan --format json
./agentcfg --machine workstation doctor --format human > doctor.txt
./agentcfg --machine workstation model status --verbose
```

`setup`, `init-local`, and `model` use text and do not accept `--format`. `profiles` uses a terminal table or piped TSV. `run` and `usage` pass through native output. Model status checks configured values, not deployment freshness, account entitlement, or connectivity.

The repository includes locks: ordinary first-time DSH use does not need `lock`. That command is for deliberate dependency maintenance. `render` is optional because plan/apply compute the required output.

## 4. Start DSH and sign in

```sh
./agentcfg --machine workstation run --cwd "/path/to/workspace"
```

The directory must exist and should be the project you want DSH to work on. Keep quotes around paths containing spaces. Daily startup uses this command without repeating sync/apply.

The following are commands **inside DSH**, not shell commands. For a Codex/ChatGPT subscription:

```text
/auth status
/auth login openai-codex
/model
```

For Cursor:

```text
/cursor-login
/model
```

Follow the native login prompts, then select the account model. `/cursor-login cancel` cancels a pending login. Cursor uses a community provider and does not require a separate DSH Web instance over SSH. The [DSH guide](dsh.md) covers device-code prerequisites, full login links, account boundaries, and the actual scope of login evidence. `doctor` success is not evidence of a working subscription request.

The default mode is workspace-write + ask, with Perry auto-review enabled for eligible pending write/edit requests. Its unresolved late-approval, OFF-state, and audit limitations matter during ordinary use. For persistent manual approval, follow the shutdown/configuration/restart procedure in the [DSH approval instructions](dsh.md#ai-approval-and-persistent-manual-mode); `/auto-review off` is not a reliable persistent emergency stop.

Exit DSH and wait for the shell before deploying changes. The manager blocks changes to its active instances and does not terminate your sessions.

## 5. Change configuration or restore the previous version

Edit the private machine TOML for machine preferences, or repository sources for shared rules, skills, and templates. Then, with the instance stopped:

```sh
./agentcfg --machine workstation validate
./agentcfg --machine workstation plan
./agentcfg --machine workstation apply
```

See [operations](operations.md) for maintaining complete skills and rules. Most selection arrays replace the whole list: include every entry you want to retain. Provider/model selections have the explicitly documented append-and-deduplicate behavior in [local configuration](local-config.md).

```sh
./agentcfg --machine workstation rollback
./agentcfg --machine workstation doctor
```

There is one backup: A → B saves A; B → C saves B. No-change or failed deployment does not rotate it. Successful rollback consumes it. Rollback restores deployed managed configuration, not Git sources, local TOML, account state, sessions, software versions, or databases. Fix the source before applying again, or the unwanted configuration will return.

On conflicts, preserve the files and inspect plan/doctor. Do not delete backups or a whole native home to force adoption. Existing nonempty unmanaged targets require an explicit safe migration.

## 6. Use your project's workflow

DSH reads project AGENTS.md and Skills without installing OpenSpec, Spec Kit, or another specification tool. Existing `openspec/`, `.specify/`, `specs/`, and user skills remain in place. `project init openspec` is available only to a Pi recipe explicitly selecting that optional capability; see [Pi](pi.md).

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| Entry point missing | Enter `/path/to/rotom`, or call the entry point by absolute path. |
| Missing virtual environment | Run `uv sync --locked` in the checkout. |
| Machine file missing | Use the same `--machine` name as initialization; omission selects `default`. |
| Toolchain mismatch | Match the requirements for the specific command above. |
| Exit 2 | Correct the reported configuration, reference, or lock error; machine TOML is not native DSH YAML. |
| Exit 3 | Fill the required service/MCP secret. Model key status comes from `model status`; subscriptions use native login. |
| Exit 4 | Stop the active instance, inspect plan/doctor, and preserve ownership/conflict/recovery evidence. |
| Exit 5 or damaged runtime | Check the toolchain and installation network, then use sync to stage a repair while preserving the account home. |

For help, share the command name, exit code, and redacted error. Never share complete machine files, environment dumps, or OAuth files. A `target-…` or `credential-…` ID maps to the private diagnostics file reported by plan/doctor. It contains no secret values but can contain private paths; inspect it locally. See [known issues](known-issues.md), [testing](testing.md), and [release status](releases.md) for current limitations and evidence.
