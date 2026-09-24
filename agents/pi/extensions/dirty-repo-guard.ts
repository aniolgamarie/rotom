/** 切换前检查显式项目；检查失败取消，脏仓库仅允许用户明确选择继续。 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { inspectGitStatus } from "@agentcfg/pi-runtime/git-status";
import { assertSessionBoundary } from "@agentcfg/pi-runtime/capability-policy";

async function checkDirtyRepo(ctx: ExtensionContext, action: string): Promise<{ cancel: boolean } | undefined> {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  try {
    const result = await inspectGitStatus(runtime, ctx);
    if (result.status !== "dirty") return;
    if (!ctx.hasUI) return { cancel: true };
    const choice = await ctx.ui.select(`有 ${result.changedFiles} 个未提交的文件，仍要${action}吗？`, ["继续", "保留当前会话"]);
    if (choice !== "继续") return { cancel: true };
    await assertSessionBoundary(runtime);
  } catch {
    if (ctx.hasUI) ctx.ui.notify("Git 状态检查未完成，已取消切换。请检查 Git 绑定、权限、活动工作区或检查超时。", "error");
    return { cancel: true };
  }
}

export default function (pi: ExtensionAPI) {
  pi.on("session_before_switch", async (event, ctx) => checkDirtyRepo(ctx, event.reason === "new" ? "新建会话" : "切换会话"));
  pi.on("session_before_fork", async (_event, ctx) => checkDirtyRepo(ctx, "分叉会话"));
}
