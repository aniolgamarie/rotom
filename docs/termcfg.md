# Terminal configuration with termcfg

`./termcfg` independently manages public zsh/tmux HOME files and pinned plugins. Prepare Python 3.11+ and the repository `.venv` with `uv sync --locked`.

```sh
./termcfg components
./termcfg init-local --component zsh --component tmux
./termcfg doctor
./termcfg plan
./termcfg sync --component zsh
./termcfg sync --component tmux
./termcfg apply
./termcfg status
```

Interactive initialization preselects available terminal programs. Noninteractive initialization requires explicit repeatable `--component` or `--none`. Use `init-local --edit` to change the selection. The private machine file stores exactly machine ID, target HOME, private state root and components; see the [fictional example](../examples/termcfg-machine.toml). Managed metadata files require 0600 and private directories 0700.

Plan, doctor and status work offline. Sync explicitly downloads the [locked plugins](../locks/termcfg/plugins.json) into private XDG data storage. Shell and tmux loading never downloads plugins. Sync defaults to a 300-second total timeout; `--timeout` accepts 10–3600 seconds. Maintainers update exact plugin commits explicitly and review the resulting lock diff:

```sh
./termcfg lock --component tmux --plugin tpm --version <full-commit>
./termcfg lock --component zsh --plugin zsh-autosuggestions --repo zsh-users/zsh-autosuggestions --entry zsh-autosuggestions.zsh --version <full-commit>
```

Zsh defaults to zinit when `--plugin` is omitted. New plugins require an allowed repository prefix and an entry path. Lock generation verifies complete archive resources and publishes under a repository lease.

Apply copies only the [declared public files](../terminals/catalog.json). Unmanaged targets require explicit adoption, including identical files. Custom `.zshenv` replacement requires separate confirmation. Suspected secrets or unclassifiable existing files stop before ordinary backup. For scripts, use the current preview ID and only the required adoption arguments:

```sh
./termcfg plan --component zsh --json
./termcfg apply --component zsh --plan-id <current-plan-id> --adopt-target <target-id> --confirm-zshenv <current-plan-id>
```

Apply backs up all affected existing files before the first replacement and journals atomic replacements. A successful change retains one previous configuration. No-change runs do not rotate backups. Recovery checks target identity and refuses external drift:

```sh
./termcfg recover
./termcfg rollback --component zsh --plan-only --json
./termcfg rollback --component zsh --plan-id <rollback-plan-id>
```

## Retiring an existing mihomo selection

Mihomo management, service commands, core locks and public proxy assets have been removed. A future proxy manager has not taken ownership. Existing processes, target files, packages, private configuration, subscriptions, logs and backups remain untouched.

Existing v1 state, including zsh-only state, needs explicit migration. First inspect `./termcfg status`. If a legacy transaction is pending, run `./termcfg recover` before migrating. Recovery uses the strict legacy journal without the removed catalog or lock.

```sh
./termcfg migrate --drop-mihomo
```

Migration holds the machine operation lease and changes only machine/state metadata. It removes the mihomo selection, target ownership records, previous-backup references and retired effect fields, writing v2 state. With no state file it updates only the machine selection. The private `drop-mihomo-migration.json` marker archives validated original metadata and backup references/paths, excluding TOML comments and all account/configuration bodies. It preserves 0600 files under the private state directory. No old target or backup is deleted or read by migration.

If interrupted, repeat the same command. Durable before/after digests allow either metadata write to resume; observed drift refuses further changes. These are best-effort checks under the machine operation lease; they do not provide atomic compare-and-swap against an external writer changing files between the final check and replacement. Completed migration is idempotent and never restores archived ownership. Ordinary commands report the migration instruction until completion. Unknown metadata fields fail validation.

Machine leases are scoped to machine IDs. Different machine IDs sharing a target HOME are not serialized; use one machine ID per HOME and avoid concurrent management of the same HOME. Native terminal acceptance remains separate from isolated tests.
