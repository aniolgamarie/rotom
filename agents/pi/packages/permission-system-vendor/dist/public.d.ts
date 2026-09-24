import { z } from 'zod';

declare const permissionStateSchema: z.ZodUnion<readonly [z.ZodLiteral<"allow">, z.ZodLiteral<"deny">, z.ZodLiteral<"ask">]>;
/** A permission decision. */
type PermissionState = z.infer<typeof permissionStateSchema>;

/**
 * Provenance of a rule — which source contributed it.
 *
 * Config scopes: "global", "project", "agent", "project-agent".
 * Synthesized:   "builtin" (universal default / evaluate() fallback),
 *                "baseline" (conditional MCP metadata auto-allow).
 * Runtime:       "session" (session approvals).
 * Rewrite:       "yolo" (composition-stage ask→allow rewrite under yolo mode),
 *                "fail-closed" (composition-stage allow→ask floor when an
 *                invalid non-global config scope is detected).
 */
type RuleOrigin = "global" | "project" | "agent" | "project-agent" | "builtin" | "baseline" | "session" | "yolo" | "fail-closed";

/**
 * Execution context of a bash command nested inside a substitution or subshell.
 * Absent for current-shell (top-level) commands.
 */
type BashCommandContext = "command_substitution" | "process_substitution" | "subshell";
/**
 * Why an indirection wrapper's floor did not apply after all (#803).
 *
 * `"core-reader"` — the command the wrapper runs is in the built-in pure-reader
 * core, so it is read-only for any argument feed and the floor's reason (an
 * unknown direction behind the wrapper) does not hold.
 *
 * A named reason rather than a boolean, so the review log states *why* a
 * wrapper was let through, and so a later source (a chain verdict, a user
 * declaration) is an added member rather than a second flag. ADR 0013 §11
 * keeps v1 at the audited core alone.
 */
type FloorExemption = "core-reader";
interface PermissionCheckResult {
    toolName: string;
    state: PermissionState;
    /** Custom denial reason from a deny-with-reason pattern, when present. */
    reason?: string;
    matchedPattern?: string;
    command?: string;
    target?: string;
    source: "tool" | "bash" | "mcp" | "skill" | "special" | "default" | "session";
    /** Which source contributed the winning rule. */
    origin: RuleOrigin;
    /**
     * Execution context of the offending nested command, when the winning bash
     * unit came from a substitution or subshell. Absent for current-shell
     * (top-level) commands.
     */
    commandContext?: BashCommandContext;
    /**
     * The command the winning bash unit actually runs, when it is a wrapper whose
     * inner command differs from the unit text (#713). Display-only: the gate
     * decides on `command`, and on `executedUnit`'s rules only when
     * {@link floorExemption} says the inner command is a proven pure reader.
     */
    executedUnit?: string;
    /**
     * Set when the winning bash unit is a wrapper the floor no longer covers,
     * naming why (#803). Recorded in the review log so an allow the floor would
     * once have prompted for is auditable to the reason that let it through.
     */
    floorExemption?: FloorExemption;
}

/**
 * The complete, structured description of a permission ask (ADR 0011 §2).
 *
 * A gate emits one of these instead of a sentence. It is complete by contract:
 * it never truncates and never decides what a human will see. Every consumer is
 * a renderer over it, eliding under its own budget — so elision is a property
 * of a render, never of the payload.
 */
interface PromptPayload {
    readonly kind: PromptPayloadKind;
    readonly request: PromptRequestFacts;
    /** Complete; each renderer elides to fit its own budget. */
    readonly evidence: readonly PromptEvidence[];
    /** Supplied by registered annotators; always marked as model-generated. */
    readonly annotations: readonly PromptAnnotation[];
}
/**
 * Which ask this payload describes — the renderers' dispatch discriminant.
 *
 * Present because the ask shapes are not separable by surface alone: a tool
 * external-directory ask and a bash one share the `external_directory` surface,
 * and the `path` gate and the per-tool gate differ only in wording. It gives
 * every renderer an exhaustive switch rather than a set of string comparisons a
 * new variant sails past — which is what let the parallel denial-context union
 * ADR 0011 §7 described dissolve into this one (#746).
 */
type PromptPayloadKind = "bash" | "mcp" | "tool" | "path" | "external_directory" | "bash_external_directory" | "skill" | "skill_read" | "forwarded";
/**
 * The invariant core (ADR 0011 §3): the facts visible in every render, that no
 * renderer's budget may elide.
 *
 * Named for what it holds — the permission request's own facts, matching the
 * package's `PermissionRequest` / `ForwardedPermissionRequest` vocabulary —
 * rather than for its contract, which this comment states instead.
 */
interface PromptRequestFacts {
    /** Who is asking, and whether the ask arrived from a subagent. */
    readonly requester: PromptRequester;
    /** The gate surface the rule fired on. */
    readonly surface: string;
    /** The gated tool name; `null` when the ask is not tool-shaped. */
    readonly toolName: string | null;
    /**
     * The invoked tool name when a shell alias re-exposes bash under another
     * name (#574) — "gated as bash, invoked as exec_command" is two facts.
     * `null` when it adds nothing.
     */
    readonly invokedToolName: string | null;
    /** The decision-relevant value: the command, path, MCP target, or skill name. */
    readonly value: string;
    /** The matched rule, including a sentinel such as `<indirection-bash-wrapper>`. */
    readonly matchedPattern: string | null;
    /**
     * Where the offending bash unit runs, when it came from a substitution or a
     * subshell. A fact rather than a rendered clause: it is what makes the
     * matched rule intelligible, and how it reads is the renderer's choice.
     */
    readonly commandContext: BashCommandContext | null;
    /**
     * For bash, the unit that will actually run — including inside an unstrippable
     * wrapper (#713). `null` when it adds nothing over {@link value}.
     */
    readonly executedUnit: string | null;
}
/** Who is asking, one hop below when the ask was forwarded. */
interface PromptRequester {
    readonly agentName: string | null;
    readonly forwarded: boolean;
    /** The requesting session, for a forwarded ask; `null` for a local one. */
    readonly sessionId: string | null;
}
/**
 * One piece of decision evidence.
 *
 * Complete on the payload; each renderer elides entries and orders them under
 * its own budget (ADR 0011 §4).
 */
interface PromptEvidence {
    readonly label: string;
    readonly text: string;
    /**
     * A secondary fact bound to this entry that a renderer may show alongside
     * {@link text} or elide independently — a path's symlink-resolved alias, for
     * instance. Bound to the entry rather than listed as a second one so an
     * elision cannot separate the two.
     */
    readonly detail: string | null;
}
/**
 * A model-generated advisory (ADR 0011 §8).
 *
 * The slot owns the attribution and the model-generated marking, so marking is
 * a property of the payload rather than a discipline each annotator must
 * remember. Structurally separate from any verdict: an annotation cannot allow,
 * deny, defer, or suppress.
 */
interface PromptAnnotation {
    readonly source: string;
    readonly text: string;
}

/**
 * Permission event channel — public contract.
 *
 * Exports channel name constants, TypeScript types for all emitted events,
 * and thin emit helpers.
 *
 * Stability guarantee: fields may be added, but existing fields will not be
 * removed or renamed without a semver-major version bump.
 */

/**
 * Emitted at `session_start` after the emitting node published its service, and
 * again at that node's first `before_agent_start` (ADR 0012 decision 3).
 *
 * Fires at least once per session and may repeat, so a handler must be
 * idempotent — registering on every emission hits the duplicate-registration
 * throw.
 */
declare const PERMISSIONS_READY_CHANNEL = "permissions:ready";
/** Emitted when a permission request is committed to the active UI prompt path. */
declare const PERMISSIONS_UI_PROMPT_CHANNEL = "permissions:ui_prompt";
/** Emitted after every permission gate resolution. */
declare const PERMISSIONS_DECISION_CHANNEL = "permissions:decision";
/**
 * Payload emitted on `permissions:ready`: plain facts about the node that
 * emitted it (ADR 0012 decision 2).
 *
 * The bus announces; the locator provides. The payload carries data a consumer
 * can log, serialize, and replay — never a live capability — so the service
 * itself is fetched with `getPermissionsService(sessionId)`.
 *
 * There is no `protocolVersion` — the published types plus package semver
 * define the broadcast contract.
 */
interface PermissionsReadyEvent {
    /**
     * The emitting node's session id: the key for
     * `getPermissionsService`. `null` when the host exposed no session
     * id, in which case this node published no keyed service.
     */
    sessionId: string | null;
    /**
     * Whether this node adjudicates its own asks (its authorizer chain runs) or
     * relays them to a serving node, which runs *its* chain over the same facts
     * (ADR 0007 §7).
     *
     * A registration needs no branch on this: extractors and formatters are read
     * by every node's own gates, and a chain link registered where no chain runs
     * is accepted and recorded rather than refused (ADR 0012 decision 4).
     */
    adjudicatesLocally: boolean;
}
/**
 * Origin of a UI prompt.
 *
 * Forwarding is orthogonal to origin: a forwarded subagent prompt keeps its
 * original source and is identified by a non-null `forwarding` field, not by a
 * dedicated source value.
 */
type PermissionUiPromptSource = "tool_call" | "skill_input" | "skill_read";
/** Forwarding context, present only when a prompt was forwarded from a non-UI subagent. */
interface ForwardedPromptContext {
    /** Requesting subagent's display name, when known. */
    requesterAgentName: string | null;
    /** Requesting subagent's session id, when known. */
    requesterSessionId: string | null;
}
/**
 * Payload emitted on `permissions:ui_prompt`, immediately before the active
 * user-facing permission UI is shown.
 *
 * Lean by design: `surface`/`value` are the normalized display projection a
 * notification consumer reads; `source` is the origin; `forwarding` is non-null
 * only for forwarded subagent prompts. There is no `protocolVersion` — the
 * published types plus package semver define the broadcast contract, and
 * consumers should read defensively.
 */
interface PermissionUiPromptEvent {
    /** Unique ID for the permission request being prompted. */
    requestId: string;
    /** Prompt origin. */
    source: PermissionUiPromptSource;
    /** Normalized display surface (e.g. "bash", "skill"), when known. */
    surface: string | null;
    /** Normalized display value (command, path, skill name, etc.), when known. */
    value: string | null;
    /** Agent name (when known). */
    agentName: string | null;
    /**
     * The ask's invariant core (ADR 0011 §3), verbatim from the prompt payload.
     *
     * Nested rather than flattened so the event and the payload share one shape:
     * a fact added to `PromptRequestFacts` reaches the bus without a second
     * hand-maintained declaration. Carries no evidence and no annotations — the
     * bus is the narrowest renderer (ADR 0011 §6), observable by any loaded
     * extension without the operator having named it.
     *
     * `request.surface` is the *gate* surface the rule fired on; the top-level
     * `surface` is the display projection. Both are here on purpose.
     */
    request: PromptRequestFacts;
    /** Forwarding context, or null for a direct prompt. */
    forwarding: ForwardedPromptContext | null;
}
/** How a permission decision was reached. */
type PermissionDecisionResolution = "policy_allow" | "policy_deny" | "session_approved" | "infrastructure_auto_allowed" | "user_approved" | "user_approved_for_session" | "user_denied" | "auto_approved" | "confirmation_unavailable"
/** A registered `authorizerChain` link granted the ask; no human was asked. */
 | "authorizer_allowed"
/** A registered `authorizerChain` link refused the ask; no human was asked. */
 | "authorizer_denied"
/** The gate threw, or an escalation failed, and the request was blocked. */
 | "gate_error";
/** Payload emitted on `permissions:decision`. */
interface PermissionDecisionEvent {
    /**
     * Identifies the permission request this decision resolves, minted when the
     * request was created. Distinct from the host's tool-call id: one tool call
     * runs several gates and so raises several requests.
     */
    requestId: string;
    /** Permission surface: "bash", "read", "mcp", "skill", "external_directory", etc. */
    surface: string;
    /** The value that was evaluated (command, tool name, skill name, path). */
    value: string;
    /** Final decision. */
    result: "allow" | "deny";
    /** How the decision was reached. */
    resolution: PermissionDecisionResolution;
    /** Which config scope contributed the winning rule (when available). */
    origin: string | null;
    /** Agent name (when known). */
    agentName: string | null;
    /** Matched pattern from the winning rule (when available). */
    matchedPattern: string | null;
    /**
     * Forwarding context for a decision this session made while serving another
     * session's forwarded request; absent on an ordinary local decision.
     *
     * The same `ForwardedPromptContext` the request's `permissions:ui_prompt`
     * carried, so a consumer that never saw the prompt can still tell a served
     * ask from a local one. Requester identity beyond it — the requester's cwd
     * and principal — stays off the bus.
     */
    forwarding?: ForwardedPromptContext | null;
}

/**
 * The child's session-approval suggestion, relayed to the serving node so a
 * human who grants "the whole session" records the same pattern the child
 * would have recorded locally.
 *
 * A plain data shape (not the `SessionApproval` value object) so it serializes
 * onto the forwarded request; the serving node rebuilds a `SessionApproval`
 * from it via `SessionApproval.multiple`.
 */
interface ForwardedSessionApproval {
    surface: string;
    patterns: readonly string[];
}
/**
 * The child-fixed facts a gate emits: the surface it evaluated and the match
 * set it computed. `requesterCwd` and `principal` are stamped at the escalation
 * edge (`ParentAuthorizer`), so a gate carries only what it alone can produce.
 *
 * Strings only — an `AccessPath` never crosses onto the wire
 * (`docs/decisions/0002-path-values-string-boundary.md`).
 */
interface ForwardedAccessFacts {
    /** Gate surface: `"path"`, `"external_directory"`, `"bash"`, a tool name, or a skill name. */
    surface: string;
    /**
     * The child-fixed match set. Path surface: `AccessPath.matchValues()`
     * (absolute ∪ cwd-relative ∪ canonical), computed at the child. Non-path
     * surface: the already-portable single value as a one-element array.
     */
    matchValues: string[];
    /** `AccessPath.boundaryValue()` (canonical) for a path surface; `null` for a non-path surface. */
    boundaryValue: string | null;
}

type PermissionReviewSource = "tool_call" | "skill_input" | "skill_read";
/**
 * Provenance of a forwarded ask: who is really asking, one hop below.
 *
 * Present on {@link PromptPermissionDetails} only when the ask was forwarded
 * from a subagent. Structurally identical to the event's `ForwardedPromptContext`
 * so the details flow straight into `buildUiPrompt`, but declared here to keep
 * the prompter layer free of an events-module import.
 */
interface ForwardedAskProvenance {
    requesterAgentName: string | null;
    requesterSessionId: string | null;
}
/** Details passed when prompting the user for a permission decision. */
interface PromptPermissionDetails {
    requestId: string;
    source: PermissionReviewSource;
    agentName: string | null;
    /**
     * The complete structured description of this ask (ADR 0011 §2).
     *
     * Required: every ask carries one, and the type is what guarantees it rather
     * than a convention each gate has to remember. Every consumer — the dialog,
     * the wire, the broadcast, the review log, the agent-facing denial text — is
     * a render over it, so no two of them can disagree.
     */
    payload: PromptPayload;
    toolCallId?: string;
    toolName?: string;
    skillName?: string;
    path?: string;
    command?: string;
    target?: string;
    toolInputPreview?: string;
    /** Override label for the "for this session" dialog option. */
    sessionLabel?: string;
    /** Explicit display-surface override (a forwarded ask carries the child's original). */
    surface?: string | null;
    /** Explicit display-value override (a forwarded ask carries the child's original). */
    value?: string | null;
    /** Present iff this ask was forwarded from a subagent; drives the non-degraded broadcast + "(Subagent)" title. */
    forwarding?: ForwardedAskProvenance;
    /**
     * The session-approval suggestion for this ask. On the child's escalation it
     * rides into the forwarded request; on the serving node it lets the dialog
     * offer a whole-session grant scope. Absent when the gate computed no
     * suggestion.
     */
    sessionApproval?: ForwardedSessionApproval;
    /**
     * The child-fixed access facts the raising gate computed (surface + match
     * set). Rides through the runner to the escalation edge, which completes
     * them into a `ForwardedAccessIntent` by stamping `requesterCwd` and
     * `principal`. On a serving node these facts are projected back off the
     * forwarded request, so a forwarded ask reaches the `Authorizer` chain with
     * the same evidence as a local one; only a version-skew request that carried
     * no intent leaves this absent.
     */
    accessIntent?: ForwardedAccessFacts;
}

/**
 * A non-terminal chain link's ruling on an `ask`: decide (`allow`/`deny`) or
 * pass the ask on to the next link (`defer`). A `deny` carries an optional
 * teaching `reason` the invoking model sees, so it can self-correct.
 */
type AuthorizerVerdict = {
    kind: "allow";
} | {
    kind: "deny";
    reason?: string;
} | {
    kind: "defer";
};
/**
 * A non-terminal link in the live-authority chain: reviews an `ask` and may
 * decide it or defer to the next link (ADR 0007). The chain injects a narrow,
 * session-scoped {@link PermissionQuery} at `authorize` time (§3), so a link
 * queries the deterministic engine at gate parity rather than reaching for the
 * cross-extension service via `Symbol.for()`. It also injects an
 * {@link AuthorizerLog} so a link can record its decision trail to the shared
 * permission review log (same §3 injection pattern).
 */
interface Authorizer {
    authorize(details: PromptPermissionDetails, query: PermissionQuery, log: AuthorizerLog): Promise<AuthorizerVerdict>;
}

/**
 * Registry for custom tool access-intent extractors.
 *
 * Lets sibling extensions declare the filesystem path a tool will access when
 * the tool's input shape is not the default `input.path` convention, so the
 * cross-cutting `path` and `external_directory` gates can see it.
 * One extractor per tool name; duplicate registration throws.
 */
/** Returns the filesystem path this tool will access, or `undefined` to decline. */
type ToolAccessExtractor = (input: Record<string, unknown>) => string | undefined;

/**
 * Registry for custom tool-input preview formatters.
 *
 * Allows extensions to register a formatter for a specific tool name so
 * permission prompts can show a human-readable summary instead of raw JSON.
 * One formatter per tool name; duplicate registration throws.
 */
/** A custom preview formatter for one tool's input. Returns `undefined` to decline. */
type ToolInputFormatter = (input: Record<string, unknown>) => string | undefined;

/**
 * Cross-extension service accessors backed by `Symbol.for()` on `globalThis`.
 *
 * `Symbol.for()` is process-global by spec, so it survives jiti's per-extension
 * module isolation (`moduleCache: false`). A consumer doing
 * `import("@gotgenes/pi-permission-system")` gets a fresh module copy, but the
 * accessors here read from the same `globalThis` slots the provider wrote to —
 * enabling direct, synchronous, type-safe function calls.
 *
 * The slot is a session-keyed map, because one process can host several
 * **nodes** (one Pi session runtime each — a root session and its in-process
 * subagent children all load their own instance of this extension). Every node
 * writes under its own session id, and `getPermissionsService(sessionId)`
 * resolves the service whose registries that node's own gates and chain read
 * (ADR 0012 decision 2).
 *
 * Best practice: resolve per use rather than caching the reference — this
 * ensures resilience across `/reload` and load-order edge cases.
 */

/**
 * The narrow review-log seam handed to a chain link at `authorize` time
 * (ADR 0007 §3, same injection pattern as {@link PermissionQuery}).
 *
 * A link uses it to record a positive decision trail to the permission review
 * log — `review` for the durable, default-on audit entry (one per handled
 * ask), `debug` for verbose or short-circuit detail gated behind the
 * `debugLog` toggle. The session's own logger is passed straight through, so a
 * link's entries land in the same `pi-permission-system-permission-review.jsonl`
 * as the gate decisions, keying to a gate entry by `requestId`.
 */
interface AuthorizerLog {
    review(event: string, details?: Record<string, unknown>): void;
    debug(event: string, details?: Record<string, unknown>): void;
}

/**
 * The narrow, read-only projection of {@link PermissionsService}: answer a
 * policy query for a surface, and report a tool-level state. This is the
 * capability an Authorizer chain link is handed (ISP) — it never sees the
 * registration surface.
 */
interface PermissionQuery {
    /**
     * Query the permission policy for a surface and value.
     *
     * @param surface   - Permission surface: "bash", "read", "mcp", "skill",
     *                    "external_directory", etc.
     * @param value     - The value to evaluate: command string, tool name, skill
     *                    name, or path. Omit or pass `undefined` for a
     *                    surface-level query.
     * @param agentName - Optional agent name for per-agent policy resolution.
     * @returns Full check result including state, matched pattern, and origin.
     */
    checkPermission(surface: string, value?: string, agentName?: string): PermissionCheckResult;
    /**
     * Query the tool-level permission state for pre-filtering tools before
     * creating a child session.
     *
     * Returns `"deny"` | `"allow"` | `"ask"` based on the composed policy.
     * Does not consider command-level rules (e.g. per-bash-command patterns) —
     * use `checkPermission` for runtime invocation gates.
     *
     * @param toolName  - Tool name (e.g. `"bash"`, `"read"`, `"my-extension:tool"`).
     * @param agentName - Optional agent name for per-agent policy resolution.
     */
    getToolPermission(toolName: string, agentName?: string): PermissionState;
}
/**
 * Public interface exposed to other extensions via
 * {@link getPermissionsService}.
 *
 * Each instance belongs to one node, and its three registration surfaces are
 * read by that node alone: extractors and formatters by its own gates, chain
 * links by its own chain. Resolve the service of the node whose behavior you
 * mean to affect.
 *
 * `checkPermission` takes a surface + optional value + optional agent name,
 * and delegates to `PermissionManager.checkPermission()` with current session
 * rules internally.
 */
interface PermissionsService extends PermissionQuery {
    /**
     * Register a custom preview formatter for a specific tool name.
     *
     * The formatter is consulted first inside `ToolPreviewFormatter.formatToolInputForPrompt`;
     * returning `undefined` falls through to the built-in switch (and ultimately
     * the JSON default).
     *
     * Only one formatter may be registered per tool name — a second call for the
     * same name throws.  The returned disposer unregisters the formatter.
     *
     * @param toolName  - Exact tool name to register for (e.g. `"mcp"`, `"my-server:run"`).
     * @param formatter - Receives the raw `input` record; return a string to use
     *                    as the prompt preview, or `undefined` to decline.
     */
    registerToolInputFormatter(toolName: string, formatter: ToolInputFormatter): () => void;
    /**
     * Register a custom access-intent extractor for a specific tool name.
     *
     * The extractor declares the filesystem path a tool will access so the
     * cross-cutting `path` and `external_directory` gates can see it. Use it for
     * tools whose path lives under a non-standard key — built-in file tools and
     * any tool exposing `input.path` (plus MCP via `input.arguments.path`) are
     * already covered by convention without registration.
     *
     * The extractor receives the raw `input` record and returns the path string,
     * or `undefined` to decline. Only one extractor may be registered per tool
     * name — a second call for the same name throws. The returned disposer
     * unregisters the extractor.
     *
     * @param toolName  - Exact tool name to register for (e.g. `"ffgrep"`).
     * @param extractor - Receives the raw `input` record; return the path string,
     *                    or `undefined` to decline.
     */
    registerToolAccessExtractor(toolName: string, extractor: ToolAccessExtractor): () => void;
    /**
     * The access extractor registered on this node for `toolName`, or
     * `undefined` when it has none.
     *
     * This is the read face of a **fact-shaping** registry, and unlike the
     * authority surfaces it is meant to be read across a node boundary: an
     * extractor produces a fact about a call (the path it touches) and decides
     * nothing, so an in-process child whose own registry has no entry may
     * resolve an ancestor node's service and use its answer to complete the
     * child's own fact-gathering (ADR 0012 decision 1).
     *
     * The same does not hold for {@link registerAuthorizer}: a link produces a
     * verdict, and live authority converges at the adjudicating node (ADR 0007
     * §7). There is deliberately no reader for it.
     */
    getToolAccessExtractor(toolName: string): ToolAccessExtractor | undefined;
    /**
     * The preview formatter registered on this node for `toolName`, or
     * `undefined` when it has none.
     *
     * Fact-shaping, and cross-node readable for the same reason as
     * {@link getToolAccessExtractor}.
     */
    getToolInputFormatter(toolName: string): ToolInputFormatter | undefined;
    /**
     * Register a named live-authority chain link (ADR 0007 §4).
     *
     * A link reviews an `ask` and returns `allow` / `deny` (with an optional
     * teaching `reason`) / `defer`. It is handed a narrow, session-scoped
     * {@link PermissionQuery} at `authorize` time so it can query the
     * deterministic engine at gate parity. Register from a `permissions:ready`
     * handler so registration is robust to load order and survives `/reload`.
     *
     * Registration alone grants **no authority**: the link decides nothing until
     * the operator names it in the `authorizerChain` config (opt-in activation),
     * and the chain owner caps every verdict with the bounded-delegation
     * checkpoint (an `allow` on an excluded surface downgrades to `defer`). Only
     * one link may be registered per name — a second call for the same name
     * throws. The returned disposer unregisters the link.
     *
     * @param name      - Operator-facing link name referenced from `authorizerChain`.
     * @param authorize - The link's decision callback
     *                    (`(details, query, log) => verdict`); `log` is an
     *                    {@link AuthorizerLog} for recording a decision trail to
     *                    the shared permission review log.
     */
    registerAuthorizer(name: string, authorize: Authorizer["authorize"]): () => void;
}
/**
 * Publish `service` as the service of the node whose session is `sessionId`
 * (ADR 0012 decision 2 — node-locality).
 *
 * Every node publishes under its own key, including an in-process subagent
 * child, so there is nothing to clobber: a child's sibling extension registers
 * an extractor, formatter, or chain link into the registry the child's own
 * gates and chain read.
 */
declare function publishPermissionsService(sessionId: string, service: PermissionsService): void;
/**
 * Retrieve the service belonging to the node whose session is `sessionId`, or
 * `undefined` when that node has published none.
 *
 * This is the supported way to obtain a node's service, for registration and
 * for policy queries alike. Take `sessionId` from the `permissions:ready`
 * payload (or from `ctx.sessionManager.getSessionId()` inside your own session
 * handler), and resolve per use rather than caching the reference.
 *
 * A caller the type checker cannot reach — JavaScript, or a consumer compiled
 * against an earlier major — may still call this with no argument. That answers
 * `undefined` rather than another node's service, and warns once so the missing
 * registration is not silent.
 */
declare function getPermissionsService(sessionId: string): PermissionsService | undefined;
/**
 * Remove the `sessionId` entry, but only when it still holds `service`
 * (identity compare-and-delete).
 *
 * Called during `session_shutdown` to avoid stale references after the node is
 * torn down. Scoping the delete to the publishing instance keeps a superseded
 * `/reload` generation's late shutdown from wiping the new generation's freshly
 * published service.
 */
declare function unpublishPermissionsService(sessionId: string, service: PermissionsService): void;

export { PERMISSIONS_DECISION_CHANNEL, PERMISSIONS_READY_CHANNEL, PERMISSIONS_UI_PROMPT_CHANNEL, getPermissionsService, publishPermissionsService, unpublishPermissionsService };
export type { Authorizer, AuthorizerLog, AuthorizerVerdict, ForwardedPromptContext, PermissionCheckResult, PermissionDecisionEvent, PermissionQuery, PermissionState, PermissionUiPromptEvent, PermissionUiPromptSource, PermissionsReadyEvent, PermissionsService, PromptAnnotation, PromptEvidence, PromptPayload, PromptPayloadKind, PromptPermissionDetails, PromptRequestFacts, PromptRequester, ToolInputFormatter };

export declare function getAgentcfgPolicySnapshot(sessionId: string): unknown;
