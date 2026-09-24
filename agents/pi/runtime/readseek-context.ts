// 父会话只登记工具界面；原生执行与直接文件 IO 只能发生在隔离 worker。
import { pluginSettings } from "./plugin-settings.ts";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";

const runtimeSlot = Symbol.for("agentcfg.pi.runtime.v1"), workerSlot = Symbol.for("agentcfg.pi.readseek.worker.v1");
export function readseekWorker() {
  const worker = globalThis[workerSlot];
  if (worker && globalThis[runtimeSlot]) reject("READSEEK_WORKER_CONTEXT_COLLISION", 4);
  return worker ?? null;
}
export function readseekSettings() {
  const worker = readseekWorker();
  const settings = worker ? worker.settings : pluginSettings("pi-readseek", "readseek").settings ?? {};
  if (!settings || typeof settings !== "object" || Array.isArray(settings) || Object.hasOwn(settings, "overrideTools")) reject("READSEEK_SETTINGS_INVALID", 2);
  return structuredClone(settings);
}
export function readseekAvailability() {
  const worker = readseekWorker();
  if (worker) return { available: typeof worker.native_binary === "string" && worker.native_binary.startsWith("/") };
  const runtime = globalThis[runtimeSlot];
  return runtime?.readseek?.availability?.() ?? { available: false, reason: "READSEEK_EXECUTOR_UNAVAILABLE" };
}
export function wrapReadseekTool(tool) {
  const selected = { ...tool, parameters: { ...tool.parameters, additionalProperties: false } };
  if (readseekWorker()) return selected;
  const owner = globalThis[runtimeSlot];
  return { ...selected, async execute(id, params, signal, onUpdate, context) {
    const runtime = globalThis[runtimeSlot];
    if (runtime !== owner) reject("READSEEK_RUNTIME_STALE", 4);
    requireOrdinaryHelper(runtime, "pi-readseek");
    if (!runtime.readseek?.execute) reject("READSEEK_EXECUTOR_UNAVAILABLE", 5);
    const result = await runtime.readseek.execute(tool.name, id, params, signal, onUpdate, context);
    if (globalThis[runtimeSlot] !== owner) reject("READSEEK_RUNTIME_STALE", 4);
    return result;
  } };
}
export function recordReadseekAnchor(action, path) {
  const worker = readseekWorker();
  if (!worker) return;
  if (!["mark", "forget", "clear"].includes(action)) reject("READSEEK_ANCHOR_EVENT", 2);
  worker.anchor_events ??= [];
  worker.anchor_events.push({ action, path: path ?? null });
}
