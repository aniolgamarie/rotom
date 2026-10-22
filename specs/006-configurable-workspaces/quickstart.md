# Quickstart and validation

This guide records implemented [feature 006](spec.md), executed isolated checks and a separately authorized future native recipe. Structured commands and test fixtures exist. Native hosts, real accounts, deployment, primary entry switching, commits and merging were not performed. Use temporary configuration for checks; the [usage guide](../../docs/herdr-workspaces.md) explains current behavior. Guarded Herdr close and existing-branch Git creation refuse before dispatch because the examined public interfaces lack the required guards.

## Run isolated verification

Use Python >=3.11 and the already prepared repository `.venv`; do not replace the system interpreter or install dependencies as part of checking. The test suite supplies blocked-network guards, fake native/host fixtures and sentinels. Synthetic Git tests admit only an explicit Git executable and bounded commands inside temporary repositories. Fake executable names in the [complete TOML example](contracts/configuration.md#complete-illustrative-document) are fixture inputs, not installed hosts.

The following shell block runs the isolated test fixtures. Run both shell blocks below sequentially in the same dedicated shell, retaining it while preparing the intervening fixtures. The EXIT trap cleans the sandbox only when that shell exits after the entire acceptance sequence, not at a Markdown block boundary. It creates a temporary HOME/XDG sandbox and runs isolated pytest coverage; it does not invoke any third-party host. Tests must enforce their own network blocking and fake-dispatch boundaries rather than relying on HOME isolation alone.

```sh
set -eu
trial_root=$(mktemp -d)
trap 'rm -rf -- "$trial_root"' EXIT
export HOME="$trial_root/home"
export XDG_CONFIG_HOME="$trial_root/config"
export XDG_DATA_HOME="$trial_root/data"
export XDG_STATE_HOME="$trial_root/state"
export XDG_CACHE_HOME="$trial_root/cache"
export DSH_HOME="$trial_root/dsh"
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$DSH_HOME"
.venv/bin/python -m pytest tests/test_work_projects.py tests/test_work_config_edit.py tests/test_work_templates.py tests/test_work_lifecycle.py
```

Record actual argv, exit code and sanitized logs for the implementation candidate. Then run affected existing `test_work*.py` and `herdr_api` tests selected from the repository test inventory; those protect existing launch handoff, identity and strict API behavior. The execution log records the exact selected modules. No new long-duration benchmark or exact Python patch-version gate is required by this document.

## Exercise the common configuration contract

In that same shell, copy the complete example into `$trial_root/local.toml` with mode `0600`; substitute temporary existing directories for `/projects`, `/cases` and `/cases/current`. Prepare `$trial_root/extra` and the referenced case directories before the next block. Create synthetic Git repositories, a `.git`-file worktree fixture, non-Git children, nested children, hidden/excluded names, symlinks and a hook sentinel under the trial root. Use fake Herdr/editor/Agent dispatch and fake selected-endpoint replies. Use a fixture-controlled launcher root for built-in candidate checks. Never read a real account, authentication or session file.

With the existing `work` entry and temporary fixtures above, the following are representative non-host CLI checks. They assume the full example's templates and a fixture-created local TOML at the shown sandbox path. These commands are implemented; fixture executable names are not prepared third-party hosts.

```sh
work --local "$trial_root/local.toml" config check
work --local "$trial_root/local.toml" list --json
work --local "$trial_root/local.toml" source add --id extra --path "$trial_root/extra" --mode directory --template dev5 --depth 1 --dry-run
work --local "$trial_root/local.toml" project add --path "$trial_root/cases/current" --mode directory --template investigation3 --dry-run
work --local "$trial_root/local.toml" named add --id investigation-third --title "Third investigation" --template investigation3 --dry-run
work --local "$trial_root/local.toml" named rename investigation-main --title "Renamed investigation" --dry-run
```

Use byte/sentinel comparisons to prove dry run creates no configuration changes, new lock files or operation receipts. Repeat CLI saves, equivalent selector saves with fake fzf, and manual TOML edits; compare canonical candidates and ensure compatible repeats are byte-idempotent. Save is separate from entry. Validate strict unknown-field rejection at every object, the opt-in boundary, invalid references/order/initial, depth bounds, exclusions, symlink containment/cycles and explicit-entry/source/built-in precedence. Disabled built-in inclusion without an explicit template must not require an implicit default template. Invalid structured input must not fall back to legacy behavior.

`work config edit` testing uses a fake single-executable editor on only the work fragment. Verify preserved unrelated content/comments/permissions, invalid-edit refusal, cooperating lock serialization and refusal of observed outside edits. Test direct manual editing between saves. Do not claim exclusion against arbitrary lock-ignoring editors during the final replacement window. No secret-bearing whole-file copies, digests or generic backups may appear in fixtures or outputs.

## Exercise lifecycle through fake public APIs

| Scenario | Required isolated evidence |
| --- | --- |
| Initial entry and reuse | One initial `shell` for dev5 or one `problem` for investigation3; no other initial types. Focus sends no commands and does not launch again. |
| Stable identities | Two checkouts of one repository and two named IDs at shared HOME stay independent; rename changes title without changing binding. |
| Type instances | Every type supports extras; extras never replace or become the default, including when created first. Later plain open creates the default with the same fixed cwd/launcher. Runtime `cd` does not alter that binding. `problem1/2/3` are one type's instances. |
| Configuration drift | Uninstantiated types use new config; existing verified instances stay focusable; contradictory creation fails; rebind requires proven zero active instances and explicit acceptance. Unused editor/Agent preparation is not required. |
| Unknown outcome | Concurrent creators, timeout after mutation and stale/missing markers cause reconciliation before new creation; status/reconcile query only, never retry or clean up. Opened/unknown is not displayed as closed without evidence. |
| Worktree creation | New/local-existing branch alternatives, ref drift, destination/occupancy races and missing coverage fail safely. `post-checkout` sentinel stays untouched, executable checkout filters cause refusal and persistent Git config stays unchanged. |
| Partial success | A separately saved source survives cancellation; successful checkout survives failed entry; Git partial/unknown results are reported without cleanup or blind replay. |
| Close on 0.9.5 | Preview lists exact members and client effects. Every mutation attempt, even confirmed with matching token, returns 5 and records zero close requests. Scope drift returns 4. No group/pane substitute occurs. |
| Compatibility | Legacy configuration/state remain untouched; invalid structured input fails; no automatic migration/adoption/ungroup/restart occurs. |

For CLI completeness, test explicit actions with no fzf installed and missing required arguments with no interactive input. Test Unicode and space-containing paths/titles as literal data. Verify pass-through exits for direct terminal/Agent/attach exec with fakes. For `config edit`, verify editor failure preserves its failure exit and publishes nothing, while editor success followed by manager validation/conflict/publication failure returns 2/4/6 respectively rather than success. Exit the dedicated shell only after the full sequence to trigger sandbox cleanup.

## Separately authorized native acceptance

Actual Herdr/Pi/DSH/Codex/editor execution requires later explicit authorization, implementation and exact dependency/API admission. Keep trial configuration/session separate from active work; do not switch the primary entry or adopt native layouts. Record candidate and lock identities, platform category, actual argv, exit codes and sanitized evidence under the repository publication/worktree gates.

Native acceptance then covers the changed ordinary-workspace initial handoff, endpoint/pane identity, independent same-repository workspaces, focus/extras/reconnect and actual selector/terminal behavior on each claimed platform. Test only deliberately selected/prepared launchers; real accounts or model calls need their own authorization. On examined Herdr 0.9.5, successful guarded close remains unavailable: verify refusal with zero close calls, and report the capability limitation. A future public atomic guard requires new exact-version review and acceptance before enabling close. Historical feature 005 results and fake API checks do not establish these native results.

## Task state

| State | Scope |
| --- | --- |
| Completed | Dependency/source admission, structured CLI/config/discovery/entry/type implementation, new-branch Git creation, close preview/refusal, legacy regression and isolated dataset |
| In progress | None within the implementation checklist |
| Failed, pending decision | None within this document package |
| Environment insufficient / unverified | Actual changed Herdr/client/Agent execution, deployment and other platforms. Successful guarded close and existing-branch creation are unavailable on the examined public capabilities; refusal is tested, success is not claimed. |

## Implementation execution log

T005 test-first command `.venv/bin/python -m pytest tests/test_herdr_api.py -q -k 'structured or v2'` exited 1 as expected before adapter implementation: 7 failed (new create/rename capability, payload stripping and admission absent), 4 passed, 26 deselected. This is a captured initial failure, not a verification pass. All replies/processes were fake and HOME/XDG temporary.

T004 final affected legacy command: `.venv/bin/python -m pytest tests/test_work_config.py tests/test_work_entry.py tests/test_work_launch.py tests/test_work_context.py tests/test_work_identity.py tests/test_work_recovery.py tests/test_work_tools.py tests/test_work_roles.py tests/test_work_shell_fallback.py tests/test_work_client_contract.py tests/test_work_review_boundary.py tests/test_work_metadata.py tests/test_work_optional_status.py tests/test_herdr_api.py -q -k 'not structured and not v2'`: exit 0, 169 passed/11 deselected. Sandbox ancestor UID mapping had caused 20 path-precondition failures; exact isolated tests passed under the trusted host ancestor view without changing protection. HOME/XDG/network/process guards remained active. An earlier invocation named a nonexistent locking test module and exited 4 before collection; it supplies no test evidence.

T006 test-first structure/literal failures and depth=1.0 parity failures were observed before implementation. Final `.venv/bin/python -m pytest -q tests/test_work_config.py tests/test_work_tools.py tests/test_config_secret_loading.py tests/test_config_schema.py`: exit 0, 261 passed. Additional depth parity subset: 9 passed. These checks used trusted ancestor execution with isolated HOME/XDG, blocked network and fake hosts; they certify configuration/secret-separation behavior only.

T007 `.venv/bin/python -m pytest tests/test_work_state.py -q --tb=short`: initial exit 1 (16 missing-module failures), then exit 0 (16 passed) after implementation. Covers read-only absence, canonical endpoint namespaces, generation drift, strict/private state, immutable single pending intent, commit ordering, durable-registration compaction, malformed/orphan receipts and unsafe/oversized files. No native endpoint was opened. A temporary structured-mode guard prevents partially implemented routing from falling through to legacy mutations during development.

T007 independent executor review found three substantive state issues; five reproductions failed first, then all 21 state tests passed after fixed-contract protection, immutable-intent/receipt identity checks and bounded malformed-JSON classification. T008 core API tests passed 37; startup-evidence test-first failures were captured. Final `.venv/bin/python -m pytest tests/test_herdr_api.py tests/test_work_state.py tests/test_work_entry.py -q --tb=short`: exit 0, 82 passed. Startup observation uses Linux same-user socket peer PID, process start/executable identity and separately recorded disk/config/source/server inputs; no read-only effective-config capability or detection-based lifecycle authority is claimed. Parent integration follows in T011, and changed native execution remains unverified.

T009 test-first payload cases initially failed 36, launch preparation cases initially failed 34. After implementation, `.venv/bin/python -m pytest tests/test_work_launch_prepare.py tests/test_work_payload_v2.py tests/test_work_state.py tests/test_work_tools.py tests/test_work_launch.py tests/test_work_config.py -q --tb=short`: exit 0, 256 passed. Coverage includes all five initial launchers, bounded strict envelope, deadlines, literal/fixed cwd and captured HOME/XDG, explicit managed profiles/runtime identity and unchanged v1 entry. No executable was launched by these preparation tests.

T010 test-first wrapper cases initially failed 12. Independent executor review then identified two accepted-to-exec windows; both were reproduced and repaired with final current-membership/deadline checks that tolerate already-completed parent pending bookkeeping. `.venv/bin/python -m pytest tests/test_work_wrapper_v2.py tests/test_work_shell_fallback.py tests/test_work_launch.py tests/test_work_payload_v2.py -q --tb=short`: exit 0, 85 passed. Wrapper performs no private writes or parent lock acquisition; tests cover one-use replay refusal, wrong intent/source/member, commit durability, expired uncommitted launch, exec failure, lost accepted/failure reports and no v2 fallback. Accepted marks handoff authorization, not task completion or proof a program will keep running; known failed metadata is never a successful launch proof.

T011 parent initial/tab handoff, durable commit/registration and lost-reply tests passed. Independent review reproduced a stale type draft creating an additional accepted default before refusal; full persisted TypeBinding equality is now required before intent publication. Final `.venv/bin/python -m pytest tests/test_work_parent_v2.py tests/test_work_state.py tests/test_work_wrapper_v2.py tests/test_work_entry.py tests/test_herdr_api.py -q --tb=short`: exit 0, 124 passed. These are isolated fake-native results, not host acceptance. T013 initial `.venv/bin/python -m pytest tests/test_work_config_edit.py -q --tb=short`: expected exit 1, 13 missing-module failures before implementation.

T012–T023 US1: initial discovery tests failed for missing module, editor tests failed 13 before implementation, CLI tests failed 6 before routing. Final `.venv/bin/python -m pytest tests/test_work_projects.py tests/test_work_config_edit.py tests/test_work_cli.py -q --tb=short`: exit 0, 62 passed. CLI, standalone work-fragment editor, manual declarations and fake selector all share the strict validator and one TOML; config saves preserve comments/unrelated bytes, compatible repeats do not rewrite, observed external edits refuse, and post-replace fsync failure reports uncertainty without rollback. Unsafe save errors expose only the proposed non-secret manual work fragment. Discovered oversized-editor cleanup read was replaced with metadata-only deletion. No native host/fzf/editor was executed and no deployment occurred.

T024–T033 US2: context tests exposed reused terminal identity and verified-workspace lookup gaps; both now refuse before control. CLI initial failures (3) covered missing enter/report routing. Final `.venv/bin/python -m pytest tests/test_work_lifecycle.py tests/test_work_cli.py tests/test_work_identity.py tests/test_work_context.py tests/test_work_entry.py tests/test_work_launch.py tests/test_work_recovery.py -q --tb=short`: exit 0, 89 passed. Explicit named/project identity, arbitrary initial launcher, canonical socket aliases, fixed starts, read-only reports, preserved saved title and initial lost-reply no-replay were tested with fakes. No native execution or platform pass is claimed.

T034–T042 US3: lifecycle test-first run failed 6 for missing open/rebind helpers; independent template tests landed after the shared implementation and have no claimed red evidence. Fixed proven-absent default registration to retire its old minimal reference before replacement, retaining moved native panes untouched. Final `.venv/bin/python -m pytest tests/test_work_templates.py tests/test_work_lifecycle.py tests/test_work_cli.py tests/test_work_roles.py tests/test_work_tools.py tests/test_work_shell_fallback.py tests/test_work_optional_status.py tests/test_work_metadata.py -q --tb=short`: exit 0, 110 passed. Includes all launchers/defaults/extras, extra-before-default, frozen cwd/HOME, focus without preparation, removed/drifted types, explicit inactive rebind, unowned native panes and six source-tamper parent/wrapper cases. Selector type/rebind actions still require current native proof; no Agent state grants lifecycle authority.

At an intermediate US4 checkpoint, implementation found an upstream capability conflict under real synthetic Git 2.43.5: deleting a reviewed existing local branch just before worktree add can trigger same-name remote fallback despite --no-guess-remote. At that checkpoint existing-branch dispatch was temporarily refused with code 5 pending capability refinement; its original success/race expectations were recorded as failing, not passing. The later T050 entry records the resolved conservative boundary and updated refusal tests. New-branch mode uses a resolved local commit and does not have this ambiguity. The combined Git/CLI command at that intermediate checkpoint was: `.venv/bin/python -m pytest tests/test_work_git.py tests/test_work_cli.py -q --tb=short`: exit 1, 37 passed / 2 known existing-branch gate failures. Both disk-configuration-drift tests pass after mandatory non-secret re-read. No live repository or remote was touched.

While that decision is pending, independent US5/US6 paths were verified: `.venv/bin/python -m pytest tests/test_work_lifecycle.py tests/test_work_cli.py tests/test_herdr_api.py -q --tb=short -k 'not worktree'`: exit 0, 99 passed / 6 deselected. `.venv/bin/python -m pytest tests/test_work_config.py tests/test_work_entry.py tests/test_work_lifecycle.py tests/test_work_cli.py tests/test_work_client_contract.py tests/test_work_review_boundary.py -q --tb=short`: exit 0, 174 passed. Close scope/refusal makes zero close calls; legacy-group/account sentinels and explicit opt-in remain intact. Documentation completion and final aggregate verification are still in progress.

### T050/T055/T059/T060 checkpoints

After documenting the examined existing-branch capability refusal (not relaxing no-remote-guessing), `.venv/bin/python -m pytest tests/test_work_git.py tests/test_work_cli.py tests/test_work_lifecycle.py tests/test_herdr_api.py -q --tb=short` exited 0: 132 passed. Git 2.43.5 synthetic tests include new-branch dirty/index/config preservation, empty hooks, filter refusal, reviewed config drift, source-directory replacement at dispatch, timeout after applied creation and zero existing-branch dispatch. Normalized mutation argv is `GIT -c core.hooksPath=PRIVATE_EMPTY -c core.fsmonitor=false -c worktree.guessRemote=false -c submodule.recurse=false -C /proc/self/fd/REPO_FD worktree add --no-guess-remote -b BRANCH -- DEST REVIEWED_COMMIT`; actual execution used an inherited pinned directory FD, not the normalized placeholder. No persistent Git config was changed.

The seven-context/30-terminal/ten-cycle dataset initially exposed nondeterministic re-entry choosing an extra by UUID order. Default-first selection repaired it; `.venv/bin/python -m pytest tests/test_work_lifecycle.py -q --tb=short -k 'seven_contexts or identity_conflicts'`: exit 0, 4 passed / 22 deselected. The completed suite retains unknown cases and never promotes extras. Further UI cancellation and three-entrance parity cases passed 10 (28 deselected). An added named-array rename case reproduced comment loss; incremental table-array merge repaired it. `.venv/bin/python -m pytest tests/test_work_config_edit.py tests/test_work_git.py tests/test_work_cli.py tests/test_work_parent_v2.py tests/test_work_wrapper_v2.py -q --tb=short`: exit 0, 113 passed after that final source correction.

## T061 aggregate execution identity

The aggregate command `.venv/bin/python -m pytest tests/test_work*.py tests/test_herdr_api.py tests/test_config_secret_loading.py tests/test_config_schema.py -q --tb=short` exited 0: **685 passed in 125.97 seconds**. The shell glob expanded to the following 24 work modules; the other three files and final options were literal argv. A later named-array comment-preservation fix and early unsupported directory-pinning refusal were verified by the 113-test affected command above; no later runtime code change is claimed.

```text
tests/test_work_cli.py
tests/test_work_client_contract.py
tests/test_work_config.py
tests/test_work_config_edit.py
tests/test_work_context.py
tests/test_work_entry.py
tests/test_work_git.py
tests/test_work_identity.py
tests/test_work_launch.py
tests/test_work_launch_prepare.py
tests/test_work_lifecycle.py
tests/test_work_metadata.py
tests/test_work_optional_status.py
tests/test_work_parent_v2.py
tests/test_work_payload_v2.py
tests/test_work_projects.py
tests/test_work_recovery.py
tests/test_work_review_boundary.py
tests/test_work_roles.py
tests/test_work_shell_fallback.py
tests/test_work_state.py
tests/test_work_templates.py
tests/test_work_tools.py
tests/test_work_wrapper_v2.py
```

Candidate: uncommitted changes on `design/configurable-workspaces`, based on `4cc763da630ae84d9906a7f0a43176629e9f61d7`; this is not a clean commit or merge claim. Runtime observed: Python 3.11.11 (minimum >=3.11), synthetic Git `/usr/bin/git` 2.43.5 (admission >=2.36). Native fixture: Herdr v0.9.5, source commit `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`, protocol 22. fzf 0.74.5 was source-reviewed and fake-tested only. No real Herdr/editor/Agent/fzf or account was launched. The existing constitution modification, active-feature selector and reviewer checklist remain outside implementation ownership.

| Public input | SHA-256 at completed runtime writes |
| --- | --- |
| `uv.lock` | `17509e5e00976ea19c683a63433459cbced254d3a7f6aff3a0e787f9462e07c0` |
| `pyproject.toml` | `6e2a6abcb5f06c1310f74781e497b225bf5fb7ef3857dea29a764f9cb0130e96` |
| v2 fixture provenance | `54088017d70f96be28c740f87efd32081ac9a7b630bacb8b2c3b43c2aa517c3f` |
| launch-source manifest | `6bc38d03649095050fb175862836f5fbc455e6f64810358290251c58a37f85a5` |

## T063 native acceptance recipe — prepared, not executed

This recipe needs a later explicit authorization for actual changed host execution. Real accounts/model calls, deployment and switching the primary entry require their own scope. Use the single available Linux server only, a separate trial session/configuration, disposable project directories and prepared official binaries. Do not stop/reload/adopt a running production server to create evidence. Servers without protected startup observations refuse managed creation; select a fresh trial session rather than stamping an existing one.

Before execution, record exact Linux distribution/kernel/architecture, filesystem category (local/network), shell/prompt identity, SSH client and client terminal version, binary path+release+asset integrity, running-server process/version/protocol, configuration load diagnostics+startup observation, source/lock identities and which launchers are deliberately prepared. Earlier macOS/Ghostty evidence belongs to feature 005 and is not a new pass. Record detection-rule/integration identities separately if displayed; lifecycle authorization does not use them. Unavailable metrics/platforms stay unverified.

1. From ordinary SSH, enter a disposable project with a shell-only template and a fresh trial session. Verify one initial managed pane and the retained unowned native startup workspace. Re-enter from the project shell and verify no additional workspace/default or injected commands. Start with shell only; an unused editor or Agent must not be required.
2. In that trial only, verify a checkout and two linked-worktree checkouts remain ordinary independent workspaces, plus two named IDs sharing the same start. Exercise a non-Git directory boundary and a subdirectory, rename, runtime cd, native tabs/splits and unchanged ownership. Verify initial editor and deliberately prepared Pi/DSH/Codex separately; account/model calls remain outside authorization until explicitly included. An initial Agent must not receive a bootstrap replacement tab or use the Rotom checkout as business cwd.
3. Verify default focus, every deliberately selected type's extra, extra-before-default, fixed cwd/HOME after runtime cd, configuration drift/removed-type focus and accepted zero-active rebind. Preserve live processes. Disconnect/reconnect a trial SSH client and verify the same process identities; missing native markers/cold restoration must refuse, not replay. Exercise fzf selection, refresh, import/source forms, cancellation and explicit CLI with fzf unavailable.
4. Verify read-only close membership includes an unowned split and discloses all-viewer effects. Matching authorization must still return 5 and issue zero close calls on the admitted API; changed scope returns 4. Existing-branch Git creation similarly refuses with 5 before dispatch; importing an existing worktree remains valid. Do not substitute group/pane closure or server stop.
5. For comparable performance, run **20 measured warm samples** of `work enter PROJECT` from an already verified trial project shell (so attach is excluded), and 20 samples of `work open SHELL_TYPE --new` using a prepared ordinary shell. Use monotonic wall-clock start/end for the complete manager invocation and record all exit codes; do not count failed samples as fast successes. Compute p95 as sorted sample at index `ceil(0.95*n)-1`: enter/reuse <=1 second and new ordinary terminal <=3 seconds. Keep terminal/prompt, dimensions, workload, source count and filesystem fixed between comparisons. Measure discovery separately using 20 offline `work list --json` samples; report it separately with no invented selector threshold. Explicitly retain the trial terminals afterward; cleanup or stopping a trial server requires deliberate confirmation that its processes may end.
6. Record exact argv, source/config/endpoint identities, sample counts and sanitized outcomes in a separate native evidence record. Without an earlier matching baseline, report first measurements rather than an upgrade-regression pass. Do not rerun the historical ten-hour calibration merely for feature 006. Other clients/platforms remain unverified.

## Analysis remediation record

The first read-only speckit-analyze pass found I1 (HIGH: unconditional original-content preservation conflicted with post-replace durability uncertainty) and I2 (MEDIUM: stale proposal-only readiness language). Spec story 1.7/FR-014/SC-005 now distinguish pre-publication preservation from post-replacement uncertainty without claiming rollback; spec background and task readiness tables now match executed evidence. No constitutional rule was weakened, no reviewer checklist was edited and no native acceptance was inferred. The subsequent read-only pass found zero unresolved issues; stable final review completed as recorded below.

## T064 stable final review and final state

At the T064 checkpoint, all 64 original implementation tasks were complete in their admitted scope. The current release refuses existing-branch Git creation and guarded workspace close before dispatch; neither successful operation is claimed. Native/client/Agent execution, other platforms, accounts, deployment, main-branch integration and primary-entry switching remain unverified or unperformed and are outside this checklist. No production process or private account/session data was accessed.

Final source review of the post-fix stable runtime found no remaining P1/P2 issues. It checked directory-FD dispatch/result evidence, the replacement regression, complete launch-source manifest and precise fixture scope. All five v1 fixture files remain byte-for-byte HEAD; v2 fixture SHA-256 entries match their actual files. Bounded public-content/relative-link/fence/ASCII-example/Python-AST/TOML/whitespace inspection covered 48 candidate files including untracked feature files and 15 Markdown files: zero findings. This limited check does not claim a complete historical secret audit. `git diff --check` exited 0. Constitution, active-feature selector and reviewer-checklist hashes match their pre-implementation values; the existing constitution change was preserved. No commit, merge, server stop or deployment occurred.

The final read-only speckit-analyze pass resolved I1/I2 and reported zero critical/high/medium/ambiguity/duplication/unmapped findings: 41 FR + 5 SC all mapped (46/46, 100%), 64 unique tasks and 37 acceptance scenarios. Checked status was finalized after review. No `.specify/extensions.yml` exists, so before/after implement/analyze hooks are absent; no registered mandatory hook was skipped.

Delegation used executor roles configured as gpt-6.1-sol/medium for bounded tests, dependency work and documentation, plus scout roles configured as gpt-6-luna/high for public-source/evidence and independent targeted review. Role configuration is reported without inferring an unexposed service model identity. The primary agent owned state/lock/recovery decisions, runtime integration, final verification and scope tradeoffs.

## Phase 10: convergence remediation

At the Phase 10 checkpoint, T065-T068 were complete and all 68 implementation tasks were checked in the admitted scope. Git failures now expose failed/partial/unknown outcomes while retaining receipt phases and recovery blocking. Only known command return facts and correlated observations support classification; path-observation EACCES/EIO stays unknown. Old receipts without command-return facts remain conservative. No command output is retained.

Registration previews now retain canonical discovery results and show mode/template/origin/path, zero matches and diagnostics before confirmation. Selector and configuration check also surface diagnostics. Early unsafe/read-only configuration refusals do not read the body or repair permissions: explicit add inputs produce a clearly unverified manual merge fragment; an editor request without safe work data produces commented guidance. Safe-file publication failure retains the validated work fragment. Per-type deadlines use the confirmed fixed binding for open/focus or current selected definition for rebind, retaining one clock through lock/connect/dispatch and ignoring unrelated templates.

Test-first evidence: T065 initially failed eight newly added cases, then passed its isolated scope; a later observation-error refinement reproduced two failures before repair. T066 reproduced six failures before implementation. T067 reproduced twelve failures with one already passing read-only-publication case. T068 reproduced five budget failures with three existing correct cases. Final checks, all exit 0:

| Actual command | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q tests/test_work_git.py tests/test_work_state.py --tb=short` | 54 passed after path-observation refinement |
| `.venv/bin/python -m pytest -q tests/test_work_cli.py tests/test_work_config_edit.py --tb=short` | 79 passed after T067 |
| `.venv/bin/python -m pytest -q tests/test_work_cli.py tests/test_work_templates.py tests/test_work_lifecycle.py tests/test_work_config_edit.py --tb=short` | 132 passed after T068 |
| `.venv/bin/python -m pytest tests/test_work*.py tests/test_herdr_api.py tests/test_config_secret_loading.py tests/test_config_schema.py -q --tb=short` | 728 passed in 154.71 seconds; shell glob expands to the same 24 work modules listed above |
| `.venv/bin/python -m pytest -q tests/test_work_cli.py -k 'type_operation_budget or removed_type_selector_focus' --tb=short` | 10 passed, 54 deselected; includes the two added selector-focus cases |
| `.venv/bin/python -m pytest -q tests/test_work_cli.py --tb=short` | 64 passed on the final test file |

The aggregate collection preceded the last two selector-focus tests, so the final CLI run supplies their runtime evidence. Those cases use the actual CLI/focus path with fake native terminals and fixed shell/Pi bindings after type removal; neither preparation nor creation occurs on focus. No native host/editor/Agent/fzf or real account was executed. Synthetic Git remains restricted to disposable temporary repositories. Tests use temporary HOME/XDG, blocked network, fake hosts and sentinels. The initial sandbox view mapped ancestor ownership incompatibly and caused existing protection checks to fail; the same isolated tests were rerun with real directory metadata, without changing permissions or disabling protections. That first environment failure is not a product pass.

Independent read-only review used scout configured as gpt-6-luna/high for configuration/presentation and executor configured as gpt-6.1-sol/medium for budgets. The executor also implemented the bounded Git package after primary-agent approval of receipt/result semantics. The primary agent reviewed state/lock/recovery decisions, repaired the observation-error case and added the review-requested focus coverage. No unresolved substantive code issue remains from those reviews. Runtime source identity is `6750c6841d5ee21ce2782dbd05b255aeb72eda33d431e750264976efb744f6c7`; dependency identities above remain unchanged.

| State | Scope |
| --- | --- |
| Completed | T065-T068 implementation and the isolated checks above |
| In progress | None within the implementation checklist |
| Failed, pending decision | None; initial red/environment failures are retained as evidence above |
| Environment insufficient / unverified | Changed native/client/Agent/account/platform acceptance, deployment, main integration and primary-entry switching. Existing-branch creation and guarded close remain unavailable with tested refusal only. |

The Phase 10 read-only specification analysis found U1 (MEDIUM): AC7/FR-015 did not explicitly distinguish a safe-value merge fragment from comment-only guidance when no safe values exist. The subsequent documentation remediation clarified both forms in spec and plan, preserving the fragment obligation and Constitution II protections. Application code and reviewer checklist were unchanged by this clarification.

## Phase 11: interactive review and removed-type selection

T069-T070 are complete; all 70 implementation tasks are checked within the admitted scope. The interactive Git worktree form now presents the reviewed destination source and coverage rules, repository/common/git-directory identities and non-secret configuration identity before the final action choice. It uses a field allowlist over the reviewed plan, summarizes Git configuration metadata and retains the existing preservation/suppression notice. An independently saved parent source leads to a renewed plan and its facts, rather than reusing the earlier preview. Cancel still creates nothing and preserves an earlier separately confirmed source save.

Removed types now contribute only specific recorded-instance rows labelled focus-only during ordinary selection. They are absent from new-extra selection and have no default-create or rebind action; an empty removed binding contributes no row. Selecting a recorded instance still uses the actual live-verified focus route, fixed shell/Pi budget and existing binding, without preparing a launcher or creating a workspace/tab. Backend refusal, creation-time fact rechecks, identity and authorization rules were unchanged.

Test-first evidence: T069 reproduced two failed preview assertions, then `.venv/bin/python -m pytest -q tests/test_work_cli.py --tb=short` exited 0 with **65 passed**. T070 reproduced six failures across removed-type rows/mapping and actual selector-focus routing before repair. After both implementations and final test refinements, the following actual command exited 0 with **172 passed**:

```text
.venv/bin/python -m pytest -q tests/test_work_cli.py tests/test_work_templates.py tests/test_work_lifecycle.py tests/test_work_git.py tests/test_work_config_edit.py --tb=short
```

This affected-scope run includes current configured-type actions, removed-type new/ordinary selection with and without instances, exact instance-locator routing, fixed focus budgets, no preparation/creation during focus, both worktree coverage paths, cancellation/save retention, and the existing Git/lifecycle/configuration regressions. It retains temporary HOME/XDG, blocked network, fake native/editor/Agent/fzf hosts and strictly disposable synthetic Git repositories. Tests used the previously authorized real ownership-metadata view without changing permissions or weakening protections. No native host, account, deployment, migration or primary-entry switch was executed; historical aggregate results above remain historical.

An executor role configured as gpt-6.1-sol/medium implemented the bounded UI/tests package; a scout configured as gpt-6-luna/high reviewed negative cases and the final stable source/tests independently. The primary agent inspected the stable implementation and test evidence, retained ownership of task/document updates and final acceptance, and found no remaining substantive issue in this scope. Service model identity beyond the role configuration is not exposed. Runtime launch-source identity is `b9b030ec352d6ab0a6e6f824ee80761c6daba2a3ebcbc5e6889d5a7086c317de`; dependencies, constitution and reviewer checklist were unchanged.

| State | Scope |
| --- | --- |
| Completed | T069-T070 implementation, affected isolated verification and stable source review |
| In progress | None within the implementation checklist |
| Failed, pending decision | None; test-first failures were repaired and are not counted as passes |
| Environment insufficient / unverified | Changed native/client/Agent/account/platform acceptance, main integration, deployment and primary-entry switching. Existing-branch creation and guarded close retain tested capability refusal only. |
