import { cpSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { isolatedDirectory } from "../helpers.ts";
import type { TestContext } from "node:test";

const pkg = fileURLToPath(new URL("../..", import.meta.url));

/**
 * 负向控制：在隔离源码副本中移除 resource 检查，验证 EXE-010 的 RESOURCE_DENIED 断言失败。
 * 正常测试要求旧进程仍活着时接替者被拒绝；移除 resource 检查后，接替者应被允许。
 */
export function exe010NegativeControl(t: TestContext): { code: number | null; output: string; manifestPath: string } {
  const root = isolatedDirectory(t);
  // 复制必要的源码和测试
  for (const dir of ["src/store", "src/contracts", "src/adapters", "src/workspace", "tests", "tests/fixtures"]) {
    mkdirSync(join(root, dir), { recursive: true });
  }
  for (const path of [
    "src/store/database.ts",
    "src/store/location.ts",
    "src/store/schema.ts",
    "src/contracts/resources.ts",
    "src/contracts/primitives.ts",
    "src/contracts/ownership.ts",
    "src/contracts/intents.ts",
    "src/contracts/writers.ts",
    "src/contracts/budget.ts",
    "src/contracts/events.ts",
    "src/adapters/process-identity.ts",
    "src/workspace/worktree.ts",
    "tests/recorded-test.ts",
    "tests/helpers.ts",
    "tests/fixtures/writer-owner.ts",
    "tests/fixtures/exe010-workspace-freeze.ts",
    "tests/cases-exe-010-contention.test.ts",
  ]) {
    const srcPath = join(pkg, path);
    const destPath = join(root, path);
    mkdirSync(dirname(destPath), { recursive: true });
    cpSync(srcPath, destPath);
  }
  writeFileSync(join(root, "package.json"), '{"type":"module"}');

  // 负向变异：移除 contracts/resources.ts 中的 RESOURCE_DENIED 检查
  const resourcesPath = join(root, "src/contracts/resources.ts");
  const original = readFileSync(resourcesPath, "utf8");
  const needle = 'if (current.used > capacity || demand.units > capacity - current.used) throw new ContractError("RESOURCE_DENIED", demand.id);';
  if (!original.includes(needle)) throw new Error("EXE010_NEGATIVE_NEEDLE_MISSING");
  const count = original.split(needle).length - 1;
  if (count !== 1) throw new Error(`EXE010_NEGATIVE_NEEDLE_COUNT: ${count}`);
  const mutated = original.replace(needle, "// EXE010_NEGATIVE: resource check removed");
  const beforeSha = createHash("sha256").update(original).digest("hex");
  const afterSha = createHash("sha256").update(mutated).digest("hex");
  writeFileSync(resourcesPath, mutated);

  // 保存变异清单
  const manifestPath = join(root, "exe010-negative-manifest.json");
  writeFileSync(manifestPath, JSON.stringify({ needle, count, beforeSha, afterSha, file: "src/contracts/resources.ts" }, null, 2));

  // 运行测试
  const child = spawnSync(
    process.execPath,
    ["--experimental-strip-types", "--test", "--test-reporter=tap", "--test-name-pattern=^\\[P EXE-010\\]", "tests/cases-exe-010-contention.test.ts"],
    {
      cwd: root,
      env: { ...process.env, NODE_TEST_CONTEXT: undefined, TASK_KEEPER_TEST_RECORD_DIR: join(root, "negative-records") },
      encoding: "utf8",
      timeout: 15000,
    }
  );

  // 保存工件
  if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
    const target = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "exe010-negative");
    mkdirSync(target, { recursive: true, mode: 0o700 });
    writeFileSync(join(target, "output.log"), child.stdout + child.stderr, { mode: 0o600 });
    writeFileSync(join(target, "exit.json"), JSON.stringify({ status: child.status, signal: child.signal }, null, 2));
    cpSync(manifestPath, join(target, "manifest.json"));
    cpSync(join(root, "negative-records"), join(target, "records"), { recursive: true });
  }

  return { code: child.status, output: child.stdout + child.stderr, manifestPath };
}
