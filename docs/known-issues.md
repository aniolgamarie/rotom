# Known issues and TODOs

This is the maintained issue register for release preparation. **Open**, **blocked**, and **not run** are different states. A historical test result applies only to its recorded candidate and scope. No item here authorizes a host patch, a credential import, or a silent fallback to broader permissions.

## Open implementation and upstream issues

| ID | Status | Impact and recovery | Completion evidence required |
| --- | --- | --- | --- |
| RUN-01 / PI-RUN-01 | Implemented; Linux native concurrency passed | DSH shared admission only verifies prepared projections. Pi retains independent supervisors with version 2 owners, exact-owner endpoints and cross-run workspace leases. Old Pi contracts require explicit sync/apply with matching source. | [Refactoring record](design/project-refactoring.md) includes matching failure/recovery, offline and native evidence. Other platforms and extended settings/auth scopes remain unverified. |
| DSH-RUN-02 | Upstream/shared-state limitation | The Cursor adapter publishes a fixed login-link filename; TUI `0.15.0` updates inject discovery with unlocked whole-file read/modify/write. Credential-store locks do not protect link publication; lost discovery is distinct from session-log corruption. | One pending Cursor login per instance; exclusive link publication reports collisions. Use the foreground session when inject discovery is lost; seek an upstream lock fix. Distinct-session and simultaneous-resume refusal passed; settings/auth stress and reviewer isolation remain unverified. |
| PUB-01 | Implemented for DSH/OMP | Publisher leases, manifest-last recoverable journals and full sync reader leases prevent cooperative readers from accepting an interrupted generation. External noncooperating edits remain conflicts. Pi dynamic-path publication still requires one publisher. | Two-writer, reader/consumer exclusion, each write boundary, drift refusal and interrupted old-generation restoration tests. |
| CFG-01 | Implemented; 220 targeted tests passed | Workspace loading defers shared secret-file bodies until an operation resolves a selected reference. Direct `load_local` callers retain the compatible eager default. | Configuration-only read sentinels, malformed/symlink/conflicting stores and legitimate required key/status/runtime resolution tests. |
| TERM-01 | Implemented; native/platform NOT RUN | termcfg now manages zsh/tmux. Existing v1 machine/state metadata needs `migrate --drop-mihomo`; pending legacy journals must recover first. Services, private data and old target files remain untouched. Different machine IDs sharing HOME are not serialized. | 106 isolated tests passed for the terminal-only package, including migration interruption/drift and generic plugin/recovery behavior; see [migration guide](termcfg.md#retiring-an-existing-mihomo-selection). Native terminal checks remain separate. |
| PI-LOCK | Rebuilt; pi-default Linux native passed | Full npm resolution regenerated all four profile locks; pi-default installed, sealed and applied in new temporary HOME directories. Ignored large assets reused verified public caches. Resolution refreshed 70 transitive versions per Node profile and 71 in the Cursor profile; direct package pins remain unchanged. | Matching dual-TUI and sandboxed resource checks passed. Other profile/platform cold builds remain unverified; this is not four-profile or cold-download acceptance. |
| DSH-AR-01 | Accepted upstream limitation | Perry `0.12.17` can execute a late approval during OFF/unload; the observed execution count was 1 where 0 was expected. Session OFF is not a guaranteed cancellation barrier. | Real-host late-response tests execute zero actions after cancellation, OFF, and unload. |
| DSH-AR-02 | Accepted upstream limitation | Session OFF can return to ON on a later turn. For persistent manual operation, cancel and exit, set `auto_review = false` in the selected machine override, plan/apply, then restart. | OFF survives turns, restart, and restoration according to an explicit upstream contract. |
| DSH-AR-03 | Open audit limitation | Native approval records persist, but complete Perry verdict records are memory-only; a cold restart yielded zero reconstructed Perry verdicts. | Durable correlation of action, session/request/call identity, decision, mode, reason, and failure after restart, without secrets. |
| DSH-AR-04 | Open boundary evidence | General reviewer filesystem and authorization-context boundaries have not been fully proved. Rotom exposes a narrow context tool, but a tool whitelist alone is not an isolation proof. | Real-host boundary/sentinel tests for the selected reviewer implementation. |
| LEASE-01 / RM-002 | Open design work | Background descendants can inherit lease descriptors and keep deployment blocked after the foreground host exits. Diagnose the holder; do not delete locks or kill unrelated processes. | Foreground, daemon, abnormal exit, concurrent deployment, and PID-reuse cases preserve protection without leaked leases. |
| PI-RUN-02 | Restricted native scope | Default recipes share admission with project discovery disabled. Explicit project-resource discovery remains exclusive because role projections depend on cwd. Native UI settings are instance-wide and concurrent preference writes have no new transaction guarantee. | Separate native projections before relaxing exclusive discovery; do not infer concurrent settings or OAuth-refresh safety from shared admission. |
| PI-SOURCE / RM-001 | Open migration work | Historical Pi derived packages and build material need a package-by-package public-API migration audit. A source URL or `kind: local` does not establish unmodified provenance. | Source classification, replacement mapping, licenses, and matching behavior tests before retiring old material. |
| GOV-01 | Documentation TODO | The constitution retains `TODO(RATIFICATION_DATE)` because its original approval date has not been confirmed. | Confirm the original date with the maintainer; never invent or reset it during a wording update. |
| REVIEW-F02 | Open development tooling | Task Keeper's old package development lock does not match current local runtime/subagent dependencies. The isolated mock job is not a successful TypeScript typecheck. | A separate complete development lock, real SDK types, `tsc --noEmit`, and existing isolated mocks all pass without lifecycle scripts or native hosts. |
| OMP-NET | Planned | Independent model, reviewer, ordinary-tool, and download proxy routing is not fully delivered. Environment inheritance is not network isolation; NO_PROXY is address matching, not per-provider authorization. | Public-API feasibility, explicit source settings, route-isolation/failure tests, and no secret-bearing proxy URLs. |
| ENV-01 | Integrated; local DSH/OMP deployment verified | New contracts separate caller development environment from native state, preserve deletion/one-shot precedence, warn without values, and keep restricted workers minimal. DSH retains TUI HOME and uses public subprocess/MCP boundaries. | [Environment record](design/project-refactoring.md#execution-environment-follow-up): complete offline coverage, matching DSH/Pi native checks and two-HOME rebuilds passed. Local doctor, zero-change plan and repeated apply passed; other platforms/profile-native scopes remain separate. |
| ENV-02 | Integrated; local terminal deployment verified | termcfg preserves custom/empty NVM_DIR, selects XDG private hooks with an explicit ambiguity warning, and retains legacy fallback without sourcing both. OMP guides now distinguish execution and storage paths. | Catalog digests, offline terminal tests and 18 real isolated zsh cases passed. Authorized local zsh updates, strict doctor and repeated apply passed. Existing shells/tmux servers and private hooks were not restarted or executed for deployment acceptance. |
| DSH-MODEL-01 | Deferred by maintainer | The locked pi-ai 0.87.1 Codex catalog does not contain gpt-6.1-sol. The RC2 adapter's dependency range excludes evaluated newer catalogs. | Reevaluate during a normal compatible upstream upgrade. No forced dependency override, model alias, vendor edit or new OAuth adapter in the environment work. Account access remains separately unverified. |

DSH auto-review remains enabled in the public recipe by explicit maintainer choice despite DSH-AR-01–04. Its functional probe passing is not full safety acceptance. Ordinary workspace operations may never enter the approval chain and therefore may receive no reviewer call. See [approval boundaries](design/approvals.md) and the [DSH guide](dsh.md).

## Environment-dependent validation

| ID | Status | Scope still to verify |
| --- | --- | --- |
| OMP-F01 / OMP-F02 | NOT RUN | Native Linux arm64 and macOS x64/arm64 behavior; platform-selection tests alone are insufficient. |
| OMP-F03–F05 | Partial / NOT RUN | Fresh native login, usage, and each provider route. Historical small Cursor/reviewer samples do not validate all providers or the current source snapshot. |
| PI-PLATFORM | Partial / NOT RUN | pi-default Linux dual-TUI and sandboxed resource checks passed. Other operating systems/architectures and remaining profile/native/cold scopes are unverified. |
| PI-LIVE | NOT RUN | Authorized Codex, Cursor, MCP/web services, and proxy routes under the relevant current Pi candidate. |
| DSH-LIVE | Partial / NOT RUN | Earlier user-observed Cursor and Codex success remains historical. This release cleanup performs no fresh authentication, paid calls, or live refresh tests. Domestic API and Codex retests were previously deferred by the user. |
| TUI-NOTIFY | NOT RUN | Actual task notifications and image rendering in each terminal/tmux combination. tmux uses upstream text fallback rather than the original portrait. |

## Fixed in this preparation

- Malformed pnpm importer/dependency structures now fail as configuration errors.
- OMP native `null` role clearing is accepted for known roles without broadening nonempty selector authorization.
- The foundation artifact assertion includes both Catppuccin themes and selectors.
- Current guides use OMP `18.8.6`, describe the formal DSH recipe, and no longer claim DSH installs OpenSpec.

See [testing](testing.md) for current automated results and [Roadmap](roadmap.md) for larger work. Do not mark an environment-dependent item passed merely because implementation or mocks exist.

## Pi public API limits

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
