// Full主会话的自有委派工具：来源取捕获的SessionManager，不从模型输入取得授权。
import { captureOperationInput } from "./private-operation-input.ts";
import { isDeepStrictEqual } from "node:util";
const fail = code => { throw new Error(code); };
const fields = {
  submit: ["schema_version", "action", "request_id", "backend", "mode", "preset", "task", "model", "cwd", "timeout_seconds", "context_artifact", "feedback_required", "allow_workspace_write", "worktree_root"],
  message: ["schema_version", "action", "request_id", "run_id", "text"],
  continue: ["schema_version", "action", "request_id", "run_id", "text", "timeout_seconds"],
  cancel: ["schema_version", "action", "request_id", "run_id"],
};
export function createOfficialDelegate({ manifest, supervisor, sessionManager, configurationSnapshot, policySnapshot }) {
  if (manifest.profile_id !== "pi-full" || !manifest.plugins.includes("model-delegate")
      || manifest.plugin_capabilities?.["model-delegate"]?.capability_id !== "unified-delegate"
      || typeof supervisor?.call !== "function" || typeof sessionManager?.getSessionId !== "function"
      || typeof configurationSnapshot !== "function" || typeof policySnapshot !== "function") fail("DELEGATE_CAPABILITY_UNAVAILABLE");
  const sessionId = sessionManager.getSessionId();
  let retired = false, source, opening, baseline;
  const pending = new Set();
  const check = async signal => {
    if (retired || signal?.aborted || sessionManager.getSessionId() !== sessionId) fail("DELEGATE_SOURCE_STALE");
    policySnapshot();
    const snapshot = await configurationSnapshot();
    if (retired || signal?.aborted) fail("DELEGATE_SOURCE_STALE");
    if (baseline === undefined) baseline = captureOperationInput(snapshot).value;
    else if (!isDeepStrictEqual(baseline, snapshot)) fail("DELEGATE_SOURCE_STALE");
  };
  const tool = { name: "model_delegate", label: "Delegate", description: "Submit or control a bounded, controller-authorized readonly delegation. Missing strict budget qualification fails closed.",
    parameters: { type: "object", additionalProperties: false, required: ["schema_version", "action", "request_id"], properties: {
      schema_version: { type: "integer", const: 3 }, action: { type: "string", enum: Object.keys(fields) }, request_id: { type: "string", minLength: 1, maxLength: 256 },
      backend: { type: "string", enum: ["pi", "codex"] }, mode: { type: "string", enum: ["review", "investigate"] }, preset: { type: "string" }, task: { type: "string", maxLength: 65536 },
      model: { type: "object", additionalProperties: false, required: ["provider_id", "model_id"], properties: { provider_id: { type: "string" }, model_id: { type: "string" } } },
      cwd: { type: "string" }, timeout_seconds: { type: "integer", minimum: 1, maximum: 86400 }, context_artifact: { type: ["string", "null"] }, feedback_required: { type: "boolean" },
      allow_workspace_write: { type: "boolean", const: false }, worktree_root: { type: "null" }, run_id: { type: "string" }, text: { type: "string", maxLength: 65536 } } },
    async execute(_id, input, signal) {
      const operation = (async () => {
        try {
          const action = captureOperationInput(input).value;
          if (action.schema_version !== 3 || !fields[action.action] || Object.keys(action).some(key => !fields[action.action].includes(key))
              || action.mode === "implement" || action.allow_workspace_write === true || action.worktree_root != null) fail("DELEGATE_ACTION_INVALID");
          await check(signal);
          if (!source) {
            opening ??= supervisor.call("delegate_source_open_v3", { session_id: sessionId }).then(reply => {
              if (retired || typeof reply.source_ref !== "string") fail("DELEGATE_SOURCE_STALE");
              source = reply.source_ref; return source;
            });
            await opening;
          }
          await check(signal);
          const result = await supervisor.call("delegate_action_v3", { source_ref: source, action });
          await check(signal);
          const failed = result.status === "unknown" || result.status === "registered-not-started" || result.actions?.some(row => row.physical_state === "failed" || row.physical_state === "timeout"
            || row.physical_state === "canceled" || row.state === "rejected") === true;
          return { content: [{ type: "text", text: JSON.stringify(result) }], details: result, isError: failed };
        } catch { return { content: [{ type: "text", text: "DELEGATE_CONTROL_UNAVAILABLE" }], details: { code: "DELEGATE_CONTROL_UNAVAILABLE" }, isError: true }; }
      })();
      pending.add(operation);
      try { return await operation; } finally { pending.delete(operation); }
    } };
  return Object.freeze({ tool, retire() { retired = true; source = undefined; }, async drain() { await Promise.allSettled([...pending]); } });
}
