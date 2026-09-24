// 受管 worker 使用唯一 runtime 的工具与证据实现；旧扩展式 child reporter 不再加载。
import { existsSync, lstatSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { ContractError } from "../contracts/primitives.ts";
export { ManagedObservation as ChildReporter } from "@agentcfg/pi-runtime/managed-observation";
export { createGuardedTools } from "@agentcfg/pi-runtime/guarded-tools";

/** 审查引用只解析候选内明确路径；实际模型 IO 另由 supervisor 完成。 */
export function guardedPath(root: string, path: unknown, write: boolean): string {
  if (typeof path !== "string" || !path || path.includes("\0") || path.startsWith("~") || path.startsWith("@")) throw new ContractError("INVALID_TOOL_PATH");
  const base = realpathSync(root), target = resolve(base, path), tail = relative(base, target);
  if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep) || tail.split(sep).includes(".git") || write && !tail) {
    throw new ContractError("TOOL_PATH_OUTSIDE_SCOPE");
  }
  let current = base;
  for (const part of tail.split(sep).filter(Boolean)) {
    current = resolve(current, part);
    if (existsSync(current) && lstatSync(current).isSymbolicLink()) throw new ContractError("TOOL_SYMLINK_ESCAPE");
  }
  if (!write && !existsSync(target)) throw new ContractError("INVALID_TOOL_PATH");
  if (realpathSync(dirname(target)) !== dirname(target)) throw new ContractError("TOOL_SYMLINK_ESCAPE");
  return target;
}
