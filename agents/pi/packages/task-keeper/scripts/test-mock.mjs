// 默认入口只列出新的隔离测试，不发现旧 PTY/RPC 验证脚本。
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../..");
const files = ["agentcfg-contract", "agentcfg-adapter", "agentcfg-evidence", "agentcfg-policy", "agentcfg-config", "agentcfg-check-counts", "agentcfg-execution", "agentcfg-workspace", "agentcfg-workflow", "agentcfg-recovery", "agentcfg-usage", "request-ledger", "one-shot-schedule"].map(name => `agents/pi/packages/task-keeper/tests/${name}.test.ts`);
const result = spawnSync(process.execPath, [resolve(root, "scripts/test-pi-mock.mjs"), ...files], { cwd: root, stdio: "inherit" });
process.exit(result.status ?? 1);
