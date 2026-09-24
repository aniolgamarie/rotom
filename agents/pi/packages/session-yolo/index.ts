// 会话覆盖只控制已获准能力的询问方式；硬 deny、角色上限和执行 grant 保持有效。
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const stateKey = Symbol.for("session-yolo:state"), invalidateKey = Symbol.for("session-yolo:invalidate");
export default function sessionYolo(pi: ExtensionAPI) {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime?.permissionAccess) throw new Error("AGENTCFG_PERMISSION_CAPABILITY_MISSING");
  const access = runtime.permissionAccess;
  const publish = (ctx: any) => {
    const state = access.state(ctx.sessionManager.getSessionId());
    (globalThis as any)[stateKey] = { ...state, effective: access.yolo(ctx.sessionManager.getSessionId(), ctx.cwd), owner: "agentcfg" };
    (globalThis as any)[invalidateKey]?.();
  };
  pi.on("session_start", (_event, ctx) => { access.require(); publish(ctx); });
  pi.on("session_shutdown", (_event, ctx) => {
    access.setMode(ctx.sessionManager.getSessionId(), "off", ctx.cwd);
    (globalThis as any)[stateKey] = { mode: "off", cwd: null, effective: false, owner: "agentcfg" };
    (globalThis as any)[invalidateKey]?.();
  });
  pi.registerCommand("yolo", { description: "Adjust session prompts within agentcfg permissions", async handler(args, ctx) {
    const mode = args.trim();
    try {
      if (mode) {
        if (!["cwd", "global", "off"].includes(mode)) { ctx.ui.notify("用法：/yolo [cwd|global|off]", "error"); return; }
        access.setMode(ctx.sessionManager.getSessionId(), mode, ctx.cwd);
      }
      publish(ctx);
      const current = access.state(ctx.sessionManager.getSessionId());
      ctx.ui.notify(`会话权限提示：${current.mode}。角色、路径拒绝与写租约限制继续生效。`, "info");
    } catch { ctx.ui.notify("权限策略不可用；本次覆盖未生效。", "error"); }
  } });
}
