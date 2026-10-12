// 自有正文仅写合成哨兵；hasUI绝不自行授予正文执行许可。
export function permissionExtension(state, save, fs, Type, timeout) {
  return (pi) => {
    pi.on("session_start", (_event, ctx) => {
      state.has_ui = ctx.hasUI; state.mode = ctx.mode; save();
    });
    pi.on("session_shutdown", () => {
      state.shutdown_seen = true; state.phase = "shutdown"; save();
    });
    pi.registerTool({ name: "probe_confirmed_body", label: "Synthetic permission probe",
      description: "Writes only a synthetic sentinel after explicit confirmation",
      parameters: Type.Object({}),
      async execute(_id, _args, signal, _update, ctx) {
        if (!signal) throw new Error("PROBE_MISSING_SIGNAL");
        const confirmed = await ctx.ui.confirm("Synthetic permission", "Allow synthetic sentinel only?", { timeout, signal });
        state.confirm_result = confirmed === true;
        state.signal_aborted = signal.aborted;
        save();
        // 生产准入形式必须同时核实正向确认与当前取消状态。
        if (!(confirmed === true && !signal.aborted)) throw new Error("PROBE_PERMISSION_DENIED");
        const fd = fs.openSync("/work/body-sentinel", "wx", 0o600);
        try { fs.writeFileSync(fd, "synthetic body\n"); fs.fsyncSync(fd); }
        finally { fs.closeSync(fd); }
        state.body_count += 1; save();
        return { content: [{ type: "text", text: "synthetic sentinel written" }], details: {} };
      },
    });
  };
}
