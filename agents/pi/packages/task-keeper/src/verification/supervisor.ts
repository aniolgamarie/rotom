// Linux/macOS 都由 agentcfg supervisor 证明整个执行范围终止，不在插件内发送 PID 信号。
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { runAuxiliary } from "@agentcfg/pi-runtime/auxiliary-executor";
import { canonical, ContractError, digest } from "../contracts/primitives.ts";
import type { VerificationBinding } from "../config.ts";
import type { ProcessIdentity } from "../adapters/process-identity.ts";

function runtimeContext(): any {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime || runtime.owner?.role !== "manager") throw new ContractError("AGENTCFG_SUPERVISOR_REQUIRED");
  return runtime;
}
export function verifierSupervisor(_binding: VerificationBinding, _cwd: string) {
  const runtime = runtimeContext(), path = join(runtime.runtimeRoot, "supervisor/scripts/pi-project-check");
  return { path, hash: digest(readFileSync(path).toString("base64")), engineHash: runtime.installed.runtime_identity };
}
export async function supervisedCommand(binding: VerificationBinding, cwd: string, _env: NodeJS.ProcessEnv,
  options: { signal?: AbortSignal; maxBytes: number; killGraceMs: number; onDispatch?: () => void; checkId?: string; jobId?: string }) {
  const runtime = runtimeContext(), checkId = options.checkId, jobId = options.jobId;
  const declared = checkId && runtime.manifest.options.checks?.[checkId];
  if (!declared || !jobId || binding.executable !== declared.executable || canonical(binding.args) !== canonical(declared.args)
      || binding.timeoutMs !== declared.timeout_seconds * 1000 || binding.kind !== declared.kind || binding.parser !== declared.parser
      || binding.minimumTests !== declared.minimum_tests || canonical(binding.inputs ?? []) !== canonical(declared.inputs)
      || Object.keys(binding.environment).length) throw new ContractError("CHECK_BINDING_CHANGED");
  const result = await runAuxiliary({ runtime, program: "check", payload: { check_id: checkId, cwd, task_id: jobId },
    cwd, taskId: jobId, signal: options.signal, onDispatch: options.onDispatch, timeoutMs: binding.timeoutMs });
  const identity: ProcessIdentity | null = result.process_identity ? { pid: result.process_identity.pid,
    bootId: result.process_identity.boot_id, startTicks: result.process_identity.start_time,
    ...(result.process_identity.namespace ? { pidNamespace: result.process_identity.namespace } : {}), executionLeaseId: result.lease_id, instanceId: runtime.owner.instance_id } : null;
  const supervisor = verifierSupervisor(binding, cwd);
  return { stdout: result.stdout, stderr: result.stderr, truncated: result.truncated, timedOut: result.timedOut, cancelled: result.cancelled,
    spawnFailed: !result.started, admissionError: null as string | null, started: result.started, lingering: 0,
    launcherExitCode: result.exitCode, exitCode: result.exitCode, commandSignal: null as string | null,
    terminalObserved: result.started && result.terminationConfirmed, terminationConfirmed: result.terminationConfirmed,
    supervisor: { executable: supervisor.path, hash: supervisor.hash, engineHash: supervisor.engineHash,
      namespace: result.process_identity?.namespace ?? null, namespaceInit: identity,
      namespaceStopped: result.terminationConfirmed, launcherStopped: result.terminationConfirmed, commandStarted: result.started,
      killErrors: [] as string[], unresolvedProcess: null as unknown, parentNamespace: null as string | null, observerPid: process.pid,
      executionLeaseId: result.lease_id, coverage: "agentcfg-supervisor" as const } };
}
