// 工作区与检查使用现有 AgentManager 槽位；没有第二条进程队列。
import { createHash, randomUUID } from "node:crypto";
import { dirname, join } from "node:path";
import { privateBytes, privateFile } from "./launch.ts";
import { canonical, digest, reject } from "./managed-types.ts";

export async function runAuxiliary({ runtime, pi, context, program, payload, cwd, taskId, signal, onDispatch, timeoutMs = 120000,
    pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)), now = () => Date.now() }) {
  const entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")];
  if (!entry?.manager || !["workspace", "check"].includes(program)) reject("CAPABILITY_MISSING", 5);
  const supervisor = runtime.supervisor, manager = entry.manager;
  const planned = await supervisor.call("workspace_identity", { path: cwd });
  const snapshot = program === "workspace" && payload.operation === "create" ? { snapshot_digest: null }
    : await supervisor.call("workspace_snapshot", { path: cwd });
  const execution_id = "aux-" + randomUUID();
  const allocated = await supervisor.call("allocate", { kind: program === "check" ? "check" : "external", execution_id,
    task_id: taskId, attempt_id: execution_id, lock_identity: runtime.installed.lock_identity, slice_identity: runtime.installed.slice_identity,
    policy_digest: digest(runtime.manifest.permission_policy), candidate_digest: snapshot.snapshot_digest, planned_workspaces: [planned] });
  let result, canceled = false, timedOut = false, started = false, failureSettled = false, resolveResult, rejectResult;
  const outcome = new Promise((resolve, reject) => { resolveResult = resolve; rejectResult = reject; });
  const stateRoot = dirname(dirname(dirname(supervisor.options.endpoint)));
  const stop = async () => {
    canceled = true;
    const current = await supervisor.call("inspect", { lease_id: allocated.lease_id });
    await supervisor.call(current.state === "allocating" ? "abort_allocation" : "cancel", { lease_id: allocated.lease_id });
    const after = await supervisor.call("inspect", { lease_id: allocated.lease_id });
    if (!after.protected) {
      if (!started) resolveResult({ stdout: "", stderr: "", truncated: false, exitCode: null, timedOut, cancelled: true,
        terminationConfirmed: true, started: false, lease_id: allocated.lease_id, process_identity: null, workspace_result: null });
      return { response_text: "", terminal_status: "canceled", termination_confirmed: true, external_work_empty: true };
    }
    return undefined;
  };
  const executor = { kind: "external", manager_run_id: execution_id, cancel: async () => { try { return await stop(); } catch (error) { rejectResult(error); throw error; } }, async execute() {
    if (signal?.aborted) return stop();
    onDispatch?.();
    const launched = await supervisor.call("start", { lease_id: allocated.lease_id, program, payload });
    started = launched.state === "running";
    if (!started) reject("START_UNKNOWN", 4);
    const deadline = now() + timeoutMs;
    for (;;) {
      const status = await supervisor.call("inspect", { lease_id: allocated.lease_id });
      if (!status.protected) break;
      if (now() >= deadline && !timedOut) { timedOut = true; await stop(); }
      if (now() > deadline + 10000) reject("TERMINATION_UNKNOWN", 4);
      await pause(250);
    }
    const directory = join(stateRoot, "activity/outputs", allocated.lease_id);
    const capture = JSON.parse(privateFile(join(directory, "capture.json")));
    const exited = JSON.parse(privateFile(join(stateRoot, "activity/exits", allocated.lease_id + ".json")));
    const proof = await supervisor.call("reconcile", { lease_id: allocated.lease_id });
    if (capture.complete !== true || exited.lease_id !== allocated.lease_id || proof.lease_id !== allocated.lease_id || proof.protected
        || proof.termination_evidence?.verified !== true || canonical(proof.process_identity) !== canonical(exited.process_identity)) reject("EVIDENCE_MISSING", 5);
    const stdout = privateBytes(join(directory, "stdout")), stderr = privateBytes(join(directory, "stderr"));
    for (const [name, text] of [["stdout", stdout], ["stderr", stderr]]) {
      if (createHash("sha256").update(text).digest("hex") !== capture.streams[name].sha256) reject("EVIDENCE_IDENTITY", 4);
    }
    result = { stdout: stdout.toString("utf8"), stderr: stderr.toString("utf8"), truncated: capture.truncated, exitCode: exited.exit_code, timedOut, cancelled: canceled && !timedOut,
      terminationConfirmed: true, started, lease_id: allocated.lease_id, process_identity: exited.process_identity,
      workspace_result: program === "workspace" && exited.exit_code === 0 ? JSON.parse(privateFile(join(stateRoot, "activity/workspace-results", allocated.lease_id + ".json"))) : null };
    resolveResult(result);
    return { response_text: "Auxiliary execution observed", terminal_status: exited.exit_code === 0 && !canceled ? "completed" : "failed",
      termination_confirmed: true, external_work_empty: true };
  } };
  const execute = executor.execute;
  executor.execute = async () => {
    try { return await execute(); }
    catch (error) {
      try {
        const observed = await supervisor.call("inspect", { lease_id: allocated.lease_id });
        if (observed.state === "allocating") await supervisor.call("abort_allocation", { lease_id: allocated.lease_id });
        const proof = await supervisor.call("reconcile", { lease_id: allocated.lease_id });
        if (proof.lease_id === allocated.lease_id && !proof.protected && proof.termination_evidence?.verified) {
          failureSettled = true;
          return { response_text: "", terminal_status: "failed", termination_confirmed: true, external_work_empty: true };
        }
      } finally { rejectResult(error); }
      throw error;
    }
  };
  let id;
  try { id = manager.spawnWithExecutor(pi ?? entry.pi, context ?? entry.getContext(), "agentcfg-" + program, "Trusted " + program, executor, { description: program, cwd, isBackground: true }); }
  catch (error) { await supervisor.call("abort_allocation", { lease_id: allocated.lease_id }); throw error; }
  const cancel = () => { manager.abort(id); };
  signal?.addEventListener("abort", cancel, { once: true });
  try {
    if (signal?.aborted) cancel();
    const value = await outcome;
    await manager.getRecord(id).promise;
    manager.consumeControlled(id);
    return value;
  } finally {
    signal?.removeEventListener("abort", cancel);
    if (failureSettled && manager.getRecord(id)) {
      await manager.getRecord(id).promise;
      manager.consumeControlled(id); manager.removeConsumedControlled(id);
    }
  }
}
