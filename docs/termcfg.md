# Terminal configuration with termcfg

`./termcfg` independently manages public zsh/tmux HOME files and pinned plugins. Prepare Python 3.11+ and the repository `.venv` with `uv sync --locked`.

Without a command it prints static task guidance and exits 2, without inspecting machine state. `--help` shows the full index; `COMMAND --help` explains parameters, effects and examples. `status` describes managed targets and recovery, `doctor` explains environment blockers, and `plan` previews changes. None of these starts or reloads a shell/tmux session.

The examples below use machine `default`. For another machine, consistently use `--machine NAME`; this selector and `--json` are accepted before or after the command. For example, `./termcfg --machine workstation status --json` observes that machine rather than `default`.

Human output shows scope, blockers/degradation, effects, target/plan/transaction IDs and conditional next actions. `--json` retains one final structured object, including errors; piping alone does not switch formats. JSON is not consent: existing TTY prompts and progress remain on stderr. An invalid machine selector is redacted as `<invalid>` in error results rather than echoed.

Suggested commands preserve the validated machine and component scope. Recovery/migration remain machine-wide. Optional per-component sync suggestions are alternatives, not required installation or a batch script. Diagnostic `--home` suggestions never transfer a plan ID or authorize writes: inspect the saved target with a fresh plan before applying there. `status` checks target contents; it is not a metadata-only health cache.

```sh
./termcfg components
./termcfg init-local --component zsh --component tmux
./termcfg doctor
./termcfg plan
# Optional plugin preparation; not required to apply public configuration.
./termcfg sync --component zsh
./termcfg sync --component tmux
./termcfg apply
./termcfg status
```

Interactive initialization preselects available terminal programs. Noninteractive initialization requires explicit repeatable `--component` or `--none`. Use `init-local --edit` to change the selection. The private machine file stores exactly machine ID, target HOME, private state root and components; see the [fictional example](../examples/termcfg-machine.toml). Managed metadata files require 0600 and private directories 0700.

Plan, doctor and status work offline. Sync explicitly downloads the [locked plugins](../locks/termcfg/plugins.json) into private XDG data storage. Shell and tmux loading never downloads plugins. Each archive download uses a 300-second default budget; `--timeout` accepts 10–3600 seconds. This is not an atomic, whole-command timeout across multiple plugins. Maintainers update exact plugin commits explicitly and review the resulting lock diff:

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

A nonzero exit does not prove that nothing changed. Inspect `reason`, `stage`, `side_effect` and any transaction facts: cached plugin activation may already have switched the selection, and an interruption after commit may occur after the journal has been removed. In the latter case, check status rather than assuming unchanged HOME. If recovery refuses target drift, preserve the target and inspect status before deciding how to resolve it; do not blindly repeat recovery or migration.

## Retiring an existing mihomo selection

Mihomo management, service commands, core locks and public proxy assets have been removed. A future proxy manager has not taken ownership. Existing processes, target files, packages, private configuration, subscriptions, logs and backups remain untouched.

Existing v1 state, including zsh-only state, needs explicit migration. First inspect `./termcfg status`. If a legacy transaction is pending, run `./termcfg recover` before migrating. Recovery uses the strict legacy journal without the removed catalog or lock.

```sh
./termcfg migrate --drop-mihomo
```

Migration holds the machine operation lease and changes only machine/state metadata. It removes the mihomo selection, target ownership records, previous-backup references and retired effect fields, writing v2 state. With no state file it updates only the machine selection. The private `drop-mihomo-migration.json` marker archives validated original metadata and backup references/paths, excluding TOML comments and all account/configuration bodies. It preserves 0600 files under the private state directory. No old target or backup is deleted or read by migration.

If interrupted, repeat the same command. Durable before/after digests allow either metadata write to resume; observed drift refuses further changes. These are best-effort checks under the machine operation lease; they do not provide atomic compare-and-swap against an external writer changing files between the final check and replacement. Completed migration is idempotent and never restores archived ownership. Ordinary commands report the migration instruction until completion. Unknown metadata fields fail validation.

Machine leases are scoped to machine IDs. Different machine IDs sharing a target HOME are not serialized; use one machine ID per HOME and avoid concurrent management of the same HOME. Native terminal acceptance remains separate from isolated tests.

## Zsh development environment and private hooks

Zsh defaults `NVM_DIR` to `$HOME/.nvm` only when it is unset. An explicit path is
preserved; an explicitly empty value disables NVM loading, including `/nvm.sh`.
The selected directory is exported. Shell startup does not install NVM or plugins.

For each of `zshenv.local` and `zshrc.local`, the shell checks
`${XDG_CONFIG_HOME:-$HOME/.config}/termcfg/` first. If that file is absent, it uses
`$HOME/.config/termcfg/` as a legacy fallback. If both files exist and refer to
different files, a fixed stderr warning is printed and neither is loaded. Paths
that refer to the same file load once. A nonempty relative `XDG_CONFIG_HOME` also
warns and skips private hooks. Warnings include no private paths or contents.
Keep private hook files outside Git and mode 0600.

Doctor/status show metadata-only hook selection for the target HOME and the
manager's current `XDG_CONFIG_HOME`. This is a preview, not evidence of an existing
shell or tmux server's environment. A private zshenv hook can change the environment
used later by zshrc; each stage selects its own hook. Changes require a new shell
for verification. Existing tmux servers retain their environment independently.
Deploy through the ordinary plan/apply drift checks; do not overwrite changed
user startup files to force these defaults.

Nonempty `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME` and
`XDG_CACHE_HOME` values must be absolute. The [XDG Base Directory
Specification](https://specifications.freedesktop.org/basedir/latest/) treats
relative values as invalid and defines HOME defaults for unset or empty values.
Termcfg rejects relative manager paths with an explicit parameter error; shell
loading skips the affected path and warns without values. Defaults require a
nonempty absolute HOME. Missing, empty or relative HOME is rejected for manager
fallbacks, without consulting account-derived home directories. Explicit absolute
XDG values remain usable. Legacy private-hook candidates are independently
checked: invalid HOME disables legacy lookup even when the selected XDG path is
valid, while an absolute selected hook can still load. Conflict and same-file
selection rules remain unchanged.

Zsh skips invalid plugin paths and initializes fallback completion without reading
or writing a dump cache when its cache path is invalid. With invalid HOME it also
skips its local-bin PATH addition, history-file default and NVM default. Existing
caller PATH, HISTFILE, HOME, XDG and explicit NVM_DIR values remain unchanged by
these guards. Empty NVM_DIR still disables NVM; an explicit relative NVM_DIR warns
and is not sourced, while an absolute value remains usable. Tmux skips TPM when
its effective data path is invalid. Doctor reports XDG states as `absolute`,
`default`, `invalid_relative` or `invalid_home`, without values. An invalid config
path prevents selecting a machine file before doctor can inspect components.

The explicit [terminal environment smoke](../scripts/smoke-termcfg-environment.py)
checks real isolated zsh guards and synthetic tmux shell guards. It never starts
or connects to a tmux server. See [testing](testing.md) for its opt-in command and
the distinction between guard checks and completion initialization evidence.

Zinit, Oh-My-Zsh and z.lua additionally require nonempty absolute HOME, an
absolute effective cache path, and an absolute ZDOTDIR when nonempty. Otherwise
the affected stateful plugins are skipped, with fixed warnings; the base
completion/prompt, absolute selected private hooks and independent plugins can
still load. Relative explicit ZSH_CACHE_DIR disables Zinit and OMZ; relative
ZSH_COMPDUMP disables OMZ; relative _ZL_DATA disables z.lua. Caller HOME, XDG and
ZDOTDIR values are not repaired. Private hook code remains user-controlled and
can perform its own actions.

Fast Syntax Highlighting uses the public FAST_WORK_DIR setting independently:
a nonempty explicit value must be absolute, and an unset/empty value defaults
to `f-sy-h` below the valid effective cache directory. Before loading FSH,
termcfg preserves an existing readable `secondary_theme.zsh` file, including
an empty user file or a user-selected symlink to a readable regular file. The
link and its target are not replaced; directory and dangling theme links skip
FSH. This is not a boundary against malicious changes by the same user. For a missing theme it copies the same installed plugin's
`share/free_theme.zsh` into a private same-directory temporary file, then
publishes it without replacement using GNU `ln -T`. This avoids the upstream
fresh-cache download branch without patching upstream or blocking curl/wget
globally. Preparation failures, invalid paths and non-file theme targets skip FSH and
warn without values. Missing `ln -T` support also skips FSH when a new theme is
needed. An existing readable user theme remains usable and is never
overwritten or described as newly prepared. Platform-specific locked-plugin
loading remains a separate native acceptance scope from synthetic guard tests.

Manager path discovery also uses only the HOME environment value, with no
account-database fallback. A new `termcfg init-local` requires nonempty absolute
HOME before acquiring its operation lease, even when all XDG paths are explicit.
`init-local --edit` retains the saved target HOME and private state root. Explicit
absolute XDG config paths remain usable for diagnostics without a HOME default.
XDG environment values are literal paths: `~/` is relative and rejected, while
dollar characters in a valid absolute path are preserved without expansion.
