// 一次 worker 只执行一项调用。OS 沙箱、租约与输出提交由父监督器负责。
import { isAbsolute, relative, resolve, sep } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { readseekWorker } from "./readseek-context.ts";

const slot = Symbol.for("agentcfg.pi.readseek.worker.v1");
const names = new Set(["edit", "grep", "search", "refs", "rename", "def", "digest", "view", "write"].map(name => "readSeek_" + name));
function fail() { throw new Error("READSEEK_WORKER_PROTOCOL"); }
function closed(value, keys) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).length !== keys.length || keys.some(key => !Object.hasOwn(value, key))) fail();
}
function inside(root, value) {
  if (typeof value !== "string" || !isAbsolute(value) || value.includes("\0") || value !== resolve(value)) return false;
  const tail = relative(root, value);
  return tail !== ".." && !tail.startsWith(".." + sep) && !isAbsolute(tail);
}

export async function executeReadseek(request, contracts, loadExtension, { signal } = {}) {
  closed(request, ["schema_version", "operation_id", "tool", "params", "snapshot_digest", "snapshot_root", "cache_root", "native_binary", "settings", "anchors", "working_directory"]);
  if (request.schema_version !== 1 || !names.has(request.tool) || typeof request.operation_id !== "string"
      || !request.operation_id || request.operation_id.length > 200 || !/^[a-f0-9]{64}$/.test(request.snapshot_digest)
      || ![request.snapshot_root, request.cache_root, request.native_binary].every(value => typeof value === "string" && inside("/", value))
      || inside(request.snapshot_root, request.cache_root) || inside(request.cache_root, request.snapshot_root)
      || !inside(request.snapshot_root, request.working_directory)
      || !Array.isArray(request.anchors) || request.anchors.length > 10000
      || request.anchors.some(path => !inside(request.snapshot_root, path))
      || !request.params || typeof request.params !== "object" || Array.isArray(request.params)
      || Object.hasOwn(request.params, "path") && !inside(request.snapshot_root, request.params.path)) fail();
  closed(contracts, ["schema_version", "tools"]);
  if (contracts.schema_version !== 1 || !Array.isArray(contracts.tools) || contracts.tools.length !== names.size
      || new Set(contracts.tools.map(row => row.name)).size !== names.size || contracts.tools.some(row => !names.has(row.name))) fail();
  if (readseekWorker() || globalThis[Symbol.for("agentcfg.pi.runtime.v1")]) fail();
  signal?.throwIfAborted();
  const worker = { settings: structuredClone(request.settings), native_binary: request.native_binary,
    cache_root: request.cache_root, anchors: [...request.anchors], anchor_events: [] };
  globalThis[slot] = worker;
  try {
    const tools = new Map();
    const register = await loadExtension();
    await register({
      registerTool(tool) {
        if (!names.has(tool.name) || tools.has(tool.name) || typeof tool.execute !== "function") fail();
        const declared = contracts.tools.find(row => row.name === tool.name);
        // TypeBox 的 symbol 标记不是 JSON 参数契约，比较序列化后的 schema。
        if (!isDeepStrictEqual(JSON.parse(JSON.stringify(tool.parameters)), declared.parameters)) fail();
        tools.set(tool.name, tool);
      },
      on(name, handler) {
        if (!["session_start", "before_agent_start"].includes(name) || typeof handler !== "function") fail();
        // 每次调用新建假 API；不运行宿主 hooks，也不清除父侧已核验 anchors。
      },
    });
    if (tools.size !== names.size) fail();
    signal?.throwIfAborted();
    const result = await tools.get(request.tool).execute(request.operation_id, structuredClone(request.params), signal,
      undefined, { cwd: request.working_directory, hasUI: false });
    signal?.throwIfAborted();
    if (globalThis[slot] !== worker || !result || !Array.isArray(result.content)) fail();
    return { schema_version: 1, operation_id: request.operation_id, tool: request.tool,
      snapshot_digest: request.snapshot_digest, result, anchor_events: worker.anchor_events };
  } finally { delete globalThis[slot]; }
}
