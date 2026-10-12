// 不注册另一份sender；现代workflow只由host-bound自有initializer装配。
export default function taskKeeperSource(pi) {
  pi.registerCommand("task-keeper-capability", { description: "Show modern workflow candidate boundary", async handler(_args, ctx) {
    ctx.ui.notify("Task Keeper现代候选：只读phase沿统一core；implement缺受管maintenance授权时不可用。", "info");
  } });
}
