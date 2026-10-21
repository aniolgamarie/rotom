# DSH current-main integration acceptance — 2026-10-21

The maintainer authorized local integration after reviewing the [ecosystem implementation](dsh-ecosystem-upgrade-20261021.md). This record covers a fresh candidate based on current clean `main`, not an ordinary merge of the retained development lineage. It records candidate acceptance before the local fast-forward; the resulting commit and ref verification are retained in private integration evidence. It does not authorize a remote push, release, launcher change, or production deployment.

## Candidate and history boundary

| Item | Identity / result |
| --- | --- |
| Target main | `467d5cd4e1cbc72e50c8bf69c6f8233a22d34168` |
| Original implementation base | `b18da6d1df885a81400d721cb46eafdd5c34bb1e` |
| Preparation | Replayed the 51 task-owned changed files onto clean main; no path overlap with main's 109 changes since the original base |
| Runtime/source/test delta digest | `02968c4025d0f91d8faced1a1d1b405fb854e7d16d9fe6fe01491fc4c8ead6c0`; the changed-code digest definition is in the ecosystem record |
| Complete DSH lock | `e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d` |
| Recipe | `76cb4d64f9b225d312f95dd1ef8ffbcf8cc11dc89bfcb221fc4883ebe6b8839f` |
| Runtime | Existing sealed runtime rechecked as `installed`; package/lock identity unchanged |

All 51 replayed files initially matched the accepted implementation byte-for-byte. Subsequent changes only add this record and update maintained acceptance summaries. Runtime code, dependency inputs, own archives, tests and native fixture sources remain unchanged. Main's existing Herdr work, Pi runtime changes and revised Pi fixtures are preserved. Other worktrees and the original development worktree are retained.

The candidate must be committed with current main as its sole parent and integrated by fast-forward. No old parent history is introduced. Repository-local public Git identity, both resolved identities, `user.useConfigOnly=true` and absence of author/committer overrides were checked. Existing private cutover metadata explicitly records approval and matches the exact configured public name/noreply identity; no private authentication or account settings were read.

## Current-main verification

| Check | Result |
| --- | --- |
| Affected Python regression | **975 passed, 0 failed, 0 skipped**, exit 0; 32 files; pytest 684.63 seconds |
| Own DSH extension Node tests | **76 passed, 0 failed, 0 skipped**, exit 0; five files; fresh HOME/XDG and no inherited smoke variables |
| Perry formal/manual/timeout native fixture | PASS, outer exit 0 |
| Teams OFF/ON/new-host-resume/OFF with Perry enabled | PASS, outer exit 0; includes one actual pending lead write reviewed by Perry |
| TUI session resume | PASS, outer exit 0 |
| TUI settings migration | PASS, outer exit 0 |
| Actual agentcfg apply/sync/run → TUI | PASS, outer exit 0 |
| Combined TUI/Perry/Teams status, write, cancel and exit | PASS, outer exit 0 |
| Native reports vs executed source and selected lock | All six reports match |
| Public documentation, selected private-identifier/path checks, staged whitespace and final source review | PASS |

The Python file selection includes all `tests/test_dsh*.py` and the dependency/backend/publication, profile ownership/preparation/recovery, adapter, deployment, runtime/concurrency, execution environment, presentation/readiness, configuration schema/resolution/policy/examples/secret loading, native fixture, rendering and public-docs contracts. The default guards still block network and real host processes. The actual argv is retained privately in full; its public form is:

```text
.venv/bin/python -m pytest -q --tb=short -o tmp_path_retention_policy=failed tests/<32 selected files> --basetemp <private-system-temporary-root>
node --test tests/node/dsh_*.test.mjs
.venv/bin/python scripts/check-public-docs.py
```

The six native commands reuse the ecosystem record's explicit `--allow-host` invocations on this current-main candidate. They use unmodified sealed packages, temporary HOME/DSH/XDG, synthetic state, deterministic models and a loopback fake HTTP model where needed. No real accounts, live model services or daily deployment are used. Exact argv, exit codes, source hashes and result files are private evidence; selected package identity and test/fixture scope remain in the public records.

### Original seven Pi fixture failures

The original development-base run produced 354 passed and seven pre-existing Pi fixture failures, independently reproduced on that old base. Current target main already updates the incomplete fixture and its obsolete reserved-variable assertions in `tests/test_execution_environment_runtime.py`. This integration preserves those revisions and reruns the current tests successfully. The original failed run remains historical evidence; it is not relabeled as a pass. No Pi source or fixture fix is added by the DSH integration.

## Final scope and status

| State | Scope |
| --- | --- |
| Completed | Clean-main replay; affected offline and six native groups; lock/runtime/source/identity/privacy review; candidate prepared for the authorized local fast-forward |
| In progress | None in implementation or acceptance |
| Failed / pending decision | None in the current-main selected checks |
| Environment insufficient / unverified | Real accounts, external model/network services, other platforms and terminal/SSH/tmux clients; historical Perry OFF/late-approval and durable-audit properties; Teams crash/multiple-writer recovery |
| Explicitly deferred | Daily-entry restoration: unsupported Pi `discovery.project_trust` still requires a separately reviewed configuration decision |

The merge changes repository code only. It neither syncs/applies the new recipe to a daily instance nor retargets an existing launcher. Account/session state and active processes are unchanged. Execution used the configured executor (`gpt-6.1-sol`, medium) for isolated checks, scout (`gpt-6-luna`, high) for independent history/identity/source evidence, and main-agent integration and native acceptance. No upstream patch or private host API was used.
