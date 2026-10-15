# Testing and support evidence

Tests must distinguish implementation contracts from actual native behavior and authenticated service behavior. A configured CI workflow is not evidence that CI ran; a historical scope closure does not validate a different source or lock.

## Default offline suite

```sh
uv sync --locked
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python scripts/check-public-docs.py
git diff --check
uv --no-config lock --check --offline
```

The default pytest contract uses temporary HOME/DSH_HOME/XDG paths, fictional providers and credentials, blocked network access, and fake subprocesses. It must not launch DSH, Pi, Codex, OMP, or read actual native authentication. Use the prepared repository environment; `agentcfg` does not use `uv run` or unversioned npx.

Filesystem permission checks need the actual user identity and a safe private temporary root. A sandbox that maps root ancestry to another UID can produce artificial failures. Use an exclusive `0700` temporary directory under a safe system temporary root; do not weaken owner, ancestor, symlink, or permission guards to make tests pass.

The public-document check validates maintained Markdown links and selected accidental local-path patterns. It reads repository text only, avoids named credential files and vendor trees, and prints finding locations and categories rather than matched values. It is not a comprehensive secret scan or an external-link validator.

## Separate validation layers

| Layer | What it proves | Required boundary |
| --- | --- | --- |
| Offline unit/contract | Schemas, rendering, field ownership, migration fixtures, conflict/recovery, bounded protocols | Temporary state, fake credentials/processes, network blocked |
| Native no-account | Actual locked packages load, commands register, TUI interaction and persistence work | Explicit isolated entry; no real account imports |
| Native approval/sandbox | Actions execute once or zero times as required; OS restrictions and failure paths work | Temporary workspace, external sentinels, deterministic reviewer; mocks alone insufficient |
| Live account/service | A specific authorized login, model route, short request, and tool result work | Separate account authorization, bounded budget, redacted evidence |
| Rebuild/migration | Same lock reconstructs new state and supported migration/recovery behaves correctly | Distinguish cold downloads from shared warm cache; synthetic old sessions only |

Native test scripts in `scripts/` have distinct purposes and arguments. Inspect their `--help` and the selected integration guide. Do not treat a script's presence, printed fixture status, or npm installation as native acceptance. A source/lock change invalidates affected evidence until rerun.

### Concurrent-run validation

The explicit DSH and Pi checks require a sealed runtime matching the selected
repository lock. They create their own synthetic configuration and new HOME/XDG
directories; never supply a real native account or session directory.

```sh
.venv/bin/python scripts/smoke-dsh-concurrency.py --allow-host --runtime <sealed-dsh-runtime> --evidence <new-private-directory>
.venv/bin/python scripts/smoke-pi-concurrency.py --allow-host --runtime <sealed-pi-default-runtime> --evidence <new-private-directory>
.venv/bin/python scripts/verify-pi.py --tier native --case host-resources --allow-host --runtime <sealed-pi-default-runtime> --output <new-private-report.json>
```

The separate SDK boundary check uses a controlled interaction driver and a simulated
supervisor with the real SDK. It sends no prompts and verifies resource drift,
session preflight, the worker tool registry, and unchanged host methods. It does not
replace the native TUI or OS sandbox checks:

```sh
node scripts/smoke-pi-public-api.mjs --allow-host <sealed-pi-default-runtime> <new-private-report.json>
```

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

Use the repository mock runner for the Pi TypeScript suites; raw `node --test`
does not install the fixture module aliases and is not an equivalent entry point:

```sh
node scripts/test-pi-mock.mjs \
  agents/pi/runtime/tests/*.test.ts \
  agents/pi/packages/task-keeper/tests/agentcfg-*.test.ts \
  agents/pi/packages/task-keeper/tests/request-ledger.test.ts \
  agents/pi/packages/task-keeper/tests/one-shot-schedule.test.ts \
  agents/pi/packages/model-delegate/tests/bridge.test.ts \
  agents/pi/packages/openai-proxy/routing.test.mjs \
  agents/pi/packages/openai-proxy/diagnostics.test.mjs
node --test tests/node/dsh_execution_environment.test.mjs
```

Both commands use synthetic inputs. They establish protocol and boundary
contracts, separately from actual native SDK, TUI and OS sandbox behavior.

The concurrency checks require two live native TUIs, independent native session
or supervisor identities, maintenance refusal while either run is active, clean
exit and terminal restoration. DSH also verifies explicit refusal of a third TUI
resuming an occupied session, then confirms that the original session still
responds. It uses bounded loopback model responses. The Pi
concurrency check sends no prompts; the separate resource test uses a synthetic
model for its guarded-read round trip. Pi's CLI check exercises the native PID
namespace; its resource check also uses the existing outer filesystem sandbox.
Neither test establishes authenticated-provider or concurrent-login safety.

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

CI currently separates Python offline tests, synthetic OMP parser/plugin checks, and explicit Task Keeper mock tests. Mock success does not establish Task Keeper typecheck success; see REVIEW-F02 in [known issues](known-issues.md).
