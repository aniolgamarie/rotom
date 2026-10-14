# Known issues and TODOs

This is the maintained issue register for release preparation. **Open**, **blocked**, and **not run** are different states. A historical test result applies only to its recorded candidate and scope. No item here authorizes a host patch, a credential import, or a silent fallback to broader permissions.

## Open implementation and upstream issues

| ID | Status | Impact and recovery | Completion evidence required |
| --- | --- | --- | --- |
| PI-LOCK | Open; blocks new Pi deployment | The checked-in Pi manifest's recipe digest does not match current source. `validate`, `plan`, `sync`, and related new-deployment paths reject it. An already deployed `run` uses its saved contract and is not automatically broken by this mismatch. | Rebuild through the real locked resolution/materialization path, inspect complete lock/vendor changes, then repeat matching native and cold-build verification. Editing only the digest is insufficient. |
| DSH-AR-01 | Accepted upstream limitation | Perry `0.12.17` can execute a late approval during OFF/unload; the observed execution count was 1 where 0 was expected. Session OFF is not a guaranteed cancellation barrier. | Real-host late-response tests execute zero actions after cancellation, OFF, and unload. |
| DSH-AR-02 | Accepted upstream limitation | Session OFF can return to ON on a later turn. For persistent manual operation, cancel and exit, set `auto_review = false` in the selected machine override, plan/apply, then restart. | OFF survives turns, restart, and restoration according to an explicit upstream contract. |
| DSH-AR-03 | Open audit limitation | Native approval records persist, but complete Perry verdict records are memory-only; a cold restart yielded zero reconstructed Perry verdicts. | Durable correlation of action, session/request/call identity, decision, mode, reason, and failure after restart, without secrets. |
| DSH-AR-04 | Open boundary evidence | General reviewer filesystem and authorization-context boundaries have not been fully proved. Rotom exposes a narrow context tool, but a tool whitelist alone is not an isolation proof. | Real-host boundary/sentinel tests for the selected reviewer implementation. |
| LEASE-01 / RM-002 | Open design work | Background descendants can inherit lease descriptors and keep deployment blocked after the foreground host exits. Diagnose the holder; do not delete locks or kill unrelated processes. | Foreground, daemon, abnormal exit, concurrent deployment, and PID-reuse cases preserve protection without leaked leases. |
| PI-SOURCE / RM-001 | Open migration work | Historical Pi derived packages and build material need a package-by-package public-API migration audit. A source URL or `kind: local` does not establish unmodified provenance. | Source classification, replacement mapping, licenses, and matching behavior tests before retiring old material. |
| REVIEW-F02 | Open development tooling | Task Keeper's old package development lock does not match current local runtime/subagent dependencies. The isolated mock job is not a successful TypeScript typecheck. | A separate complete development lock, real SDK types, `tsc --noEmit`, and existing isolated mocks all pass without lifecycle scripts or native hosts. |
| OMP-NET | Planned | Independent model, reviewer, ordinary-tool, and download proxy routing is not fully delivered. Environment inheritance is not network isolation; NO_PROXY is address matching, not per-provider authorization. | Public-API feasibility, explicit source settings, route-isolation/failure tests, and no secret-bearing proxy URLs. |

DSH auto-review remains enabled in the public recipe by explicit maintainer choice despite DSH-AR-01–04. Its functional probe passing is not full safety acceptance. Ordinary workspace operations may never enter the approval chain and therefore may receive no reviewer call. See [approval boundaries](design/approvals.md) and the [DSH guide](dsh.md).

## Environment-dependent validation

| ID | Status | Scope still to verify |
| --- | --- | --- |
| OMP-F01 / OMP-F02 | NOT RUN | Native Linux arm64 and macOS x64/arm64 behavior; platform-selection tests alone are insufficient. |
| OMP-F03–F05 | Partial / NOT RUN | Fresh native login, usage, and each provider route. Historical small Cursor/reviewer samples do not validate all providers or the current source snapshot. |
| PI-PLATFORM | NOT RUN | Other operating systems/architectures and current native/cold validation after PI-LOCK is resolved. |
| PI-LIVE | NOT RUN | Authorized Codex, Cursor, MCP/web services, and proxy routes under the relevant current Pi candidate. |
| DSH-LIVE | Partial / NOT RUN | Earlier user-observed Cursor and Codex success remains historical. This release cleanup performs no fresh authentication, paid calls, or live refresh tests. Domestic API and Codex retests were previously deferred by the user. |
| TUI-NOTIFY | NOT RUN | Actual task notifications and image rendering in each terminal/tmux combination. tmux uses upstream text fallback rather than the original portrait. |

## Fixed in this preparation

- Malformed pnpm importer/dependency structures now fail as configuration errors.
- OMP native `null` role clearing is accepted for known roles without broadening nonempty selector authorization.
- The foundation artifact assertion includes both Catppuccin themes and selectors.
- Current guides use OMP `18.8.6`, describe the formal DSH recipe, and no longer claim DSH installs OpenSpec.

See [testing](testing.md) for current automated results and [Roadmap](roadmap.md) for larger work. Do not mark an environment-dependent item passed merely because implementation or mocks exist.
