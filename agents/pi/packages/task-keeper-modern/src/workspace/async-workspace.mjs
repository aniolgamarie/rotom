import { runAuxiliary } from "../../runtime/auxiliary-executor.mjs";
import { ContractError } from "../contracts/primitives.mjs";
export class WorkspaceOperationError extends ContractError {
    result;
    constructor(result){
        super("WORKSPACE_OPERATION_FAILED", result.reason);
        this.result = result;
    }
}
export async function workspaceOperation(input, signal, onDispatch) {
    const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
    if (!runtime) throw new ContractError("AGENTCFG_SUPERVISOR_REQUIRED");
    try {
        const result = await runAuxiliary({
            runtime,
            program: "workspace",
            payload: input,
            cwd: input.cwd,
            taskId: input.jobId,
            signal,
            onDispatch,
            timeoutMs: input.timeoutMs ?? 120000
        });
        if (!result.terminationConfirmed || result.exitCode !== 0 || !result.workspace_result) {
            throw new WorkspaceOperationError({
                terminationConfirmed: result.terminationConfirmed,
                reason: "workspace_result_unverified",
                stderr: ""
            });
        }
        return result.workspace_result;
    } catch (error) {
        if (error instanceof WorkspaceOperationError) throw error;
        throw new WorkspaceOperationError({
            terminationConfirmed: false,
            reason: "workspace_execution_unknown",
            stderr: ""
        });
    }
}
