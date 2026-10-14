// 只通过锁定运行包的公开导出启动；环境快照仅含继承的进程环境。
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

if (process.argv[2] === "--deny-package-operation") {
  console.error("Managed DSH dependencies can only be changed through agentcfg lock/sync; native package updates are disabled.");
  process.exit(5);
}

const [runtimeRoot, patchFile, ...args] = process.argv.slice(2);
if (!runtimeRoot || !patchFile || !path.isAbsolute(runtimeRoot) || !path.isAbsolute(patchFile)) {
  throw new Error("managed runtime and patch paths must be absolute");
}
// 新版 TUI 从公开 --profile 识别设置来源；此标志只给宿主，不作为用户提示词。
if (args[0] === "--profile") {
  if (args[1] !== "agentcfg") throw new Error("managed profile identity must be agentcfg");
  args.splice(0, 2);
}
const require = createRequire(path.join(runtimeRoot, "package.json"));
const { runProfile } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh/profile-boot")));
const { createLaunchEnvironmentSnapshot } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-launch-environment")));
process.env.DSH_TUI_WORKSPACE_TARGET = process.cwd();
const environment = createLaunchEnvironmentSnapshot([{ source: "process", values: process.env }]);
await runProfile({ environment, profile: "agentcfg", patchFiles: [patchFile], args,
  packageManager: { command: process.execPath, args: [process.argv[1], "--deny-package-operation"], env: {} },
});
