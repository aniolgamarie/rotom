# Changelog

Notable user-visible changes are recorded here. Unreleased entries describe repository changes; they do not imply a published tag or newly executed native acceptance.

## Unreleased

### Fixed

- Malformed frozen pnpm importer and dependency structures now produce a configuration error instead of an uncaught attribute error.
- OMP project model-role values may use native `null` clearing without quarantining an otherwise valid role file. Unknown roles and unauthorized nonempty selectors remain rejected.
- The OMP foundation test now checks the 36-artifact contract, including both Catppuccin resources and theme selectors.

### Documentation

- Established English user guides, reference documentation, design explanations, release scope, known issues, and contribution/security policies.
- Removed temporary handoffs, repeated phase reports, and raw machine-specific acceptance output from the publication tree; preserved project specifications and third-party provenance.
- Replaced private machine paths in maintained public material and documented the separate Git history remediation process.
- Corrected stale OMP version statements and removed obsolete DSH OpenSpec installation guidance.

### Existing integration baseline

- DSH Core `0.2.0-rc.2`, TUI `0.15.0`, Cursor subscription `0.6.12`, Perry auto-review `0.12.17`.
- OMP official `18.8.6`, with an independent permission plugin and Catppuccin theme resources.
- Pi adapter with four declared profiles; current source/lock mismatch remains an open new-deployment blocker.

See [release scope](docs/releases.md) and [known issues](docs/known-issues.md) for limitations. Historical tests retain their original candidate and platform; documentation consolidation does not upgrade them to current results.
