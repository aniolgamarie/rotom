# DSH plugin and SSH assessment — 2026-10-17

Candidate: Core `0.2.1-rc.2` with unmodified TUI source commit
`e709863019d56897e64495699c3a945cce194d00`. This is an assessment;
no plugin installation, deployed configuration change or remote connection was performed.
See [upgrade validation](dsh-rc21-tui-main-20261017.json).

Implementation follow-up: [worktree implementation record](dsh-ssh-implementation-20261017.json)
and [SSH usage and limits](../dsh-ssh.md). The assessment below records the
initial decision; the follow-up distinguishes implemented configuration from
pending native/deployment evidence.

## Selected upgrade scope

The user selected the following scope after the assessment. Inclusion in the
plan does not mark a component as implemented, enabled or accepted in runtime.

| Order | Work | Status and acceptance boundary |
| --- | --- | --- |
| 1 | Core `0.2.1-rc.2` and the fixed TUI main commit | Candidate built and checked; real host/account acceptance remains pending. |
| 2 | Official SSH remote workspace | Selected priority because server projects are a frequent workflow; separate profile composition and remote validation are pending. |
| 3 | Official `dsh-tmux-context` | Selected for integration; check the effective composition before adding a row, then verify actual-pane detection and no-op outside tmux. |
| 4 | Official experimental Git Worktrees | Selected for integration; verify worktree creation, Session directory changes and file-policy behavior, preserving existing worktrees and branches. |

### Implementation review corrections

- The current TUI workspace registry directly canonicalizes host paths. Its
  public provider extension does not replace every internal path consumer.
  The first SSH integration therefore uses the official headless bundle;
  loading TUI in that profile is rejected. Local interactive TUI remains intact.
- Tmux location detection uses the Harness process's terminal but queries its
  shell service. Moving that shell to SSH would mix host and target coordinates.
  Tmux-context is therefore enabled only in the local TUI composition.
- Git Worktrees remains a local-composition capability until the SSH combination
  has its own evidence. MCP and Perry auto-review are also excluded from the
  first SSH profile, and writes default to read-only.
- The selected release has no published SSH helper assets. A trusted helper
  installation and its digest are prerequisites for actual SSH acceptance;
  no automatic helper deployment is implemented.

Tmux completion notifications are deferred at the user's request. Do not change
notification settings or tmux notification/focus options as part of this upgrade.
Web access and the three Web UI plugins also remain deferred.

Integration preparation uses repository/temporary homes, fake processes and
isolated tests. Starting a real third-party host or connecting to an actual SSH
endpoint is a separate explicitly authorized validation step, following the
repository's existing test boundary. Account/session/configuration ownership and
active-instance protection remain in force.

## Completed

- Existing TUI/auth, Cursor, Perry and repository adapters passed the candidate's
  frozen installation and public module identity/import checks. These checks do
  not mount the host, authenticate accounts or exercise reviewer lifecycle.
- Cursor `0.6.12` still declares peers for the older DSH prerelease line.
  Installer peer warnings remain, but the selected app-boot uses semver
  `includePrerelease: true`, under which `0.2.1-rc.2` satisfies
  `^0.2.0-rc.2`. Static inspection also confirms that the current direct row
  names the repository terminal adapter rather than recursively gating its
  dependencies. This is not a demonstrated startup blocker; actual provider
  behavior remains unverified.
- Perry `0.12.17` retains the lifecycle, OFF persistence and audit limitations
  recorded in [known issues](../known-issues.md). The upgrade does not fix them.
- The repository-owned review-context and execution-environment adapters now
  declare their corresponding public Core APIs at `0.2.1-rc.2`.
- [Better Sidebar](https://github.com/omdsh-dev/DSH-better-sidebar) declares a
  Web client and requires DSH `0.2.1-rc.1` or newer. The candidate meets that floor;
  this does not prove full runtime compatibility or TUI rendering.
- [dsh-context](https://github.com/bowenliang123/dsh-context) declares a Web
  client. Its `/context` opens a browser dialog. Its explicit compatibility matrix
  currently lists `0.1.7-rc.2` and `0.2.0-rc.2`, not the selected `0.2.1-rc.2`.
- [Annotation](https://github.com/omdsh-dev/dsh-annotation/blob/main/README.zh-CN.md)
  implements browser selection and DOM decoration; it provides no TUI interface.
  These three plugins remain deferred with Web access.
- The selected TUI source already provides context/status panels and task
  completion notifications. Its documented tmux integration requires
  `allow-passthrough on` for OSC notifications and `focus-events on` for focus
  reporting. End-to-end delivery depends on the client terminal.

## Selected optional integrations

- `@deepseek-ai/dsh-tmux-context`: already present in the candidate's complete
  lock. The [official README](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/context/tmux-context/README.md)
  describes opt-in context about the actual Harness tmux pane/session/window;
  it does not share sibling-pane contents. It is selected for the upgrade plan.
  Current effective profile activation has not been verified. This context
  describes the pane containing the Harness process; it must not be presented
  as the SSH target's pane when Harness runs on another machine.
- `@deepseek-ai/dsh-experimental-worktree` plus
  `@deepseek-ai/dsh-experimental-tool-worktree`: already present in the lock.
  The [selected-tag tool documentation](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/experimental/tool-worktree/README.md)
  describes an optional, disabled-by-default bundle that creates a worktree and
  branch and changes the calling Session's directory. It does not merge or
  remove checkouts. It is selected for integration, subject to the repository's
  existing worktree/publication rules; it remains experimental and has not been
  exercised in this TUI composition. Verify it first with a disposable Git
  repository. Compatibility with SSH-provided paths and remote Git execution
  must be established separately before enabling the same tool in the SSH
  profile; a remote path must never fall through to local Git/filesystem access.

## Selected SSH sequence

1. Prioritize a local Harness operating on remote files/processes. Prepare a separate
   profile using the official `@deepseek-ai/dsh-ssh`, `dsh-fs-ssh`,
   `dsh-subprocess-ssh` and `dsh-sandbox-ssh` family at the selected Core release.
   Replace the local provider composition coherently; the current development
   subprocess adapter subclasses the local provider and cannot simply be stacked
   over a remote provider. Keep host and remote environment/path ownership distinct.
2. Prepare the pinned remote helper installation and existing OpenSSH alias
   integration without copying private keys or account configurations into the
   managed recipe. Record helper provenance/digest and a rollback path. The
   target alias and remote workspace are deployment inputs, not public defaults.
3. Validate composition, environment/path separation and failure handling with
   fake processes first. For an authorized real endpoint, begin with remote
   read-only operations, then commands, terminals, cancellation, disconnect
   handling, workspace write restrictions and approvals before enabling writes.
4. Explicitly decide where PTC and MCP execute. TUI consumers of paths also need
   validation; upstream documents headless/custom compositions rather than a
   universal remote UI guarantee. Prove there is no local filesystem/process
   fallback for remote operations and no accidental host HOME/XDG path propagation.

Ordinary SSH into a server running the whole DSH remains a supported alternative
workflow to assess separately; tmux notification work is outside this plan.

The [official SSH documentation at the selected tag](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/ssh/ssh/README.zh.md)
requires Linux/macOS endpoints, an existing OpenSSH alias and known-host setup,
socket forwarding and a preinstalled helper with a pinned digest. It provides
neither interactive authentication nor automatic reconnect/replay. Helper cleanup
on disconnect/lease expiry differs from keeping a whole remote DSH session alive
inside tmux.

[flymysql/dsh-remote](https://github.com/flymysql/dsh-remote) remains a secondary
candidate for multi-machine/SFTP needs. Its mirror and separate `rw_*` tools need
approval/sandbox integration review; default self-updating also conflicts with a
fixed managed lock unless disabled.
[aijunjiang/dsh-remote-ssh](https://github.com/aijunjiang/dsh-remote-ssh) full mode
disables local sandbox/permission preset components and lacks remote PTY support;
it is not selected for the daily profile. Its optional upstream source patches
are excluded by repository policy.

## In progress

Repository implementation is complete in the dedicated upgrade worktree; see
the linked implementation record for test results and remaining native limits.
No deployed instance has been changed.

## Failed pending decision

None. Installer peer warnings and existing limitations remain explicit;
they are not recorded as functional passes.

## Environment unverified

- Real host/TUI startup, authenticated provider requests and Perry lifecycle on
  the candidate have not been exercised.
- No actual SSH endpoint, remote helper, sandbox or disconnect behavior has
  been tested. Terminal notification work is deferred.
- Tmux-context activation and actual-pane/no-tmux behavior remain unverified.
- Worktrees creation, file policy and TUI Session directory changes remain
  unverified, including compatibility with the separate SSH composition.
- The three Web plugins have not been installed or tested against the candidate.

This follow-up used read-only upstream documentation and repository evidence.
The SSH/plugin and static compatibility evidence scouts ran with the configured
`gpt-6-luna` / `high` role;
the earlier source build used `gpt-6.1-sol` / `medium`. Neither is evidence of a
real remote runtime pass.
