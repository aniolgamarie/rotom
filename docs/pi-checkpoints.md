# Pi code checkpoints

`git-checkpoint` stores persistent code snapshots in the current agentcfg instance. It restores ordinary file contents and permission bits within an explicit scope. It does not switch branches, restore the Git index, call `git stash`, or run project Git filters.

## Configuration

Select the extension and scope in private local configuration. Merge other required extensions into this array, which replaces the existing selection:

```toml
[overrides.profiles.pi-default.agent_options.resources]
extensions = ["git-checkpoint"]

[overrides.profiles.pi-default.agent_options.checkpoints]
paths = ["src", "tests"]
max_files = 2000
max_bytes = 33554432
max_checkpoints = 100
```

Also select `pi-subagents` for the existing manager queue. Declare the project root in `agent_options.paths.roots`; cwd must belong to it and its Git worktree identity must be verifiable. FilePolicy must permit `ls/list` and `read/read` for capture. Restore additionally requires `write/write`, `write/create` for new files, and `edit/delete` for deletions. Parent deny rules, read-only roots, and secret roots remain effective.

Selecting the extension grants no permissions. If a restore needs a missing permission, including delete, the whole restore is rejected before modifying files.

## Operation

- `turn_start` attempts a checkpoint associated with the current session leaf. `agent_end` no longer clears snapshots.
- `/checkpoint` saves the current state manually.
- `/checkpoint-restore` lists checkpoints matching this session/workspace/permission scope. `/checkpoint-restore FULL_ID` selects a particular snapshot.
- Forking from a checkpointed node previews write/delete counts in UI. Restore requires an explicit choice; there is no automatic restore without UI.

Changes after preview invalidate restore and require a new preview. A pre-restore backup is saved before execution. Mid-operation failure reports `partial` and cancels that fork rather than claiming success. Its backup ID can be previewed and restored.

Capture/restore acquires the shared cross-instance worktree lease. Other writers or unfinished unknown execution block it. Completion requires a helper exit record plus independent physical termination proof; a cancellation acknowledgment is insufficient.

## Scope and storage

Only policy-permitted, ordinary single-link files are captured, including eligible untracked files. `.git`, `.ssh`, `.pi`, `.codex`, `auth.json`, `.env`, and `.env.*` are excluded before reading bodies. Deny other secret directories through parent policy or machine roots.

The per-file limit is 1 MiB. Exceeding file-count or total-byte limits fails rather than truncating a supposedly complete snapshot. Symlinks, special files, and directories are not restored as ordinary files; empty directory structure is not snapshot content. Files newly added within scope but absent from the target snapshot require delete permission. The index, branches, and out-of-scope files are excluded.

Metadata and bodies are stored separately with private permissions in the instance's `pi-home/checkpoints/`. They are excluded from public configuration, generic logs, and synchronization sources. Session, project/directory identity, policy, scope, and runtime must match; snapshots from other identities are not adopted automatically. Theme/quota changes do not invalidate an otherwise identical file scope.

At `max_checkpoints`, new capture is refused without deleting history. Adjust the source limit if needed; there is no automatic cleanup command.

The previous implementation held `git stash create/apply` references only in memory and cleared them on agent end. Migration neither reads/converts those stashes nor deletes Git records. These snapshots are not a Git stash format/merge compatibility layer. Native Git/index/merge work requires separately authorized Git operations.

Current release evidence must match the current runtime identity. Isolated tests and historical event checks do not establish current native loading or event ordering; see [testing](testing.md) and [Pi diagnostics](pi-diagnostics.md).
