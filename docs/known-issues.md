# Known issues and TODOs

This is the maintained issue register for release preparation. **Open**, **blocked**, and **not run** are different states. A historical test result applies only to its recorded candidate and scope. No item here authorizes a host patch, a credential import, or a silent fallback to broader permissions.

## Open implementation and upstream issues

| ID | Status | Impact and recovery | Completion evidence required |
| --- | --- | --- | --- |
| RUN-01 | Implemented; historical Linux DSH native concurrency passed | DSH shared admission only verifies prepared projections. | [Refactoring record](design/project-refactoring.md) retains its historical candidate and scope; settings/auth stress and other platforms remain separate. |
| PI-RUN-01 | Conservative manager admission; native NOT RUN | Pi records each main run independently. Active/unknown owners block exclusive maintenance. Production has no complete-release observer, so manager exit remains unknown. | Complete identity-matched descendant/resource observation and separately authorized native evidence; no timeout/forced marker cleanup. |
| DSH-RUN-02 | Historical source finding; current concurrency revalidation pending | The Cursor adapter publishes a fixed login-link filename; historical TUI `0.15.0` review found unlocked whole-file inject discovery updates. That concurrent-discovery finding has not been revalidated on selected TUI `0.16.1`. Credential-store locks do not protect link publication; lost discovery is distinct from session-log corruption. | One pending Cursor login per instance; exclusive link publication reports collisions. Use the foreground session when inject discovery is lost; seek an upstream lock fix. Historical distinct-session and simultaneous-resume refusal passed; current settings/auth concurrency stress and reviewer isolation remain unverified. |
| PUB-01 | Implemented for DSH/Pi/OMP | Publisher leases, manifest-last recoverable journals and full sync reader leases prevent cooperative readers from accepting interrupted generations. External noncooperating edits remain conflicts. | Two-writer, reader/consumer exclusion, each write boundary, drift refusal and interrupted old-generation restoration tests. |
| CFG-01 | Implemented; 220 targeted tests passed | Workspace loading defers shared secret-file bodies until an operation resolves a selected reference. Direct `load_local` callers retain the compatible eager default. | Configuration-only read sentinels, malformed/symlink/conflicting stores and legitimate required key/status/runtime resolution tests. |
| TERM-01 | Implemented; native/platform NOT RUN | termcfg manages terminal components, including optional Herdr configuration. Existing v1 machine/state metadata needs `migrate --drop-mihomo`; pending legacy journals must recover first. Services, private data and old target files remain untouched. Different machine IDs sharing HOME are not serialized. | 106 isolated tests passed for the terminal-only package, including migration interruption/drift and generic plugin/recovery behavior; see [migration guide](termcfg.md#retiring-an-existing-mihomo-selection). Native terminal checks remain separate. |
| WORK-CLOSE | Capability unavailable; isolated refusal tested, native NOT RUN | The feature 006 reviewed Herdr API has no atomic workspace-membership guard. Mutating `work close`, including a matching reviewed scope, returns 5 with zero close dispatches; read-only preview remains available. | Admit a public server-enforced scope guard and separately authorize exact-combination native acceptance before enabling close. See [workspace close](herdr-workspaces.md#断开收起和关闭) and [feature evidence](../specs/006-configurable-workspaces/quickstart.md). |
| WORK-EXISTING-BRANCH | Capability unavailable; isolated refusal tested, native NOT RUN | Git existing-branch creation lacks the required atomic local-ref guarantee against concurrent deletion and remote fallback. `--existing-branch` permits preview, but creation returns 5 with zero worktree-add dispatches; new-branch creation and import remain separate supported paths. | Admit a reviewed public atomic guarantee before enabling existing-branch creation; tested refusal is not successful native creation. See the [Git capability boundary](../specs/006-configurable-workspaces/contracts/cli.md#examined-git-capability-refinement) and [feature evidence](../specs/006-configurable-workspaces/quickstart.md). |
| PI-LOCK | Official 1.3.0 complete lock; native NOT RUN | Base/Pro have independent npm slices and source/content identities. Legal notices are verified separately from unchanged host files. Linux evidence is limited to manager rebuilding and isolation. | [Current acceptance](../specs/005-rebuild-pi-toolkit/acceptance.md) separates frozen/final candidates, dependency preparation, native and account results. |
| DSH-AR-01 | Accepted upstream limitation | Perry `0.12.17` can execute a late approval during OFF/unload; the observed execution count was 1 where 0 was expected. Session OFF is not a guaranteed cancellation barrier. | Real-host late-response tests execute zero actions after cancellation, OFF, and unload. |
| DSH-AR-02 | Accepted upstream limitation | Session OFF can return to ON on a later turn. For persistent manual operation, cancel and exit, set `auto_review = false` in the selected machine override, plan/apply, then restart. | OFF survives turns, restart, and restoration according to an explicit upstream contract. |
| DSH-AR-03 | Open audit limitation | Native approval records persist, but complete Perry verdict records are memory-only; a cold restart yielded zero reconstructed Perry verdicts. | Durable correlation of action, session/request/call identity, decision, mode, reason, and failure after restart, without secrets. |
| DSH-AR-04 | Open boundary evidence | General authorization-context boundaries have not been fully proved. The selected Perry/Core pair reviews inline without tools; the separately defined preset's narrow tool list does not prove OS or same-user credential isolation. | Real-host context/sentinel tests for the selected reviewer implementation. |
| LEASE-01 / RM-002 | Open design work | Background descendants can inherit lease descriptors and keep deployment blocked after the foreground host exits. Diagnose the holder; do not delete locks or kill unrelated processes. | Foreground, daemon, abnormal exit, concurrent deployment, and PID-reuse cases preserve protection without leaked leases. |
| PI-RUN-02 | Native loading/interaction NOT RUN | Fixed managed resources and session directory, no-approve and no-resource flags, plus loading preflight are implemented. Project AGENTS context remains; UI preferences are native-owned and no concurrent preference/OAuth-refresh guarantee is inferred. | New official-host discovery, resume/branch, terminal and account tests under separate authorization. |
| PI-SOURCE / RM-001 | Repository retirement implemented; final feature gates open | Old SDK/supervisor/delegate packages and four old profiles are absent; required legal/source records and private historical state remain. | [Retirement execution](../specs/005-rebuild-pi-toolkit/retirement-execution.md), main-agent final review and current-candidate verification. No old platform recovery prerequisite. |
| GOV-01 | Documentation TODO | The constitution retains `TODO(RATIFICATION_DATE)` because its original approval date has not been confirmed. | Confirm the original date with the maintainer; never invent or reset it during a wording update. |
| REVIEW-F02 | Retired historical development issue | Task Keeper and its mock job are no longer distributed. Historical mock results never established real SDK typechecking. | No new Task Keeper development lock or old-platform rebuild is part of Base/Pro. |
| OMP-NET | Planned | Independent model, reviewer, ordinary-tool, and download proxy routing is not fully delivered. Environment inheritance is not network isolation; NO_PROXY is address matching, not per-provider authorization. | Public-API feasibility, explicit source settings, route-isolation/failure tests, and no secret-bearing proxy URLs. |
| ENV-01 | Integrated; local DSH/OMP deployment verified | New contracts separate caller development environment from native state, preserve deletion/one-shot precedence, warn without values, and keep restricted workers minimal. DSH retains TUI HOME and uses public subprocess/MCP boundaries. | [Environment record](design/project-refactoring.md#execution-environment-follow-up): complete offline coverage, matching DSH and historical pre-reboot Pi native checks and two-HOME rebuilds passed; that Pi evidence does not apply to the new official 1.3.0 combination. Local doctor, zero-change plan and repeated apply passed; other platforms/profile-native scopes remain separate. |
| ENV-02 | Integrated; local terminal deployment verified | termcfg preserves custom/empty NVM_DIR, selects XDG private hooks with an explicit ambiguity warning, and retains legacy fallback without sourcing both. OMP guides now distinguish execution and storage paths. | Catalog digests, offline terminal tests and 18 real isolated zsh cases passed. Authorized local zsh updates, strict doctor and repeated apply passed. Existing shells/tmux servers and private hooks were not restarted or executed for deployment acceptance. |
| DSH-TEAMS | Bounded Linux acceptance passed; upstream limits retained | Official rc2 Teams is selected by the public `dsh-default` profile; an explicit complete machine plugin override can disable it. Existing deployments change only after explicit apply. It shares workspace, version-checked task state and inbox messages; it supplies no file locks, cross-process exclusion, exactly-once execution or automatic abandoned-task release. | Fresh/fork, inbox processing, task revision checks, clean restart and TUI/Perry composition passed in isolated fixtures. Crash/multiwriter recovery, live model judgment and other platforms remain unverified; see the [ecosystem record](acceptance/dsh-ecosystem-upgrade-20261021.md). |
| DSH-MODEL-01 | Deferred by maintainer | The locked pi-ai 0.87.1 Codex catalog does not contain gpt-6.1-sol. The RC2 adapter's dependency range excludes evaluated newer catalogs. | Reevaluate during a normal compatible upstream upgrade. No forced dependency override, model alias, vendor edit or new OAuth adapter in the environment work. Account access remains separately unverified. |

DSH auto-review remains enabled in the public recipe by explicit maintainer choice despite DSH-AR-01–04. Its functional probe passing is not full safety acceptance. Ordinary workspace operations may never enter the approval chain and therefore may receive no reviewer call. See [approval boundaries](design/approvals.md) and the [DSH guide](dsh.md).

The selected Perry `0.13.7` / Core `0.2.1-rc.2` combination uses no-tool inline review: Perry checks legacy `subagents.start`, while Core exposes `startActivation`. The public `rotom-auto-review` preset passed an independent activation probe but is not selected by this approval path. Inline review needs a recent real parent `request/header`; a direct tool call without it falls back to human handling. Historical `0.12.17` lifecycle failures remain revalidation cases, and complete persistent verdict audit remains unsupported. The selected official TUI `0.16.1` passed isolated session-resume/settings-migration/CLI scenarios, and the matching Perry formal/manual/timeout scenarios passed. Those results do not close the historical lifecycle/audit cases. See the [ecosystem record](acceptance/dsh-ecosystem-upgrade-20261021.md) and [Perry integration record](acceptance/dsh-perry-public-integration-20261021.md).

## Environment-dependent validation

| ID | Status | Scope still to verify |
| --- | --- | --- |
| OMP-F01 / OMP-F02 | NOT RUN | Native Linux arm64 and macOS x64/arm64 behavior; platform-selection tests alone are insufficient. |
| OMP-F03–F05 | Partial / NOT RUN | Fresh native login, usage, and each provider route. Historical small Cursor/reviewer samples do not validate all providers or the current source snapshot. |
| PI-PLATFORM | Linux bounded / other platforms NOT RUN | Linux manager rebuilding, local/loopback-SSH UI and authorized shared-model/tool evidence are recorded in current Pi support. macOS and other platforms have no current acceptance. |
| PI-LIVE | Bounded / deferred | Shared-default sessions, one synthetic-file tool task, Context7 keyless service and synthetic Chromium passed within recorded scope. Brave/Cursor real accounts are deferred by user decision; Pro awaits compliant community plugins. |
| DSH-LIVE | Partial / NOT RUN | Earlier user-observed Cursor and Codex success remains historical. This release cleanup performs no fresh authentication, paid calls, or live refresh tests. Domestic API and Codex retests were previously deferred by the user. |
| TUI-NOTIFY | NOT RUN | Actual task notifications and image rendering in each terminal/tmux combination. tmux uses upstream text fallback rather than the original portrait. |

## Fixed in this preparation

- Malformed pnpm importer/dependency structures now fail as configuration errors.
- OMP native `null` role clearing is accepted for known roles without broadening nonempty selector authorization.
- The foundation artifact assertion includes both Catppuccin themes and selectors.
- Current guides use OMP `18.8.6`, describe the formal DSH recipe, and no longer claim DSH installs OpenSpec.

See [testing](testing.md) for current automated results and [Roadmap](roadmap.md) for larger work. Do not mark an environment-dependent item passed merely because implementation or mocks exist.

## Historical Pi public API observations

The observations below apply to the retired SDK/four-profile candidate. They are not current
Base/Pro support statements. See [current Pi support and limits](pi-support.md).

- Pi 0.84.4 native session import has no source-file preflight event. Managed `/import` is disabled; current-format resume and fork remain supported. Revisit when an upstream public hook can validate the source before copy/migration.
- pi-cursor 1.4.29 has no public transport audit injection API. Cursor read-only `model_delegate` is rejected before credential access or spawn. Cursor main sessions remain separately available; model-delegate support requires an upstream public connector or equivalent auditable transport.
- Trusted extensions execute JavaScript in the host process. Resource selection and grant checks do not isolate a malicious selected extension or other same-user process.

Filesystem executors with an unsupported root ancestor owner remain unsupported
for private configuration operations. The fixed `unsupported-root-owner`
diagnostic propagates through initialization and initial configuration reads with
exit 4. Read-only root mounts and a different `TMPDIR` do not change this trust
boundary. Private-path tests require a working baseline and report NOT RUN when
that root prevents it; classification mocks do not establish native support.

The terminal XDG follow-up validates effective paths, including HOME defaults,
and validates legacy hooks independently. Missing, empty or relative HOME cannot
supply plugin, hook, cache, local-bin PATH, history or NVM defaults; explicit
absolute XDG/NVM paths remain usable. Relative NVM_DIR is preserved but not
sourced. Doctor reports invalid public path states without values. Existing
absolute paths, empty/unset XDG defaults with a valid HOME, hook conflict and
same-file selection, and explicit empty NVM_DIR semantics are preserved. The
[explicit terminal smoke](../scripts/smoke-termcfg-environment.py) provides
reproducible guard checks; synthetic tmux checks are not tmux-server acceptance,
and completion initialization is separately READY or NOT VERIFIED.

The locked FSH plugin's missing-secondary-theme branch can download a theme at
startup. Termcfg now prepares that theme from the same installed lock's local
free-theme file before loading FSH, with no-overwrite publication, and skips FSH
if preparation or absolute working-path checks fail. Existing user themes,
including empty files, are preserved. Stateful Zinit/OMZ/z.lua loading also
validates HOME, effective cache and the relevant public override paths before
sourcing. Synthetic fixture smoke checks do not replace real locked-plugin and
platform acceptance; private user hooks remain outside this controlled scope.
Affected historical terminal evidence does not transfer to this changed startup
source; real locked-plugin acceptance must be recorded against the new snapshot.

CLI and shared-key default discovery no longer consult account HOME when the
HOME environment value is missing, empty or relative. Relative default XDG config
paths fail as parameter errors instead of selecting a cwd file. New termcfg
selection validates HOME before its write lease; editing keeps the saved target.
Explicit absolute config/secret selections remain available. Existing readable
FSH theme links are user-selected inputs and remain unchanged; directory or
dangling links are skipped, without claiming protection from same-user tampering.
Nonempty XDG values are absolute literal environment paths: `~/` is rejected,
and dollar characters are preserved rather than expanded. Explicit machine TOML
secret-file paths retain their documented configured-path syntax.

## Current Pi admission gaps

Powerline 0.20.2 and mjakl 3.1.0 remain held. Tintinweb 0.22.0 can bypass its foreground cap through
background/resume; the user retained the community-only route and deferred Pro. The status-information gate is complete with the user's explicit acceptance of the permission
explanation, branch-average speed and narrow-screen details. Per-main two-investigation enforcement
is not delivered. Fixed optional choices have complete-lock wiring and native evidence recorded in
[current delivery acceptance](../specs/005-rebuild-pi-toolkit/current-delivery-acceptance.md), including
real synthetic-file tools, cancellation/recovery and positive cache display. Brave/Cursor real-account
acceptance is deferred; no-account loading does not prove authentication or entitlement. Actual billing,
real remote machines and other platforms remain outside the verified scope. See [support](pi-support.md)
and the [module register](../specs/005-rebuild-pi-toolkit/module-admission.md).
