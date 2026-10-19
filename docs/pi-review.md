# Pi interactive review and editor

> Historical reference for the retired Pi SDK/four-profile integration. Its commands, roles,
> plugins and support claims do not apply to current Base/Pro and must not be used as current
> operating instructions. The original body remains for historical scope only. See the
> [current Pi guide](pi.md), [migration boundary](pi-migration.md) and [support matrix](pi-support.md).


`pi-slopchop` preserves diff, last-commit, whole-file, submodule, annotation-shortcut, and feedback views. The derived version is `0.10.1-agentcfg.1`; its complete source and MIT license are in the four-profile source closure. This does not establish current-lock or native UI acceptance; see [testing](testing.md).

## Explicit bindings

Select `pi-slopchop`, `pi-subagents`, and `pi-permissions` in the target profile's `plugins`, retaining other required entries. Supply actual paths/versions in private configuration:

```toml
[overrides.profiles.pi-default.agent_options.paths.roots.project]
path = "/absolute/path/to/checkout"
purpose = "project"

[overrides.profiles.pi-default.agent_options.slopchop]
git_tool_ref = "review-git"
editor_tool_ref = "review-editor"

[overrides.profiles.pi-default.agent_options.external_tools.review-git]
executable = "/absolute/path/to/git"
version = "YOUR_GIT_VERSION"
args = []
project_root = "project"
read_roots = ["project"]
write_roots = []
timeout_seconds = 30

[overrides.profiles.pi-default.agent_options.external_tools.review-editor]
executable = "/absolute/path/to/nvim"
version = "YOUR_NVIM_VERSION"
args = ["--clean", "+{line}", "--", "{path}"]
project_root = "project"
read_roots = ["project"]
write_roots = ["project"]
interactive = true
timeout_seconds = 1800
```

Git must be read-only, noninteractive, with no custom arguments. The dedicated interface generates fixed review arguments. NUL-delimited inventories preserve spaces, newlines, and Unicode. Hooks, external diff/textconv, fsmonitor, global configuration, and automatic object downloads are disabled.

The editor is optional; edit reports a missing binding if omitted. Arguments support one standalone `{path}` plus optional `{line}`/`+{line}`, with `--` before the file. There is no EDITOR discovery or shell string construction. `--clean` is Neovim-specific; other editors need their own isolation arguments.

Grant commands in the selected Permission Policy source:

```json
[
  {"id":"review-git","kind":"command","effect":"allow","command_ref":"tool:review-git","tool_ids":["bash"],"operations":["execute"]},
  {"id":"review-editor","kind":"command","effect":"allow","command_ref":"tool:review-editor","tool_ids":["editor"],"operations":["execute"]}
]
```

Review bodies still require file-read permission. File denies and role caps remain effective. Never expand permissions by editing the generated manifest.

## Workspace and terminal behavior

Review queries and editors use cross-instance worktree leases. Active candidates, other writers, and unknown termination block operations. Nested repositories protect both parent/child workspaces. Read-only submodule access verifies metadata inside the declared parent repository's modules directory.

Editor write scope is the complete declared `write_roots`, not just the opened file. Set roots accordingly. `.git`, protected state, and denied paths remain unwritable. Networking is disabled and HOME is private; global editor configuration is not loaded automatically.

The supervisor creates a private PTY and forwards input, screen output, and resize through its control interface. The controlling terminal is assigned only after execution authorization. Missing output, unconfirmed input, or unknown termination prevents success. Cancellation must be followed by physical termination proof before workspace protection is released.

Shortcut/annotation settings come from `agent_options.slopchop.shortcuts`, not old `~/.pi` or project `slopchop.json`. Invalid formats and key conflicts fail explicitly.

## Evidence boundary

Plugin type checks, deterministic archives, and isolated Git/file/editor admission, PTY forwarding, and execution-gate tests cover implementation contracts. They do not establish current real keyboard/refresh behavior, submodule combinations, macOS terminal behavior, or platform termination. The Pi 0.84.4 complete lock has been rebuilt; historical native/cold evidence remains limited to its recorded candidates; see [Pi diagnostics](pi-diagnostics.md) and [known issues](known-issues.md).
