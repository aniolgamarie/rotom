// 只通过公开 ExtensionAPI/ExtensionToolContext 注册和调用；不取 runner 私有字段。
export function createProbeExtension(state, Type) {
  return (pi) => {
    const empty = Type.Object({});
    const result = (text) => ({ content: [{ type: "text", text }], details: {} });
    for (const kind of ["tool_call", "tool_result", "tool_execution_start", "tool_execution_end"]) {
      pi.on(kind, (event) => {
        state.hooks.push({ type: event.type, tool: event.toolName, id: event.toolCallId, parent: event.parentToolCallId ?? null, error: event.isError ?? null });
        if (kind === "tool_call" && event.toolName === "probe_leaf" && state.blockLeaf) return { block: true, reason: "Synthetic nested denial" };
      });
    }
    pi.on("session_start", (_event, ctx) => state.starts.push({ hasUI: ctx.hasUI, mode: ctx.mode }));
    const tool = (name, execute) => pi.registerTool({ name, label: name, description: "Synthetic SDK probe only", parameters: empty, execute });
    tool("probe_leaf", async (_id, _args, signal) => {
      state.leafCalls += 1;
      state.leafHasSignal = signal !== undefined;
      return result("synthetic leaf");
    });
    tool("probe_parent", async (_id, _args, _signal, _update, ctx) => {
      const nested = await ctx.executeTool("probe_leaf", {});
      state.nestedError = nested.isError;
      if (nested.isError) throw new Error("PROBE_NESTED_FAILED");
      return result("synthetic parent");
    });
    tool("probe_ui_required", async (_id, _args, _signal, _update, ctx) => {
      state.uiHasUI = ctx.hasUI;
      // 自有受许可操作在无 UI 时 fail closed；这不是宿主全局 UI 权限证明。
      if (!ctx.hasUI) { state.uiDenied = true; throw new Error("PROBE_UI_REQUIRED"); }
      throw new Error("PROBE_UNEXPECTED_UI");
    });
    tool("probe_cancel_leaf", async (_id, _args, signal) => {
      if (!signal || signal.aborted) throw new Error("PROBE_INVALID_CANCEL_SIGNAL");
      state.cancelReady();
      await new Promise((resolve) => signal.addEventListener("abort", () => {
        state.cancelObserved = signal.aborted;
        state.parentAborted = state.parentSignal?.aborted === true;
        resolve();
      }, { once: true }));
      return result("synthetic cancelled leaf");
    });
    tool("probe_cancel_parent", async (_id, _args, signal, _update, ctx) => {
      state.parentSignal = signal;
      // 不传人工 AbortController；观察 SDK 默认继承调用者的 signal。
      await ctx.executeTool("probe_cancel_leaf", {});
      return result("synthetic cancelled parent");
    });
  };
}
