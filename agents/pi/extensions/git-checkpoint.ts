/** 代码恢复点持久化到当前实例；预览、明确选择、写租约和逐文件权限检查由agentcfg负责。 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { checkpointClient } from "@agentcfg/pi-runtime/checkpoints";

export default function (pi: ExtensionAPI) {
  const client = (ctx: ExtensionContext) => checkpointClient((globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")], ctx);
  const restore = async (ctx: ExtensionContext, id: string): Promise<boolean> => {
    if (!ctx.hasUI) return false;
    const preview = await client(ctx).preview(id);
    const choice = await ctx.ui.select(`恢复此范围内的代码？写入 ${preview.write_count} 个文件，删除 ${preview.delete_count} 个文件。恢复前会保存备份。`, ["恢复", "保留当前代码"]);
    if (choice !== "恢复") return false;
    const result = await client(ctx).restore(preview);
    if (result.status !== "completed") {
      ctx.ui.notify(`恢复未完成；恢复前备份：${result.backup_id}`, "error");
      throw new Error("CHECKPOINT_RESTORE_INTERRUPTED");
    }
    ctx.ui.notify(`代码已恢复；恢复前备份：${result.backup_id}`, "info");
    return true;
  };
  pi.on("turn_start", async (_event, ctx) => {
    try { await client(ctx).capture(ctx.sessionManager.getLeafEntry()?.id); }
    catch { ctx.ui.notify("代码恢复点未创建：请检查快照范围、权限或活动工作区冲突。", "warning"); }
  });
  pi.on("session_before_fork", async (event, ctx) => {
    try {
      const { checkpoints } = await client(ctx).list(event.entryId);
      const checkpoint = checkpoints.find((item: { entry_id: string }) => item.entry_id === event.entryId);
      if (checkpoint) await restore(ctx, checkpoint.checkpoint_id);
    } catch {
      ctx.ui.notify("代码恢复未完成，已取消本次分叉。", "error");
      return { cancel: true };
    }
  });
  pi.registerCommand("checkpoint", {
    description: "保存当前授权范围内的代码恢复点",
    handler: async (_args, ctx) => {
      try {
        const result = await client(ctx).capture(ctx.sessionManager.getLeafEntry()?.id);
        ctx.ui.notify(`恢复点 ${result.checkpoint_id}，共 ${result.files} 个文件`, "info");
      } catch { ctx.ui.notify("恢复点未创建：请检查快照范围、权限或活动工作区冲突。", "error"); }
    },
  });
  pi.registerCommand("checkpoint-restore", {
    description: "预览并恢复当前会话的代码恢复点或恢复前备份",
    handler: async (id, ctx) => {
      try {
        if (!ctx.hasUI) throw new Error("CHECKPOINT_INTERACTIVE_REQUIRED");
        const { checkpoints } = await client(ctx).list();
        let selected = id.trim();
        if (!selected) {
          const labels = checkpoints.map((item: { checkpoint_id: string; reason: string; created_at: string }) =>
            `${item.created_at} · ${item.reason === "before-restore" ? "恢复前备份" : "恢复点"} · ${item.checkpoint_id}`);
          if (!labels.length) { ctx.ui.notify("当前会话与范围没有可恢复的快照。", "info"); return; }
          const choice = await ctx.ui.select("选择恢复点", labels);
          if (!choice) return;
          selected = checkpoints[labels.indexOf(choice)].checkpoint_id;
        }
        await restore(ctx, selected);
      } catch { ctx.ui.notify("恢复未完成：请检查恢复点、权限或工作区是否已变化。", "error"); }
    },
  });
}
