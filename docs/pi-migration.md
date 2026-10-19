# Pi reboot migration boundary

`pi-default`, `pi-managed`, `pi-cursor` and `pi-codex` are retired public profile IDs.
They are rejected rather than redirected to `pi-base` or `pi-pro`. The new adapter does not
load the old SDK loop, Task Keeper, AgentManager, model-delegate, permission bridges or old plugins.
The [retirement inventory](../specs/005-rebuild-pi-toolkit/retirement-inventory.md) records
source mapping and deletion prerequisites; the [execution record](../specs/005-rebuild-pi-toolkit/retirement-execution.md)
lists retired repository artifacts and retained legal/history boundaries. Repository retirement does
not imply user-state migration or native/account acceptance.

## Existing state stays owned by its existing instance

No catalog change deletes or imports native homes, OAuth/trust, sessions/history, user preferences,
old task databases, reports, backups, caches, activity records or worktree ownership markers.
Do not copy authentication to the new profiles. Prepare a new isolated Base/Pro instance and
perform any required native login there through your own explicit authorized action.

Preserve old configuration, state and account locations until their ownership and recovery needs
are understood. Active or unknown old owners block unsafe maintenance; a parent process exiting
or a cancellation acknowledgment is insufficient proof that descendants released resources.
Do not automatically stop, adopt, resume or replay old work. Unknown ownership requires an explicit
trusted investigation and remains a conflict until its resources can be proven released.

Old task recovery is not a new product startup prerequisite. Historical recovery commands and
records must not be used to continue distributing the retired execution platform. Stop using
those task routes and retain their data in place; any later private archive is a separate owner action.
Never delete a marker, database or session merely to make the new configuration deploy.

## Review a new deployment

Use the [new guide](pi.md) and review explicit lock/sync/plan/apply operations. Keep one writer for
a given target; do not point old and new managers at the same native home. Resolve conflicts
rather than overwriting unmanaged data. Nonempty targets are not automatically adopted.
UI initialization preserves preferences only within an already legitimate ownership boundary.

Public pending/rollback recovery restores managed configuration while preserving unmanaged additions.
It does not migrate task databases, downgrade runtime packages or undo tool effects. New run ownership
uses a Linux child-subreaper observation established before spawn. Only complete kernel evidence
releases that run; live descendants, unsupported observation or manager failure preserve unknown
and block maintenance. This does not clear historical unknown ownership.

`plan --from-pi-home` is a metadata-only inventory proposal, not an adoption or conversion command:

```sh
./agentcfg --local /private/config/pi-base.toml --profile pi-base plan --from-pi-home /private/old-pi-home
```

The paths are illustrative. The command writes a private count proposal, does not read authentication,
model bodies or session contents, and does not copy models, import accounts or automatically adopt a
home. Starter comparison (`--from-starter`) is unsupported. Keep opaque legacy owner markers in
place: nonempty old activity/lease state or worktree ownership blocks unsafe managed startup or
maintenance, without interpreting or deleting its body. Inventory output cannot clear that gate.
Use the new [Base](../examples/pi-base.local.toml) or [Pro](../examples/pi-pro.local.toml) binding
shape; only `roles.main` is supported. Then explicitly resolve the selected local dependency inputs
with `--local ... --profile pi-base lock --agent pi`, as described in the [guide](pi.md).

Current support is limited to the scope in [Pi support](pi-support.md). The old SDK/supervisor
platform and its recover/project commands are absent from current distribution. Historical guides
remain historical references, not executable instructions for Base/Pro. Linux manager rebuilding
and isolated tests do not establish macOS, native terminal, account or model acceptance.
