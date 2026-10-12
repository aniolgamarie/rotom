import { readFileSync, readdirSync, lstatSync, realpathSync } from "node:fs";
import { resolve, isAbsolute, join, relative } from "node:path";
import { createHash } from "node:crypto";
import { digest, ContractError } from "../contracts/primitives.mjs";
import { verifierSupervisor, checkBindingSnapshot } from "./supervisor.mjs";
import { taskKeeperRuntimeIdentity } from "../adapters/task-keeper-identity.mjs";
export function verificationInputs(bindings, cwd) {
    const records = [
        {
            checkId: "task-keeper-runtime",
            path: "@task-keeper-runtime",
            hash: taskKeeperRuntimeIdentity()
        }
    ];
    let bytes = 0;
    for (const [checkId, binding] of Object.entries(bindings)){
        const supervisor = verifierSupervisor(binding, cwd);
        records.push({
            checkId,
            path: `@supervisor:${supervisor.path}`,
            hash: supervisor.hash
        });
        records.push({
            checkId,
            path: "@verification-runtime",
            hash: supervisor.engineHash
        });
        if (binding.read_roots !== undefined || binding.trusted_inputs !== undefined) records.push({
            checkId,
            path: "@trusted-input-declaration",
            hash: digest({
                read_roots: binding.read_roots ?? null,
                trusted_inputs: binding.trusted_inputs ?? null
            })
        });
        const literalNode = binding.executable === process.execPath && [
            "-e",
            "--eval"
        ].includes(binding.args[0]);
        if (!binding.inputs && !literalNode) throw new ContractError("CHECK_INPUTS_REQUIRED", checkId);
        const visit = (path)=>{
            const info = lstatSync(path);
            if (info.isSymbolicLink()) throw new ContractError("CHECK_INPUT_SYMLINK");
            if (info.isDirectory()) {
                for (const child of readdirSync(path).sort())visit(join(path, child));
                return;
            }
            if (!info.isFile() || records.length >= 10000 || (bytes += info.size) > 64 * 1024 * 1024) throw new ContractError("CHECK_INPUTS_TOO_LARGE");
            records.push({
                checkId,
                path: relative(cwd, path),
                hash: createHash("sha256").update(readFileSync(path)).digest("hex")
            });
        };
        for (const input of binding.inputs ?? []){
            if (isAbsolute(input) || input.split(/[\\/]/).includes("..")) throw new ContractError("CHECK_INPUT_OUTSIDE_WORKSPACE");
            const path = resolve(cwd, input), canonical = realpathSync(path);
            if (canonical !== cwd && !canonical.startsWith(realpathSync(cwd) + "/")) throw new ContractError("CHECK_INPUT_OUTSIDE_WORKSPACE");
            visit(path);
        }
    }
    return {
        digest: digest(records),
        files: records
    };
}
export async function verificationContracts(bindings, cwd, taskId, signal) {
    const before = digest(bindings), contracts = {};
    for (const checkId of Object.keys(bindings).sort())contracts[checkId] = await checkBindingSnapshot(bindings[checkId], cwd, checkId, taskId, signal);
    if (signal?.aborted || digest(bindings) !== before) throw new ContractError("CHECK_BINDING_SNAPSHOT_STALE");
    return {
        contracts,
        digest: digest(contracts)
    };
}
