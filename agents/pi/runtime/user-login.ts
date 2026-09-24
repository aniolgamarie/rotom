// 用户命令使用现有队列；bootstrap 没有模型管理者时仅执行一个监督登录操作。
import { randomUUID } from "node:crypto";
import { dirname, join } from "node:path";
import { privateFile } from "./launch.ts";
import { digest, reject } from "./managed-types.ts";

export async function loginCodex(runtime, pi, ctx, { pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)), now = () => Date.now(),
    setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  if (!runtime.manifest.options.model_delegate?.backends?.includes("codex")) reject("DELEGATE_BACKEND_UNBOUND", 2);
  if (runtime.managedRequestScope?.getStore()) reject("USER_CONTROL_REQUIRED", 4);
  const entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")];
  if (!entry?.manager && !runtime.manifest.bootstrap) reject("CAPABILITY_MISSING", 5);
  const id = "login-" + randomUUID(), supervisor = runtime.supervisor, deadline = now() + 300000;
  const lease = await supervisor.call("allocate", { kind: "codex", execution_id: id, task_id: null, attempt_id: id,
    lock_identity: runtime.installed.lock_identity, slice_identity: runtime.installed.slice_identity,
    policy_digest: digest(runtime.manifest.permission_policy), candidate_digest: null, planned_workspaces: [] });
  let resolveOutcome, rejectOutcome, canceled = false;
  const outcome = new Promise((resolve, fail) => { resolveOutcome = resolve; rejectOutcome = fail; });
  const cancel = async () => {
    canceled = true;
    const observed = await supervisor.call("inspect", { lease_id: lease.lease_id });
    await supervisor.call(observed.state === "allocating" ? "abort_allocation" : "cancel", { lease_id: lease.lease_id });
    const proof = await supervisor.call("reconcile", { lease_id: lease.lease_id });
    if (!proof.protected && proof.termination_evidence?.verified) {
      resolveOutcome({ state: "canceled", lease_id: lease.lease_id, model_execution: "not-run" });
      return { terminal_status: "canceled", response_text: "", termination_confirmed: true, external_work_empty: true };
    }
    return undefined;
  };
  const execute = async () => {
    try {
      if (canceled || now() >= deadline) return cancel();
      await supervisor.call("start", { lease_id: lease.lease_id, program: "codex-login", payload: {} });
      while (now() < deadline + 10000) {
        const observed = await supervisor.call("reconcile", { lease_id: lease.lease_id });
        if (!observed.protected && observed.termination_evidence?.verified) {
          const root = dirname(dirname(dirname(supervisor.options.endpoint)));
          const exit = JSON.parse(privateFile(join(root, "activity/exits", lease.lease_id + ".json")));
          if (exit.lease_id !== lease.lease_id || exit.exit_code !== 0) reject("DELEGATE_LOGIN_FAILED", 5);
          const result = { state: canceled ? "canceled" : "ended", lease_id: lease.lease_id, model_execution: "not-run" };
          resolveOutcome(result);
          return { terminal_status: canceled ? "canceled" : "completed", response_text: "Login command ended; authentication and model use remain separately verifiable.", termination_confirmed: true, external_work_empty: true };
        }
        if (now() >= deadline && !canceled) { await cancel(); canceled = true; }
        await pause(250);
      }
      reject("TERMINATION_UNKNOWN", 4);
    } catch (error) {
      rejectOutcome(error);
      const observed = await supervisor.call("inspect", { lease_id: lease.lease_id });
      if (observed.state === "allocating") await supervisor.call("abort_allocation", { lease_id: lease.lease_id });
      const proof = await supervisor.call("reconcile", { lease_id: lease.lease_id });
      if (!proof.protected && proof.termination_evidence?.verified) return { terminal_status: "failed", response_text: "", termination_confirmed: true, external_work_empty: true };
      throw error;
    }
  };
  const timer = setTimer(() => {
    if (entry?.manager) entry.manager.abort(id);
    else void cancel().catch(rejectOutcome);
  }, Math.max(1, deadline - now()));
  timer?.unref?.();
  try {
    if (entry?.manager) {
      entry.manager.spawnWithExecutor(pi, ctx, "model-login", "USER_CODEX_LOGIN", { kind: "external", manager_run_id: id, execute, cancel },
        { description: "Codex login", cwd: join(runtime.instanceRoot, "user-home"), isBackground: true });
    } else void execute().catch(() => {});
    const result = await outcome;
    const mirror = entry?.manager.getRecord(id);
    if (mirror) {
      await mirror.promise;
      entry.manager.consumeControlled(id); entry.manager.removeConsumedControlled(id);
    }
    return result;
  } catch (error) { await cancel().catch(() => {}); throw error; }
  finally { clearTimer(timer); }
}
