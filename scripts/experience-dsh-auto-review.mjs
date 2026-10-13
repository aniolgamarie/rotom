// 独立实验入口；公开 API、原生 TUI/Perry，不创建审批器或审计替代品。
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
const [runtime, patch, ...args] = process.argv.slice(2);
if (process.version !== "v24.14.0" || !path.isAbsolute(runtime ?? "") || !path.isAbsolute(patch ?? "")) {
  throw new Error("EXPERIENCE_RUNTIME_OR_NODE_INVALID");
}
const require = createRequire(path.join(runtime, "package.json"));
const { runProfile } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh/profile-boot")));
const { createLaunchEnvironmentSnapshot } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-launch-environment")));
process.env.DSH_TUI_WORKSPACE_TARGET = process.cwd();
await runProfile({ environment: createLaunchEnvironmentSnapshot([{ source: "process", values: process.env }]),
  profile: "agentcfg", patchFiles: [patch], args,
  packageManager: { command: "/bin/false", args: [], env: {} } });
