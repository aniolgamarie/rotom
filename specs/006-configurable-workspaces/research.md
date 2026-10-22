# Research: Configurable Workspaces

**Date**: 2026-10-22
**Feature**: [spec.md](spec.md)
**Status**: Historical Phase 0 decisions with implementation admission refinements below; configuration-writer coordination confirmed by the user. Current implementation and verification status is recorded in [plan](plan.md) and [quickstart](quickstart.md).

This is design evidence, not implementation, deployment or native acceptance. Existing feature 005 results retain their original scope. No real private configuration, credentials or sessions were inspected. Research used repository source and official upstream materials.

## R1. Reuse the existing CLI, preparation and launch handoff

**Decision**: Extend the existing `work`/termcfg path. Keep agentcfg responsible for managed Agent preparation and execution; keep Herdr responsible for terminals and layouts; use the independent editor launcher. Add no daemon, shell command language, Agent scheduler or terminal inventory service.

**Rationale**: [work.py](../../src/termcfg/work.py) already serializes cooperating Rotom operations and implements pending/ready/commit/accepted launch handoff. [work_shell.py](../../src/termcfg/work_shell.py) verifies source, selected configuration, endpoint and pane identity before exec. [work_config.py](../../src/termcfg/work_config.py) checks prepared Agent contracts without loading credentials. These mechanisms must be extended for structured identity, not replaced by command injection.

**Alternatives considered**: A new manager duplicates lifecycle ownership. Sending commands into a shell loses argv and exactly-once launch boundaries. Treating native titles or environment variables as ownership is insufficient.

## R2. Runtime compatibility and dependency admission

**Decision**: Keep Python >=3.11 and the prepared repository `.venv`. The observed 3.11.11 is evidence, not a universal patch-version requirement. No requirement to replace the system interpreter. Add tomlkit only in implementation, with an explicit dependency/lock change and source review; 0.15.2 is the researched candidate. fzf is an optional external selection frontend, with 0.74.5 the researched stable candidate, not a mandatory exact version on every machine.

**Rationale**: tomllib reads TOML but cannot preserve its formatting during edits. tomlkit documents preservation of comments and layout; its [0.15.2 package metadata](https://raw.githubusercontent.com/python-poetry/tomlkit/0.15.2/pyproject.toml) declares MIT and Python >=3.9. Its [official project](https://github.com/python-poetry/tomlkit) documents the editing model. The [fzf release](https://github.com/junegunn/fzf/releases/tag/v0.74.5) identifies the current candidate. Required selector options must be verified against an exact release during implementation; CLI actions remain usable if it is absent.

**Alternatives considered**: Re-serializing with a non-preserving writer changes unrelated content. A home-grown TOML editor expands maintenance and safety risk. A full TUI toolkit or Git lifecycle manager is unnecessary for selecting an already bounded list. Worktrunk remains a future alternative with separate ownership review, not an additional default dependency.

**Admission record**: No dependencies installed, locks changed, assets downloaded or host processes started by this planning step. Exact package hashes, fzf license/source identity and supported option fixture are implementation admission requirements, not already verified deployment facts.

### T002 dependency admission — 2026-10-22

**Completed**: Admitted `tomlkit==0.15.2` in `pyproject.toml` and explicitly regenerated `uv.lock` with uv 0.12.13. The official [exact-version PyPI metadata](https://pypi.org/pypi/tomlkit/0.15.2/json) identifies the [upstream project](https://github.com/python-poetry/tomlkit), MIT license, Python >=3.9, no runtime dependencies and a non-yanked release. The project requirement remains Python >=3.11; observed Python 3.11.11 is only this execution's interpreter. All existing non-project dependency records are unchanged.

| Admitted artifact from `files.pythonhosted.org` | SHA-256 recorded in `uv.lock` and checked against PyPI |
| --- | --- |
| `tomlkit-0.15.2.tar.gz` | `83e32755ba1d20d9340bd069ee97e9f6232ba2346b63ffcba425de01f7e327a6` |
| `tomlkit-0.15.2-py3-none-any.whl` | `05562412163a3037b94497385fb7f9204c637bc605af7a48199e41cf2272f437` |

Downloaded the exact source distribution and independently checked its SHA-256, package version, MIT metadata and included permission text. A bounded scan of its 12 library Python files found no matches for the reviewed process/network/eval hooks; this is source-admission evidence, not a complete security audit. The wheel was installed by the locked sync; its locked integrity identity matches official metadata.

**Preparation and validation**: Preserved the existing shared `.venv` symlink under ignored `.cache/t002/shared-venv-link`, created an ordinary worktree-local `.venv`, then installed 17 packages using `uv sync --locked`. A before/after content-hash and link-target comparison of all 1,018 shared-environment files/links passed. No writes were made through the retained link. Normalized executed argv (working directory: feature worktree):

```text
uv lock --cache-dir .cache/t002/uv --python /usr/bin/python3.11 --no-python-downloads --default-index https://pypi.org/simple
uv venv .venv --python /usr/bin/python3.11 --no-python-downloads --cache-dir .cache/t002/uv
uv sync --locked --cache-dir .cache/t002/uv --python /usr/bin/python3.11 --no-python-downloads --default-index https://pypi.org/simple
uv lock --check --offline --cache-dir .cache/t002/uv --python /usr/bin/python3.11 --no-python-downloads
.venv/bin/python -m pytest --version
```

All five commands exited 0. The default sandbox blocked direct public-network requests; the exact metadata/artifact fetches and lock/sync preparation succeeded with explicit command escalation. Offline lock validation passed. The isolated interpreter imported tomlkit 0.15.2, pytest 9.1.1 and jsonschema 4.26.0; a synthetic TOML roundtrip and one-field edit preserved comments/layout and unrelated bytes. `git diff --check -- pyproject.toml uv.lock` passed. Ignored evidence logs: `.cache/t002/source-review.log`, `.cache/t002/verification.log`, `.cache/t002/commands.log`.

**In progress / failed pending decision**: None within T002. **Not verified**: Feature implementation, full regression suite, other Python/platform combinations and native hosts; no host was started. Startup entrypoints were unchanged and use the prepared environment without downloads or `uv run`.

## R3. Stable Herdr candidate and public workspace creation

**Decision**: As of 2026-10-22, evaluate Herdr 0.9.5 first. Recheck the official stable channel when implementation selects a candidate; do not hard-code 0.9.5 as the only future supported release. New structured workspaces use ordinary `workspace.create`, never `worktree.open/create`.

**Rationale**: The [official release](https://github.com/herdrdev/herdr/releases/tag/v0.9.5) is marked latest stable. Its tagged [workspace schema](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/src/api/schema/workspaces.rs) exposes a literal environment mapping on ordinary creation. The existing shell wrapper can therefore receive a versioned one-use intent for the initial pane, including an initial editor or Agent, without creating a second tab or injecting input. The current Rotom wrapper allowlist does not yet include this method and must be expanded with audited request/result schemas. Existing protocol-22 fixtures are a subset, not evidence that this new method is implemented in Rotom.

**Alternatives considered**: Native Git worktree operations carry group semantics and would contradict independent workspace ownership. `layout.apply` bootstrap replacement creates unnecessary intermediate processes. Rolling documentation and an installed binary version alone do not establish the required API capability.

**Evidence boundary**: The tagged schema is current research evidence. Source references in the earlier [design](../../docs/design/configurable-workspaces.md) explain ordinary versus grouped creation; implementation must freeze reviewed tagged handler/source and complete exact bundled-schema validation. No new native creation test has run.

## R4. Safe close is a capability gate, not a double-read guarantee

**Decision**: For the currently examined 0.9.5 public API, keep Rotom's mutating close disabled. Read-only scope preview is allowed. Dispatch requires a future verified public operation that atomically checks the reviewed membership/identity (or an equivalent server-enforced exclusion covering every native client). No such public guard is present in the tagged close request schema.

**Rationale**: A member can be added after a client-side recheck and before an unconditional workspace close. A Rotom advisory lock does not stop native UI or another socket client. `close_group = false` addresses linked-group behavior, not tab/pane membership compare-and-swap. Repeated reads, short delays, a scope hash supplied only to Rotom, or “only one visible client” cannot provide that guarantee.

**Alternatives considered**: Group closure can affect another workspace. Closing enumerated panes individually is a partially destructive substitute and may race with moves. Upstream patches, private APIs, killing the server and reconstructing active layouts are prohibited. Relaxing FR-036 requires an explicit specification revision, not an implementation shortcut.

**Readiness consequence**: Unsupported close returns dependency/native-capability exit 5 without a close request. Scope drift or conflicting ownership returns 4. Refusal cases can be tested now using fakes; successful native close remains unavailable and must not be reported as delivered. This follows the spec's unsupported-capability assumption and does not waive FR-035–037 or SC-004.

## R5. One local configuration and bounded discovery

**Decision**: Introduce explicit `machine.work.model = "structured-v1"`. Absent `model` keeps legacy seven-role Git-only behavior. Structured-only fields without opt-in are rejected; invalid structured input never falls back. Reuse the machine-local TOML selected by `--machine` or `--local`, the existing non-secret load path, and strict local schema.

**Rationale**: Explicit opt-in avoids changing active installations when new defaults are added. The templates, sources, explicit directory entries and named contexts are one configuration contract for CLI, selector and manual edits. The built-in executing Rotom checkout is an ephemeral candidate, not a saved project record.

**Resolution**: Directory identity is endpoint plus canonical selected project boundary; named identity is endpoint plus stable local ID. Sources scan a configured bounded depth, default 1, without following symlinks by default or traversing external worktree metadata. Explicit entry outranks the deepest matching source, which outranks the built-in candidate. Equal-priority incompatible definitions fail.

**Alternatives considered**: Inferring opt-in from `include_rotom` changes legacy behavior. A project database or background watcher competes with the TOML file. Git common-directory identity merges distinct worktrees. Caller PWD and guessed main checkout do not establish a trusted Rotom root.

## R6. Configuration writer coordination: confirmed contract

**Decision**: The user confirmed the shared-lock convention on 2026-10-22. All cooperating CLI/TUI saves and `work config edit` use a stable lock keyed by canonical configuration selection. Direct manual TOML editing remains supported between save operations; users avoid overlapping it with a configuration save. The [spec clarification](spec.md#clarifications), story 1.7 and FR-014 encode this boundary.

**Rationale**: [Tree.replace](../../src/agentcfg/storage.py) reads safely, rechecks identity and atomically replaces a file, but acknowledges the final external-process race. Atomic rename is not a content-conditional compare-and-swap. [Python 3.11 os.replace](https://docs.python.org/3.11/library/os.html#os.replace) documents atomic replacement; [flock](https://man7.org/linux/man-pages/man2/flock.2.html) is advisory. Observed outside edits cause refusal; no guarantee is claimed against a writer ignoring the lock during the final replacement window.

**Editing boundary**: `work config edit` opens a private staging fragment containing only the non-secret `machine.work` subtree, not the full machine TOML or credentials. Use the explicitly configured single editor executable. Hold the config lock across editing, validate the complete proposed configuration, recheck the original file and publish only an accepted change. An invalid fragment leaves the original intact. Whole-file direct editing remains a separate manual entrance.

**Save requirements**: Safe private ownership/link checks; same-directory temporary file and atomic publication; comment, unrelated content and permission preservation; no-op idempotence; no secret-bearing file digest, editor copy or generic backup. Failed/unsafe/read-only saves produce a diagnostic and the proposed work fragment without false success. Config and native/Git operation locks are never nested; save finishes before a fresh lifecycle preview.

**Alternatives considered**: A strict guarantee against arbitrary uncoordinated writers would require refusing automatic replacement where exclusion cannot be proved. The user chose the cooperative editing convention instead. Treating optimistic checks as a universal compare-and-swap would misstate the actual guarantee.

## R7. Minimal binding and operation state

**Decision**: Maintain a small private version-2 binding/receipt store, separate from termcfg deployment state and Agent state. It records endpoint generation evidence, workspace/type/instance identity, fixed startup/launch selection and unresolved operation receipts. It never stores candidate inventories, screen text, commands typed by users, credentials or task completion.

**Rationale**: Arbitrary user-defined types cannot be encoded as unlimited workspace metadata keys. Existing v1 native metadata is bounded and may disappear on cold restore. Durable receipts prevent unknown creation from being treated as absent, but never authorize control on their own. Live public native identities and marker agreement remain mandatory.

**Resolution**: A new creation writes durable intent before dispatch and passes operation ID/epoch via the public environment mapping. The wrapper derives its actual workspace/pane/terminal identity from a pinned caller query, cross-checks the intent and self-reports readiness. Parent and child commit the same intent before one exec. Missing response triggers read-only reconciliation, never resubmission. Cold restoration or missing marker produces stale/unknown ownership, not automatic adoption or Agent resume.

**Alternatives considered**: Titles, newest logs and request IDs are not ownership or idempotency keys. Persistent paths in native tokens risk truncation. A general process database or scheduler exceeds scope. Blindly deleting receipts can permit duplicate creation.

## R8. Fixed type bindings and minimal selector

**Decision**: Separate type key, instance ID and mutable label. Bind each workspace/type's resolved start directory and selected launcher/profile/editor contract at first instantiation. Default focus does not re-prepare, execute, inject input or change cwd. Extras use the same binding; explicit rebind requires zero verified live instances and a fresh accepted binding.

**Rationale**: `problem1/2/3` are instances of `problem`. A shell's later `cd` is runtime state. Uninstantiated types can use new configuration; contradictory changes to bound types block creation while existing verified instances remain focusable.

**Selector decision**: fzf consumes a bounded escaped display list with opaque selection IDs mapped back to in-memory objects. Never parse a displayed path as a command. Use argv without shell/eval, clear inherited fzf option overrides, single selection and cancel semantics; no shell preview or execute bindings. A refresh reruns discovery, not a watcher. Read-only configuration checks do not spawn fzf, Herdr, editors or Agents.

## R9. Git owns worktree creation

**Decision**: Use explicit local Git argv, not another worktree manager. New-branch mode requires a local base resolved to a commit; existing-local-branch mode rejects a base. Reject all existing destinations and require visible configured source coverage before creation. Adding coverage is a separately confirmed config save followed by a fresh preview.

**Rationale**: The [worktree manual](https://git-scm.com/docs/git-worktree) distinguishes new branches, existing occupied branches and force/reset options. Rotom's policy is stricter: no force, reset, remote guessing, fetch, stash or automatic cleanup. A durable intent precedes dispatch; timeout/failure enters read-only reconciliation. Successful checkout plus failed entry retains the checkout.

**Hook/bootstrap boundary**: Use per-invocation `core.hooksPath` pointing at a verified empty private directory, and disable external fsmonitor for these operations; never modify persistent Git config. The [Git configuration manual](https://git-scm.com/docs/git-config/2.56.0#Documentation/git-config.txt-corehooksPath) documents hook redirection. A checkout may also run configured content filters, per [gitattributes](https://git-scm.com/docs/gitattributes). The first implementation must detect executable checkout filters and refuse creation with an explicit limitation rather than silently running them or bypassing required content conversion. This bounded refusal avoids adding a filter engine or claiming hook suppression prevents every Git subprocess.

**Alternatives considered**: Worktrunk adds a second lifecycle owner and hook/bootstrap surface for this scope. Native Herdr worktree creation introduces grouping. Disabling filters silently can leave unusable content. A failed Git call does not establish that it changed nothing.

## R10. Validation, migration and upgrades

**Decision**: Default verification remains temporary HOME/XDG/state, synthetic repositories, blocked network and fake hosts. Test each failure boundary, Unicode/space paths and all three configuration entrances. Add exact tagged API fixtures without overstating their completeness. Keep actual native support separate and authorize it later.

**Rationale**: The existing [upgrade policy](../../docs/herdr-upgrades.md) and [feature 005 evidence](../005-herdr-project-workspaces/implementation-evidence.md) are dependencies, not proof of these changed flows. Legacy state and grouped native layouts remain untouched. A structured trial uses a separate explicitly chosen session/configuration; no active adoption, automatic ungroup, Agent resume or primary-entry switch.

**Performance**: Preserve the user's existing enter/reuse and new-terminal budgets for comparable unchanged scope; record discovery cost separately, without inventing selector thresholds. Select affected upgrade checks, not another historical ten-hour run. Pure planning requires no native benchmark.

## Historical research task record

This table records the research/planning checkpoint before implementation. Later dependency admission and isolated execution are recorded below and in [quickstart](quickstart.md); its unverified list is not the current implementation status.

| State | Work |
| --- | --- |
| Completed | Local reuse map; current stable discovery; tagged workspace request inspection; selector/TOML/Git candidate research; identity/unknown-outcome and close capability decisions |
| In progress | None within the completed research/planning workflow |
| Failed, pending decision | None; configuration-writer coordination is confirmed, not waived |
| Environment insufficient / unverified | New native workspace handoff; independent grouping effects; successful guarded close (not exposed by current public request); exact new dependency lock/asset/selector compatibility |

Research delegation used scout roles configured as gpt-6-luna/high for local and upstream evidence. Their findings were reviewed by the primary agent; the wrapper's existing allowlist is not treated as the full upstream API. No runtime pass is claimed.

## Implementation source recheck: 2026-10-22

T001 rechecked the official latest-release redirect and tagged workspace request source. Stable remains v0.9.5, tag commit `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01` (the existing audited source identity). The tagged request accepts ordinary creation env and exposes no guarded close membership parameter. Protocol 22 and the existing bounded source fixture remain admission inputs, not native acceptance. No host was started or installed.


## Implementation admission refinement: running configuration

Tagged `src/api/schema.rs`, `src/api/schema/server.rs`, `src/api/schema/session.rs` and `src/api/schema/response.rs` expose no read-only query for effective server configuration. Disk `config check` and ping therefore cannot prove a pre-existing server uses the prepared default shell/no-auto-resume contract. No existing repository startup receipt supplies that proof.

T008 will conservatively require protected startup evidence for structured creation: this entry explicitly starts a fresh selected server after checking the prepared config and trusted wrapper, verifies those disk inputs again, pins the discovered socket and records the observed server identity. A pre-existing server without that evidence is not repaired/reloaded/stopped/adopted; offline/read-only functions remain available, and managed creation refuses with preparation guidance. Startup evidence is a bounded observation rather than an upstream effective-config attestation; changes to its recorded inputs or endpoint invalidate it. Agent detection/integrations are not used to authorize terminal lifecycle; their native acceptance remains separately recorded. This refinement narrows admission without introducing a new process or pretending disk configuration describes a running instance.

## Implementation handoff metadata ordering

T010 uses one `rotom-work-launch-v2` source for every pane ready/commit/accepted/failed patch, and `rotom-work-v2` for workspace identity/pending. Tagged pane/workspace handlers enforce source-scoped sequence freshness while token keys live in one shared resource map. A different source can clear a shared key but loses ordering with the original stream; it is not a safe substitute for the same ordered failure clear. No TTL or empty-map clear is used. Late-event tests and readback protect bounded patches; this source review is not native execution.

## Implementation initial-create lost-reply limit

An ordinary initial workspace has no immutable public birth marker. If its creation response is lost, a uniquely ready pane might have been moved into a different ordinary workspace before parent correlation. The parent therefore queries matching op/epoch evidence but does not commit or claim ownership from that fact alone. It retains a dispatched/unknown receipt, never resends creation and requires later explicit recovery evidence. With a validated creation response, the returned workspace/root-pane/terminal identities constrain correlation; an existing-workspace tab already has its verified target identity. This conservative refusal satisfies the lost-result contract without trusting titles, startup workspace environment or inventing an upstream idempotency field.

### T021 optional selector admission

fzf v0.74.5, tag commit `c0a193e031f01fb50bf6f7be4381990a3753f7cf`, MIT, was rechecked against the [official release](https://github.com/junegunn/fzf/releases/tag/v0.74.5), [tagged manual](https://raw.githubusercontent.com/junegunn/fzf/v0.74.5/man/man1/fzf.1) and [license](https://raw.githubusercontent.com/junegunn/fzf/v0.74.5/LICENSE). Public `--read0`, `--print0`, single selection, delimiter/with-nth and display options are admitted by version/help capability inspection; other capable versions are not rejected solely for differing patch versions. No binary is installed or bundled. The invocation always supplies NUL-delimited stdin and removes every inherited FZF_* variable before capability inspection and selection. No preview, execute binding or default command is enabled. Exit 1/130 means cancellation, 2 means error. An asserted --no-preview option is not used. Exact runtime interactive behavior remains separately unverified.

## Implementation Git capability and result review

Observed synthetic-repository execution used `/usr/bin/git` 2.43.5. The CLI admits Git >=2.36 for boolean `core.fsmonitor=false`, rather than pinning a patch version. [Official worktree documentation](https://git-scm.com/docs/git-worktree), [configuration](https://git-scm.com/docs/git-config) and [attributes](https://git-scm.com/docs/gitattributes) define the public options and filter limitations. Tagged [worktree.c](https://github.com/git/git/blob/v2.50.0/builtin/worktree.c) and [refs.c](https://github.com/git/git/blob/v2.50.0/refs.c), plus the isolated 2.43.5 deletion-at-dispatch reproduction, establish that --no-guess-remote does not guard explicit short-branch fallback; full refs/heads input can detach HEAD. Existing-branch creation therefore refuses with 5 before state/dispatch; import and read-only preview remain supported. This conservative refinement preserves the spec capability assumption and no-remote-guessing requirement without claiming user approval of the optional preference question.

New-branch execution freezes an explicit local commit, re-reads the non-secret selected configuration, checks visible source/refs/occupancy and identities, writes immutable intent then dispatched receipt, and invokes one worktree add. A Linux O_PATH directory FD, passed explicitly to the child for -C /proc/self/fd/FD, prevents path replacement from silently redirecting that source directory. Repository/common/gitdir/config/binary/parent observations are checked before dispatch and result acceptance. This is not a transaction against arbitrary external Git/config writers; detected drift or uncertain results are retained as unknown, never compensated by deletion or reset. The checkout destination uses its persistent path. Hooks use a verified empty private directory, fsmonitor and submodule recursion are disabled per invocation, caller GIT_* controls are removed, and executable configured filters are refused. No command output is persisted. The original dirty/index/config bytes and hook/filter sentinels were checked in synthetic repositories.
