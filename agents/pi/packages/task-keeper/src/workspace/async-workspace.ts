import { runAuxiliary } from "@agentcfg/pi-runtime/auxiliary-executor";
import { ContractError } from "../contracts/primitives.ts";

export class WorkspaceOperationError extends ContractError {
  readonly result: { terminationConfirmed: boolean; reason: string; stderr: string };
  constructor(result: { terminationConfirmed: boolean; reason: string; stderr: string }) {
    super("WORKSPACE_OPERATION_FAILED", result.reason); this.result = result;
  }
}
export async function workspaceOperation<T>(input: { operation: "create" | "snapshot"; cwd: string; stateRoot: string; jobId: string;
  baselineTree?: string; extraInputs?: string[]; timeoutMs?: number }, signal?: AbortSignal, onDispatch?: () => void): Promise<T> {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime) throw new ContractError("AGENTCFG_SUPERVISOR_REQUIRED");
  try {
    const result = await runAuxiliary({ runtime, program: "workspace", payload: input, cwd: input.cwd, taskId: input.jobId,
      signal, onDispatch, timeoutMs: input.timeoutMs ?? 120000 });
    if (!result.terminationConfirmed || result.exitCode !== 0 || !result.workspace_result) {
      throw new WorkspaceOperationError({ terminationConfirmed: result.terminationConfirmed, reason: "workspace_result_unverified", stderr: "" });
    }
    return result.workspace_result as T;
  } catch (error) {
    if (error instanceof WorkspaceOperationError) throw error;
    throw new WorkspaceOperationError({ terminationConfirmed: false, reason: "workspace_execution_unknown", stderr: "" });
  }
}
