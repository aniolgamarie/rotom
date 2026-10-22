# Configurable workspace integration preparation — 2026-10-22

This record covers preparation of the configurable workspace implementation on current `main`. It does not record a merge, remote update, deployment, launcher change or native terminal acceptance. The [usage guide](../herdr-workspaces.md) explains the workflow; [feature 006](../../specs/006-configurable-workspaces/spec.md) and its [verification record](../../specs/006-configurable-workspaces/quickstart.md) retain the requirements, decisions and historical execution evidence.

## Candidate and preserved scope

| Item | Identity / result |
| --- | --- |
| Target main | `2d51a1485da5036c410b076cb98c81175aeebcb4` |
| Original feature HEAD | `4cc763da630ae84d9906a7f0a43176629e9f61d7`, plus its reviewed implementation changes |
| Preparation | 50 task-owned files replayed onto current main; no overlap with main's eight changed files since the common base |
| Source / test / contract digest | `57d5f997955d2de445cd8743febe355c4261c9139748f47586fe3355d31070d9` |
| Python lock | `17509e5e00976ea19c683a63433459cbced254d3a7f6aff3a0e787f9462e07c0` |
| Python project input | `6e2a6abcb5f06c1310f74781e497b225bf5fb7ef3857dea29a764f9cb0130e96` |
| Added runtime dependency | `tomlkit==0.15.2`, with its complete locked artifact identity |
| Feature tasks | 70/70 complete; native verification and deployment are recorded separately |

The digest covers 33 changed files: the changed files under `src/`, `tests/`, `schemas/`, and `examples/`, together with `pyproject.toml` and `uv.lock`. For each file, concatenate its sorted repository-relative path, NUL, lowercase SHA-256 and newline, then hash the complete UTF-8 bytes. These files match the original implementation byte-for-byte; before/after-test hashes confirm they remained unchanged during current-main checks. Main's DSH default-profile changes are preserved. No upstream host source, dependency vendor or running process is changed.

The candidate is prepared on current main without importing the three intermediate design-only commits. Repository-local public name/email and `user.useConfigOnly=true` must match both resolved Git identities immediately before committing; author/committer environment overrides must be absent. The [previous integration record](dsh-main-integration-20261021.md#candidate-and-history-boundary) documents approval of the same configured public identity. The original private approval artifact is not re-read during this preparation; no account, authentication or session file is read.

## Current-main checks

| Check | Result |
| --- | --- |
| Affected isolated regression | PASS, exit 0: **1483 passed, 0 failed, 0 skipped** across 47 selected files; pytest 370.28 seconds |
| Offline lock consistency | PASS, exit 0: `uv lock --check --offline --no-python-downloads --python .venv/bin/python --cache-dir <temporary-cache>` |
| Prepared Python environment | Python 3.11.11; installed applicable locked versions match, including tomlkit 0.15.2 |
| Selected public content | PASS: selected final files, local links/anchors and private-identifier/path checks have zero findings |
| Documentation and final difference review | PASS: documentation status/navigation, whitespace and stable replay scope reviewed; final commit binding retained privately |
| Native Herdr / terminal / Agent acceptance | NOT RUN for feature 006 |

The isolated regression uses temporary HOME/XDG, synthetic configuration and credentials, fake processes and the existing network guards. It starts no real Herdr, Agent, editor or model service. Expanded argv, source-input hashes, exit code, timing, JUnit output and raw logs are retained privately. The normalized argv is:

```text
.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider -o tmp_path_retention_policy=failed tests/test_work*.py tests/test_herdr*.py tests/test_config*.py tests/test_execution_environment.py tests/test_execution_environment_runtime.py tests/test_public_docs.py tests/test_dependencies.py --junitxml=<private-evidence>/pytest.xml
```

An attempted fresh offline `uv sync --locked` could not obtain the uncached tomlkit wheel and is not counted as installation acceptance. The newly created empty environment was removed; checks use the existing prepared environment after verifying applicable locked package versions. A first documentation-check invocation used unsupported system Python 3.8 and failed before inspection; the Python 3.11 invocation passed. Neither failure is relabeled as a successful fresh installation or supported Python 3.8 execution.

## Documentation and temporary files

The usage guide, configuration reference, navigation, release notes and known limitations describe implemented behavior. Old design-only status is marked historical; the superseded accumulated design-review draft and constitution's explicitly temporary Sync Impact Report are omitted. Constitution 2.4.0 normative text and the unknown original ratification-date TODO are retained. All 70 task descriptions/completion markers and formal feature evidence remain intact.

Task-owned ignored logs, temporary test HOME data, dependency-check caches and bytecode were archived outside the publication tree with private directory/file permissions, verified against a file manifest, then removed from the original development directory. Prepared environments and original implementation files remain. This cleanup does not remove other development checkouts, credentials, accounts, sessions, launchers or active work. Historical commands in the research record remain historical; their ignored temporary paths are not promised as permanent storage.

## Capability and acceptance boundary

- `machine.work.model = "structured-v1"` explicitly enables templates, bounded project sources and independent named contexts. Legacy configuration remains supported without an automatic conversion.
- Ordinary project/named entry, fixed per-type startup contracts, extra instances, local configuration editing and new-branch worktree creation have isolated contract coverage. A successful simulated handoff does not prove native host loading or a completed business task.
- Mutating whole-workspace close remains unsupported: the pinned public protocol lacks atomic membership protection. Preview is available; actual close exits 5 without dispatch.
- Existing-branch worktree creation remains unsupported: the public Git invocation cannot provide the required atomic reference guarantee. Preview is available; actual creation exits 5 without dispatch. New-branch creation is a separate path.
- Feature 005's prior native, macOS/Ghostty and performance results retain their original scope. They do not validate feature 006. No new terminal, input, clipboard, Agent-account, resource-baseline or cross-platform pass is claimed.

| State | Scope |
| --- | --- |
| Completed | Clean-main replay; feature implementation and prior convergence; temporary-file preservation/cleanup; documentation consolidation; offline lock consistency; 1483 affected isolated checks; stable final review and clean candidate preparation |
| In progress | None in the preparation scope; merging main, deployment and native acceptance are separate actions |
| Failed / pending decision | No implementation decision pending; attempted offline environment creation and unsupported-interpreter check are recorded above |
| Environment insufficient / unverified | Feature 006 native host/client/Agent behavior, production deployment, current native performance and other platforms |

The local executor (`gpt-6.1-sol`, medium) organized documentation; the scout (`gpt-6-luna`, high) independently checked history, identity evidence and dependency scope; the main agent owns replay, cleanup, source preservation and final acceptance. The prepared commit and final target-ref check are bound in private integration evidence once complete.
