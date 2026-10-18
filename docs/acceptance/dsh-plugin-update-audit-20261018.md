# DSH plugin update audit — 2026-10-18

Scope: every managed DSH plugin in `agents/dsh/plugins.toml`, its upstream
provider where a repository-owned wrapper is used, and the official Core
cohort. This is a read-only version assessment; no upstream package was
updated, no deployed instance was changed, and no native/account check ran.

| Managed plugin | Current selection | Latest checked upstream selection | Result |
| --- | --- | --- | --- |
| TUI | `0.15.0`, source commit `e709863` | npm `latest=0.16.1`; upstream release `v0.16.1` | Update available; retained current pin |
| Codex auth | Public `./oauth` from the same fixed TUI | Same `0.16.1` TUI update | Updates with TUI; no independent package |
| Cursor auth | Own terminal adapter `0.1.2`, upstream `dsh-cursor-subscription@0.6.12` | `0.6.12` | No upstream version update found |
| Perry auto-review | `dsh-auto-review@0.12.17` | `0.12.17` | No update found |
| Review context | Own `rotom-dsh-review-context@0.1.1` | Repository-owned | No external release stream |
| tmux-context | Official `0.2.1-rc.2` | npm `next=0.2.1-rc.2` | No newer published cohort found |
| Git Worktrees | Official runtime and tool `0.2.1-rc.2` | Both npm `next=0.2.1-rc.2` | No newer published cohort found |
| SSH subscription auth | Own `rotom-dsh-ssh-subscription-auth@0.1.0` | Repository-owned, new in this change | No external release stream |

The ancillary execution-environment `0.1.1` and SSH shell-env `0.1.0` adapters
are also repository-owned; there is no external update to fetch for them.

## Source and compatibility findings

- [TUI upstream releases](https://github.com/ccch1mneyyy/dsh-TUI/releases) and
  [registry metadata](https://registry.npmjs.org/%40deepseek-harness-tui%2Fdsh-tui)
  identify `0.16.1`. Its peer declarations explicitly accept Core
  `0.2.1-rc.2`. This does not validate our complete composition. Current local
  terminal/auth wrappers pin the TUI `0.15.0` public API; a TUI update needs
  its own wrapper, source/lock, module-identity and behavior review.
- [Cursor upstream releases](https://github.com/orrinzeng/dsh-cursor-subscription/releases)
  and [registry metadata](https://registry.npmjs.org/dsh-cursor-subscription)
  still identify `0.6.12`. Its prerelease peer range requires the host's
  `includePrerelease` interpretation; a plain semver check is not native
  provider acceptance.
- [Perry upstream releases](https://github.com/PerryLink/dsh-auto-review/releases)
  and [registry metadata](https://registry.npmjs.org/dsh-auto-review) still
  identify `0.12.17`. Existing lifecycle/audit limitations remain unchanged.
- [Core registry](https://registry.npmjs.org/%40deepseek-ai%2Fdsh),
  [tmux-context registry](https://registry.npmjs.org/%40deepseek-ai%2Fdsh-tmux-context),
  [Worktrees runtime registry](https://registry.npmjs.org/%40deepseek-ai%2Fdsh-experimental-worktree)
  and [Worktrees tool registry](https://registry.npmjs.org/%40deepseek-ai%2Fdsh-experimental-tool-worktree)
  each report `next=0.2.1-rc.2`, which matches this repository. Their `latest`
  tags lag behind: Core `0.2.0-rc.2`, tmux-context `0.0.1-rc.1`, and both
  Worktrees packages `0.2.1-alpha.2`. These tags must not cause a downgrade.
  Exact rc.2 peers for the official optional packages align with the selected
  Core cohort.

Better Sidebar, dsh-context and Annotation are not installed managed plugins.
Their earlier [TUI applicability assessment](dsh-plugin-ssh-assessment-20261017.md)
remains separate; this audit does not add or endorse them.

## Verification boundary

The evidence comes from public upstream repositories/releases and a direct
read of npm registry package metadata, including dist-tags and tagged-version
peer declarations. A scout performed the independent release/source review;
the main agent closed the tmux-context search-index ambiguity through direct
registry reads. No account, authentication, session or private machine file
was read for this audit. Published-version findings apply to this date;
runtime compatibility and native activation remain separately unverified.
