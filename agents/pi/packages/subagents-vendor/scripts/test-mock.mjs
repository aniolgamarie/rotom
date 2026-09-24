// 只运行明确列出的隔离 mock；不执行上游 e2e。
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../..");
const names = ["agent-manager", "manager-config", "manager-executor", "managed-bridge", "managed-store-rpc"];
const result = spawnSync(process.execPath, [resolve(root, "scripts/test-pi-mock.mjs"), ...names.map(name => `agents/pi/runtime/tests/${name}.test.ts`)], { cwd: root, stdio: "inherit" });
process.exit(result.status ?? 1);
