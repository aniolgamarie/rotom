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
| Pi | [Overview](pi.md), [state](pi-agent-state.md), [checkpoints](pi-checkpoints.md), [Codex admission](pi-codex-admission.md), [diagnostics](pi-diagnostics.md), [dirty repositories](pi-dirty-repo-guard.md), [MCP](pi-mcp.md), [ReadSeek](pi-readseek.md), [review](pi-review.md), [web](pi-web.md), [migration](pi-migration.md), [optional OpenSpec](openspec.md) |
| termcfg | [Configuration and commands](termcfg.md), [design](termcfg-design.md) |

## Understand and maintain

- [Architecture](architecture.md), [adapter contract](adapters.md), and [project review and refactoring plan](design/project-refactoring.md).
- [Configuration state and recovery](design/configuration-state.md), [approval boundaries](design/approvals.md), and [model routing](design/model-routing.md).
- [Testing and support](testing.md), [acceptance summary](acceptance.md), [versions](releases.md), and [changelog](../CHANGELOG.md).
- [Known issues and TODOs](known-issues.md), [Roadmap](roadmap.md), [contributing](../CONTRIBUTING.md), and [security](../SECURITY.md).
- [Publication policy](publication-policy.md), [worktrees and merge gates](worktrees.md), and [history remediation](history-cleanup.md).

Dated handoffs, repeated progress snapshots, and raw machine-specific acceptance output were removed from the publication tree. Their useful conclusions are consolidated here; summaries are not byte-for-byte replacements for the original evidence and do not renew historical acceptance.

Three legacy summary paths remain because locked plugin/fixture READMEs refer to them. They contain maintained scope notes, not raw logs; retaining the paths avoids changing runtime resource identities solely for documentation links.
