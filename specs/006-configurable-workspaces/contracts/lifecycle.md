# Lifecycle and Failure Contract

**Status**: Implemented ordering/refusal contract with isolated checks; native acceptance remains separate.
**Related**: [data model](../data-model.md), [CLI](cli.md), [configuration](configuration.md), [native admission](native-api.md).

## Common ordering and authorization

Each action progresses through resolve, read-only preview/validation, explicit authorization, final recheck, durable intent where needed, dispatch and outcome verification. Fully specified CLI input authorizes only its declared action. Cancellation before authorization and every dry run perform no current-action filesystem/native mutation: no lock-file creation, operation receipt, host start or directory creation. Existing independent confirmed actions stay saved.

Config writes use one stable config lock keyed by canonical selected config path, not the current file inode. All CLI/TUI saves and config edit participate. Keep the lock file stable through atomic replacements; never unlink a live lock. Direct external edits are supported between saves; observed outside changes refuse publication, without a universal exclusion guarantee.

Native/Git operations reuse the existing per-UID operation lock. The config lock and operation lock are never held together. Complete a config save, release its lock and make a fresh lifecycle preview before acquiring the operation lock. The wrapper does not take the parent's operation lock. File-state updates use short safe I/O operations under the already held operation lock, not another conflicting lifecycle lock.

The operation deadline is total, not renewed for every API read. Preserve the existing bounded 30-second ordinary / 60-second managed-Agent creation policy unless affected evidence justifies a reviewed change. Interactive configuration editing has its own lifetime; do not kill an editor after the management timeout. Other config writers wait within a bounded lock-acquisition budget and return 4 if busy.

## Configuration registration and editing

1. Resolve the explicit source/project/named proposal; validate existing paths, selected mode, IDs, references, bounded discovery and canonical conflicts. Do not launch a host or open terminals.
2. Interactive input previews only the proposed owned TOML fragment and actual registration boundary/candidates. Complete CLI arguments supply equivalent save authorization.
3. Acquire the config lock, re-read safely and compare the original identity/content in memory. Do not persist a whole-file digest that may include inline secrets.
4. Apply a comment-preserving edit only to machine.work. Validate the entire proposed ordinary configuration through the existing secret-separated loader/schema/reference checks, without resolving credentials.
5. A compatible duplicate is a no-op: no rewrite or backup rotation. An incompatible duplicate fails. A changed file requires fresh validation/review or refusal, not overwrite.
6. Publish through a same-directory private temporary file and atomic replacement after final expected-identity/ancestor checks; preserve unrelated text/comments and original safe permissions.
7. If publication fails, retain original content wherever the write did not commit and report the observed outcome accurately. A failure after replace/fsync can be an unknown durability result: inspect read-only before retry, do not claim unconditional rollback.
8. Unsafe/read-only/uneditable input yields a diagnostic and proposed non-secret fragment, not a success code.

Config edit uses the explicitly selected editor executable on a private machine.work fragment while holding the same config lock. It does not stage the full machine document or credentials. After editor exit, revalidate/review the fragment before publication; unchanged/cancelled edits leave the original untouched. An invalid fragment may be shown locally with a diagnostic but is not applied. Editor exit is not proof of config acceptance.

## Directory entry and initial instance

Before any native effects, resolve one configured/built-in candidate and its canonical boundary/template. Verify only the initial launcher's preparation; unused editor/Agent launchers are not prerequisites for shell entry. Outside Herdr, entry may start/attach the explicitly selected prepared session; inside it, resolve the current caller rather than starting another endpoint. Ordinary checks/imports never do this.

Within the operation lock:

1. Discover and pin the selected endpoint, verify public capability/configuration, and inspect live markers plus private bindings.
2. If one current managed binding agrees, reconcile known completed bookkeeping and focus it. If conflicting/unmarked same-context ownership is observed, refuse instead of adopting or creating.
3. For genuinely new identity with no unresolved intent, resolve workspace_start and initial type binding. Persist a version-2 intent before dispatching ordinary workspace.create with explicit cwd/label, focus=false and one-use payload.
4. The wrapper verifies payload version, expiry, trusted Rotom source, selected non-secret launch/config contract, endpoint and authorized durable intent. Its own pane.current supplies actual workspace/pane/terminal IDs; title/cwd do not.
5. Publish bounded pane ready markers. The parent matches exactly one pane/op/epoch, verifies returned/observed identities and independent ordinary workspace provenance, records fixed bindings and publishes workspace identity/pending markers.
6. Persist commit-issued before publishing commit for that root pane. The wrapper waits for matching parent commit, workspace markers and unchanged membership, revalidates preparation and deadline, then reports accepted and executes once.
7. Parent observes accepted/commit agreement, commits binding/default references, clears pending only when the result is proved, and focuses. The initial type owns exactly one instance; no bootstrap replacement tab.
8. Remove the one-use payload from the final environment and preserve the established launcher/cwd/HOME/credential contract. Do not auto-run task commands or install dependencies.

For an existing workspace, type opening follows the same intent/ready/commit/accepted protocol using tab.create and an explicit workspace ID. A new type first resolves its fixed binding; an existing type compares the current requested contract with that binding before creating. A plain verified default focus bypasses creation/preparation and injects no input. A structured --new is always extra and never changes the default.

## Handoff failure windows

| Failure boundary / observed fact | Required result |
| --- | --- |
| Before durable intent/dispatch | Fail with no native creation |
| Intent persisted but dispatch not proved | Keep pending until an original operation can prove no dispatch or reconcile; do not guess from missing panes |
| Create response lost | Query uniquely marked op/epoch on pinned endpoint; never resend create |
| More than one matching ready/accepted pane | Conflict 4; no commit, adoption or cleanup |
| Created pane lacks expected marker | Unknown 4; preserve it and intent |
| Parent dies before commit | Wrapper cannot execute business launcher without matching commit/deadline; no later replay |
| Commit may have applied, accepted response missing | Unknown until read-only evidence; do not cancel, retry launch or infer harmless timeout |
| Accepted/commit uniquely proved | Original operation may finalize binding bookkeeping only; never exec again |
| OS exec fails after accepted | Publish failed and clear this pane's commit under bounded failure-report budget; parent cannot treat it as a successful launcher |
| Failure report also uncertain | Wrapper exits; do not leave a fallback shell carrying a valid accepted Agent identity |
| Metadata lost / endpoint replaced / cold restore | Stale or unknown 4; no automatic adoption, default recreation or Agent resume |
| Complete native query proves default closed or moved out | Mark its reference absent during the next authorized operation; preserve any moved pane, never promote an extra |
| Marker missing on an existing numeric native ID | Conflict/unknown, not absence; no creation based on that observation |

An uncommitted wrapper may return to a clearly unowned ordinary shell only after an irreversible failure path proves it cannot later exec. A committed/possibly accepted wrapper must retain the existing conservative no-false-fallback rule. Do not turn expired deadline or idle Agent state into permission to clear uncertain operations.

Status/reconcile are read-only reports. When facts later prove an already completed operation, a subsequent original command may finalize that operation's registration without replaying it. Unresolved outcomes never expire automatically and --new is not a bypass. Users retain native navigation/manual terminals while unrelated work continues; any server stop/old-state retirement is separate explicit work after active tasks finish.

## Git worktree creation

Git reports distinguish `failed`, `partial` and `unknown` without changing the receipt phase or authorizing a retry. A proved nonzero command return plus complete observations of no branch/checkout effects can establish failure; correlated expected-commit/registration effects establish a partial result even if execution remains uncertain. Missing effects after a possible timeout, unrelated paths/refs or unavailable observations remain unknown. Receipts optionally retain the command return code, never its output; older receipts without it stay conservative. Status/reconcile derive the current interpretation read-only. A durable completed outcome remains historical, with current observations separately reported; neither it nor an accepted launcher proves business-task completion. Retained partial/unknown receipts still block conflicting creation and are never automatically cleaned up.

Only a Git-mode project resolved through a configured source or explicit project entry can be the repository source. The unsaved built-in candidate alone is not registration and does not grant coverage over its parent. Importing an existing worktree is a configuration action, not creation.

Preview includes canonical source/common-repository facts, branch mode, validated local ref identities, absent destination and existing parent identity, source coverage/template, relevant config selection, hook/bootstrap policy and dirty-work preservation. Base may resolve an explicit local branch/tag/HEAD/commit; reject ambiguous names, remote guessing and network resolution. New-branch and existing-local-branch modes are exclusive; the existing mode rejects a base and occupied branches.

A destination must satisfy visible configured-source coverage, depth and exclusions. If missing, the picker can invoke separately authorized Add parent search root, release config save state and return to a fresh worktree preview. Later cancellation retains that earlier save. Never register a nonexistent project or write a future-project record.

Immediately before dispatch, under the operation lock, recheck repository/path identities, ref object IDs, occupancy, destination absence, source policy and template. Changed facts require fresh review/refusal. Persist the reviewed operation intent before the single Git invocation.

Use subprocess argv, no shell. Per invocation redirect hooks to a verified empty private directory, disable external fsmonitor and remote guessing, remove caller Git repository/config override variables, and avoid network/submodule/bootstrap commands. Detect executable checkout filters and refuse the first implementation's unsupported combination; do not silently disable required conversion or run the filter. Recheck relevant Git configuration before dispatch.

Normalized argv shape for new-branch mode (each item is separate data, not a shell string):

```text
git -c core.hooksPath=EMPTY_PRIVATE_DIRECTORY
    -c core.fsmonitor=false
    -c worktree.guessRemote=false
    -C REGISTERED_CHECKOUT
    worktree add -b VALIDATED_NEW_BRANCH -- DESTINATION RESOLVED_BASE_COMMIT
```

Existing mode validates the local branch for preview but does not dispatch on the examined Git capability. New-branch dispatch uses a pinned Linux directory FD for -C and verifies reviewed repository/common/gitdir/config identities again before and after the call. External writers are not serialized by this FD; changed evidence retains an unknown result. Git owns its repository locks; Rotom's lock does not serialize arbitrary external Git users. A concurrent change detected after dispatch is a retained partial/conflict outcome, not permission to reset or delete anything.

| Result | Required behavior |
| --- | --- |
| Known pre-dispatch refusal | No checkout/branch/native creation |
| Git exits nonzero / times out / response unavailable | Read-only reconciliation of local refs, worktree list and destination; report known/partial/unknown effects |
| Git proves successful checkout, create-only selected | Commit receipt and finish; do not open Herdr |
| Git succeeds, explicit entry fails | Retain checkout and report separate enter path; no compensation deletion |
| Partial branch/checkout/config state | Preserve it, return 4 where recovery is required; no automatic retry, force, reset, stash or cleanup |
| Ref/filter/hook/coverage capability unsupported | Refuse before dispatch with the relevant 2/5 diagnostic |

A Git creation can update shared repository metadata; it must not modify/copy the original dirty worktree. Verify dirty/index sentinels and persistent config are unchanged using a synthetic repository. Do not call status in a way that runs external filters/fsmonitor merely to build a preview.

## Named title update

Named add saves configuration only; named enter is separate. Rename changes title while retaining local ID/endpoint identity. Save the new title first under the config contract. Then update only an already verified live matching native workspace through workspace.rename; do not create or attach one. If the live update fails, keep the saved title and report presentation pending/unknown, not a full rollback or successful native update. Later entry may reconcile that presentation against the same verified binding. Other endpoints' native workspaces remain untouched; their next configuration load follows their explicitly selected local configuration.

## Close, detach and data boundaries

Preview must enumerate actual tabs/panes, including unowned native splits inside the selected workspace. Show stable context/endpoint, shared impact on all clients and retention of sibling workspaces/checkout/branch/config/server. The preview scope digest binds membership/epoch, not titles, process cwd, Agent state or an idle indicator.

On the currently examined Herdr candidate, guarded close is unavailable. Dry-run preview may succeed with capability unavailable shown. A mutating request returns 5 and sends no close. No destructive half-implementation is allowed. A later admitted public exact-scope guard must atomically reject changed membership; this contract does not invent such an upstream field.

Never pass group-wide intent for this feature, close individual panes as a substitute, delete repository data, stop the server or reconstruct active layouts. Detach is native client disconnection; fold is presentation where supported. Neither is a workaround for missing safe close.

## Verification scope

Tests inject changes at every boundary above, including config replacement after preview, source/ref drift, missing metadata, moved/reused native IDs, response loss and late events. Assert exact mutation calls and absence of unrelated writes, hosts, network and cleanup. Real native validation is separate and exact-version scoped; fakes cannot certify upstream behavior.

### Examined Git capability refinement

Existing-branch mode remains available for read-only preview and rejects a base. Creation returns exit 5 with zero worktree-add calls: a reviewed short local branch can be deleted before Git resolves it and trigger same-name remote fallback, even with `--no-guess-remote`; a full refs/heads argument can detach HEAD. This release preserves the no-remote-guessing constraint through capability refusal, not a client-side atomicity claim. New-branch mode passes the reviewed local commit. Importing existing worktrees is unchanged. Future positive existing-branch admission requires public capability review or an explicit requirement revision.
