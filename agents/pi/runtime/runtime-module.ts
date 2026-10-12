// 根 runtime/*.mjs 与 profile/node_modules 分开；解析锚点必须来自当前冻结切片。
import { realpathSync } from "node:fs";
import { isAbsolute, join, relative, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { reject } from "./managed-types.ts";

export async function runtimeModule(name, runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")]) {
  if (!["http-proxy-agent", "https-proxy-agent", "undici", "@earendil-works/pi-mcp"].includes(name)) reject("RUNTIME_MODULE_UNDECLARED", 5);
  if (!runtime?.runtimeRoot || !runtime.installed?.entrypoint) reject("RUNTIME_MODULE_UNBOUND", 5);
  // 固定Node24的公开parentURL解析须显式启用；不能退回require条件或checkout查找。
  const legacy = runtime.installed.schema_version === 1;
  if (!legacy && !process.execArgv.includes("--experimental-import-meta-resolve")) reject("RUNTIME_MODULE_RESOLVER_UNAVAILABLE", 5);
  const root = realpathSync(runtime.runtimeRoot);
  const inside = value => {
    const path = realpathSync(value), tail = relative(root, path);
    if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep)) reject("RUNTIME_MODULE_BOUNDARY", 5);
    return path;
  };
  const entry = inside(join(root, runtime.installed.entrypoint));
  // 历史schema1仍消费原require条件，既有Bun/Node运行包不借此次改动重选入口。
  const target = inside(legacy ? createRequire(entry).resolve(name) : fileURLToPath(import.meta.resolve(name, pathToFileURL(entry).href)));
  return import(pathToFileURL(target).href);
}
import { createRequire } from "node:module";
