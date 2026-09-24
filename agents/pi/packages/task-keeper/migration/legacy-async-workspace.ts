import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { newId, ContractError } from "../contracts/primitives.ts";
import { runVerification, type VerificationResult } from "../verification/runner.ts";

export class WorkspaceOperationError extends ContractError {
  readonly result: VerificationResult;
  constructor(result: VerificationResult) {
    super("WORKSPACE_OPERATION_FAILED", `${result.reason}; ${result.stderr}`); this.result = result;
  }
}

export async function workspaceOperation<T>(input: { operation: "create" | "snapshot"; cwd: string; stateRoot: string; jobId: string;
  baselineTree?: string; extraInputs?: string[]; timeoutMs?: number }, signal?: AbortSignal, onDispatch?: () => void): Promise<T> {
  const directory = join(input.stateRoot, "operations"); mkdirSync(directory, { recursive: true, mode: 0o700 });
  const id = newId("workspace-op"), inputFile = join(directory, `${id}.input.json`), outputFile = join(directory, `${id}.output.json`);
  writeFileSync(inputFile, JSON.stringify(input), { flag: "wx", mode: 0o600 });
  const result = await runVerification("workspace-operation", { "workspace-operation": {
    executable: process.execPath, args: ["--experimental-strip-types", fileURLToPath(new URL("./worker.ts", import.meta.url)), inputFile, outputFile],
    environment: {}, timeoutMs: input.timeoutMs ?? 120000, kind: "build", parser: "exit-code", minimumTests: 1,
  } }, { jobId: input.jobId, snapshot: "workspace-operation", cwd: input.cwd }, { signal, onDispatch });
  writeFileSync(join(directory, `${id}.execution.json`), JSON.stringify(result), { flag: "wx", mode: 0o600 });
  if (result.status !== "passed") throw new WorkspaceOperationError(result);
  try { return JSON.parse(readFileSync(outputFile, "utf8")) as T; }
  catch { throw new WorkspaceOperationError({ ...result, reason: "workspace_result_invalid" }); }
}
