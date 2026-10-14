# Terminal and proxy configuration with termcfg

`./termcfg` is independent of `./agentcfg`. It manages public zsh/tmux/mihomo HOME files, pinned runtime packages, and the mihomo user process it starts; it does not read agent recipes. Prepare Python 3.11+ and the repository `.venv` with `uv sync --locked`.

## Daily workflow

```sh
./termcfg components
./termcfg init-local
./termcfg doctor
./termcfg plan
./termcfg sync --component zsh
./termcfg sync --component tmux
./termcfg sync --component mihomo
./termcfg apply
./termcfg status
```

Sync only the components you need. First initialization preselects zsh/tmux when detected locally; mihomo is not selected by default. `init-local --edit` changes the selection and shows old → new. Noninteractive use requires explicit repeatable `--component zsh` selections or `--none`.

The default machine file is `$XDG_CONFIG_HOME/termcfg/machines/default.toml`, falling back to `$HOME/.config/termcfg/machines/default.toml`. It stores machine ID, target HOME, private state root, and selected components, with file mode 0600 and managed directory mode 0700. The [fictional example](../examples/termcfg-machine.toml) is not ready for a real HOME without adaptation.

Plan/doctor neither download nor change HOME targets. Sync consumes the checked-in [mihomo lock](../locks/termcfg/mihomo.json) and [plugin lock](../locks/termcfg/plugins.json), installing in private XDG data storage. Directories and executable entries use 0700; archives/nonexecutables use 0600.

Apply copies only nonsecret files in the [per-file source catalog](../terminals/catalog.json). It does not install, start/reload a proxy, or switch existing shell/tmux sessions. Missing subscription/API/private proxy settings do not block unrelated components.

Maintainers explicitly generate reviewed lock updates. For example, `./termcfg lock --component mihomo --version v1.19.31` selects an official core. Plugins need exact 40-character commits:

```sh
./termcfg lock --component tmux --plugin tpm --version <full-commit>
./termcfg lock --component zsh --plugin zsh-autosuggestions --repo zsh-users/zsh-autosuggestions --entry zsh-autosuggestions.zsh --version <full-commit>
```

Zsh's default zinit may omit --plugin. A new plugin needs repo and entry. Its ID must match the repository basename (dots/hyphens allowed), and repositories must use allowed prefixes: tmux-plugins/, zdharma-continuum/, zdharma/, zsh-users/, skywind3000/, or ohmyzsh/. Lock downloads/checks the full archive and atomically updates the repository lock; review and commit its diff. Ordinary users do not need lock generation.

Sync reports download progress, with a 10-second connection timeout and 300-second total limit by default; `--timeout` accepts 10–3600 seconds. Long operations emit phase heartbeats every 1.5 seconds.

## Adoption, backup, and recovery

Existing unmanaged files require explicit adoption even when identical to the public source. Interactive apply lists target IDs, actions, and backups, then asks once for the full operation. Overwriting custom nonsecret `.zshenv` requires another specific confirmation. Suspected secrets/subscriptions or unclassifiable old targets stop processing before ordinary hashing/backup. Move private values into a separate 0600 file and preview again. Declared old starter links are adopted only at declared targets, preserving the link itself in backup.

For scripts, use IDs from the current preview; preview again after any target change:

```sh
./termcfg plan --component zsh --json
./termcfg apply --component zsh --plan-id <current-plan-id> --adopt-target <target-id> --confirm-zshenv <current-plan-id>
```

Omit adoption when there is no existing target, and omit the extra .zshenv confirmation when it is unnecessary. Apply completes/verifies the operation's old-configuration backup before replacing the first target. Replacements are individually atomic and recorded in a private journal. A successful actual change retains one prior configuration backup; no-change runs do not rotate it. User changes cause drift/conflict rather than silent overwrite.

After interruption, inspect status then recover. Recovery checks file identity again; external changes can block automatic restoration.

```sh
./termcfg status
./termcfg recover
./termcfg rollback --component zsh
./termcfg rollback --component zsh --plan-only --json
./termcfg rollback --component zsh --plan-id <rollback-specific-id>
```

Interactive rollback previews/asks. Scripted rollback needs its own plan ID. It restores the last successful deployment's prior **public configuration**. A previously absent target is removed only when still owned and unchanged. It does not downgrade core/plugins. Interrupted rollback also retains a journal; recover restores the version from before those writes.

## Private proxy configuration and service

Public base.yaml defines local ports and safe defaults. Only explicit service start/reload/restart reads `$XDG_STATE_HOME/termcfg/machines/default/mihomo/private.yaml` (default `$HOME/.local/state/termcfg/machines/default/mihomo/private.yaml`). It merges structured YAML into mode-0600 effective.yaml in the same private 0700 directory. Status/stop do not read subscription bodies.

Private YAML may contain proxies, proxy-providers, proxy-groups, rules, rule-providers, dns, and secret. It requires a nonempty controller secret and at least one of proxies/proxy-providers. Keep it out of Git. The old mihomo-mgr configuration is separate; its old process/API/subscription entry points are disabled. Manually review/migrate needed private values rather than importing the entire old file automatically.

```sh
./termcfg service status
./termcfg service start
./termcfg service reload
./termcfg service restart
./termcfg service stop
```

Service operations require a manager-owned lease and check UID, PID, process-start identity, and executable. They refuse takeover of external services, reused PIDs, or occupied controller ports. Core sync and public configuration apply separately persist pending_core_effect and pending_config_effect; file operations do not signal a running process. Explicit service operations verify the process/controller API and clear each cause only with sufficient evidence, otherwise reporting unverified. Failed startup health checks attempt to stop only the newly started, still-matching child and preserve diagnostic state.

## Diagnostics and exit codes

Doctor reports ready/blocked/degraded/unverified by component and normally returns 0; `doctor --strict` fails on required blockers. Status separates files, backups/recovery, runtime packages, both pending-effect causes, and service leases.

Progress uses stderr; final summaries use stdout. `--json` stdout contains one final JSON object without private YAML, URLs, keys, file bodies, or raw subprocess stderr. Network/service waits show phase/heartbeat; failures provide reason codes and next commands.

| Code | Meaning |
| --- | --- |
| 0 | Success; read-only diagnosis may still show degradation/pending effects |
| 2 | Arguments, machine configuration, catalog, or lock invalid |
| 3 | Explicit service operation lacks private configuration/credentials |
| 4 | Ownership, drift, concurrent activity, stale snapshot, or recovery conflict |
| 5 | Required environment, dependency asset, or service health failure |
| 6 | Filesystem/internal failure or controlled interruption; inspect status first |

Default tests use temporary HOME/XDG, fake core/API/subprocesses, and blocked network. See [testing](testing.md), [known issues](known-issues.md), and the [design](termcfg-design.md). Real HOME, real core/subscriptions, and tmux-server smoke require separate explicit authorization and are not default test behavior.
