import { readFileSync, readlinkSync } from "node:fs";

export interface ProcessIdentity { pid: number; bootId: string; startTicks: string; pidNamespace?: string }
export interface ProcessMonitor {
  current(): ProcessIdentity | null;
  stopped(identity: ProcessIdentity): boolean | null;
}

/** Linux adapter: PID alone is not a lifecycle proof, because PIDs are reused. */
export function processIdentity(pid = process.pid): ProcessIdentity | null {
  if (process.platform !== "linux" || !Number.isSafeInteger(pid) || pid < 1) return null;
  try {
    const stat = readFileSync(`/proc/${pid}/stat`, "utf8");
    const fields = stat.slice(stat.lastIndexOf(")") + 2).trim().split(/\s+/);
    const startTicks = fields[19];
    if (!/^\d+$/.test(startTicks)) return null;
    return { pid, bootId: readFileSync("/proc/sys/kernel/random/boot_id", "utf8").trim(), startTicks, pidNamespace: readlinkSync(`/proc/${process.pid}/ns/pid`) };
  } catch { return null; }
}

export function originalProcessStopped(identity: ProcessIdentity): boolean | null {
  if (process.platform !== "linux") return null;
  try {
    if (readFileSync("/proc/sys/kernel/random/boot_id", "utf8").trim() !== identity.bootId) return true;
    // A PID is meaningful only in the namespace of the observer that recorded it.
    // Legacy/foreign namespace records cannot prove that an external writer stopped.
    if (!identity.pidNamespace || readlinkSync(`/proc/${process.pid}/ns/pid`) !== identity.pidNamespace) return null;
  } catch { return null; }
  try {
    // Read identity and state from the same kernel record. A second stat read can race
    // reaping and turn an already observed zombie back into a false "running" result.
    const stat = readFileSync(`/proc/${identity.pid}/stat`, "utf8"), fields = stat.slice(stat.lastIndexOf(")") + 2).trim().split(/\s+/);
    if (!/^\d+$/.test(fields[19])) return null;
    return fields[19] !== identity.startTicks || ["Z", "X"].includes(fields[0]);
  } catch { /* A disappearance is confirmed with a kernel signal lookup below. */ }
  try { process.kill(identity.pid, 0); return null; }
  catch (error) { return (error as NodeJS.ErrnoException).code === "ESRCH" ? true : null; }
}

export const linuxProcessMonitor: ProcessMonitor = { current: () => processIdentity(), stopped: originalProcessStopped };
