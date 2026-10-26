# Changelog

Notable user-visible changes are recorded here. Unreleased entries describe repository changes; they do not imply a published tag or newly executed native acceptance.

## Unreleased

### Changed

- Added Kimi K3.1 Pro and K3.1 Pro Highspeed (`k3.1-pro`, `k3.1-pro-highspeed`) to the official optional pool and to the OMP/Pi/DSH TF binding catalogs, per the official model guide checked 2026-10-24. K3.1 models only support thinking mode, so bindings disable the off level (Pi `disabled_thinking_levels`, OMP `thinking.requiresEffort`); output budgets reuse the K3 client cap and TF gateway availability, behavior, and pricing remain unverified, with no TF cost declared in `omp-kernel`. Default roles and fallback chains are unchanged.
- Added named proxy configurations: declare multiple proxies under `[machine.proxies.<name>]` (`url`, optional `all_proxy`/`no_proxy`) in the local machine file, pick a persistent default with `machine.environment.proxy`, and override per launch with `run --proxy <name>`. A selection injects the eight standard `HTTP(S)_PROXY`/`ALL_PROXY`/`NO_PROXY` variables; caller proxy variables are never inherited implicitly, and selections conflict-checked against `inherit`/`values`/`unset`. Host-specific overrides such as OMP `PI_PROXY` remain explicit values. Raw non-HTTP transports (Cursor subscription HTTP/2 streams, Codex WebSocket) remain outside environment-proxy coverage.
- Added explicit `structured-v1` workspace configuration with shared selector/CLI/manual registration, bounded discovery, independent directory/named contexts, fixed default/extra terminal bindings and reviewed new-branch Git worktree creation. Isolated verification is recorded for [feature 006](specs/006-configurable-workspaces/quickstart.md); native acceptance and deployment remain unverified. Guarded workspace close and existing-branch Git creation return 5 before dispatch.
- Selected unmodified official npm TUI `0.16.1` (gitHead `73ff99fbed56563bf154d719effd09f9f9725349`); the former `0.15.0` source-build archive is historical. Cursor/SSH wrapper metadata now targets TUI `0.16.1` as versions `0.1.3`/`0.1.1`, preserving upstream Cursor `0.6.12` and Core `0.2.1-rc.2`.
- Added explicit opt-in official rc2 Agent Teams with a deployed selection flag. It remains outside default plugins; isolated Linux member/task/restart and TUI/Perry combination acceptance passed. Instance maintenance protection remains unchanged, and native manifest-writing `/team on/off` is unsupported in managed profiles.
- Isolated Linux TUI session-resume/settings-migration/CLI and matching Perry formal/manual/timeout scenarios passed for the selected ecosystem; real account and other-platform scope remains separate.
- Selected official Perry `0.13.7`; the current Core combination uses inline review without tools. A Rotom-owned public reviewer preset is separately available and probed. Native single-operation sandbox escalation can be routed to AI behind a tool-name gate; unknown tools remain human. Review timeout defaults to 90 seconds with strict override options, and doctor remains configuration-only. Bounded native acceptance does not establish persistent verdict audit or repairs for historical OFF/late-approval failures.
- Ordinary execution has a versioned caller-environment contract, persistent unset, name-only one-shot overrides and value-free default warnings. Native account/session ownership remains separate; restricted Pi workers retain a minimal environment.
- DSH, Pi and OMP use shared ordinary-run admission with exclusive maintenance. DSH prepares shared launch resources during recoverable apply/rollback; Pi separates supervisor control by full run owner and retains cross-run workspace writer leases.
- DSH/OMP lock resolution publishes recoverable generations under repository leases; sync protects its complete lock-consumption period. Pi publication remains single-publisher.
- Rebuilt the complete Pi 0.84.4 lock against the current adapter/runtime sources and exact toolchains. Direct pins remain unchanged; transitive resolution changes and limited Linux native acceptance are recorded separately.
- Workspace configuration loading defers shared credential-file reads until a selected operation resolves a secret reference.
- termcfg manages zsh/tmux and optional Herdr configuration. Explicit `migrate --drop-mihomo` retires legacy metadata while preserving running proxy services, private data, targets and backups.

### Fixed

- `lock` and `sync` for DSH/Pi can reach the npm registry through an explicitly selected named proxy: pass `--proxy <name>` to resolve `[machine.proxies.<name>]` into npm-native `npm_config_proxy`/`npm_config_https_proxy`/`npm_config_noproxy` for the build environment only. Caller proxy variables and the ordinary-session proxy default are not inherited by these operations. Unsupported backends, including OMP, reject an explicit proxy with `lock-proxy-unsupported` or `sync-proxy-unsupported`. Calls without a proxy retain the existing narrow backend contract; proxy support cannot substitute for explicit maintenance admission. Setup keeps its existing build-environment and approval rules.
- DSH development subprocesses and stdio MCP can use caller HOME/XDG while TUI preferences remain isolated. termcfg preserves explicit NVM_DIR and selects private hooks through XDG with conflict diagnostics.
- Pi upgrade previews read the persisted manifest baseline, allowing `plan` to run after deployment while rejecting corrupt saved manifests.
- Malformed frozen pnpm importer, dependency, and package-name structures now produce a configuration error instead of an uncaught attribute error.
- OMP project model-role values may use native `null` clearing without quarantining an otherwise valid role file. Unknown roles and unauthorized nonempty selectors remain rejected.
- The OMP foundation test now checks the 36-artifact contract, including both Catppuccin resources and theme selectors.

### Documentation

- Established English user guides, reference documentation, design explanations, release scope, known issues, and contribution/security policies.
- Removed temporary handoffs, repeated phase reports, and raw machine-specific acceptance output from the publication tree; preserved project specifications and third-party provenance.
- Replaced private machine paths in maintained public material and completed the separately authorized local main-only history cleanup; retained private refs and remote history remain outside that cleanup.
- Added publication privacy, explicit public commit identity, and pre-integration gates for every branch and worktree, including migration of retained old-lineage work.
- Corrected stale OMP version statements and removed obsolete DSH OpenSpec installation guidance.

### Historical integration baseline

- DSH Core `0.2.0-rc.2`, TUI `0.15.0`, Cursor subscription `0.6.12`, Perry auto-review `0.12.17`.
- OMP official `18.8.6`, with an independent permission plugin and Catppuccin theme resources.
- Pi adapter with four declared profiles; complete locks regenerated through real npm resolution, with isolated pi-default materialization. Other profile/platform acceptance remains separate.

See [release scope](docs/releases.md) and [known issues](docs/known-issues.md) for limitations. Historical tests retain their original candidate and platform; documentation consolidation does not upgrade them to current results.

⚠ 1 unresolved conflict detected
- ours = HEAD
- theirs = feat/proxy-passthrough-pi-cursor-20261025
NOTICE: Inspect a block by reading `conflict://<N>` (add `/ours` / `/theirs` / `/base` to render a single side). Resolve with `write({ path: "conflict://<N>", content })`, or bulk-resolve every registered conflict with `write({ path: "conflict://*", content })`. Writes replace ONLY the marker block (markers + all sides) — never repeat the lines before/after it; they stay in place.
`content` shorthand: a line that is exactly `@ours` / `@theirs` / `@base` / `@both` expands to that recorded section. `@both` is ours-then-theirs with no separator — only for additive conflicts where each side adds something different; NEVER for competing edits of the same lines (pick a side or write the combined text). Lines that are not a token pass through verbatim, so `"// keep both\n@ours\n@theirs"` literally writes the comment, then ours, then theirs.
Per-id bulk: `write({ path: "conflict://*", content: "1: @ours\n2: @theirs\n…" })` resolves each listed id with that side in ONE call — the cheapest way through many pick-one conflicts; unlisted ids stay registered.
Resolve each block faithfully: keep one side (`@ours`/`@theirs`), or combine them when both intents apply — never invent content beyond the recorded sides, and never stack both sides of competing edits. Resolve several conflicts in a single turn by issuing multiple `write` calls at once; ids stay valid as earlier blocks are resolved.

──── #1  L9-14 ────
<<< ours
- Added Kimi K3.1 Pro and K3.1 Pro Highspeed (`k3.1-pro`, `k3.1-pro-highspeed`) to the official optional pool and to the OMP/Pi/DSH TF binding catalogs, per the official model guide checked 2026-10-24. K3.1 models only support thinking mode, so bindings disable the off level (Pi `disabled_thinking_levels`, OMP `thinking.requiresEffort`); output budgets reuse the K3 client cap and TF gateway availability, behavior, and pricing remain unverified, with no TF cost declared in `omp-kernel`. Default roles and fallback chains are unchanged.
>>> theirs
- Added named proxy configurations: declare multiple proxies under `[machine.proxies.<name>]` (`url`, optional `all_proxy`/`no_proxy`) in the local machine file, pick a persistent default with `machine.environment.proxy`, and override per launch with `run --proxy <name>`. A selection injects the eight standard `HTTP(S)_PROXY`/`ALL_PROXY`/`NO_PROXY` variables; caller proxy variables are never inherited implicitly, and selections conflict-checked against `inherit`/`values`/`unset`. Host-specific overrides such as OMP `PI_PROXY` remain explicit values. Raw non-HTTP transports (Cursor subscription HTTP/2 streams, Codex WebSocket) remain outside environment-proxy coverage.
