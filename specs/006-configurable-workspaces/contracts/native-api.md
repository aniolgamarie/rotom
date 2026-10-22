# Native API Contract

**Status**: Adapter extension implemented and fixture-tested; actual native behavior remains unverified and deployment is separate.
**Scope**: Public Herdr APIs only; [research R3/R4](../research.md#r3-stable-herdr-candidate-and-public-workspace-creation) and [lifecycle](lifecycle.md).

## Admission and version identity

Herdr 0.9.5 is the stable candidate researched on 2026-10-22. Its tagged [workspace request schema](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/src/api/schema/workspaces.rs) and [wire protocol](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/src/protocol/wire.rs) are source evidence, not native acceptance. Protocol 22 remains the starting adapter capability; a version number alone is not admission.

### Bounded v2 fixture evidence

`tests/fixtures/herdr-native/v2/` is a deliberately limited audit fixture for the workspace and tab methods newly needed by this contract. Its `api-schema.json` is not Herdr's complete generated schema. It records the request shapes for `workspace.create`, `workspace.rename`, `workspace.close` and `tab.rename`; `responses.json` contains fictional successful response examples for workspace creation and workspace/tab rename, plus an explicit unsupported-capability sentinel for close. The sentinel is Rotom fixture metadata, not a Herdr wire response. No successful close response is admitted because the tagged close request has no exact-membership compare-and-set condition.

The field evidence comes from tagged [`src/api/schema/workspaces.rs`](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/src/api/schema/workspaces.rs) (`WorkspaceCreateParams` lines 6–18, `WorkspaceCloseParams` lines 20–24, `WorkspaceRenameParams` lines 26–30), and method-to-parameter bindings from [`src/api/schema.rs`](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/src/api/schema.rs) (lines 74–91). `WorkspaceCreateParams` has optional `source_workspace_id`, `cwd`, `label`, default-false `focus`, and an env string map; it has no argv member. Rename requires `workspace_id` and `label`. Close requires `workspace_id` and has default-false `close_group`, with no expected membership/revision field.

The successful example result shapes are bounded to the tagged [`src/api/schema/response.rs`](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/src/api/schema/response.rs) variants `WorkspaceCreated` (workspace, tab and root pane; lines 53–57) and `WorkspaceInfo` (workspace; lines 50–52). All IDs and values in the examples are synthetic. Provenance includes the exact v0.9.5 commit, protocol, source file hashes, Apache-2.0 license identity and fixture digests in `tests/fixtures/herdr-native/v2/source.json`; `LICENSE` carries the upstream license text. This bounded fixture does not replace running binary, server, effective configuration, or metadata-capacity checks.

The bounded `tab.rename` admission uses required `tab_id` and `label` from commit-pinned [`TabRenameParams`](https://raw.githubusercontent.com/herdrdev/herdr/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/tabs.rs) (lines 24–28), the public method binding in `schema.rs` (lines 100–111), and `TabInfo` in `response.rs` (lines 83–85). The tabs schema hash is reused from the v1 audit of that exact commit; v1 fixtures remain unchanged. The reviewed [handler](https://raw.githubusercontent.com/herdrdev/herdr/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/app/api/tabs.rs) (lines 136–164) changes only the selected tab's custom name, persistence and rename event; it does not replace processes or layouts. No handler file hash is asserted. This method sets the initial purpose tab's label because ordinary `workspace.create.label` labels the workspace. Structured capability admission requires rename; legacy admission does not. Lost mutation replies remain unknown and are never resent.

Structured admission uses the frozen upstream tag/commit/source identities and audited public request/result fixtures. Validate the candidate's bundled schema, required fields, metadata constraints and running ping. Check disk binary, selected server, effective configuration and relevant detection/integration identities separately. Never invoke installation or update during work entry.

An existing native server must already use the prepared shell wrapper and accepted no-auto-resume configuration. If this cannot be verified, refuse a managed launch; do not change the running server or recreate panes to make it fit. Fresh server startup uses existing protected headless startup and keeps its native temporary workspace. This feature does not silently adopt or close that initial native workspace.

## Method ownership

| Public operation | Structured use | Required validation |
| --- | --- | --- |
| ping, workspace.list/get, pane.list/get/current, tab.get | Read current identities and capability evidence | Strict bounded envelopes/results, explicit caller IDs; no focus fallback |
| workspace.create | Create an ordinary independent workspace | Explicit cwd, label, focus=false, one-use env intent; no worktree operation |
| workspace.report_metadata, pane.report_metadata | Publish bounded identity/handshake markers | Owned source, capacity/sequence/value limits, readback |
| tab.create | Open one managed purpose instance | Explicit workspace, fixed cwd, label, focus=false, one-use env intent |
| workspace.focus, tab.focus, pane.focus | Focus verified current membership | Explicit native IDs; re-resolve after moves, no input injection |
| workspace.rename | Best-effort presentation of a verified named context | Config title saved first; explicit workspace ID, recheck epoch |
| workspace.close | **Not dispatched on current candidate** | Requires admitted server-side exact-scope guard absent in 0.9.5 |
| worktree.open/create, layout.apply, pane input/run, session stop | Not used for structured project lifecycle | No grouping, replacement, injected commands or server termination |

Preserve legacy method use and validation under legacy mode. Do not merely add every API method to a shared allowlist. Add precise local request/result schemas and verify the actual public capability used by each new path. New optional native fields may be tolerated where documented; unknown Rotom config/intent fields fail.

## Endpoint and caller rules

Keep Linux O_PATH/procfs endpoint pinning in [herdr.py](../../../src/termcfg/herdr.py). Connect each request through the pinned FD, not by re-resolving the socket pathname. A replacement server cannot be treated as the old endpoint. A retained dev/inode pair is not a durable boot token; restored marker loss is stale ownership, not permission to attach old numeric IDs.

The public transport handles one request per connection. Request IDs associate responses; no durable idempotency guarantee is assumed. Once a mutation may have been sent, broken response/timeout becomes unknown. No reconnect-and-resend. Read-only reconciliation uses the same pinned endpoint when available.

Environment-supplied pane IDs identify a candidate caller only. Resolve it through explicit pane.current and verify actual workspace/terminal identity, markers and receipt. Do not use a global focused-pane fallback or trust launch-time workspace/tab variables after native moves.

## Initial pane handoff

Tagged ordinary workspace creation accepts literal env but no argv field. Use the prepared `rotom-work-shell` path already supported by Rotom configuration. The one-use version-2 intent is the only additional environment payload; never overwrite native HERDR identity variables or carry it into the final child environment.

A new workspace ID is unknown before creation. Persist an authorized intent containing context, epoch, initial type, fixed start/launch choices, source/config-selection digests and endpoint identity first. The wrapper discovers its own actual workspace/pane/terminal through its caller ID, checks the intent and publishes ready. The parent correlates the unique op/epoch, verifies ordinary independent workspace identity, records returned native IDs, establishes workspace markers and commits this exact root pane. The wrapper checks those markers and commit before one accepted/exec path.

Use the exact state machine in [lifecycle.md](lifecycle.md); do not simplify it into “env means owned”. A missing response, an unmarked pane or an expired wrapper cannot establish that nothing was created.

## One-use intent envelope

The proposed ROTOM_WORK_LAUNCH_V2 value is a bounded JSON object (<=16 KiB UTF-8). Reject duplicate/unknown fields, non-finite values, invalid types and expired/extended deadlines. Its exact schema must be encoded in implementation and fake fixtures; raw payloads are private and never logged.

| Field group | Contract |
| --- | --- |
| version / creation | Version is integer 2; action distinguishes workspace-initial from existing-workspace tab creation; kind is default or extra, with initial always default |
| Identity | Random op/instance/epoch IDs, context kind and owner digest, ASCII type key; existing-tab form requires workspace ID, initial form obtains it from the actual caller and parent correlation |
| Trusted selection | Explicit local-file selection, session, trusted executing Rotom root, source digest and normalized non-secret launch/binding digest |
| Fixed process start | Resolved startup cwd, captured caller HOME and accepted launch/HOME boundary; never reconstruct from the server's current focused pane |
| Private intent location | Absolute protected state root/receipt reference, checked with existing ownership/link primitives; no lookup from a changed child XDG environment |
| Native endpoint | Selected socket address and expected dev/inode; every query uses the pinned endpoint, never a replacement pathname |
| Deadline | Parent's absolute monotonic expiry, bounded by the selected operation budget; child cannot restart or extend it |

Only the parent writes private binding/receipt state under the operation lock. The wrapper reads the authorized immutable intent and reports native readiness, without acquiring that lock or writing a second private record. Caller-derived native IDs and current markers must agree before commit. An alternate XDG root with missing private records is not permission to duplicate an already marked native identity.

## Close capability

The examined request has workspace_id and close_group, with no expected membership/revision condition. Rotom cannot guarantee FR-036 through a local double-read. `close_group=false` does not prevent a new pane joining after preview.

Expose read-only preview, show all selected workspace tabs/panes and the shared effect on every viewer, and return a clear missing-capability result for mutating close. A scope digest supplied to Rotom is review binding, not a server lock. No future task may invent an upstream parameter, use private APIs, close panes one by one as a substitute, or patch Herdr.

A later public capability can be admitted only with a new exact-source/schema review and tests inserting membership changes at the dispatch boundary. Until then, successful close is unverified/unavailable. Specification requirements are retained; refusal is not represented as successful closure.

## Evidence and fallback

Record candidate, protocol, audited source/fixture/lock identities, normalized actual argv, exit code, environment category and result. Keep private raw receipts outside the repository; publish no host/session data, screens, credentials or private paths.

If a capability is missing, return 5 before its mutation. Identity conflicts/unknown outcomes return 4. Existing native terminals remain available through native navigation. Do not silently downgrade to title matching, grouped creation, shell injection, private control or automatic state repair.

## Effective-configuration evidence limit

The examined public API has no read-only effective-config query. Protected startup observations bind explicitly observed binary/config/wrapper/source inputs to process start/executable identity and the same-user socket peer PID. Disk config checking is not relabeled as an attestation of a pre-existing running server. Existing servers without matching evidence are neither adopted nor restarted; managed creation refuses, while offline/read-only operations remain available. See the implementation refinement in research. Initial creation with a lost response also remains unknown because a moved pane cannot prove the birth identity of its current ordinary workspace; it is queried but never blindly committed or recreated.
