# Documentation

English is the authoritative language for maintained user and developer documentation. [简体中文](../README.zh-CN.md) provides a translated overview. Specifications under `specs/`, `.specify/`, and `openspec/` are project records; historical scope and language are preserved.

## Start and configure

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
- [Configurable workspaces](design/configurable-workspaces.md) and [interaction flows](design/configurable-workspaces-interactions.md): implemented local templates, directory and named contexts, fixed instance launch contracts and reviewed Git creation, with [isolated verification](../specs/006-configurable-workspaces/quickstart.md). Native acceptance and deployment remain unverified; guarded workspace close and existing-branch Git creation refuse before dispatch. The [Herdr guide](herdr-workspaces.md) is the usage reference.
- [Testing and support](testing.md), [acceptance summary](acceptance.md), [versions](releases.md), and [changelog](../CHANGELOG.md).
- [Known issues and TODOs](known-issues.md), [Roadmap](roadmap.md), [contributing](../CONTRIBUTING.md), and [security](../SECURITY.md).
- [Publication policy](publication-policy.md), [worktrees and merge gates](worktrees.md), and [history remediation](history-cleanup.md).

Dated handoffs, repeated progress snapshots, and raw machine-specific acceptance output were removed from the publication tree. Their useful conclusions are consolidated here; summaries are not byte-for-byte replacements for the original evidence and do not renew historical acceptance.

Three legacy summary paths remain because locked plugin/fixture READMEs refer to them. They contain maintained scope notes, not raw logs; retaining the paths avoids changing runtime resource identities solely for documentation links.
