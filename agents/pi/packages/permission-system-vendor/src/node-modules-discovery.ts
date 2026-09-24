// 只定位当前冻结运行包的依赖目录；没有全局 npm 或开发 checkout 兜底。
import { dirname, basename, join, relative, isAbsolute, sep } from "node:path";
import { realpathSync } from "node:fs";

export function discoverGlobalNodeModulesRoot(_fromUrl = import.meta.url): string | null {
  const runtime = (globalThis as Record<symbol, any>)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime) throw new Error("AGENTCFG_RUNTIME_REQUIRED");
  const root = realpathSync(runtime.runtimeRoot);
  let path = dirname(realpathSync(join(root, runtime.installed.entrypoint)));
  while (path !== dirname(path)) {
    const tail = relative(root, path);
    if (tail === ".." || tail.startsWith(".." + sep) || isAbsolute(tail)) throw new Error("AGENTCFG_MODULE_BOUNDARY");
    if (basename(path) === "node_modules") return path;
    path = dirname(path);
  }
  throw new Error("AGENTCFG_MODULE_BOUNDARY");
}
