import { realpathSync, statSync } from "node:fs";
import { isAbsolute } from "node:path";
import { ContractError, digest } from "../contracts/primitives.mjs";
export function sharedWriteResources(bindings) {
    const result = {};
    for (const [checkId, binding] of Object.entries(bindings).sort(([a], [b])=>a.localeCompare(b))){
        const ids = new Set();
        for (const path of binding.sharedMutableDirectories ?? []){
            if (!isAbsolute(path)) throw new ContractError("SHARED_DIRECTORY_MUST_BE_ABSOLUTE", checkId);
            let canonical;
            try {
                canonical = realpathSync(path);
                if (!statSync(canonical).isDirectory()) throw new Error("not a directory");
            } catch  {
                throw new ContractError("SHARED_DIRECTORY_UNAVAILABLE", checkId);
            }
            ids.add(`shared-directory-${digest(canonical)}`);
        }
        if (ids.size) result[checkId] = [
            ...ids
        ].sort().map((id)=>({
                id,
                capacity: 1,
                units: 1
            }));
    }
    return result;
}
export function allSharedWriteResources(resources) {
    return [
        ...new Map(Object.values(resources).flat().map((resource)=>[
                resource.id,
                resource
            ])).values()
    ].sort((a, b)=>a.id.localeCompare(b.id));
}
