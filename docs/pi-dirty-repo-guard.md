# Pi Git status checks before session changes

> Historical reference for the retired Pi SDK/four-profile integration. Its commands, roles,
> plugins and support claims do not apply to current Base/Pro and must not be used as current
> operating instructions. The original body remains for historical scope only. See the
> [current Pi guide](pi.md), [migration boundary](pi-migration.md) and [support matrix](pi-support.md).


`dirty-repo-guard` checks an explicitly declared Git worktree before creating, switching, or forking a session. Fixed Git queries run through the existing `pi-subagents` manager and agentcfg supervisor rather than direct `pi.exec`.

## Configuration

Use actual project/executable paths and the installed Git version. Extension arrays replace previous selections, so retain other required extensions:

```toml
[overrides.profiles.pi-default.agent_options.resources]
extensions = ["dirty-repo-guard"]

[overrides.profiles.pi-default.agent_options.paths.roots.project]
path = "/absolute/path/to/checkout"
purpose = "project"

[overrides.profiles.pi-default.agent_options.dirty_repo_guard]
tool_ref = "git"

[overrides.profiles.pi-default.agent_options.external_tools.git]
executable = "/absolute/path/to/git"
version = "YOUR_GIT_VERSION"
args = []
project_root = "project"
read_roots = ["project"]
write_roots = []
timeout_seconds = 20
```

Select `pi-subagents` and add an explicit command authorization to the selected Permission Policy's source `rules`:

```json
{
  "id": "git-status",
  "kind": "command",
  "effect": "allow",
  "command_ref": "tool:git",
  "tool_ids": ["bash"],
  "operations": ["execute"]
}
```

Edit policy sources, never generated `agentcfg-manifest.json`. Extension selection grants no Git permission and changes no deny rules. The binding must be read-only, noninteractive, and free of custom arguments; the dedicated entry supplies fixed status arguments. Ordinary Bash/editor commands retain their existing `.git` isolation.

## Results

| Observation | Session action |
| --- | --- |
| Clean repository | Continue |
| Uncommitted/untracked files | Require explicit UI Continue; dismissal or no UI cancels |
| Declared directory is not a worktree and has no ancestor Git marker | Continue without starting Git |
| Missing Git, damaged marker, denied access, timeout, truncated output, stderr warning, or unknown termination | Cancel; never report clean |
| Another managed writer or uncollected controlled task result | Cancel until the operation is completed/collected |

The declared project must be the actual worktree root. Starting in its subdirectory checks the whole worktree. Nested repositories, a misdeclared subdirectory root, or damaged metadata never silently become nonrepositories. Verified ordinary and linked worktrees are admitted; linked worktree private/common Git directories are explicitly mounted read-only and rechecked before execution.

Checks share cross-instance workspace leases with writers. Completion requires an exit record, captured-output digest, and independent physical termination proof. Worktree/metadata are read-only and networking is disabled. Git optional locks, fsmonitor, hooks, automatic object fetch, and user/system configuration are disabled. Project Git configuration still contributes semantics; filters or external object paths outside the sandbox may fail, cancelling the switch.

A complete status check requires the complete declared scope. A machine/FilePolicy deny on any worktree or necessary metadata subpath rejects the check rather than hiding files and reporting clean. Keep such denies and leave this extension unselected if appropriate; checkpoints can independently use a smaller scope.

The fixed query is `git status --porcelain=v1 -z --untracked-files=all --ignore-submodules=none`. NUL-delimited names preserve newlines; a rename counts as one item. Results follow Git index, ignore, and sparse-worktree semantics; this is not a monitor for arbitrary external writes.

## Evidence

Isolated Python/Node, type-check, and historical native evidence must be interpreted by identity and platform. No documentation rewrite establishes current Git sandbox/session behavior. See [testing](testing.md), [Pi diagnostics](pi-diagnostics.md), and [known issues](known-issues.md).
