// 只执行固定的工作区动作；本入口不加载 Pi 宿主或扩展。
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { realpathSync, readFileSync } from "node:fs";
import { strictJson } from "./strict-json.ts";
import { privateFile, writePrivate } from "./private-files.ts";
import { SupervisorClient, inheritedControlDirectory } from "./supervisor-client.ts";
import { canonical, closed, reject } from "./managed-types.ts";

export async function workspaceMain(argv) {
  if (argv.length !== 4 || argv[0] !== "--input" || argv[2] !== "--runtime-root" || !isAbsolute(argv[1]) || !isAbsolute(argv[3])) reject();
  const runtimeRoot = realpathSync(argv[3]), input = strictJson(privateFile(argv[1]));
  closed(input, ["schema_version", "input", "output", "lease_id", "grant_generation", "protected_roots"], ["input_scope"]);
  const profile = JSON.parse(privateFile(join(runtimeRoot, "runtime/profile.json")));
  if (input.schema_version !== 1 || process.version !== profile.toolchains.node) reject("WORKSPACE_RUNTIME_MISMATCH", 5);
  const client = new SupervisorClient({ ...inheritedControlDirectory(), python: process.env.AGENTCFG_PYTHON, client: process.env.AGENTCFG_SUPERVISOR_CLIENT,
    endpoint: process.env.AGENTCFG_SUPERVISOR_ENDPOINT, capability: process.env.AGENTCFG_SUPERVISOR_CAPABILITY });
  delete process.env.AGENTCFG_SUPERVISOR_CAPABILITY;
  const proof = await client.call("authorize", { lease_id: input.lease_id, grant_generation: input.grant_generation });
  if (!proof.valid) reject("GRANT_STALE", 4);
  const owner = await client.call("handshake", {});
  globalThis[Symbol.for("agentcfg.pi.runtime.v1")] = { owner, instanceRoot: dirname(dirname(input.input.stateRoot)) };
  const require = createRequire(join(runtimeRoot, profile.entrypoint));
  const modern = profile.schema_version === 2 && profile.profile_id === "pi-full";
  const within = path => {
    const actual = realpathSync(path), tail = relative(runtimeRoot, actual);
    if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep)) reject("WORKSPACE_MODULE_BOUNDARY", 5);
    return actual;
  };
  let api;
  if (modern) {
    // 机械生成包只公开JS；不恢复旧starter或借Jiti载入node_modules TS。
    const corePath = within(require.resolve("@agentcfg/pi-task-keeper/core"));
    api = await import(pathToFileURL(within(join(dirname(corePath), "src/workspace/worktree.mjs"))).href);
  } else {
    const packageRoot = dirname(require.resolve("starter-pi-task-keeper/package.json"));
    const { createJiti } = await import(pathToFileURL(within(require.resolve("jiti"))).href);
    const loader = createJiti(import.meta.url, { moduleCache: false });
    api = await loader.import(within(join(packageRoot, "src/workspace/worktree.ts")));
  }
  const value = input.input;
  if(modern&&!input.input_scope)reject("INPUT_SNAPSHOT_SCOPE");
  if(input.input_scope)api.validateInputScope(input.input_scope);
  const hidden=input.input_scope?.protected_inputs.map(row=>join(value.cwd,row.relative_path))??[];
  const artifacts=input.input_scope?.policy.artifact_exclusions.map(row=>join(value.cwd,row.relative_path))??[];
  const privatePaths=[...input.protected_roots,...hidden,...artifacts];
  if(input.input_scope)api.semanticScopeAdmission(value.cwd,input.input_scope);
  const sourceSecrets=input.input_scope&&value.operation==="create"?api.secretStates(value.cwd,input.input_scope,"source"):[];
  let result;
  if (value.operation === "create") {
    const workspace = api.createWorkspace(value.cwd, value.stateRoot, value.jobId, value.extraInputs ?? [], privatePaths,!!input.input_scope);
    result = { ...workspace, baseline: api.captureTree(workspace.path, value.stateRoot, value.jobId, value.extraInputs ?? [], workspace.protectedRoots,!!input.input_scope) };
  } else if (value.operation === "snapshot") {
    const snapshot = api.sourceSnapshot(value.cwd, value.extraInputs ?? [], privatePaths,!!input.input_scope);
    const captured = api.captureTree(value.cwd, value.stateRoot, value.jobId, value.extraInputs ?? [], privatePaths,!!input.input_scope);
    result = { snapshot, captured, patch: value.baselineTree ? api.treeDiff(value.cwd, captured.gitDir, value.baselineTree, captured.tree) : "" };
  } else reject();
  if(input.input_scope)result.semantic_source=api.semanticSource(result.cwd??value.cwd,input.input_scope,value.extraInputs??[],sourceSecrets);
  const recordPath = join(value.stateRoot, "workspace-protection", value.jobId + ".json");
  const protection = JSON.parse(readFileSync(recordPath, "utf8"));
  protection.files = result.snapshot.files.map(file => file.path);
  writePrivate(recordPath, canonical(protection) + "\n");
  writePrivate(input.output, canonical(result) + "\n");
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  workspaceMain(process.argv.slice(2)).catch(() => { process.stderr.write("WORKSPACE_OPERATION_FAILED\n"); process.exitCode = 5; });
}
