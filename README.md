# Rotom

**Reproducible configuration and isolated instances for coding agents.**

[Getting started](docs/getting-started.md) · [Documentation](docs/README.md) · [Roadmap](docs/roadmap.md) · [Known issues](docs/known-issues.md) · [简体中文](README.zh-CN.md)

Rotom keeps shared model definitions, rules, complete skill packages, native configuration templates, and dependency locks in Git. Machine overrides, credentials, native logins, and sessions stay private. `rotom` routes agent, terminal, and workspace commands to the existing managers. `agentcfg` validates, previews, installs, deploys, and launches DSH, Pi, and OMP through their own adapters. `termcfg` separately manages selected zsh/tmux configuration and pinned plugins. Proxy service management is outside its scope.

Integrations use official configuration, public extension APIs, and official CLIs. Rotom does not modify agent host source or official binaries. Historical deviations remain documented as migration work; they are not permission to build new patched hosts.

## Current status

This repository is preparing its first public release. The manager package version is `0.1.0`; no release tag is implied by that value. See [versions and release scope](docs/releases.md) and the [changelog](CHANGELOG.md).

| Integration | Locked host | Status and boundary |
| --- | --- | --- |
| DSH | Core `0.2.1-rc.2`, TUI `0.16.1` | One `dsh-default` recipe; Cursor Provider and Perry auto-review `0.13.7`. Core is a prerelease. Auto-review has accepted, unresolved upstream limitations. |
| OMP | `18.12.6` | Unmodified official runtime with an independent Rotom permission plugin. Platform and operation coverage is recorded separately. |
| Pi | Official `1.3.0` | `pi-base` / `pi-pro` use the official CLI and complete npm locks. Bounded Linux UI, model/session and selected-module evidence is recorded by source snapshot. Status information is delivered with three accepted display differences; Pro investigation waits for upstream, and Brave/Cursor account acceptance is deferred. See [support and limits](docs/pi-support.md) and the [integration checks](specs/005-rebuild-pi-toolkit/integration-candidate.md). |
| termcfg | Component-specific locks | Explicit terminal configuration and plugin downloads; independent of agent profiles. Legacy metadata has an explicit migration path. |

Read [known issues](docs/known-issues.md) before selecting an integration. Python tests, native smoke, and authenticated model calls provide different evidence; [testing and support](docs/testing.md) explains the distinction.

Candidate maintenance implementation and grouped validation are complete on `feat/tool-maintenance-workflows-20261026`, based on main `45953f0`; it remains on the task branch and is not merged; merging needs separate human approval. DSH/Pi/OMP now have staged exact stop → independently approved ordinary setup → one-session current-terminal handoff in the candidate. Loading remains unconfirmed, with no continuation input. Pi leases cover Rotom participants; OMP may fork a competing writer into a new session ID. Native Pi/OMP TUI/PTY checks and affected regressions have source-specific passing evidence; the validation record distinguishes grouped coverage, corrected failures, and skipped cases. See the [workflow guide](docs/tool-maintenance-workflows.md) for commands, boundaries and separate evidence.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and the selected agent's locked toolchain. DSH was tested with Node `24.14.0` and npm `11.19.1`; accepted compatibility ranges and installation requirements are in the [DSH guide](docs/dsh.md).

```sh
git clone <repository-url> rotom
cd rotom
uv sync --locked
./rotom --help
./rotom agent profiles
./rotom agent init-local --machine workstation --profile pi-base
./rotom agent --machine workstation --profile pi-base model status
```

Start from a known checkout. Its `./rotom`, `./agentcfg`, and `./termcfg` use the already prepared repository `.venv`; invoking them does not run `uv`, install dependencies, or fall back to system Python for business commands. The explicit `uv sync --locked` above prepares that environment. Source-checkout help does not require an installed entry binding.

Agent `init-local` creates private machine and shared credential files and adds missing placeholders without overwriting existing values. Use `model key kimi-code`, `model key glm-code`, or `model key deepseek` in the selected agent scope for hidden key entry. OAuth accounts are logged in through the selected native instance. Missing model credentials do not prevent startup; that route remains unavailable. Rotom never imports another application's login automatically.

Review the selected profile before explicitly preparing and deploying it:

```sh
./rotom agent --machine workstation --profile pi-base setup
./rotom run pi --machine workstation --profile pi-base --cwd /path/to/workspace
```

`setup` previews, consumes the existing dependency lock, and deploys. For separate reviewable steps, use `validate`, `plan`, `sync`, and `apply`. Preparation never automatically starts the agent. Daily `run` requires an existing compatible deployment and does not implicitly sync, deploy, or log in. A pending runtime update does not automatically replace a valid deployed runtime. The legacy `agentcfg` and `termcfg` entries retain their existing syntax and defaults.

Terminal initialization is separate from agent initialization. Work commands reuse an existing agentcfg machine document with work settings; they have no `work init-local` command:

```sh
./rotom term init-local --machine terminal-box --component zsh
./rotom work --machine workstation config check
./rotom work --machine workstation config edit
./rotom work --local /absolute/path/to/machine.toml config edit
```

The work examples require an existing structured work configuration; `config edit` reviews changes through an interactive editor. See the [Herdr guide](docs/herdr-workspaces.md) for the initial work configuration. Initializing an agent profile does not initialize terminal settings, work settings, or other agent profiles.

### Navigation, explicit commands, and defaults

With stdin, stdout, and stderr all attached to TTYs, `./rotom` and incomplete command groups offer navigation and missing-field input. A complete command goes straight to its executor. `--interactive` requires all three TTYs; `--no-input` forbids input and returns 2 when required data or equivalent approval is missing. Selecting a target does not approve a write, deployment, or process action. Hidden credentials remain interactive input, never command-line values.

```sh
./rotom agent model key --help
./rotom --no-input agent --machine workstation --profile pi-base plan
./rotom run pi --machine workstation -- --help
```

Help at every management level is static. All tokens after `run --`, and the entire tail of `agent usage` including `--help`, belong to the native command. Management selectors precede agent/work subcommands; root `run` selectors follow `run`, and terminal selectors can appear before or after its subcommand. `agent init-local` takes its selectors after `init-local`.

For already deployed instances, the short forms are `./rotom run dsh`, `./rotom run pi`, and `./rotom run omp`. Explicit machine/local/profile selectors take precedence over saved defaults. Root `run` then uses `defaults.agent_machine` and `run_profiles.dsh` / `.pi` / `.omp`, finally machine `default` and `dsh-default` / `pi-base` / `omp-default`. Ordinary `agent run` uses the selected machine's management `default_profile`, rather than root `run_profiles`. An invalid explicit selection or selected saved reference fails instead of silently choosing another target.

Agent, terminal, and work machine preferences are independent, even though work reads agentcfg machine documents. Once the referenced machines exist, save only the defaults you intend to use:

```sh
./rotom config show
./rotom config set defaults.agent_machine workstation
./rotom config set defaults.term_machine terminal-box
./rotom config set defaults.work_machine workstation
./rotom config set run_profiles.pi pi-base
./rotom config unset defaults.agent_machine
```

Saving or clearing preferences does not initialize, deploy, or run anything. Existing workspaces retain their fixed type bindings and launch contracts.

### Install or repair the shell entry

From the known checkout, select the terminal machine's saved target HOME and review an explicit trusted checkout source:

```sh
./rotom term --machine terminal-box plan --component zsh --entry-repo /absolute/path/to/rotom
./rotom term --machine terminal-box apply --component zsh --entry-repo /absolute/path/to/rotom --plan-id PLAN_ID
```

Use the exact current plan ID after reviewing source, target HOME, changes, and ownership. Unmanaged targets require separate `--adopt-target TARGET_ID` approval; replacing a custom `.zshenv` additionally requires `--confirm-zshenv PLAN_ID`. A diagnostic `--home` override does not authorize deployment to another HOME. Installing this entry does not initialize or deploy agent/work configurations.

The zsh transaction manages three entry files: `.local/bin/rotom` (0700), `.local/share/rotom/entry.json` (0600), and `.local/share/rotom/zsh/site-functions/_rotom` (0644). zshrc deduplicates PATH and puts the completion directory in a deduplicated fpath before plugin initialization and every compinit. The installed launcher locates its binding from its own fixed installation layout, independently of the caller's HOME, XDG variables, or working directory. It uses `python3 -I -S -B` only for standard-library binding lookup, then hands off to the exact prepared interpreter. The binding permits only the fixed `rotom` entry and `.venv/bin/python` paths in the recorded checkout; it is not an arbitrary command or template runner.

An existing binding stays selected when another checkout updates terminal files. Changing the source or repairing a moved/missing checkout requires an explicit trusted `--entry-repo` and a newly reviewed plan. If the installed command or binding is damaged, use `./rotom` from a known prepared checkout; it never searches for a replacement repository or prepares a missing environment. Use recorded recovery/rollback where available; supplying `--entry-repo` does not authorize overwriting malformed or unowned binding bytes. Pending recovery and ownership drift must be resolved before another apply:

```sh
./rotom term --machine terminal-box recover
./rotom term --machine terminal-box rollback --component zsh --plan-only
./rotom term --machine terminal-box rollback --component zsh --plan-id ROLLBACK_PLAN_ID
```

Recovery uses recorded payloads, backups, and identities; it does not regenerate old bytes from the current checkout. Drift or insufficient ownership evidence preserves pending state for review. Catalog readers accept static v1 and v2 catalogs; v2 also supports the one fixed entry-binding generator. Pure static operations retain state/journal v2 unless v3 is already in use. Generated entry artifacts require v3, and subsequent operations preserve v3 rather than downgrade it. Pending journals retain their original schema; an older tool that cannot read v3 must refuse rather than discard its fields.

Historical baseline evidence: the unified CLI/input paths have 3,347 isolated passing checks, and terminal/entry integration has 433. These are simulated, offline checks. A separate authorized Linux acceptance run also passed in dedicated temporary HOME/source copies: four plan/apply/rollback transitions, sixteen installed-entry checks across two working directories, and twelve fresh zsh/PTY Tab cases. The source and prepared Python environment must both have trusted ancestor permissions; this result does not validate a daily checkout with unsafe ancestors. See the [native entry acceptance record](specs/008-rotom-command-experience/main-review.md#19-真实-zsh-入口与-tab-验收). `agent instances list` now provides read-only human/JSON observations. DSH `agent instances stop --dry-run` and `agent maintenance plan --operation setup --run ID` now provide read-only target plans, shared-resource references, historical session clues, and explicit blockers. Use the full run ID from `instances list`; review the current plan before explicitly requesting stop. A digest alone is not authorization. Exact Linux managed-DSH `stop_only` is admitted in that baseline for newly launched runs with a verified original-host control endpoint and the full runtime lock `e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d`. Noninteractive actual stop requires the reviewed current plan ID (missing: 2; mismatch: 4). That baseline did not admit setup/maintenance execution, restore, other platforms/tools, old runs or force (5). In that baseline, current-terminal `resume` is admitted for the exact verified Linux managed-DSH runtime lock. It preserves the requested session, original directory, and native exit code, while reporting load confirmation as unknown and sending no continuation text. Pi/OMP recovery, other platforms and other terminal locations were outside that baseline’s admission. These limits do not renew or replace the integrations' separate historical evidence.

Strict v1/v2 run-record reading is implemented. DSH/Pi have an isolated-tested Linux registration integration that records the manager identity, deployed ownership, and observed start directory; host, session, and terminal details remain unknown without evidence. On other platforms DSH retains its ordinary launch leases and reports that reliable identity registration is unavailable; Pi retains its existing reliable-identity prerequisite. Fresh Linux OMP scopes can register cooperatively only after verifying all three resource owners; existing or incomplete scopes retain their protection. Read-only listing separates manager birth identity, host identity, start/session directories, historical session references, and unknown terminal capabilities. No-profile listing includes all profiles in the selected machine; unavailable records remain visible and cause exit 4. Listing itself grants no recovery or process-control authority; see the [session capability record](docs/rotom-session-capabilities.md).

Once a scope contains v2 run records, use a compatible checkout for that scope: old v1 readers reject those records. Configuration rollback does not downgrade run ownership records or remove active/unknown protection.

Instance listings and DSH stop previews show the deployment digest and locked runtime identity recorded at launch. Legacy records retain unknown versions instead of inheriting today's configuration. For DSH v2 plans, unknown external resource coverage is disclosed without independently blocking an exact selected stop; setup still requires complete coverage and rejects unselected shared references. Verified original process identity, explicit approval, and the registered control endpoint remain required; missing evidence does not fall back to PID guessing. An authorized isolated check using a copy of the installed current-lock DSH runtime has verified one startup and one precise graceful stop, including the persisted signal result, descendant exit observation, original lease release, and terminal restoration. A later controlled Rotom resume run observed the original synthetic history and working directory with a new run, zero terminal input, load confirmation unknown, and continue not sent. A public read-only hook identified the additional localhost model request as the TUI’s automatic recap, outside the Agent loop. Final current-terminal recovery acceptance passed, including active-TUI and external-writer rejection and recovery after release. The ordinary CLI route has also passed a separate native run and is admitted for the exact Linux managed-DSH lock with `--here`. A subsequent default-runtime native three-select-two stop passed: the unselected third owner and process identities stayed active with no request/dispatch and shared EX still blocked; a distinct plan then stopped only that third run. All three managers exited 0, owners became idle_confirmed, original leases and termios were restored, input stayed zero, and source bytes were unchanged. That historical task snapshot was 86/117; the candidate workflow supersedes its maintenance availability limit. Historical failed assertions remain recorded. See the [stop capability and validation record](docs/rotom-stop-capabilities.md).

To stop exact supported runs, replace these fictional scope/run values, `PLAN_ID` and `BATCH_ID` with the observed IDs:

```sh
./rotom agent --machine workstation --profile dsh-default instances stop --run 11111111111111111111111111111111 --dry-run
./rotom --no-input agent --machine workstation --profile dsh-default instances stop --run 11111111111111111111111111111111 --plan-id PLAN_ID --wait-seconds 30
./rotom --no-input agent --machine workstation --profile dsh-default maintenance status --batch BATCH_ID --format json
./rotom --no-input agent --machine workstation --profile dsh-default maintenance cancel --batch BATCH_ID --format json
```

The whole selection shares one deadline: 30 seconds by default, 1–300 allowed. Unknown or expired execution returns 4 with the batch preserved; requests are never automatically resent or escalated to force. Status is read-only. Cancel handles only unposted active items or reconciles an already confirmed close; it cannot undo an uncertain dispatch. Saved session details stay historical and do not authorize automatic restore or continuation. See command `--help` and the [default-stop acceptance](specs/008-rotom-command-experience/main-review.md#62-dsh-默认入口的精确停止验收).

Historical Linux OMP Domain setup batches also retain their read-only status route. It requires an existing batch and an explicit public profile whose declared tool is `omp`; the name prefix does not select the tool. Use the selected local file or machine path; the query does not discover batches, infer a historical profile, or scan other machines. Without an explicit profile, status retains the DSH route. Replace `BATCH_ID` with the existing full 32-character lowercase hexadecimal ID:

```sh
./rotom --no-input agent --local /path/to/machine.toml --profile omp-default maintenance status --batch BATCH_ID --format json
```

The OMP JSON preserves the original `operation_result` separately from the query's `exit_code`. `protected` describes only this batch's resource intent, not global resource availability. A successful operation awaiting handoff still returns 4; completed handoff with the current target and resources verified returns 0. Unknown or pending observations return 4, and an existing nonzero operation result keeps its code. A normally observed batch cancelled before any dispatch returns 0 only to report cancellation; an abnormal observation still returns 4. `manual` does not mean the session has resumed, and `continue_status` stays `not_sent`. Output supports `auto`, `human`, and `json`; its only next command is the exact status query. For these legacy Domain batches, status grants no stop/execute/restore/cancel authority; new workflow batches use the separate staged interface. The CLI change passed 336 isolated checks; a later fixture wording correction passed its 21 checks separately, without adding those counts or claiming native validation. That historical progress snapshot remains 86/117; new candidate tasks are tracked separately.

The candidate also provides stopped-session history without Herdr: `./rotom resume --stopped --list --format human` shows saved session IDs, directories, titles/notes and per-item status; `./rotom resume pi --stopped` selects a complete maintenance item for current-terminal handoff. Noninteractive single-item selection requires exact `--batch` and `--run`. Location recovery also accepts `--stopped --batch B --all --original|--new-tab` for a completed maintenance workflow: it validates the whole same-scope batch, dispatches independent terminals one at a time, preserves earlier facts and marks later items not_dispatched after the first failure or unknown result. Final native acceptance passed all twelve groups without tracing and admits the six exact Linux managed combinations for both locations; this does not enable ordinary `--session` location recovery. New DSH/Pi Herdr V1/V2 launches and compatible new-tab recovery use the resident launcher; ordinary rotom run does not. Loading and automatic continuation remain unknown/not_sent. See the [six-combination, two-location support matrix and four verified work entries](docs/rotom-pane-capabilities.md#本轮精确组合验收清单). OMP has no default work type; supported new-tab recovery creates a resident that can later restore in place. The previous full isolated snapshot completed with 14,153 passed and 13 skips across 14,166 unique tests. The shared-readiness correction passed 3,740 affected tests with 4 skips plus an official Pi Base paired workflow. Location recovery accepts `--wait-seconds 1..300` (default 30), shared across the batch; it does not limit the Agent after handoff. The feature is not merged into main, and T125 still needs human approval. Add matching `--label RUN_ID=TITLE` arguments to maintenance plan/stop to preserve a short note. OMP can use its independent title metadata; DSH/Pi do not scan transcripts to generate summaries. Incomplete legacy snapshots only offer a manual recovery command. Loading stays unconfirmed and no continuation is sent. See the [stopped-session guide](docs/tool-maintenance-workflows.md#已停止会话清单与快捷恢复); this candidate remains on the task branch pending human approval to merge.

Ordinary `resume --session` now rejects a pending durable request for the same full session reference across separate CLI calls, returns 4 and offers a scoped query. Complete release plus a saved native exit permits a new explicit request; loading remains unconfirmed and continuation is not sent. Concurrent workflow metadata waits only for its first short lock, within the existing batch deadline during position preparation. Latest source-specific checks are recorded in the [validation record](specs/008-rotom-command-experience/tool-workflow-validation.md); the earlier full-suite and shared-readiness results above remain separate snapshots.

Historical authorized isolated official-host checks cover the current-terminal CLI stop/setup/stopped-history/resume flow for DSH, Pi and OMP; they do not establish admission for the new location paths. The additional Pi lock `a68d9dcf…` has separate Base and Pro checks and exact handoff admission; main’s four existing lock edits remain untouched. See the [current native validation record](specs/008-rotom-command-experience/tool-workflow-validation.md) for source binding, the OMP exit-lock fix, and remaining limits.

## What Rotom manages

- Shared model and provider references, with independent credentials, protocols, routes, and billing.
- Deterministic native configuration and complete declared rules, skills, agents, and resources.
- Locked runtime packages, integrity checks, staged installation, and drift diagnostics.
- Stable instance HOME directories, active leases, field ownership, conflict detection, and interrupted-write recovery.
- One previous generation of managed configuration. Configuration rollback does not downgrade software or migrate session databases.

Files that mix native and managed settings use field-level ownership. Initialization-only UI preferences respect later native edits; unknown native fields are preserved. Unknown fields in Rotom input fail validation.

## Documentation

- [Staged tool maintenance workflows](docs/tool-maintenance-workflows.md) — candidate commands, writer boundaries and acceptance status.

| Goal | Start here |
| --- | --- |
| Install and launch | [Getting started](docs/getting-started.md) |
| Configure shared keys and models | [Local configuration](docs/local-config.md), [model catalog](docs/model-catalog.md) |
| Use a specific integration | [DSH](docs/dsh.md), [OMP](docs/omp.md), [Pi](docs/pi.md), [Herdr workspaces](docs/herdr-workspaces.md), [termcfg](docs/termcfg.md) |
| Diagnose, update, or recover | [Operations](docs/operations.md), [known issues](docs/known-issues.md) |
| Understand the design | [Architecture](docs/architecture.md), [approval boundaries](docs/design/approvals.md) |
| Contribute or report a security issue | [Contributing](CONTRIBUTING.md), [security policy](SECURITY.md) |

English is the authoritative documentation language. The Chinese landing page is a supplementary translation. Project specifications and historical governance material may retain their original language and scope; they do not override current implementation and support statements.

## License

Rotom is distributed under the [MIT license](LICENSE). Bundled third-party material retains its own licenses, notices, and source records. Those records are intentionally preserved.
