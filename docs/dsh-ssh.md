# DSH SSH remote workspace

The `dsh-ssh` profile composes the official Core `0.2.1-rc.2` SSH providers
with the official headless runner. It submits one task per invocation and can
resume an exact persisted session through `--session-id`. Harness, model calls
and session storage stay on the invoking machine; project files, shell commands
and PTC execution use the remote provider composition.

This integration has offline configuration coverage. Real host, helper, SSH,
PTY, cancellation and sandbox acceptance are separate unverified steps. The
current TUI has consumers that still assume host filesystem paths; this profile
therefore rejects TUI and other optional plugins rather than loading that UI.
For interactive TUI work, running the complete managed DSH on the server through
an ordinary SSH session remains a separate deployment workflow.

## Preparation

Both endpoints must be Linux or macOS. Prepare an existing OpenSSH alias with
noninteractive authentication and known-host verification. The official provider
uses BatchMode, strict host-key checks, no agent forwarding and Unix socket
forwarding. Authentication remains owned by OpenSSH; do not put passwords,
private keys or their contents in agentcfg options.

Install a trusted executable SSH helper matching the selected upstream release
on the target. Preserve its complete native-resource directory layout. Place it
outside the project and outside replaced temporary directory trees; configure
its absolute executable path and the executable SHA-256 from its trusted
manifest. An executable digest alone does not authenticate a malicious server
or establish that a writable installation is safe.

At the implementation review, the public `dsh-v0.2.1-rc.2` GitHub Release had no
assets: no published helper archives or `SHA256SUMS` were available. The
`ssh-helper-runtime` source workspace is private to the upstream build and is
not an npm installation command. This profile does not download, build or deploy
a helper automatically. Obtain a trusted unmodified upstream build before
attempting real SSH acceptance; do not replace this prerequisite with a guessed
hash. See the [selected-tag helper documentation](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/ssh/ssh-helper-runtime/README.zh.md).

## Private configuration

Add an SSH option table to the existing private machine file, or adapt the
[public standalone example](../examples/dsh-ssh.local.toml). All example targets,
paths and digest values are placeholders. The all-zero digest is not a working
helper identity.

```toml
[overrides.profiles.dsh-ssh.agent_options.ssh]
host = "project-server"
workspace = "/srv/project"
helper = "/opt/dsh-helper/0.2.1-rc.2/dsh-ssh-helper"
helper_hash = "<trusted-executable-sha256>"
permission_mode = "read-only"
```

Only this profile requires those deployment parameters. An unconfigured SSH
profile does not block `dsh-default`; selecting it without the parameters fails
before deployment. Invalid options and unknown fields fail with the framework's
redacted adapter/schema diagnostic. Public reports must not include the real
alias or remote path.

The profile uses the shared API-key model defaults and existing secret-reference
mechanism on the invoking machine. It does not import another profile's OAuth
sign-ins or copy model credentials to the server. The regular `dsh-default`
profile retains its Codex/Cursor provider selections.

## Managed commands

Using an existing private machine selection:

```sh
./agentcfg --machine workstation --profile dsh-ssh validate
./agentcfg --machine workstation --profile dsh-ssh plan
./agentcfg --machine workstation --profile dsh-ssh apply
./agentcfg --machine workstation --profile dsh-ssh sync
./agentcfg --machine workstation --profile dsh-ssh run -- "Summarize the project structure without changing files"
./agentcfg --machine workstation --profile dsh-ssh run -- --json "Inspect the build configuration"
./agentcfg --machine workstation --profile dsh-ssh run -- --session-id <session-id> "Continue the analysis"
```

`validate`, `plan` and `apply` prepare configuration without connecting to SSH;
`sync` installs the fixed runtime dependencies. `run` starts the real host,
connects to the configured endpoint and may call the selected model. Real runs
retain their separate explicit authorization requirement during agent-operated
acceptance. The commands above are instructions, not an execution record.

New sessions resolve their cwd through the remote filesystem provider. Resuming
another workspace's session is refused by the official headless runner. The
profile has separate managed instance/session ownership from `dsh-default`.

## Initial capability boundary

- Default file effects are `read-only`. An explicitly configured
  `permission_mode = "workspace-write"` selects remote workspace writes; verify
  real remote confinement and approval behavior before using it. The profile
  does not offer `danger-full-access` as a managed option.
- Local filesystem and subprocess providers are replaced together with the
  sandbox provider. The shell's default cwd and policy workspace use the same
  configured remote path. The local development-environment subprocess adapter
  is not mounted. Host HOME/XDG snapshots are not sent as remote environment
  values. The public shell-env adapter also strips host `DSH_HOME` and
  `DSH_PROFILE_DIR` facts from model shell calls.
- PTC uses the official verified `ctx.ssh.ptcLaunch` capability; it does not use
  the host Node executable or bootstrap path as a remote executable.
- TUI, tmux-context, Git Worktrees, auto-review and MCP are rejected in this
  profile until their complete remote path and execution behavior is validated.
  The local TUI profile includes tmux-context and Git Worktrees independently.
- Shell background jobs/promotion and host spill retention are disabled. Remote
  provider output collection remains bounded; any retained provider output paths
  belong to the server. They must not be opened through host-local file APIs.
- Shared rules are supplied through the public system-prompt configuration;
  project instructions and files are read through the remote filesystem.
- Disconnect does not transparently reconnect or replay operations. An unknown
  mutation outcome must be inspected before retrying. The helper cleans managed
  work on connection closure or lease expiry; this is not a persistent remote
  DSH session manager.
- Sandbox file effects do not by themselves restrict network access or process
  visibility. Enforcement depends on the remote OS/backend and needs native
  evidence on that target.

See [official SSH documentation](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/ssh/ssh/README.zh.md),
[upgrade/plugin plan](acceptance/dsh-plugin-ssh-assessment-20261017.md) and
[testing boundaries](testing.md).
