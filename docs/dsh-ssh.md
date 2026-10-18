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
helper assets: no helper archives or `SHA256SUMS` were available. The
`ssh-helper-runtime` source workspace is private to the upstream build and is
not an npm installation command. This profile does not download, build or deploy
a helper automatically. Automatic helper management is outside the selected scope.

### Manual helper installation

Follow the [version-matched official installation instructions](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/ssh/ssh-helper-runtime/README.zh.md#use-this-package).
The [selected Release assets](https://github.com/deepseek-ai/deepseek-harness/releases/expanded_assets/dsh-v0.2.1-rc.2)
checked on 2026-10-18 contained source archives and attestation, with no helper
binaries or checksums. Source archives cannot be installed as helper executables.

1. Obtain the matching official helper archive and its `.sha256` or
   `SHA256SUMS`, or build an unmodified checkout of the selected upstream tag
   using its locked dependencies and native prerequisites. The official build
   command is `pnpm exec tsx scripts/build-exe-for-ssh-helper.ts`; outputs go
   under `dist-exe/ssh-helper/`. Node 24, compiler/header and platform-specific
   prerequisites are described in the linked instructions.
2. Verify the archive checksum. Extract the complete distribution into a
   versioned directory outside the project and replaced temporary mounts.
   Preserve executable/native-resource paths, licenses and `manifest.json`.
3. Set `helper_hash` to the executable SHA-256 from that verified manifest.
   The archive checksum identifies different bytes; do not substitute it or a
   guessed hash. Configure the remote executable path and project path below.
4. Retain trusted build provenance and complete the official native/SSH
   validation for the target platform before treating the installation as
   accepted. Keep the previous helper version while validating a replacement.

See the [official native build workflow](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/.github/workflows/build-exe-for-ssh-helper.yml).
Rotom has not built or installed a helper. This topology keeps model credentials
on the invoking machine.

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

The profile keeps shared API-key model defaults. To additionally select the
`codex` and/or `cursor` subscription providers, enable the repository-owned
`ssh-subscription-auth` plugin in the private machine file:

```toml
[overrides.profiles.dsh-ssh]
providers = ["codex", "cursor"] # select either or both
plugins = ["ssh-subscription-auth"]
```

Authentication and model requests remain on the
invoking machine. It does not import another profile's sign-ins or copy model
credentials to the server; sign in once in this profile's own instance. The
regular `dsh-default` profile retains its existing login integration.

Leave these additions absent for the existing API-key-only composition.
Model/provider selections are additive across model-default layers; an empty
array does not remove a provider selected by an earlier layer. To return to
API-key-only, remove the subscription selection and its plugin together.
Unknown OAuth provider ids and subscriptions without the matching plugin are
rejected.

## Subscription authentication

After preparing the managed profile, use these explicit operations:

```sh
./agentcfg --machine workstation --profile dsh-ssh run -- --subscription-auth codex login
./agentcfg --machine workstation --profile dsh-ssh run -- --subscription-auth codex status
./agentcfg --machine workstation --profile dsh-ssh run -- --subscription-auth codex models
./agentcfg --machine workstation --profile dsh-ssh run -- --subscription-auth cursor login
./agentcfg --machine workstation --profile dsh-ssh run -- --subscription-auth cursor models
./agentcfg --machine workstation --profile dsh-ssh run -- --subscription-auth cursor logout
```

Both providers accept `login`, `status`, `models` and `logout`. Login requires
a private interactive terminal. Manual-code prompts show `/1`, `/2`, etc. for
actions; plain numeric input remains a hidden code. Authorization links/codes
and manual responses stay outside task/session output. Status prints selected sign-in
facts; models prints model ids. Model listing may contact the provider. These
operations start no task, connect no SSH and invoke no model. The manager takes
the instance's exclusive lifecycle lock; active tasks must exit normally first.

The integration uses public authentication exports from the fixed TUI package
and Cursor plugin without mounting a TUI surface. Codex credentials live under
this instance's `$DSH_HOME/dsh-auth/credentials.json`; Cursor uses the official
local credential service and accepts only its managed file source. Token
protocols, persistence and refresh remain owned by upstream components.
Cursor's upstream refresh queue is in-process only: cross-process token
rotation has not been established, so do not run parallel Cursor tasks in this
profile until that behavior is accepted.

Authentication does not change the selected main model. After listing the
account's models, define a model and select it for this profile (the id below
is a placeholder). Merge values into existing TOML tables rather than adding
duplicate table headers:

```toml
[overrides.models.ssh-subscription-main]
provider = "codex" # use "cursor" for Cursor subscription models
remote_id = "<model-id-from-models-output>"
input = ["text"]

[overrides.profiles.dsh-ssh]
models = ["ssh-subscription-main"]

[overrides.profiles.dsh-ssh.roles]
main = "ssh-subscription-main"
```

Apply the model selection before running tasks. Codex maps to `openai-codex`
and Cursor to `cursor-subscription`. API-key models keep the existing secret
references. Real terminal login, refresh and model calls remain unverified;
the checked behavior uses synthetic stores, fake providers and blocked network.

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
  The only admitted SSH plugin is the host-side subscription adapter; accepting
  it does not enable remote TUI consumers.
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
