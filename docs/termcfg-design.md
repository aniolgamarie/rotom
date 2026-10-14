# Terminal configuration manager design

`./termcfg` manages public terminal configuration, fixed runtime packages, and its own mihomo user process independently of `./agentcfg`. Its implemented components are `zsh`, `tmux`, and `mihomo`. It does not read agent profiles, models, or API keys and is never invoked implicitly by agentcfg setup/run. This document describes the implemented design; see the [user guide](termcfg.md) for operation and the [feature specification](../specs/003-sync-terminal-tools/spec.md) for requirements.

## Command and side-effect boundaries

| Command | Responsibility |
| --- | --- |
| `components` | List available components |
| `init-local` | Save explicit machine/component selection; `--edit` changes an existing selection |
| `plan` | Offline read-only target preview and deterministic plan ID |
| `status`, `doctor` | Report file, environment, package, recovery, and service facts separately |
| `lock --component … --version …` | Explicit networked maintenance of a repository dependency lock |
| `sync --component …` | Consume a lock to prepare fixed plugins or mihomo core |
| `apply` | Back up and copy selected public files after review |
| `rollback --component …` | Restore the previous successful public-configuration state |
| `recover` | Reconcile an interrupted file transaction |
| `service status\|start\|stop\|reload\|restart` | Inspect or explicitly operate the manager-owned mihomo process |

`plan/status/doctor` accept repeated `--component` selectors and diagnostic `--home`. `apply` accepts repeated component selectors, `--plan-id`, repeated `--adopt-target`, and `--confirm-zshenv`. Rollback has its own `--plan-only` preview and `--plan-id`. Global `--machine` and `--json` are also accepted on subcommands. There is no `mihomo-mgr` component name or invented `plan --adopt` interface.

The private machine TOML at `${XDG_CONFIG_HOME:-~/.config}/termcfg/machines/NAME.toml` has exactly four fields: `machine_id`, `target_home`, `private_state_root`, and `components`. It is an owned ordinary single-link 0600 file in private 0700 management directories. Target/state paths must be canonical and current-user-owned; private state cannot be the target HOME or lie inside the repository. Unknown fields fail validation. The [example](../examples/termcfg-machine.toml) uses fictional paths.

Interactive initialization preselects locally available zsh/tmux, with mihomo unselected. Noninteractive initialization requires explicit repeated `--component` or `--none`. Component selection does not install or reload programs.

## Public source projection

[terminals/catalog.json](../terminals/catalog.json) records each source, target ID/component, digest, and target mode. [Source provenance](../terminals/SOURCES.md) retains origin and license information. Files are copied rather than linked to the checkout.

| Component | Managed targets | Separate runtime preparation |
| --- | --- | --- |
| zsh | `.zshrc`, whole `.zshenv` | Locked zinit/selected plugins |
| tmux | `.tmux.conf`, `.config/tmux/scripts/fzf-window.sh` | Locked TPM/selected plugins |
| mihomo | `.config/termcfg/mihomo/base.yaml`, `.local/bin/mihomo-mgr` | Locked official mihomo core |

Configuration loading must not perform implicit Git/plugin downloads. Runtime preparation belongs to explicit sync and consumes `locks/termcfg/mihomo.json` or `locks/termcfg/plugins.json`. It stages and verifies private packages; configuration apply does not install dependencies. Existing shells/tmux servers keep running without automatic reload or session restoration.

The shipped legacy-named mihomo-mgr program does not provide an alternative owner for process/API/subscription management; those old entry points are disabled. The CLI component remains `mihomo`, with explicit termcfg service operations.

## Ownership, adoption, and file transactions

Preview lists source identity, destination, action, reason, and backup scope. Actions include `create`, `replace`, `adopt-required`, `unchanged`, `blocked`, and `conflict`. Its plan identity binds machine/HOME/components, state, dependency locks, source digests, and target identities. Apply rechecks these facts before writing.

Existing unmanaged files require explicit adoption even when their contents already match the public source. Only classified old source links can be adopted; other links, unsafe paths, special/multilink files, or ownership conflicts stop the operation. Old timestamp backups and markers do not establish ownership. Source/target content suspected to contain credentials, subscriptions, or unclassified private data is rejected before ordinary digest/backup handling. Move private values to an explicit private file before retrying.

Interactive apply previews all selected targets and asks for combined adoption confirmation. A custom nonsecret `.zshenv` needs an additional explicit confirmation because the whole file is replaced, including content outside any old marker. Noninteractive apply binds adoption and `.zshenv` confirmation to the current plan ID. Silence or a stale plan is not consent.

Every existing configuration target across all selected components is backed up and verified before the first target is overwritten. Ordinary files preserve contents/necessary metadata; adopted legacy links preserve the link itself. Each write uses atomic replacement, with a private persistent journal for the multi-file sequence. This does not claim an atomic transaction across an entire directory or running processes.

State records target type, ownership/component, source identity, and before/after identity without logging bodies or secrets. Drift after deployment blocks updates and rollback. No-op apply neither rewrites targets nor rotates the single previous backup. A successful changed apply retains only the preceding configuration state.

Rollback rechecks current identities, restores the previous configuration, and removes originally absent targets only while still owned and unchanged. Core/plugin version changes are outside configuration rollback. Interrupted apply/rollback leaves an observable journal; `status` identifies pending recovery and explicit `recover` rechecks identities before restoration. External changes retain the conflict rather than being overwritten.

Terminal HOME targets have different modes/projection rules from agentcfg's isolated agent artifacts. The implementation reuses safety concepts without weakening the agent deployment contract.

## Mihomo private state and service ownership

The public base contains local ports and nonsecret defaults. Only explicit service start/reload/restart reads `<private_state_root>/mihomo/private.yaml`, validates it, and structurally combines it into private 0600 `effective.yaml` within a 0700 runtime directory. Accepted private keys are `proxies`, `proxy-providers`, `proxy-groups`, `rule-providers`, `rules`, `dns`, and `secret`. A nonempty controller secret and at least one of proxies/proxy-providers are required. Private subscriptions/credentials never enter public source or generic configuration backups. Status/stop do not read subscription bodies.

Old mihomo-mgr configuration is not implicitly imported. Users review and migrate needed private values separately. Apply/rollback leave subscriptions, runtime caches, logs, and unrelated old state intact.

Service leases bind UID, PID, process-start identity, executable, core digest, and public-configuration identity. Operations require the manager's own matching lease. External processes, reused PIDs, unknown identities, and occupied controller ports are refused rather than adopted. Start failure attempts to stop only the newly created matching child and preserves diagnostic state if completion cannot be established.

Syncing core sets `pending_core_effect`; applying public proxy configuration sets `pending_config_effect`. Neither signals a running process. Explicit service operations check process and controller health and clear only the effects supported by evidence. A healthy process alone does not establish loaded configuration; `/configs` observations must match public settings before marking configuration effective. Insufficient evidence remains `unverified`.

## Diagnostics and validation

Progress goes to stderr and the final summary to stdout. JSON mode emits one final object, excluding private YAML, URLs, credentials, file bodies, and raw child stderr. Waits show stages/heartbeats; failures include fixed reasons and next commands. Doctor separates required blockers, optional degradation, and unverified runtime facts. Default doctor can return 0 with reported problems; `--strict` makes required blockers nonzero.

Exit codes are 0 success, 2 arguments/configuration/lock format, 3 missing private service configuration/credentials, 4 ownership/drift/concurrency/stale-plan/recovery conflicts, 5 environment/dependency/service-health failure, and 6 filesystem/internal failure or controlled interruption.

Default tests use temporary HOME/XDG, blocked network, and fake packages/processes/controller APIs. Native shell/tmux loading, real mihomo, subscriptions, and real HOME migration require separate explicit authorization. Source implementation, isolated results, and actual platform/service acceptance remain distinct; see [testing](testing.md) and [known issues](known-issues.md).
