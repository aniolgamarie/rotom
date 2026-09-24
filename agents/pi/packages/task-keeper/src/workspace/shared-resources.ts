import { realpathSync, statSync } from "node:fs";
import { isAbsolute } from "node:path";
import type { VerificationBinding } from "../config.ts";
import { ContractError, digest } from "../contracts/primitives.ts";
import type { ResourceDemand } from "../orchestration/scheduler.ts";

export type SharedWriteResources = Record<string, ResourceDemand[]>;

/** Resolve only explicitly declared, existing shared roots; never create or infer paths. */
export function sharedWriteResources(bindings: Record<string, VerificationBinding>): SharedWriteResources {
  const result: SharedWriteResources = {};
  for (const [checkId, binding] of Object.entries(bindings).sort(([a], [b]) => a.localeCompare(b))) {
    const ids = new Set<string>();
    for (const path of binding.sharedMutableDirectories ?? []) {
      if (!isAbsolute(path)) throw new ContractError("SHARED_DIRECTORY_MUST_BE_ABSOLUTE", checkId);
      let canonical: string;
      try { canonical = realpathSync(path); if (!statSync(canonical).isDirectory()) throw new Error("not a directory"); }
      catch { throw new ContractError("SHARED_DIRECTORY_UNAVAILABLE", checkId); }
      ids.add(`shared-directory-${digest(canonical)}`);
    }
    if (ids.size) result[checkId] = [...ids].sort().map(id => ({ id, capacity: 1, units: 1 }));
  }
  return result;
}

export function allSharedWriteResources(resources: SharedWriteResources): ResourceDemand[] {
  return [...new Map(Object.values(resources).flat().map(resource => [resource.id, resource])).values()].sort((a, b) => a.id.localeCompare(b.id));
}
