import { spawnSync } from "node:child_process";
const runtimeKey = Symbol.for("agentcfg.pi.runtime.v1");
export function processIdentity(pid = process.pid) {
    const runtime = globalThis[runtimeKey], owner = runtime?.owner, identity = owner?.process_identity;
    if (!identity || identity.pid !== pid || !owner.lease_id) return null;
    return {
        pid,
        bootId: identity.boot_id,
        startTicks: identity.start_time,
        ...identity.namespace ? {
            pidNamespace: identity.namespace
        } : {},
        executionLeaseId: owner.lease_id,
        instanceId: owner.instance_id
    };
}
export function originalProcessStopped(identity) {
    const runtime = globalThis[runtimeKey];
    if (!identity.executionLeaseId || identity.instanceId !== runtime?.owner?.instance_id) return null;
    try {
        const options = runtime.supervisor.options;
        const result = spawnSync(options.python, [
            "-I",
            options.client
        ], {
            input: JSON.stringify({
                schema_version: 1,
                request_id: "process-reconcile",
                method: "reconcile",
                args: {
                    lease_id: identity.executionLeaseId
                }
            }) + "\n",
            encoding: "utf8",
            timeout: 30000,
            maxBuffer: 1024 * 1024,
            env: {
                PATH: process.env.PATH,
                HOME: process.env.HOME,
                AGENTCFG_SUPERVISOR_ENDPOINT: options.endpoint,
                AGENTCFG_SUPERVISOR_CAPABILITY: options.capability
            }
        });
        if (result.status !== 0) return null;
        const reply = JSON.parse(result.stdout);
        if (!reply.ok || reply.result.lease_id !== identity.executionLeaseId) return null;
        const observed = reply.result.process_identity;
        if (observed && (observed.pid !== identity.pid || observed.boot_id !== identity.bootId || observed.start_time !== identity.startTicks)) return null;
        return reply.result.protected === false ? true : reply.result.process_status === "alive" ? false : null;
    } catch  {
        return null;
    }
}
export const supervisorProcessMonitor = {
    current: ()=>processIdentity(),
    stopped: originalProcessStopped
};
export const linuxProcessMonitor = supervisorProcessMonitor;
