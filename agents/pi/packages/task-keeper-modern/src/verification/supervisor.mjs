import { readFileSync } from "node:fs";
import { join } from "node:path";
import { runAuxiliary } from "../../runtime/auxiliary-executor.mjs";
import { canonical, ContractError, digest } from "../contracts/primitives.mjs";
function runtimeContext() {
    const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
    if (!runtime || runtime.owner?.role !== "manager") throw new ContractError("AGENTCFG_SUPERVISOR_REQUIRED");
    return runtime;
}
export function verifierSupervisor(_binding, _cwd) {
    const runtime = runtimeContext(), path = join(runtime.runtimeRoot, "supervisor/scripts/pi-project-check");
    return {
        path,
        hash: digest(readFileSync(path).toString("base64")),
        engineHash: runtime.installed.runtime_identity
    };
}
function assertCheck(binding, runtime, checkId) {
    const declared = runtime.manifest.options.checks?.[checkId];
    if (!declared || binding.executable !== declared.executable || canonical(binding.args) !== canonical(declared.args) || binding.timeoutMs !== declared.timeout_seconds * 1000 || binding.kind !== declared.kind || binding.parser !== declared.parser || binding.minimumTests !== declared.minimum_tests || canonical(binding.inputs ?? []) !== canonical(declared.inputs) || canonical(binding.requiredTestIds ?? null) !== canonical(declared.required_test_ids ?? null) || canonical(binding.read_roots ?? null) !== canonical(declared.read_roots ?? null) || canonical(binding.trusted_inputs ?? null) !== canonical(declared.trusted_inputs ?? null) || Object.keys(binding.environment).length) throw new ContractError("CHECK_BINDING_CHANGED");
}
export async function checkBindingSnapshot(binding, cwd, checkId, taskId, signal) {
    const runtime = runtimeContext(), before = digest({
        manifest: runtime.manifest,
        installed: runtime.installed,
        owner: runtime.owner
    });
    const fixed = canonical(binding);
    if (signal?.aborted) throw new ContractError("CHECK_BINDING_SNAPSHOT_CANCELLED");
    assertCheck(binding, runtime, checkId);
    const result = await runtime.supervisor.call("check_binding_snapshot", {
        check_id: checkId,
        task_id: taskId,
        cwd
    });
    if (signal?.aborted) throw new ContractError("CHECK_BINDING_SNAPSHOT_CANCELLED");
    if (runtimeContext() !== runtime || before !== digest({
        manifest: runtime.manifest,
        installed: runtime.installed,
        owner: runtime.owner
    }) || canonical(binding) !== fixed) throw new ContractError("CHECK_BINDING_SNAPSHOT_STALE");
    assertCheck(binding, runtime, checkId);
    if (!result || Object.getPrototypeOf(result) !== Object.prototype || Object.keys(result).sort().join() !== "check_id,contract_digest,schema_version,task_id" || result.schema_version !== 1 || result.check_id !== checkId || result.task_id !== taskId || typeof result.contract_digest !== "string" || !/^[a-f0-9]{64}$/.test(result.contract_digest)) throw new ContractError("CHECK_BINDING_SNAPSHOT_INVALID");
    return result.contract_digest;
}
export async function supervisedCommand(binding, cwd, _env, options) {
    const runtime = runtimeContext(), checkId = options.checkId, jobId = options.jobId;
    if (!checkId || !jobId) throw new ContractError("CHECK_BINDING_CHANGED");
    assertCheck(binding, runtime, checkId);
    if (typeof options.contractDigest !== "string" || !/^[a-f0-9]{64}$/.test(options.contractDigest)) throw new ContractError("CHECK_CONTRACT_REQUIRED");
    const result = await runAuxiliary({
        runtime,
        program: "check",
        payload: {
            check_id: checkId,
            cwd,
            task_id: jobId,
            contract_digest: options.contractDigest
        },
        cwd,
        taskId: jobId,
        signal: options.signal,
        onDispatch: options.onDispatch,
        timeoutMs: binding.timeoutMs
    });
    const identity = result.process_identity ? {
        pid: result.process_identity.pid,
        bootId: result.process_identity.boot_id,
        startTicks: result.process_identity.start_time,
        ...result.process_identity.namespace ? {
            pidNamespace: result.process_identity.namespace
        } : {},
        executionLeaseId: result.lease_id,
        instanceId: runtime.owner.instance_id
    } : null;
    const supervisor = verifierSupervisor(binding, cwd);
    return {
        stdout: result.stdout,
        stderr: result.stderr,
        truncated: result.truncated,
        timedOut: result.timedOut,
        cancelled: result.cancelled,
        spawnFailed: !result.started,
        admissionError: null,
        started: result.started,
        lingering: 0,
        launcherExitCode: result.exitCode,
        exitCode: result.exitCode,
        commandSignal: null,
        terminalObserved: result.started && result.terminationConfirmed,
        terminationConfirmed: result.terminationConfirmed,
        supervisor: {
            executable: supervisor.path,
            hash: supervisor.hash,
            engineHash: supervisor.engineHash,
            namespace: result.process_identity?.namespace ?? null,
            namespaceInit: identity,
            namespaceStopped: result.terminationConfirmed,
            launcherStopped: result.terminationConfirmed,
            commandStarted: result.started,
            killErrors: [],
            unresolvedProcess: null,
            parentNamespace: null,
            observerPid: process.pid,
            executionLeaseId: result.lease_id,
            coverage: "agentcfg-supervisor"
        }
    };
}
