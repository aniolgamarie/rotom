import { existsSync, lstatSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { ContractError } from "../contracts/primitives.mjs";
export { ManagedObservation as ChildReporter } from "../../runtime/managed-observation.mjs";
export { createGuardedTools } from "../../runtime/guarded-tools.mjs";
export function guardedPath(root, path, write) {
    if (typeof path !== "string" || !path || path.includes("\0") || path.startsWith("~") || path.startsWith("@")) throw new ContractError("INVALID_TOOL_PATH");
    const base = realpathSync(root), target = resolve(base, path), tail = relative(base, target);
    if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep) || tail.split(sep).includes(".git") || write && !tail) {
        throw new ContractError("TOOL_PATH_OUTSIDE_SCOPE");
    }
    let current = base;
    for (const part of tail.split(sep).filter(Boolean)){
        current = resolve(current, part);
        if (existsSync(current) && lstatSync(current).isSymbolicLink()) throw new ContractError("TOOL_SYMLINK_ESCAPE");
    }
    if (!write && !existsSync(target)) throw new ContractError("INVALID_TOOL_PATH");
    if (realpathSync(dirname(target)) !== dirname(target)) throw new ContractError("TOOL_SYMLINK_ESCAPE");
    return target;
}
