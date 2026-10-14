# DSH user guide

rotom maintains one DSH recipe, **`dsh-default`**, using unmodified upstream packages and small repository-owned public-API adapters. Its defaults are native **workspace-write + ask**, with Perry auto-review enabled for eligible pending write/edit requests. Core is a prerelease. The user accepted the known lifecycle and audit limitations for daily deployment on 2026-10-14; that deployment does not mean the outstanding safety gates passed or that upstream is stable. See [known issues](known-issues.md), [testing](testing.md), and [releases](releases.md).

Legacy patched instances must not receive an in-place apply of this configuration. Preserve their account/session/configuration recovery boundaries and test migration in a separate HOME/XDG/instance scope first. The former separate `dsh-auto-review` daily entry point has been retired; manual and AI-assisted approval use the same recipe and instance.

## Packages and reproducibility

| Component | Pinned version | Source/boundary |
| --- | --- | --- |
| DSH Core | `0.2.0-rc.2` | `639ed015397290b3745d163aafe02ffee4aa3f84`; prerelease |
| TUI | `0.15.0` | `18e4a206afc367f055a2b3379bb221abcbb5d99e`; original npm package |
| Cursor provider | `dsh-cursor-subscription@0.6.12` | `936fb5b40b8efb50a5bb2031c81f3c8f553bf7f8`; original package |
| Terminal adapter | `rotom-dsh-cursor-terminal@0.1.2` | `agents/dsh/packages/cursor-terminal`; public TUI QuestionBridge, no copied OAuth/wire implementation |
| Authentication | TUI `./oauth` | Only `openai-codex`; not the old standalone dsh-auth package |
| AI approval | `dsh-auto-review@0.12.17` | Original [Perry package](https://github.com/PerryLink/dsh-auto-review/releases/tag/v0.12.17), SHA `2b931b8375f9ee9ebe20e80ef336c69804e1aac0` |
| Review context | `rotom-dsh-review-context@0.1.0` | Constant configuration context; no file/environment/account reads or authority grants |
| Shared runtime | Cordis `4.0.5-alpha.1`, Schemastery `3.18.5-alpha.1` | Prereleases required by Perry's peer floor; main/reviewer/subagent module identity checked |
| Toolchain | Node `24.14.0`, npm `11.19.1`, pnpm `11.19.0` | pnpm original archive pinned by integrity; no global install |

`locks/dsh/pnpm-lock.yaml` is the sole complete installation lock; manifest v2 declares `resolution_kind=pnpm`. Normal npm resolution encounters ERESOLVE between TUI's optional stable Schema peer range and Perry's alpha floor. No force, legacy-peer-deps, overrides, or deleted peer declaration is used. There is no npm-ci path for this recipe. A successful pnpm install does not mean every upstream peer declaration agrees.

Sync verifies the pnpm archive's SHA-512 and uses the fixed installer with `--frozen-lockfile --ignore-scripts --node-linker=hoisted --package-import-method=copy`. The reviewed native preparation step is official `ensure-spawn-helper.mjs`, setting the packaged helper executable. Apply/run do not install or follow latest.

pnpm's release-age policy has one exact exception for `@deepseek-harness-tui/dsh-tui@0.15.0`, recorded in lock-policy/manifest and lock identity. Wildcards, other packages, or unselected versions are rejected. It uses a temporary public pnpm-workspace.yaml in staging, removed afterward, without changing global pnpm settings. Other supply-chain checks remain enabled.

Peer checks still warn about disabled working-activity and experimental Web UI. Working-activity dynamically changes Session event tables and is disabled; TUI supplies its own spinner, chat, cards, and status. Experimental Agent Teams and voice are not enabled. Runtime identity/native loading evidence is narrower than a clean whole-tree peer check.

## Setup and startup

Prepare the repository and private machine configuration as described in [getting started](getting-started.md):

```sh
cd /path/to/rotom
uv sync --locked
./agentcfg init-local --machine workstation --profile dsh-default
./agentcfg --machine workstation --profile dsh-default model status
./agentcfg --machine workstation --profile dsh-default setup
./agentcfg --machine workstation --profile dsh-default run --cwd /path/to/workspace
```

Explicit profile selection avoids changing another recipe's machine default. Default instance/state roots are `$HOME/.local/share/agentcfg/instances/dsh/dsh-default` and `$HOME/.local/state/agentcfg/dsh/dsh-default`, subject to XDG and machine path settings. HOME/DSH_HOME identities remain stable; OAuth, sessions, and logs belong to native services.

Some installations provide personal `dsh`, `dsh-config`, and `dsh-cursor-login-url` shell wrappers. They are local conveniences, not upstream commands or repository-wide prerequisites. Use the portable agentcfg commands above. A wrapper must keep the same selected machine/profile, toolchain, and manager contract rather than create a second configuration system.

The default main route remains the public Kimi Code configuration unless explicitly overridden. A missing login does not prevent another configured API route from starting. A route without its required key cannot make requests and does not silently switch to another paid service.

### Optional TF gateway models

`agents/dsh/content.toml` supplies eleven `dsh-…` bindings: four Kimi, five GLM, and two DeepSeek models. Providers reuse `kimi_tf`, `zhipu_tf`, and `deepseek_tf`; keys remain `secret:omp_kimi_tf_key`, `secret:omp_zhipu_tf_key`, and `secret:omp_deepseek_tf_key`. Kimi/DeepSeek use OpenAI Completions and GLM uses native Anthropic Messages through the locked llm-pi-ai, without an added runtime dependency.

Select them explicitly in `overrides.profiles.dsh-default` and provide private `tf_openai_url` and `tf_anthropic_url`; see [dsh-tf.local.toml](../examples/dsh-tf.local.toml). Machines without a gateway are not forced to enable it. Core specifications reuse shared templates; DSH reasoning/compat uses public DSH fields and does not receive OMP native fields. Gateway IDs, quotas, and tool round trips require actual service evidence. Native loading or a local fake service is not TF account validation.

Use model status to find missing values and model key to update only the selected private source. In `/model`, TF providers appear as `agentcfg-kimi_tf`, `agentcfg-zhipu_tf`, and `agentcfg-deepseek_tf`. Selecting the pool does not change main automatically.

### Network proxy considerations

If needed, explicitly allow nonsecret HTTP_PROXY, HTTPS_PROXY, NO_PROXY, and NODE_USE_ENV_PROXY through `machine.environment.inherit`; set actual values only in your local launch environment. A local helper may set them and exec the normal entry point. It does not create a new HOME/profile or change models/permissions. The proxy must support HTTP or mixed traffic, and loopback refers to the machine running DSH.

Node 24.14.0 supports environment proxying for its native HTTP(S)/fetch path. Cursor 0.6.12's AgentRun model stream uses HTTP/2 directly with no public proxy hook; **do not assume all Cursor traffic follows an environment proxy**. Local proxy wrappers are not a remedy for every provider transport.

## Codex/ChatGPT subscription authentication

Enter these inside DSH:

```text
/auth status
/auth login openai-codex
/model
```

The mounted provider is `openai-codex`, not `openai`. `/provider` is a native interactive management wizard that shares the same auth service. Subscription login is not an OpenAI API key and does not read a global Codex HOME.

Over SSH, choose **Device code login (headless)** in the native login-method prompt when available. It avoids a remote localhost callback. Account/workspace policy must enable device-code login; see the [official authentication instructions](https://learn.chatgpt.com/docs/auth#preferred-device-code-authentication-beta). This prerequisite cannot fix network errors. In browser mode, paste the code or complete callback URL into the native panel; callback and polling belong to upstream.

The current pi-ai login asks for the method before issuing/polling a device code. Fetch failure ends that attempt. Run `/auth login openai-codex` again for a new flow; use Cancel sign-in on an active panel first. If the TUI is stuck, exit and restart with the intended network environment. Do not delete authentication directories or roll back configuration to retry login.

Auth success/status notifications are brief, about four seconds by default, and are not chat history. Repeat `/auth status` if you missed one. For a persistent view, open `/provider`, choose Add then OAuth, and inspect account/expiry descriptions with arrow keys; Esc exits without login/logout. No public global notification-duration control is documented for this integration. A provider wizard's local summary is not a cross-process notification history.

The user reported successful device-code sign-in after restarting with the intended proxy environment. The original fetch failure's cause remains unresolved. This feedback establishes that login observation only: real model/tool requests, restart credential recovery, and refresh were not thereby verified. Local fake OAuth tests cover issue/poll failures, reopening, cancellation, and no request before answering the method prompt; anonymous network probes cannot establish the cause of an actual OAuth failure. See [testing](testing.md).

The native `/kernel` external Codex kernel is a different path with its own authentication/permissions. This DSH provider and reviewer integration do not automatically govern it.

## Cursor authentication

```text
/cursor-login
/cursor-login url
/cursor-login status
/cursor-login models
/cursor-login cancel
/cursor-login logout
/model
```

The native authentication panel provides Copy, Open browser again, and Cancel sign-in. Reopening the URL displays the same pending attempt instead of spawning parallel logins. Upstream controls validity; the adapter has a ten-minute observation limit and ends the panel on success, failure, cancel, or exit.

SSH clipboard/browser behavior depends on the client. During a pending login, the full link is also available to the user locally at `DSH_HOME/cursor-login-url.txt` with mode 0600. Do not paste it into chat/logs. Existing files, symlinks, and user modifications are not overwritten or deleted.

The provider uses remote PKCE polling, without guessing localhost forwarding or requiring a persistent Web UI. `models` explicitly refreshes the account catalog; a short notification shows the count and `/model` shows the full list. A failed refresh produces an unknown/empty catalog, not a claim that built-in fallback models are available. Unknown usage remains unknown. Status/model errors do not cancel a pending login.

Authentication, refresh, and logout belong to upstream public AuthService/CredentialStore APIs; the manager imports no IDE/browser/keychain credentials. Logout cancels adapter-owned pending requests. If logout cannot be confirmed, requests stay paused until explicit successful login; completed side effects cannot be undone.

The framework provider ID stays `cursor`; native routing is `cursor-subscription`, replacing `oauth-cursor`. The old `agent_options.cursor_port` is removed: this terminal flow does not create that proxy port. Old fields fail strict validation. Remove them only through a reviewed migration of configuration intent; do not rewrite old sessions or convert oauth-subs credentials. New native homes need new login. Actual account catalogs, model/tool round trips, resume, refresh, and quota correspondence need their own evidence.

## Settings and preference ownership

Defaults use the native DSH kernel, standard preset, Catppuccin Mocha, the native welcome screen, and whale branding. `agent_options.show_welcome=false` skips the launchpad through public `DSH_TUI_NO_LAUNCHPAD`. Visual minimal mode is separate from the tools preset; the recipe retains file tools, compaction, and native subagents.

TUI 0.15 uses isolated HOME `.dsh-tui/settings.json` with `version/values/imported`. First launch imports editable defaults from `dsh-home/profiles/agentcfg/cordis.patch.yml`; native user settings take precedence afterward. Rotom does not adopt/reset/delete settings.json or provide bidirectional synchronization. Packaged `lib/settings.json` is a field catalog, not the active file.

| Setting group | Ownership |
| --- | --- |
| API providers, Core `agent-default-model`, kernel/preset/modes | Managed by per-row-ID cordis-yaml three-way comparison. TUI provider/model are not pinned over restored session routes. |
| Whale, idle, minimal, sidebar/panels, brand | First initialization only; later native changes survive apply. |
| Theme, home/onboarding markers, status bar | Initial preferences; existing unknown fields and later user choices remain intact. |
| Global AGENTS.md, complete framework skills, exclusive overlay, themes, launcher | Managed files with explicit ownership. |
| Account state, sessions, logs | Native state, excluded from configuration backup/capture. |

Unknown rows/fields and unevaluated scalar JavaScript are preserved. Duplicate IDs/keys, invalid structures, and managed parents converted to JavaScript fail. Nonempty unowned preference files conflict on first adoption rather than being overwritten.

Whale defaults are whale=true, whaleGirl=false, companion.skin=whale, minimal=false, whaleIdle=false, brand=deepseek; the sidebar starts collapsed with todo/jobs/agents/trajectory/info available. Companion skin can take precedence over other header artwork; choose it explicitly in native settings. Users may select other artwork, idle animation, and banner fonts through `/settings`; rotom does not force them back on apply.

The default theme is `rotom-catppuccin`, with Poimandres assets retained as an option. `/theme` changes native preference. Brand behavior can affect theme choice; no environment variable forcibly overrides the user's selection. Theme capture is an initial-default proposal, not a guarantee of continuous synchronization.

The thin launcher uses public `@deepseek-ai/dsh/profile-boot` and an environment snapshot. It does not patch Node fs, discover dotenv, or implicitly import cwd/.env or DSH_HOME/.env. Working cwd stays the business project.

The native package manager points to a managed entry that rejects package operations. TUI `/update` can still appear and has an upstream manual path that may write profile installation settings before invoking external dsh. **Do not use `/update` in managed instances.** Updates go through reviewed locks, sync, and apply. Doctor/run check runtime/profile drift rather than patching TUI to hide commands.

### Effort, images, and status

Use `/status`, `/tokens`, `/settings`, `/panel`, `/preset`, and `/permission`; consult the current `/help` for shortcuts. Manual reasoning-effort selection persists through the native settings flow. An unavailable effort is displayed as **Default**, rather than a fabricated reasoning level. The message's Thinking timer measures a runtime phase and is distinct from the selected effort.

`terminalImages` defaults to false, unlike the native TUI default. It controls renderer image-protocol detection for image previews and header artwork, while model image-input capability remains available. This provides the plain terminal/tmux fallback. Change the native terminal-image setting and use `/restart` to take effect. tmux Ctrl+B may intercept the default sidebar shortcut; rebind supported native shortcuts as needed. PTY results alone do not prove SSH/tmux client interaction.

Status bar defaults are compact=true; model, thinking, cwd, contextUsage, cache, tokens, cost, tps, gitBranch, sessionTitle, goal, mode, and contextBar enabled; sessionId, activity, trajectory, and shortcutHint disabled. These eighteen preferences initialize once. TUI controls layout and hides unavailable data. Model is the current label; thinking is effort; tokens are cumulative input/output; cache is the last usage's cache-read/input proportion, not subscription balance; tps is output speed. Costs are shown only when reported or supported by native estimation, not invented as zero for Cursor. The cwd basename `workspace` does not prove permission mode. Use `/permission` for effective permissions and `/auto-review status` for approval state; there is no dedicated auto-review status-bar field.

### Transcript navigation in tmux

A full-screen TUI manages its own alternate-screen transcript; tmux copy mode's screen buffer is not the whole conversation. Back in DSH, PgUp/PgDn scroll pages and End goes to the bottom. Ctrl+E expands/collapses older loaded messages. `/vim` edits the draft; it does not add j/k transcript scrolling.

Ctrl+O opens transcript browsing. Press `/`, enter a keyword, Enter, then n/N for matches. Esc closes search and returns to the prior location; only then can Ctrl+O exit browsing. This is keyword navigation, not a replacement for page scrolling. The earlier [upstream interaction guide](https://github.com/ccch1mneyyy/dsh-TUI/blob/v0.14.0/docs/interaction.en.md#L229-L257) documents that version's behavior; native `/help` remains the version-specific reference. There is no supported rotom plugin guaranteeing Vim transcript scrolling.

Ctrl+T opens trajectory: arrows, PgUp/PgDn, g/G, Enter for detail, q to exit. It need not position the chat viewport. `/export` writes `dsh-tui-export-<timestamp>.md` in the current cwd for less/editor browsing. Export reflects the currently projected session, not necessarily every unloaded historical message. Minimal UI and full-screen draft editing do not turn the TUI into ordinary terminal scrollback.

## AI approval and persistent manual mode

Only a real pending native approval request enters the reviewer. Ordinary sandbox-allowed operations run directly. Hard denies precede AI. Production/external writes, destructive deletion, permission changes, dynamic scripts, unknown tools, or unclear targets require human approval or denial. A single approval is not a general bash/python/make allowlist.

`agent_options.auto_review=true` loads base → constant review context → Perry → TUI. Perry handles eligible native approval/request events before the human responder. The official Full-access Auto review is not loaded.

| Setting | Effective configuration |
| --- | --- |
| enableByDefault | true; new sessions start ON |
| toolsPolicy | default human; only pending write/edit use AI |
| reviewerProvider/model | spawn; no fixed reviewerModel, inheriting the current session route without switching paid sources |
| reviewerTools | `rotom_review_context`, constant explanation only; no read/glob/grep/Shell |
| contextBudget | Most recent turn, at most 6000 characters; tool/file text saying “approved” does not create user authorization |
| Timeout/budgets | 30 seconds; up to three reviews and one failure per turn; verdictCacheTtlMs=0 |
| riskPolicy | Only low-risk allow can execute automatically; higher-risk allow delegates to a human |
| fallbackPolicy | Delegate on timeout, malformed/model errors, or exhausted budget; no execution if human approval is unavailable/fails |
| allowUnmarkedAudit | false; native asked/decided events persist, but complete Perry verdict/reason remains in memory on this RC |

Native file tests observed one write after AI allow; deny, never, high risk, review errors/human failure, and budget exhaustion did not write. Unknown tools used human approval; ordinary workspace writes did not call the reviewer. Manual mode was checked using false → apply → full restart, leaving workspace-write + ask and no registered Perry service/command.

The reviewer's native catalog still exposes subagent. At the tested depth=1/maxDepth=1, another valid delegation was rejected and created no child; read attacks were denied and no write/Shell/run_code was presented. That evidence applies to the tested standard/spawn/native presentation only. Changed depth/provider/PTC needs separate verification. Tool allowlists do not prove OS read-root confinement or same-user credential isolation. General normalized read/context-source boundaries remain unproved.

**Unresolved upstream failures:** OFF can return to ON on the next turn; an in-flight approval may still execute after off or unload; complete Perry verdicts cannot be reconstructed from cold persistent audit. Configuration risk text is not a deterministic Shell/path analyzer. These remain failures despite acceptance for daily use.

```text
/auto-review status
/auto-review on
/auto-review off
/permission
```

`off` and unloading are **not reliable persistent emergency stops**. For persistent manual approval, cancel the current turn, quit TUI, and edit the existing private machine table (do not duplicate TOML tables):

```toml
[overrides.profiles.dsh-default.agent_options]
auto_review = false
```

Then, with DSH stopped:

```sh
./agentcfg --machine workstation --profile dsh-default plan
./agentcfg --machine workstation --profile dsh-default apply
./agentcfg --machine workstation --profile dsh-default run --cwd /path/to/workspace
```

A complete restart disables the Perry row and retains native human approval in the same profile/account/session scope. To restore AI review, set true and apply/restart. Configuration rollback is not a substitute for this procedure and does not cancel already executed side effects.

## Models, retries, and permission boundaries

`/model` selects the current model and saves native new-session preference in isolated HOME `.dsh-tui/model.json`, without changing rotom's global main role. New sessions prefer that complete native selection, otherwise Core `agent-default-model`. `/resume` restores a session's last recorded request route. The previous TUI provider/model pin has been removed where ownership is complete and fields have not drifted; drift conflicts instead of being overwritten. Native preferences/accounts/sessions are not migrated. Rollback can restore the old pin and its overriding behavior.

Route fixes do not rewrite history. If a resumed session already sent a request through the default model, select the desired model again. A selection never used in a request has no new request/header and is not guaranteed to become the restored route; an empty session likewise has none. Public startup resume received host regression evidence, while the actual picker and repaired Cursor account resume retain their separately unverified scope.

Cursor internal POST retry and provider recovery are both zero: one attempt avoids resending a request whose server-side outcome is unknown. Static APIs default to normal/0 with explicit maximum 2; always is rejected. Codex OAuth uses the upstream dsh-llm-retry default of five retries, at most six attempts, with native cancellation/backoff. TUI exposes no OAuth retry override. Account-side failure/Retry-After behavior remains unverified; do not repeat already successful tools to repair a model stream.

`/permission workspace-write` selects native workspace-write + ask. `never` denies operations needing approval; it does not mean allow everything.

| Channel | Boundary |
| --- | --- |
| File tools | Native ToolRuntime/file policy; only pending write/edit can use AI review. |
| Shell | Pending approvals are human; native sandbox-allowed actions can execute directly. External/link sentinel denial does not prove every command is AI-reviewed. |
| MCP | Pending approval defaults human; local file sandbox does not confine remote effects. Real service interactions remain separately unverified. |
| Native subagents | Native tool filters/inheritance; parent approval does not audit every child action. Independent read roots are not established. |
| External kernels | Their own native authentication/permissions; DSH plugin coverage is not implied. |
| PTC/run_code | Native public runtime path; untested channels remain not run. |
| Plugins/direct Node | Trusted code with host process privileges; not all effects pass approval or OS confinement. |

Workspace-write restricts file writes, not general network/environment/credentials or same-user processes. Selected model keys are injected at runtime and may be visible to tool processes. AI review is not protection against malicious same-user code. A confined operation without a usable sandbox must fail rather than fall back to Full access. Displaying a configured mode is not backend verification.

## Workflow tools, migration, and verification

DSH does not install OpenSpec, Spec Kit, or their workflow skills. Existing project `openspec/`, `.specify/`, `specs/`, AGENTS.md, and user skills remain intact. `project init openspec` is retained only for explicitly selected optional Pi capability and fails closed for DSH.

Rollback restores managed configuration only. Runtime/lock deployment, native session formats, and account recovery are separate. Do not downgrade sessions written by a newer host or copy real sessions across homes automatically. Legacy ownership, old settings/env-guard, pending transactions, or nonempty unknown files can block apply; do not clear ownership to force adoption. Preserve retired data privately rather than enabling a historical patched host as a daily runtime.

Native smoke tests are **separate, explicitly authorized actions**, not part of ordinary pytest. Available scripts include smoke-dsh.py, smoke-dsh-ui.py (including settings migration), smoke-dsh-auth-panel.py, check-dsh-cursor-panel.mjs, and smoke-dsh-rebuild.py. Consult their `--help` and [testing](testing.md) before use. They use temporary homes, fake models/OAuth or declared runtime copies; shared-cache rebuilds are not cold builds. No-account host results do not verify real accounts, clipboard/browser behavior over SSH, or current provider requests.

Default tests isolate HOME/DSH/XDG, block network and real host subprocesses, and use fictional state and sentinels. See [testing](testing.md) for executed commands and scope, and [known issues](known-issues.md) for the unresolved upstream lifecycle/audit work.
