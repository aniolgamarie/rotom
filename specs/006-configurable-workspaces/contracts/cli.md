# CLI contract (implemented; native acceptance separate)

These spellings define the implemented structured CLI. Capability-gated operations refuse rather than dispatching an unsafe substitute. [Configuration](configuration.md), [lifecycle](lifecycle.md) and [native API](native-api.md) define validation, identity and operation handling.

## Invocation and common behavior

Syntax is `work [--machine ID | --local FILE] COMMAND`; bare `work` opens the candidate/action selector. Global options precede the subcommand, are mutually exclusive and use existing machine-selection defaults when absent. No implicit selection is saved. Structured commands require explicit structured opt-in and defined templates. The selector is optional: complete explicit CLI actions work without fzf. Missing required noninteractive input fails with exit 2; no inferred profile, mode, template or permission substitutes for it.

The selector uses opaque IDs mapped to in-memory candidates; display text is never evaluated. Esc/cancellation before confirmation has no current-action effects. Full explicit saving/creation arguments authorize their stated action directly. `--dry-run` previews without writing configuration, creating a new lock file, operation receipt, branch, checkout or native object. A previous separately confirmed action remains complete.

## Command surface

```text
work [--machine ID | --local FILE]
work [--machine ID | --local FILE] list [--json] [--live]
work [--machine ID | --local FILE] source add --id ID --path PATH --mode MODE --template NAME [--depth N] [--include-hidden] [--exclude GLOB] [--follow-symlinks] [--dry-run]
work [--machine ID | --local FILE] project add --path PATH --mode MODE --template NAME [--dry-run]
work [--machine ID | --local FILE] named add --id ID --title TITLE --template NAME [--start-path PATH] [--dry-run]
work [--machine ID | --local FILE] named enter ID
work [--machine ID | --local FILE] named rename ID --title TITLE [--dry-run]
work [--machine ID | --local FILE] enter PATH
work [--machine ID | --local FILE] open [TYPE] [--new]
work [--machine ID | --local FILE] rebind TYPE [--accept]
work [--machine ID | --local FILE] config check
work [--machine ID | --local FILE] config edit
work [--machine ID | --local FILE] worktree create --repo PATH (--new-branch NAME --base LOCAL_REF | --existing-branch NAME) --path DEST --template NAME [--enter] [--dry-run]
work [--machine ID | --local FILE] status [--json]
work [--machine ID | --local FILE] reconcile [--json]
work [--machine ID | --local FILE] close [--dry-run | --scope TOKEN --yes]
```

| Command | Contract |
| --- | --- |
| `list` | Default offline configuration/discovery only. Show canonical paths/origins, selected templates and named IDs/titles. `--live` queries only an already running selected endpoint; it never starts it. |
| `source add` | Save a rule, not its current candidate snapshot. `MODE` is `git` or `directory`; depth defaults to 1, hidden exclusion to true, no symlink following. `--include-hidden` sets `exclude_hidden = false`; repeatable `--exclude` builds basename-glob exclusions. Preview bounded candidates and proposed fragment. |
| `project add` | Save one existing project with explicit mode/template. Preview actual canonical registration boundary; Git may resolve a subdirectory to checkout root, directory mode never climbs. Importing a worktree creates no checkout/branch. |
| `named add` | Save ID/title/template and optional existing start directory only. Omitted start means caller HOME. Entry is a separate command; same start directories do not merge named IDs. |
| `named enter` | Resolve exactly the saved ID at the verified endpoint, then enter or safely create its independent ordinary workspace. |
| `named rename` | Save title first under the config lock, preserving ID/binding. After lock release, a verified live binding permits public native rename. A native failure/unknown result leaves the saved title intact and reports partial success; no compensating config rewrite. No live verified binding means configuration-only rename, with an explicit synchronization diagnostic where needed. |
| `enter PATH` | Resolve one confirmed source/explicit/built-in project and its mode/template before side effects. Refuse absent/ambiguous coverage and unknown ownership; do not guess legacy fallback. |
| `open` | With no TYPE, select from the ordered configured types and verified existing instances. With TYPE, focus the verified default or create it when safely absent. `--new` always creates an extra, even before any default exists, without promoting it; later plain open creates the default using the same fixed binding. No focus-time input injection, cwd change or restart. Legacy semantics remain unchanged. |
| `rebind TYPE` | Only in the verified current workspace and with no active instances of that type. Review the newly resolved cwd/launcher contract and require explicit acceptance. Noninteractive use requires `--accept`. Unknown outcomes or unprovable absence block it. |
| `config check` | Offline read-only complete schema, reference, path and conflict checks. No host, selector, editor, credentials or install. |
| `config edit` | Invoke explicitly configured `machine.editor` as one executable on a private non-secret `machine.work` fragment while holding the shared config lock; validate/merge safely or leave original intact. Never open the whole private file or install software. |
| `status`, `reconcile` | Read only the selected endpoint and private receipts to explain verified, stale, partial or unknown outcomes. No mutation, retry, adoption, automatic write or cleanup. Lack of proof remains unknown. |

Saving source/project/named configuration never enters it or launches terminal processes. All saves share the configuration contract's cooperative lock, preservation and external-edit refusal behavior. CLI, selector and manual TOML use one schema and configuration; no second registry exists.

Registration previews include canonical resulting candidates and discovery diagnostics before saving; the selector also displays candidate mode. An initial unsafe/read-only configuration refusal may provide an explicit-input-only manual fragment, marked as unverified against existing references/conflicts. It never reads an unsafe file or reports a saved configuration. With no safe context or explicit entry, `config edit` provides commented guidance only.

Structured type operations retain one deadline through locking, connection, verified context, preparation and dispatch: 30 seconds for ordinary launch contracts, 60 seconds for Pi/DSH. Open/focus uses an existing fixed binding when present, including removed types; rebind uses the selected current definition. A same-named type in another template cannot change that budget. Interactive selection/confirmation precedes the authorized operation's deadline.

Removed types have only specific recorded-instance, focus-only selector actions, with live proof still checked on selection. They never appear as default creation, new extra or rebind choices; a removed type with no recorded instance contributes no row. Current configured types retain their normal create/extra/rebind actions.

## Worktree creation

Only a registered Git project is eligible. Exactly one branch mode is required: a new branch with an explicit local base, or an existing unoccupied local branch without `--base`. No fetch or remote guessing. Refuse existing destinations, duplicate new names and occupied branches. Destination must already have visible source coverage; an uncovered parent-source addition is a separately confirmed save followed by a fresh creation preview. Do not register nonexistent projects or derive parent coverage from the built-in Rotom candidate.

Before interactive create-only/create-and-enter confirmation, show the reviewed branch/base/commit/destination/template, repository/common/git-directory identities, destination source coverage rules and non-secret configuration identity. The presentation selects approved plan fields and summarizes Git configuration metadata without dumping the whole plan or local configuration. After an independently saved source, it uses the renewed plan. Presentation never substitutes for dispatch-time revalidation.

Review resolved repository/refs, branch mode, destination, template and configuration; recheck immediately before dispatch. Drift requires refusal or renewed review. Use per-invocation empty private `core.hooksPath` and disabled external fsmonitor, preserving persistent Git config. Detect executable checkout filters and refuse with the documented limitation; hook suppression alone does not suppress every possible Git subprocess. No force/reset/deletion/stash, dirty-change copy, bootstrap, dependency installation, secret copy or service launch.

Default is create only. `--enter` requests ordinary independent workspace entry only after successful creation. Git success followed by entry failure preserves the checkout and reports explicit `enter` retry guidance. Git timeout/failure may have partial effects: retain evidence and require read-only reconciliation without blind retries or automatic deletion. See [lifecycle](lifecycle.md).

## Close and capability refusal

Close always refers to the verified current workspace. `--dry-run` produces a read-only preview of stable identity, every tab/pane, all viewing-client effects and an opaque scope token. Bare interactive close reviews the same scope and requires explicit acceptance. Noninteractive mutation requires both `--scope TOKEN` and `--yes`; a bare `--yes`, token alone or `--dry-run` combined with authorization fails. A token is scope correlation, not a server-side guard.

Herdr 0.9.5 lacks the required public atomic membership/identity guard. Therefore every mutating form, including accepted interactive close and a matching scope token, returns exit 5 with zero close calls. A future verified public atomic guard is required before enabling dispatch; repeated client reads or a Rotom lock do not satisfy it. Scope/ownership drift returns 4, and unsupported native capability returns 5. Do not close enumerated panes, reconstruct layouts, use grouped close or stop the server as a substitute. Checkout, branch and configuration remain outside close scope. Use native detach/fold directly; no new wrapper command is introduced.

## Output and exit codes

Human and JSON outputs preserve outcome distinctions: success, unchanged, conflict, partial success, stale and unknown. JSON contains typed candidate identities/origins and operation evidence appropriate to the command, never credentials or terminal/session contents. A configured candidate is not necessarily open. Endpoint unavailability, a missing marker or unresolved receipt cannot turn an opened/unknown sidebar entry into closed without authoritative absence evidence. Status is never task-completion or closure permission.

`status` and `reconcile` never update registration. A later invocation of the original command may finish local registration only after authoritative evidence establishes its accepted completed operation; it does not resend creation or exec. Unresolved outcomes remain blocked pending evidence.

| Exit | Manager result |
| --- | --- |
| 0 | Success; may include drift or login-needed guidance where permitted by the existing contract |
| 2 | Argument, configuration or lock validation error |
| 3 | Required credentials missing |
| 4 | Ownership conflict, active-instance conflict or recovery pending/unknown |
| 5 | Dependency/native capability check failure or required runtime missing |
| 6 | Filesystem/internal operation failure |

Direct terminal, Agent and attach exec preserves the actual child exit code. `config edit` has two phases: an editor failure preserves its failure exit code and publishes nothing; editor success proceeds to manager validation/publication, which may return 2 for invalid configuration, 4 for conflict or 6 for filesystem/internal failure. An editor exit of 0 does not establish manager success. A partial operation reports both completed and unresolved effects rather than claiming rollback.

### Examined Git capability refinement

Existing-branch mode remains available for read-only preview and rejects a base. Creation returns exit 5 with zero worktree-add calls: a reviewed short local branch can be deleted before Git resolves it and trigger same-name remote fallback, even with `--no-guess-remote`; a full refs/heads argument can detach HEAD. This release preserves the no-remote-guessing constraint through capability refusal, not a client-side atomicity claim. New-branch mode passes the reviewed local commit. Importing existing worktrees is unchanged. Future positive existing-branch admission requires public capability review or an explicit requirement revision.
