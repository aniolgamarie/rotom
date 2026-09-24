export interface AuxiliaryResult {
  stdout: string; stderr: string; truncated: boolean; exitCode: number | null; timedOut: boolean; cancelled: boolean;
  terminationConfirmed: boolean; started: boolean; lease_id: string; process_identity: any; workspace_result: unknown;
}
export function runAuxiliary(options: { runtime: any; program: "workspace" | "check"; payload: unknown; cwd: string; taskId: string;
  pi?: unknown; context?: unknown; signal?: AbortSignal; onDispatch?: () => void; timeoutMs?: number }): Promise<AuxiliaryResult>;
