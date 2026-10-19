# Testing and support evidence

Tests must distinguish implementation contracts from actual native behavior and authenticated service behavior. A configured CI workflow is not evidence that CI ran; a historical scope closure does not validate a different source or lock.

The Core `0.2.1-rc.2` / fixed TUI main candidate has a separate [acceptance record](acceptance/dsh-rc21-tui-main-20261017.json). Its source build, frozen install and public module checks do not replace real TUI, account or platform smoke. Existing Perry safety limitations remain open. The later SSH/plugin worktree has its own [implementation record](acceptance/dsh-ssh-implementation-20261017.json); [SSH usage](dsh-ssh.md) describes its deliberately narrower headless boundary.

## Default offline suite

```sh
uv sync --locked
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python scripts/check-public-docs.py
git diff --check
uv --no-config lock --check --offline
```

The default pytest contract uses temporary HOME/DSH_HOME/XDG paths, fictional providers and credentials, blocked network access, and fake subprocesses. It must not launch DSH, Pi, Codex, OMP, or read actual native authentication. Use the prepared repository environment; `agentcfg` does not use `uv run` or unversioned npx.

HOME discovery contracts use unset, empty and relative HOME with absolute
synthetic XDG paths, and replace `Path.home()` with a failure sentinel. Invalid
CLI defaults and shared-key defaults must fail before configuration/credential
reads; new termcfg selection must fail before entering its write lease. Explicit
absolute config/secret selection and saved termcfg edit targets remain usable.
Nonempty XDG environment paths are literal absolutes: `~/.config` is invalid,
while `$literal` inside an absolute path is not interpolated. Explicit TOML
secret paths retain their separate configured `~/` syntax.
The CLI `~/child/../target` test checks delegation to the existing private-directory
guard; it does not substitute for the controlled filesystem suite's actual
no-follow and ownership evidence.

Filesystem permission checks need the actual user identity and a safe private temporary root. An executor whose filesystem root has an unsupported owner is rejected with the fixed, redacted `unsupported-root-owner` diagnostic (exit 4). Read-only mounts do not establish trusted ownership. Changing `TMPDIR` cannot repair a shared unsupported root ancestor. Use an exclusive `0700` temporary directory under a safe system temporary root in a supported execution environment; do not weaken owner, ancestor, symlink, or permission guards to make tests pass.

`tests/test_paths.py` first proves a normal private-directory create/open/write baseline before running filesystem guards. If root ownership is unsupported, those cases are explicitly skipped as NOT RUN, and their native boundary evidence remains BLOCKED. Independent classification/propagation unit tests can still run; mocked ownership is not native sandbox evidence.

The public-document check validates maintained Markdown links and selected accidental local-path patterns. It reads repository text only, avoids named credential files and vendor trees, and prints finding locations and categories rather than matched values. It is not a comprehensive secret scan or an external-link validator.

### Controlled Linux offline executor

A supported Linux user-namespace executor can run the offline suite without
relaxing Rotom's private-path checks:

```sh
.venv/bin/python scripts/test-sandboxed.py --help
.venv/bin/python scripts/test-sandboxed.py --allow-sandbox --venv <absolute-prepared-venv> --evidence <new-absolute-private-directory>
.venv/bin/python scripts/test-sandboxed.py --allow-sandbox --suite filesystem --venv <absolute-prepared-venv> --evidence <another-new-absolute-private-directory>
```

This explicit entry requires `/usr/bin/bwrap` and an already prepared Python
3.11+ environment with a conventional `bin/python` and corresponding
`lib/pythonX.Y` or `lib64/pythonX.Y` standard library distribution. Unsafe broad
bindings, including account HOME directories and non-system source ancestors,
are rejected without expanding the distribution to a parent directory. It
copies only Git-tracked regular working-tree files into a private snapshot; add new files to Git's index before acceptance. It does not
clone, download or install anything. The snapshot and selected venv/interpreter
distribution are mounted read-only, with no host HOME or Git metadata mounted.
The venv remains at its original absolute location, and the snapshot contains a
synthetic `.venv` link to it so entry/temporary-venv tests retain their contract.
An explicitly selected venv or distribution may be a HOME child directory;
only that exact subtree is mounted, never its HOME parent or account/session
siblings. Layout checks do not prove a selected tree contains only tool inputs:
select dedicated public tool environments, without mixed authentication or
session data. The entry does not scan private sibling directories.
Only a new evidence output directory and isolated temporary filesystem are
writable; the snapshot has no writable alias inside the executor. User, PID,
network, IPC and UTS namespaces are isolated, capabilities are dropped, root and
proc are read-only, and the process environment is rebuilt from fixed synthetic
values (also on bwrap versions without `--clearenv`).

A bounded real baseline first checks private create/read modes, symlink/hardlink
refusal, read-only mounts and blocked networking. Baseline or executor failure
records BLOCKED and exits nonzero without running pytest. A passing baseline
starts the fixed offline pytest command in a fresh executor, with a short
`/tmp` test root and a two-hour timeout. The default `--suite full` runs the
complete suite. `--suite filesystem` runs
only `tests/test_paths.py` and `tests/test_execution_environment.py` for the real
filesystem and rendering boundary checks; neither selection accepts arbitrary
pytest or host arguments. The report records the selection. Pytest failures
remain FAIL; skipped cases retain their own limitations. Default pytest only mocks this entry's
process and argument contracts and never starts bwrap. Entry tests may still
launch their narrowly allowed synthetic Python subprocesses inside the executor;
no third-party agent hosts or terminal-native smoke is enabled.

Keep the new `0700` evidence directory private. Its `0600` report records the
source manifest, lock hashes, interpreter identity, exact argv and stage exit
codes, alongside private raw logs and pytest XML. Each attempted stage records
its argv before launch; timeout/interruption keeps a BLOCKED record with no
exit code instead of reporting success. Raw evidence can contain host
paths and must not be published. Unsupported user namespaces or outer sandbox
permissions require a supported outer executor; the entry never escalates,
disables isolation or weakens ownership checks automatically. A controlled
executor PASS does not establish support in the original unsupported namespace,
other platforms, real agent hosts or authenticated services.

## Separate validation layers

| Layer | What it proves | Required boundary |
| --- | --- | --- |
| Offline unit/contract | Schemas, rendering, field ownership, migration fixtures, conflict/recovery, bounded protocols | Temporary state, fake credentials/processes, network blocked |
| Native no-account | Actual locked packages load, commands register, TUI interaction and persistence work | Explicit isolated entry; no real account imports |
| Native approval/sandbox | Actions execute once or zero times as required; OS restrictions and failure paths work | Temporary workspace, external sentinels, deterministic reviewer; mocks alone insufficient |
| Live account/service | A specific authorized login, model route, short request, and tool result work | Separate account authorization, bounded budget, redacted evidence |
| Rebuild/migration | Same lock reconstructs new state and supported migration/recovery behaves correctly | Distinguish cold downloads from shared warm cache; synthetic old sessions only |

Native test scripts in `scripts/` have distinct purposes and arguments. Inspect their `--help` and the selected integration guide. Do not treat a script's presence, printed fixture status, or npm installation as native acceptance. A source/lock change invalidates affected evidence until rerun.

### Terminal environment validation

Inspect the explicit entry before running it:

```sh
.venv/bin/python scripts/smoke-termcfg-environment.py --help
.venv/bin/python scripts/smoke-termcfg-environment.py --allow-terminal --evidence <new-absolute-private-directory>
```

This separate opt-in entry launches real zsh and sh with synthetic HOME, ZDOTDIR
and XDG discovery paths, a minimal PATH, no inherited account environment and
bounded child timeouts. Invalid HOME cases start with a safe temporary HOME,
then unset or change it inside the test shell before explicitly sourcing the
repository files. It tests repeated loading, XDG combinations, HOME fallbacks,
private-hook conflicts and same-file selection, and NVM defaults/overrides.
Additional synthetic plugin fixtures verify stateful loading guards, separate
FSH working paths, fresh-theme publication, unchanged existing/empty themes
and readable user theme links (both link and target),
invalid/failed theme preparation, concurrent no-overwrite publication, and zero
curl/wget attempts. Download counters are checked independently of shell exit
status. These fixture entries are not the locked upstream plugins; the report
marks locked-plugin acceptance NOT RUN.
All fixtures live beneath the new private evidence directory and are removed at
the end. Reports contain fixed results and repository-relative source digests,
without private paths or captured shell bodies. The tmux portion executes the
configuration's shell guards with synthetic tmux/TPM commands; it never starts or
connects to a real tmux server. Default pytest only tests the entry's opt-in and
reporting contracts without starting terminal programs.

Guard PASS does not establish completion functionality: each zsh case separately
records `completion_initialization` as READY or NOT VERIFIED from the initialized
completion table and function. An executor can pass path guards while its system
completion directories fail compaudit; this entry does not bypass that check or
claim interactive completion, plugin-native, tmux-server or other-platform
acceptance. Relative XDG values and unset/empty defaults follow the
[XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/);
termcfg additionally requires a nonempty absolute HOME before forming its HOME
defaults and does not replace caller variables.

### Concurrent-run validation

The explicit DSH check requires a sealed runtime matching the selected repository lock.
It creates synthetic configuration and a new HOME/XDG; never supply a real account or session directory.

```sh
.venv/bin/python scripts/smoke-dsh-concurrency.py --allow-host --runtime <sealed-dsh-runtime> --evidence <new-private-directory>
```

Pi's retired SDK, supervisor and public-API smoke runners are no longer distributed.
Use the current [Pi quickstart](../specs/005-rebuild-pi-toolkit/quickstart.md) for separate
isolated, dependency-only, native and account gates. Native startup needs independent authorization.
Without a production complete-release observer, Pi manager exit leaves its run unknown and blocks
exclusive maintenance; historical concurrency checks do not close this limit.

### Development-environment validation

The DSH environment entry loads the locked public subprocess extension in the real
host and renders its synthetic stdio MCP configuration through the normal adapter.
It observes ordinary and PTY children, the standard Bash tool, MCP assignment and
deletion, and removal of synthetic manager credential variables. An external
sentinel checks that the original workspace-write sandbox still rejects writes.
It makes no model requests and does not import accounts:

```sh
.venv/bin/python scripts/smoke-dsh-environment.py --allow-host --runtime <sealed-dsh-runtime> --evidence <new-private-directory>
```

The synthetic DSH execution test remains independent of native-host validation:

```sh
node --test tests/node/dsh_execution_environment.test.mjs
```

The Pi Task Keeper/SDK mock runner and its dedicated fixtures were retired together with that
execution platform. Current Pi isolation uses `tests/test_pi_reboot_configuration.py`,
`tests/test_pi_reboot_dependencies.py`, `tests/test_pi_reboot_runtime.py`,
`tests/test_pi_reboot_pipeline.py` and `tests/test_pi_retirement.py`.
They use temporary state and fake processes; they do not establish authenticated-provider or
native TUI safety. DSH concurrency still requires two live native TUIs, maintenance refusal,
occupied-session refusal, clean exit and terminal restoration under its separate authorized scope.

Large source/asset fixtures can consume substantial temporary storage. To remove
passed pytest fixtures after each case while retaining failures, add
`-o tmp_path_retention_policy=failed -o tmp_path_retention_count=1`. Keep private logs
outside pytest's temporary fixture root. Keep explicit `--basetemp` paths short
for Unix-domain socket fixtures; a long test prefix can exceed the existing socket
path limit before any operation starts. Current results and limitations belong to
the single [refactoring record](design/project-refactoring.md).

## Release-preparation results

The baseline review of `66ad5e4` ran the full Linux x86_64 offline suite: **3602 passed, 1 failed, 9 skipped, 7 subtests passed**. The sole failure was the obsolete OMP artifact count. The narrow code fix then passed **136 tests** across dependency, OMP foundation, and project-role suites. Final results for the prepared snapshot are recorded in [release verification](release-verification.md).

The checked-in DSH and OMP locks were readable at that baseline. Pi's lock was internally identifiable but stale against source at the time. The subsequent [refactoring record](design/project-refactoring.md) records its complete rebuild and matching validation separately. Default fixtures construct synthetic locks, so a passing suite does not by itself prove every checked-in runtime lock is current.

## Historical support summary

- **DSH:** Linux no-account TUI, simulated-model native interaction, OS sandbox checks, and selected approval-chain cases were previously run. Perry's overall safety gate failed on late approval, OFF persistence, audit persistence, and incomplete reviewer-boundary proof. These limitations remain accepted in the enabled recipe.
- **OMP:** Official Linux x64 host, independent plugin, and limited historical Cursor/reviewer calls have evidence for their specific candidates. Other platforms and provider-specific login/usage remain separate work.
- **Pi:** Candidate lock `9d6a9270…` passed its narrowed historical Linux software scope (81 cases). It does not establish current native/cold acceptance or current lock validity.
- **termcfg:** Configuration and transaction behavior has isolated tests; component-native and platform claims must retain their own execution scope.

Raw dated machine reports were retired from the public tree during documentation cleanup. These summaries preserve conclusions and limits; they do not claim the retired evidence is reproducible from the current public snapshot or silently transfer its hashes. Project specifications and necessary provenance remain.

## Recording new evidence

Record the exact command and exit code, source commit/digest, configuration and lock identity, platform/architecture category, cache sharing, sanitized log location, and PASS/FAIL/BLOCKED/NOT RUN status. Avoid kernel hostnames, personal usernames, business paths, tokens, secret bodies, or authentication URLs. Keep raw output private or ignored and review it before publication.

CI separates Python offline tests from synthetic OMP parser/plugin checks. The retired Task Keeper mock job is absent; its historical results are not current Pi acceptance.
