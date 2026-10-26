# Proposal: opt-in strict restore with an observable startup outcome

Historical issue draft retained for optional research; **not submitted upstream**.
There is currently **no plan to submit it**, and upstream changes are not a
resume delivery dependency. The current delivery uses the existing official
explicit-session restore entry with separate requested-target, launch-dispatch,
load-confirmation, and continuation states. An unconfirmed load permits a safe
handoff to the user, never a `restored` claim or automatic continuation.
Scope/ownership/cwd and native writer-conflict protection remain dispatch gates.
The strict outcome below concerns optional stronger confirmation; it does not
block that handoff. Cached Core in-memory creation probes are not restore tests.
This is a proposed contract, not an available API or a validated TUI restore.
Source review scope: dsh-TUI `0.16.1`, commit
`73ff99fbed56563bf154d719effd09f9f9725349`, with Core `0.2.1-rc.2`.
No conclusion about other versions is intended.

## Request

Could TUI expose two small, opt-in capabilities for restoring an exact session?

1. A strict restore policy that rejects **any existing Agent** at the actual
   `resolveAgent` reuse branch, including Agents whose initialization succeeded.
2. A public, retained startup outcome tied to the session actually adopted by
   the foreground channel and to that channel's binding/lifecycle identity.

Keep the existing TUI mount reservation, persisted preset/route resolution,
setup, and official awaited `ctx.agents.resume(...)` path. Plugins should not
need to recreate these steps or acquire ownership of TUI's handle.
Default startup behavior can remain unchanged.

## Why foreground identity alone is insufficient

The following is a **source-derived logical interleaving**, not a reproduced
runtime trace:

| Step | Possible operation |
| --- | --- |
| 1 | Core publishes Agent A to its registry before all `agent/created` listeners finish. |
| 2 | An early listener observes A; a later asynchronous listener remains pending. |
| 3 | TUI resolves the requested session, finds A, and takes the existing-Agent reuse branch. |
| 4 | A plugin can observe a matching foreground session/cwd while A's initialization has no committed result. |
| 5 | The later listener rejects; initialization fails and Core performs its failure cleanup. |

An observed creation event, registry hit, matching foreground metadata, or idle
state does not establish that initialization succeeded. `whenIdle()` also
releases waiters after failed maintenance; an extra empty maintenance operation
does not recover the original initialization outcome.

Pinned official sources:

- [TUI existing-Agent reuse and disk restore](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/plugin.ts#L2834).
- [Core publication and initialization failure handling](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent-loop/src/index.ts), [idle/maintenance implementation](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent-loop/src/agent.ts), and [awaited resume API](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent/src/index.ts#L383).
- [TUI persisted restore preparation](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/plugin.ts#L2854), [internal startup Promise](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/plugin.ts#L735), and [completion handling](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/plugin.ts#L2747).
- [Public channel contract](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/adapter/ports/channel-ui.ts#L554), [resumeTo implementation](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/channel/session-resume.ts#L145), and [package exports](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/package.json).

`resumeTo()` is awaitable, but its successful result does not distinguish an
unchanged target, adoption of a live Agent, and disk restoration. Exporting the
internal startup Promise alone would likewise leave the reuse case unresolved.

### Narrow Core-only reproduction

The [manual probe](../../tests/manual/dsh_initialization_probe.mjs) mounts only
public Core services and creates an in-memory Agent, holding `agent/created` on
an explicit Promise gate. Run it with an explicitly selected isolated package
installation: `node dsh_initialization_probe.mjs --runtime-root /path/to/runtime`.
It does not install packages, load persistence, start TUI, or send input.

On 2026-10-24, both cases passed in a network-isolated process with an empty
inherited environment, temporary HOME, and read-only package mounts: registry
visibility preceded creation completion; releasing the gate allowed success;
throwing after release rejected creation and removed both registry entries.
The cache reports Core `0.2.1-rc.2` and Cordis `4.0.5`; its eight direct-package
lock integrity entries match the candidate lock, and their files were unchanged
by this run. Fresh npm archive retrieval failed, so archive byte identity and
the full dependency closure remain unverified. This is a cached-package behavior
experiment, not a reproduction of TUI foreground adoption or a restore test.

## Proposed minimum semantics

**Strict policy.** Fix the requested target before startup. Missing target,
writer conflict, or loading/initialization failure must fail the attempt without
creating a replacement session or taking a recent-session/safe-mode cold-start
fallback. Reject existing Agents at the reuse decision itself; checking an empty
registry earlier leaves a race. If a competitor appears afterward, propagate
official resume admission/writer conflicts rather than catching and reusing it.
The official persistence backend retains writer ownership and its documented
[platform/filesystem limits](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/session/session-persistence-jsonl/README.md).

**Outcome.** A name such as `startupOutcome` is illustrative only. A retained
snapshot/subscription or equivalent Promise plus current-binding validation
would suffice. The public result needs only:

- An opaque identity for this startup attempt and `pending`, `committed`, or
  `failed` state, with bounded failure categories.
- On commitment, actual session identity and persisted cwd, strict-resume origin,
  and the binding identity under which the foreground channel adopted it.
- A lifecycle/binding validity check: channel/owner identity and a generation or
  equivalent identity that changes on switching, reload, and same-ID rebinding.

Commit only after official resume, setup, and all initialization listeners that
affect success complete, and after the corresponding foreground adoption is
committed. Define the ordering of adoption, outcome publication, and invalidation
so a transient notification cannot certify an adoption that subsequently rolls
back. Separate observer notification from that transaction: a subscriber throwing
must not turn an already committed restore into a failed restore or roll it back.

Late subscribers must retrieve the outcome and establish its current validity
without a snapshot/subscription race. Existing versions/generations may suffice
if their combined ordering is specified; an observation gap must be detectable
and leave validity unknown until resynchronized. The result must be available
during ordinary chat startup, without activating a diagnostic scene. If public
`ChannelUi` access cannot provide that, a public plugin service or startup-caller
result with equivalent semantics would work; private getters would not.

Historical commitment and current validity are separate facts. Switching or
owner destruction invalidates authority over the current foreground binding;
it does not rewrite a past committed attempt as failed. A timeout, lost observer,
or missing notification means the consumer has no confirmed result, not that
initialization necessarily failed. Neither circumstance should trigger an
automatic retry or duplicate restore.

## Suggested acceptance matrix

These are proposed tests, **not executed or passing results**.

| Case | Required outcome |
| --- | --- |
| Existing target, successful disk restore | One committed strict-resume outcome after initialization and foreground adoption, with actual session/cwd and binding identity. |
| Missing target, including deletion during open | Failed attempt; no replacement session or cold-start fallback. |
| External writer conflict | Failed attempt through official writer admission; no lock bypass or fallback. |
| Existing initialized Agent | Strict policy rejects at the reuse branch. |
| Existing Agent still initializing | Strict policy rejects; registry visibility cannot produce commitment. |
| Later initialization listener rejects | The restoring attempt fails; earlier creation/foreground/idle observations cannot produce commitment. |
| Late subscription or switch between snapshot and subscription | Retained result plus ordering/validity check yields the correct binding or explicit unknown; no stale success. |
| Switch, reload, or same session ID rebound | Old attempt remains historical; it cannot certify the new binding. |
| Channel owner destroyed | Current validity is revoked; previous commitment remains historical. |
| Observer callback throws | Committed restore remains committed; observer failure is isolated. |

## Scope

This proposal does not require reusable-Agent support, a Core-wide Agent query
service, full event replay, durable audit logs, final shutdown sealing, input
readiness, automatic continuation, or downstream run/batch/IPC protocols.
No message bodies, credentials, or session file contents are needed.
A future reuse extension could await an initialization result shared by the
exact Agent lifecycle; caching success by session ID alone would be insufficient.

Local context: [reviewed startup contract](../rotom-dsh-startup-contract.md) and
[session capability boundaries](../rotom-session-capabilities.md). No upstream,
vendor, runtime, or production configuration was modified for this draft.
