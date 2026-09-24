import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { configLoader } from "../config";

export function registerProcessSettings(pi: ExtensionAPI): void {
  pi.registerCommand("ps:settings", { description: "查看 agentcfg 管理的进程设置", async handler(_args, ctx) {
    ctx.ui.notify(JSON.stringify(configLoader.getConfig(), null, 2) + "\n通过 agentcfg 的机器覆盖修改设置；命令、读写根和交互输入在 external_tools 中声明。", "info");
  } });
}
