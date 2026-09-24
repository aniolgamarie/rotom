// 根 runtime/*.mjs 与 profile/node_modules 分开；解析锚点必须来自当前冻结切片。
import { createRequire } from "node:module";
import { realpathSync } from "node:fs";
import { isAbsolute, join, relative, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { reject } from "./managed-types.ts";

export async function runtimeModule(name) {
  if (!["http-proxy-agent", "https-proxy-agent", "undici"].includes(name)) reject("RUNTIME_MODULE_UNDECLARED", 5);
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime?.runtimeRoot || !runtime.installed?.entrypoint) reject("RUNTIME_MODULE_UNBOUND", 5);
  const root = realpathSync(runtime.runtimeRoot);
  const inside = value => {
    const path = realpathSync(value), tail = relative(root, path);
    if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep)) reject("RUNTIME_MODULE_BOUNDARY", 5);
    return path;
  };
  const entry = inside(join(root, runtime.installed.entrypoint));
  const target = inside(createRequire(entry).resolve(name));
  return import(pathToFileURL(target).href);
}
