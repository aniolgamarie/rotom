# Changelog

Notable user-visible changes are recorded here. Unreleased entries describe repository changes; they do not imply a published tag or newly executed native acceptance.

## Unreleased

### Changed

- DSH, Pi and OMP use shared ordinary-run admission with exclusive maintenance. DSH prepares shared launch resources during recoverable apply/rollback; Pi separates supervisor control by full run owner and retains cross-run workspace writer leases.
- DSH/OMP lock resolution publishes recoverable generations under repository leases; sync protects its complete lock-consumption period. Pi publication remains single-publisher.
- Rebuilt the complete Pi 0.84.4 lock against the current adapter/runtime sources and exact toolchains. Direct pins remain unchanged; transitive resolution changes and limited Linux native acceptance are recorded separately.
- Workspace configuration loading defers shared credential-file reads until a selected operation resolves a secret reference.
- termcfg now manages zsh/tmux only. Explicit `migrate --drop-mihomo` retires legacy metadata while preserving running proxy services, private data, targets and backups.

### Fixed

- Malformed frozen pnpm importer, dependency, and package-name structures now produce a configuration error instead of an uncaught attribute error.
- OMP project model-role values may use native `null` clearing without quarantining an otherwise valid role file. Unknown roles and unauthorized nonempty selectors remain rejected.
- The OMP foundation test now checks the 36-artifact contract, including both Catppuccin resources and theme selectors.

### Documentation

- Established English user guides, reference documentation, design explanations, release scope, known issues, and contribution/security policies.
- Removed temporary handoffs, repeated phase reports, and raw machine-specific acceptance output from the publication tree; preserved project specifications and third-party provenance.
- Replaced private machine paths in maintained public material and completed the separately authorized local main-only history cleanup; retained private refs and remote history remain outside that cleanup.
- Added publication privacy, explicit public commit identity, and pre-integration gates for every branch and worktree, including migration of retained old-lineage work.
- Corrected stale OMP version statements and removed obsolete DSH OpenSpec installation guidance.

### Existing integration baseline

- DSH Core `0.2.0-rc.2`, TUI `0.15.0`, Cursor subscription `0.6.12`, Perry auto-review `0.12.17`.
- OMP official `18.8.6`, with an independent permission plugin and Catppuccin theme resources.
- Pi adapter with four declared profiles; complete locks regenerated through real npm resolution, with isolated pi-default materialization. Other profile/platform acceptance remains separate.

See [release scope](docs/releases.md) and [known issues](docs/known-issues.md) for limitations. Historical tests retain their original candidate and platform; documentation consolidation does not upgrade them to current results.
