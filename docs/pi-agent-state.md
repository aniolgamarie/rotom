# Pi terminal state notifications

`gentle-agent-state` runs only in the parent session and requires an explicit mode. Without configuration it refuses to load; it never discovers a global `~/.config/agent-state/scripts/agent-report.sh` automatically.

## Terminal-title mode

Use OSC titles with a compatible terminal, including native Ghostty. The title is explicitly configured; no terminal query or background script is needed.

```toml
[overrides.profiles.pi-default.agent_options.resources]
extensions = ["gentle-agent-state"]

[overrides.profiles.pi-default.agent_options.agent_state]
mode = "osc"
title = "Pi — my project"
```

Arrays replace the whole previous value, so retain any other selected extensions. The title appends working during work and blocked while an explicit user-input tool waits. Idle/exit restores the configured title. Without UI it emits no terminal control sequences. It does not inspect or guess the previous shell title.

## External reporting service

Service mode preserves the `agent-report.sh PANE STATE` convention for explicitly configured tmux/Zellij integrations. Supply actual machine paths, executable version, script closure, and socket:

```toml
[overrides.profiles.pi-default.agent_options.agent_state]
mode = "service"
executable = "/usr/bin/bash"
version = "YOUR_BASH_VERSION"
args = ["/absolute/agent-state/scripts/agent-report.sh"]
files = [
  "/absolute/agent-state/scripts/agent-report.sh",
  "/absolute/agent-state/scripts/tmux-agent-report.sh",
]
socket_paths = ["/absolute/tmux/server.sock"]
pane_env = "TMUX_PANE"
timeout_seconds = 5

[overrides.profiles.pi-default.agent_options.agent_state.environment]
TMUX = "/absolute/tmux/server.sock,0,0"
```

- Select `pi-subagents`; the service uses its existing manager/supervisor, timeout, cancellation, and independent termination proof.
- Choose exactly one of literal `pane` or `pane_env`. The latter accepts only `TMUX_PANE` or `ZELLIJ_PANE_ID`; a missing selected variable fails explicitly.
- `executable` must be a real executable, not a symlink. List the script and every adjacent script it loads in `files`; bodies and identities are rechecked before execution. Missing dependencies never fall back to global HOME.
- Only declared scripts, sockets, and system runtime libraries are mounted; no project is mounted. TCP is disabled. Unix sockets must be declared, nonsymlink endpoints owned by the current user.
- Writable state is limited to this instance's `pi-home/service-state/agent-report/`, which becomes `XDG_RUNTIME_DIR`. HOME is a per-run temporary directory.
- `environment` permits only a closed set of terminal fields; it rejects `BASH_ENV`, PATH, and credential injection. Bind extra dependencies explicitly rather than relying on install/start discovery.

Legacy scripts that inspect the terminal, global audio services, or global configuration may be rejected. Script exit 0 does not establish visible notification success.

Notifications are serialized and pending duplicates coalesce to the latest state. Completing one of several outstanding user-input requests does not prematurely show working. Exit waits at most 500 ms for notifications; remaining managed processes follow normal supervisor shutdown and no new notifications are queued.

This optional UI feature emits one fixed warning on failure without raw script errors or private terminal data. Isolated mock/type checks do not establish real tmux/Zellij or sound behavior. See [testing](testing.md) and [Pi diagnostics](pi-diagnostics.md) for current evidence requirements.
