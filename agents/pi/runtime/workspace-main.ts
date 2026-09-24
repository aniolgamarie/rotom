// 只执行固定的工作区动作；本入口不加载 Pi 宿主或扩展。
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { realpathSync, readFileSync } from "node:fs";
import { privateFile, writePrivate } from "./launch.ts";
import { SupervisorClient } from "./supervisor-client.ts";
import { canonical, closed, reject } from "./managed-types.ts";

export async function workspaceMain(argv) {
  if (argv.length !== 4 || argv[0] !== "--input" || argv[2] !== "--runtime-root" || !isAbsolute(argv[1]) || !isAbsolute(argv[3])) reject();
  const runtimeRoot = realpathSync(argv[3]), input = JSON.parse(privateFile(argv[1]));
  closed(input, ["schema_version", "input", "output", "lease_id", "grant_generation", "protected_roots"]);
  const profile = JSON.parse(privateFile(join(runtimeRoot, "runtime/profile.json")));
  if (input.schema_version !== 1 || process.version !== profile.toolchains.node) reject("WORKSPACE_RUNTIME_MISMATCH", 5);
  const client = new SupervisorClient({ python: process.env.AGENTCFG_PYTHON, client: process.env.AGENTCFG_SUPERVISOR_CLIENT,
    endpoint: process.env.AGENTCFG_SUPERVISOR_ENDPOINT, capability: process.env.AGENTCFG_SUPERVISOR_CAPABILITY });
  delete process.env.AGENTCFG_SUPERVISOR_CAPABILITY;
  const proof = await client.call("authorize", { lease_id: input.lease_id, grant_generation: input.grant_generation });
  if (!proof.valid) reject("GRANT_STALE", 4);
  const owner = await client.call("handshake", {});
  globalThis[Symbol.for("agentcfg.pi.runtime.v1")] = { owner, instanceRoot: dirname(dirname(input.input.stateRoot)) };
  const require = createRequire(join(runtimeRoot, profile.entrypoint));
  const packageRoot = dirname(require.resolve("starter-pi-task-keeper/package.json"));
  const within = path => {
    const actual = realpathSync(path), tail = relative(runtimeRoot, actual);
    if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep)) reject("WORKSPACE_MODULE_BOUNDARY", 5);
    return actual;
  };
  const { createJiti } = await import(pathToFileURL(within(require.resolve("jiti"))).href);
  const loader = createJiti(import.meta.url, { moduleCache: false });
  const api = await loader.import(within(join(packageRoot, "src/workspace/worktree.ts")));
  const value = input.input;
  let result;
  if (value.operation === "create") {
    const workspace = api.createWorkspace(value.cwd, value.stateRoot, value.jobId, value.extraInputs ?? [], input.protected_roots);
    result = { ...workspace, baseline: api.captureTree(workspace.path, value.stateRoot, value.jobId, value.extraInputs ?? [], workspace.protectedRoots) };
  } else if (value.operation === "snapshot") {
    const snapshot = api.sourceSnapshot(value.cwd, value.extraInputs ?? [], input.protected_roots);
    const captured = api.captureTree(value.cwd, value.stateRoot, value.jobId, value.extraInputs ?? [], input.protected_roots);
    result = { snapshot, captured, patch: value.baselineTree ? api.treeDiff(value.cwd, captured.gitDir, value.baselineTree, captured.tree) : "" };
  } else reject();
  const recordPath = join(value.stateRoot, "workspace-protection", value.jobId + ".json");
  const protection = JSON.parse(readFileSync(recordPath, "utf8"));
  protection.files = result.snapshot.files.map(file => file.path);
  writePrivate(recordPath, canonical(protection) + "\n");
  writePrivate(input.output, canonical(result) + "\n");
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  workspaceMain(process.argv.slice(2)).catch(() => { process.stderr.write("WORKSPACE_OPERATION_FAILED\n"); process.exitCode = 5; });
}
