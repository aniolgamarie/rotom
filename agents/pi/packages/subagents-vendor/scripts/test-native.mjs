// 宿主测试独立授权；缺少显式标志时在 import/进程创建之前拒绝。
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
if (process.argv[2] !== "--allow-host") { process.stderr.write("Native tests require explicit --allow-host authorization.\n"); process.exit(2); }
const entry = fileURLToPath(new URL("../node_modules/vitest/vitest.mjs", import.meta.url));
const result = spawnSync(process.execPath, [entry, "run", ...process.argv.slice(3)], { stdio: "inherit" });
process.exit(result.status ?? 1);
