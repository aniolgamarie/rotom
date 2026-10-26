# Documentation

English is the authoritative language for maintained user and developer documentation. [简体中文](../README.zh-CN.md) provides a translated overview. Specifications under `specs/`, `.specify/`, and `openspec/` are project records; historical scope and language are preserved.

## Start and configure

- [Unified checkout and shell entry](../README.md#quick-start): prepared `.venv`, separate agent/terminal initialization, explicit existing work configuration, three-TTY navigation, automation, preferences, reviewed shell-entry deployment, and recovery.
- [Getting started](getting-started.md): prerequisites, private file creation, deployment, and first launch.
- [Local configuration](local-config.md): machine overrides, shared credentials, ownership, and merge rules.
- [Model catalog](model-catalog.md): stable model IDs, providers, capabilities, and independent billing routes.
- [Operations](operations.md): daily commands, diagnostics, updates, recovery, and rollback.

## Integration guides

| Integration | Guides and references |
| --- | --- |
| DSH | [Daily use, authentication, UI, and permissions](dsh.md) |
| OMP | [Overview](omp.md), [kernel recipe](omp-kernel.md), [profiles](omp-profiles.md), [models](omp-model-presets.md), [dependencies](omp-dependencies.md), [usage](omp-usage.md), [approval diagnostics](omp-approval-diagnostics.md), [support](omp-support.md) |
| Pi | [Base/Pro guide](pi.md), [support and sources](pi-support.md), [migration](pi-migration.md), [current feature record](../specs/005-rebuild-pi-toolkit/implementation-status.md) |
| Herdr | [Switching, daily commands, reconnecting, keys and rollback](herdr-workspaces.md), [upgrades](herdr-upgrades.md), [structured workspace verification](../specs/006-configurable-workspaces/quickstart.md), [current-main preparation](acceptance/configurable-workspaces-main-20261022.md), [historical seven-role verification](../specs/005-herdr-project-workspaces/quickstart.md) |
| termcfg | [Configuration and commands](termcfg.md), [design](termcfg-design.md) |

## Understand and maintain

- [Architecture](architecture.md), [adapter contract](adapters.md), and [project review and refactoring plan](design/project-refactoring.md).
- [Configuration state and recovery](design/configuration-state.md), [approval boundaries](design/approvals.md), and [model routing](design/model-routing.md).
- [CLI interaction strategy](design/cli-interaction.md): first-delivery status summaries, contextual guidance and static parameter/help improvements; implementation evidence, test limits and conditional follow-ups.
- [Rotom command and session experience proposal](../specs/007-rotom-cli-entry/README.md), [feature specification](../specs/008-rotom-command-experience/spec.md) and [implementation plan](../specs/008-rotom-command-experience/plan.md): Chinese project records with staged requirements and evidence gates. Unified routing/defaults, three-stream input policy, static help/restricted ID completion, and managed zsh entry deployment are implemented. Current isolated evidence covers 3,347 unified CLI/input checks and 433 terminal/entry checks; a separate authorized Linux run passed temporary-HOME entry binding/rollback, sixteen installed-entry calls, and twelve fresh zsh/PTY Tab cases, as recorded in the [native entry acceptance](../specs/008-rotom-command-experience/main-review.md#19-真实-zsh-入口与-tab-验收). That result requires trusted source/toolchain ancestors and does not cover the daily checkout or third-party plugins. Read-only `agent instances list` is implemented, with per-field evidence and explicit unknown/OMP limits. Current-terminal `resume --here` and explicit `agent instances stop` are admitted for the exact verified Linux managed-DSH lock; stop additionally requires a newly registered original-host control endpoint and the reviewed current plan. Recovery reports load confirmation as unknown and sends no continuation text. Full setup/maintenance execution and restore, other tool/platform combinations, original-pane recovery and automatic continuation remain unavailable; see the [session](rotom-session-capabilities.md) and [stop](rotom-stop-capabilities.md) capability records. The [CLI contract](../specs/008-rotom-command-experience/contracts/cli.md) and [entry deployment contract](../specs/008-rotom-command-experience/contracts/entry-deployment.md) define the current boundaries; historical integration evidence is separate.
- [Configurable workspaces](design/configurable-workspaces.md) and [interaction flows](design/configurable-workspaces-interactions.md): implemented local templates, directory and named contexts, fixed instance launch contracts and reviewed Git creation, with [isolated verification](../specs/006-configurable-workspaces/quickstart.md). Native acceptance and deployment remain unverified; guarded workspace close and existing-branch Git creation refuse before dispatch. The [Herdr guide](herdr-workspaces.md) is the usage reference.
- [Latest-main planning review](../specs/008-rotom-command-experience/main-review.md): fetched refs, pinned TUI source findings, the earlier planning snapshot and the feature implementation handoff onto main `109e2e7`, existing Pi release observation, and revised registration/listing versus shared-resource dependencies. The integration candidate now targets main `9a4d9a1`; later sections record actual isolated and native checks separately from the earlier source review and migration.
- [Session capability evidence](rotom-session-capabilities.md): strict v1/v2 run records, isolated-tested DSH/Pi Linux registration and read-only instance listing, verified current-terminal DSH recovery, remaining strict-load limitations, and the OMP shared-runtime owner boundary. Record metadata does not itself admit resume, stop, terminal control, or input.
- [Stop-channel evidence](rotom-stop-capabilities.md) and [original-pane comparison](rotom-pane-capabilities.md): Chinese research records with finite fake models for exact host targeting, manager preservation, complete release before parking, and one-shot resume requests. Exact Linux managed-DSH `stop_only` has passed native verification; original-pane recovery remains unavailable.
- [Testing and support](testing.md), [acceptance summary](acceptance.md), [versions](releases.md), and [changelog](../CHANGELOG.md).
- [Known issues and TODOs](known-issues.md), [Roadmap](roadmap.md), [contributing](../CONTRIBUTING.md), and [security](../SECURITY.md).
- [Publication policy](publication-policy.md), [worktrees and merge gates](worktrees.md), and [history remediation](history-cleanup.md).

Dated handoffs, repeated progress snapshots, and raw machine-specific acceptance output were removed from the publication tree. Their useful conclusions are consolidated here; summaries are not byte-for-byte replacements for the original evidence and do not renew historical acceptance.

Three legacy summary paths remain because locked plugin/fixture READMEs refer to them. They contain maintained scope notes, not raw logs; retaining the paths avoids changing runtime resource identities solely for documentation links.
