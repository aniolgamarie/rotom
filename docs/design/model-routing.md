# Models, routes, and authentication

A stable Rotom model ID expresses a local reference. A provider binds protocol, endpoint, credential ownership, and remote model ID. Shared model specifications do not merge accounts or billing. A TF binding and an official API binding may describe similar capabilities while remaining separate routes.

## Resolution

Shared default providers/models are added as selectable entries. Explicit profile roles keep precedence over the default main model. Other arrays retain replacement semantics. Rotom does not fabricate OAuth endpoints, silently change roles to another paid service, or reuse a legacy key under a new provider.

A `secret:<name>` reference resolves through private SecretStore inputs at the required operation. Public templates, render output, digests, and logs contain references rather than key values. Empty placeholders do not hide a valid shared value; two nonempty sources for the same secret are a conflict. Native OAuth tokens are owned by the native credential service in the correct instance, not by the public model catalog.

Missing API credentials leave the route unavailable without preventing ordinary host startup. Operation-specific MCP/service requirements can still fail with the documented missing-credential exit code. Do not infer readiness from a displayed model name alone.

## Cursor Provider versus delegation

DSH Cursor subscription is a main-session Provider: model selection and inference are routed through its plugin. Calling Cursor CLI/ACP as a delegated tool is a different capability and is not a replacement for that Provider. Pure terminal authentication uses the plugin's public authentication interface through a thin Rotom command adapter; it must not copy an OAuth implementation or import another application account.

Model discovery failure must remain unverified. A fallback catalog is not an account-confirmed catalog, and missing usage is unknown rather than zero. Authentication success alone does not prove text streaming, tool calls, restart restoration, or context compression.

## Protocol regression rationale

An older Cursor integration incorrectly treated consecutive user messages as separate unanswered turns. DSH can append rules, runtime context, and skill metadata after the actual task, so forwarding only the last message sent injected context as the task. Regression cases must retain the last actual user task plus relevant adjacent context, then preserve tool call/result identity across turns and compression.

Do not fix that class of defect by rewriting the upstream package in node_modules. Validate the selected unmodified package against no-account protocol cases and bounded authorized live calls. Keep failure injection deterministic for 401, 429, interruptions, cancellation, and refresh failures; do not deliberately exhaust a real account or blindly replay an ambiguously processed request.

## Reasoning and retries

Effort support is model/protocol-specific. DSH's `/effort` exposes the supported route behavior and persists manual selection in native instance state. Rotom intentionally sets no universal medium default: unsupported reasoning levels must not be invented. A missing UI reading does not establish that every model uses identical reasoning behavior.

DSH TUI's `upstreamRetry = false` prevents new implicit retry seeding; it does not disable every lower-level OAuth client's retry logic. Explicit API request policies remain bounded and cancelable. Never rerun a completed side-effecting tool merely to recover a model stream. Respect Retry-After within the configured waiting budget.

See [model catalog](../model-catalog.md), [local configuration](../local-config.md), [DSH](../dsh.md), and [OMP model presets](../omp-model-presets.md).
