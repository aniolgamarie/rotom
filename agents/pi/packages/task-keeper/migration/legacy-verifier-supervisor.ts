import { spawn } from "node:child_process";
import { accessSync, constants, readFileSync, readlinkSync, realpathSync } from "node:fs";
import { delimiter, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { ContractError, digest, newId } from "../contracts/primitives.ts";
import { processIdentity, originalProcessStopped, type ProcessIdentity } from "../adapters/process-identity.ts";
import type { VerificationBinding } from "../config.ts";
import type { Writable } from "node:stream";
import { setTimeout as delay } from "node:timers/promises";

const engineSource = () => digest(["supervisor.ts", "namespace-command.ts", "../adapters/process-identity.ts"].map(file => readFileSync(new URL(file, import.meta.url), "utf8")));
const loadedEngine = engineSource();

export function verifierSupervisor(binding: VerificationBinding, cwd: string) {
  if (process.platform !== "linux") throw new ContractError("VERIFIER_PID_NAMESPACE_UNAVAILABLE");
  if (engineSource() !== loadedEngine) throw new ContractError("VERIFIER_RUNTIME_CHANGED_RELOAD_REQUIRED");
  const name = binding.supervisorExecutable ?? "bwrap";
  const paths = isAbsolute(name) || name.includes("/") ? [resolve(cwd, name)] : (process.env.PATH ?? "").split(delimiter).map(dir => join(dir, name));
  const executable = paths.find(path => { try { accessSync(path, constants.X_OK); return true; } catch { return false; } });
  if (!executable) throw new ContractError("VERIFIER_SUPERVISOR_UNAVAILABLE");
  const path = realpathSync(executable);
  return { path, hash: digest(readFileSync(path).toString("base64")), engineHash: digest([loadedEngine, process.version, process.platform, process.arch]) };
}
function namespaceChild(launcher: number, pid: number, namespace: string): ProcessIdentity | null {
  try {
    if (!Number.isSafeInteger(pid) || pid < 1 || namespace === readlinkSync(`/proc/${process.pid}/ns/pid`) || readlinkSync(`/proc/${pid}/ns/pid`) !== namespace) return null;
    let cursor = pid;
    for (let depth = 0; depth < 64 && cursor > 1; depth++) {
      if (cursor === launcher) return processIdentity(pid);
      const stat = readFileSync(`/proc/${cursor}/stat`, "utf8"); cursor = Number(stat.slice(stat.lastIndexOf(")") + 2).trim().split(/\s+/)[1]);
    }
  } catch { /* No OS proof means no command authorization. */ }
  return null;
}
export async function supervisedCommand(binding: VerificationBinding, cwd: string, env: NodeJS.ProcessEnv,
  options: { signal?: AbortSignal; maxBytes: number; killGraceMs: number; onDispatch?: () => void }) {
  const supervisor = verifierSupervisor(binding, cwd), nonce = newId("verify"), parentNamespace = readlinkSync(`/proc/${process.pid}/ns/pid`);
  const child = spawn(supervisor.path, ["--unshare-user", "--unshare-pid", "--die-with-parent", "--bind", "/", "/", "--dev-bind", "/dev", "/dev", "--proc", "/proc", "--chdir", cwd,
    "--info-fd", "3", process.execPath, "--experimental-strip-types", fileURLToPath(new URL("./namespace-command.ts", import.meta.url)), nonce, parentNamespace, binding.executable, ...binding.args],
  { cwd, env: { ...env, NODE_NO_WARNINGS: "1" }, detached: true, stdio: ["ignore", "pipe", "pipe", "pipe", "pipe", "pipe"] });
  const launcher = child.pid ? processIdentity(child.pid) : null;
  let proof: ProcessIdentity | null = null, namespace = "", namespacePid = 0, started = false, done = false;
  let timedOut = false, cancelled = false, spawnFailed = false, admissionError: string | null = null, forcedUnknown = false, launcherClosed = false;
  let stderr = "", bytes = 0, truncated = false, info = "", control = "", lingering = 0;
  const stdoutChunks: Buffer[] = [], stderrChunks: Buffer[] = [];
  const killErrors: string[] = [];
  let finished: { code: number | null; signal: string | null } | null = null;
  let killTimer: ReturnType<typeof setTimeout> | undefined;
  const kill = () => {
    if (proof && originalProcessStopped(proof) === false) try { process.kill(proof.pid, "SIGKILL"); } catch (error) { killErrors.push(`namespace:${(error as NodeJS.ErrnoException).code}`); }
    if (launcher && originalProcessStopped(launcher) === false) try { process.kill(-launcher.pid, "SIGKILL"); } catch (error) { killErrors.push(`launcher:${(error as NodeJS.ErrnoException).code}`); }
  };
  const stop = () => {
    // Cancellation can beat the namespace handshake. The launcher may exit
    // before its child can be identified, so revoke the unopened command gate
    // as well: EOF makes that child exit without ever receiving authorization.
    const authorization = child.stdio.at(5) as Writable;
    if (!started && !authorization.writableEnded) authorization.end();
    if (launcher && originalProcessStopped(launcher) === false) try { process.kill(-launcher.pid, "SIGTERM"); } catch { /* Escalate below. */ }
    killTimer ??= setTimeout(kill, options.killGraceMs);
  };
  const abort = () => { cancelled = true; stop(); };
  const authorize = () => {
    if (done || started || !namespacePid || !namespace) return;
    proof = namespaceChild(child.pid!, namespacePid, namespace);
    if (!proof) { admissionError = "VERIFIER_NAMESPACE_NOT_PROVEN"; stop(); return; }
    if (options.signal?.aborted || timedOut) { abort(); return; }
    try {
      if (options.onDispatch?.constructor.name === "AsyncFunction") throw new ContractError("ASYNC_VERIFICATION_GUARD_NOT_SUPPORTED");
      const result: unknown = options.onDispatch?.();
      if (result && typeof (result as { then?: unknown }).then === "function") { void Promise.resolve(result).catch(() => {}); throw new ContractError("ASYNC_VERIFICATION_GUARD_NOT_SUPPORTED"); }
      if (options.signal?.aborted) { abort(); return; }
      started = true;
      (child.stdio.at(5) as Writable).end(nonce);
    } catch (error) { admissionError = error instanceof Error ? error.message : "verification_admission_denied"; stop(); }
  };
  child.stdio[3]!.on("data", chunk => {
    info += chunk.toString(); if (info.length > 8192) { admissionError = "INVALID_SUPERVISOR_INFO"; stop(); return; }
    try { namespacePid = JSON.parse(info)["child-pid"]; authorize(); } catch { /* Wait for complete JSON. */ }
  });
  child.stdio[4]!.on("data", chunk => {
    control += chunk.toString(); if (control.length > 8192) { admissionError = "INVALID_SUPERVISOR_PROTOCOL"; stop(); return; }
    let index: number;
    while ((index = control.indexOf("\n")) >= 0) {
      const line = control.slice(0, index); control = control.slice(index + 1);
      try {
        const event = JSON.parse(line); if (event.nonce !== nonce) throw new Error("nonce");
        if (event.type === "ready") { namespace = event.namespace; authorize(); }
        else if (event.type === "finished") {
          if ((event.code !== null && (!Number.isSafeInteger(event.code) || event.code < 0 || event.code > 255))
            || (event.signal !== null && typeof event.signal !== "string") || !Number.isSafeInteger(event.lingering) || event.lingering < 0) throw new Error("terminal");
          finished = { code: event.code, signal: event.signal }; lingering = event.lingering;
        }
        else if (event.type === "spawn_error") { spawnFailed = true; stderr += `command_spawn_failed: ${String(event.code)}\n`; }
        else { admissionError = "INVALID_SUPERVISOR_PROTOCOL"; stop(); }
      } catch { admissionError = "INVALID_SUPERVISOR_PROTOCOL"; stop(); }
    }
  });
  const collect = (chunk: Buffer, channel: "stdout" | "stderr") => {
    const remaining = Math.max(0, options.maxBytes - bytes); bytes += chunk.length; truncated ||= chunk.length > remaining;
    (channel === "stdout" ? stdoutChunks : stderrChunks).push(chunk.subarray(0, remaining));
  };
  child.stdout!.on("data", chunk => collect(chunk, "stdout")); child.stderr!.on("data", chunk => collect(chunk, "stderr"));
  // Closing control pipes after cancellation is expected and must not become an unhandled stream error.
  for (const pipe of child.stdio.slice(3)) pipe?.on("error", () => { if (!cancelled && !timedOut && !done) { admissionError ??= "SUPERVISOR_CHANNEL_LOST"; stop(); } });
  options.signal?.addEventListener("abort", abort, { once: true }); if (options.signal?.aborted) abort();
  const timer = setTimeout(() => { timedOut = true; stop(); }, binding.timeoutMs);
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  const launcherCode = await new Promise<number | null>(resolveExit => {
    child.once("error", () => { spawnFailed = true; });
    child.once("close", code => { launcherClosed = true; resolveExit(code); });
    watchdog = setTimeout(() => {
      forcedUnknown = true; kill();
      for (const pipe of child.stdio) pipe?.destroy(); resolveExit(null);
    }, binding.timeoutMs + options.killGraceMs * 2);
  });
  done = true; clearTimeout(timer); clearTimeout(watchdog); clearTimeout(killTimer); options.signal?.removeEventListener("abort", abort);
  // bubblewrap's outer process can exit just before its namespace reaper finishes cleanup.
  // Observe the kernel identity, and force the owned namespace closed if descendants remain.
  let namespaceStopped = proof ? originalProcessStopped(proof) === true : !started;
  if (proof && !namespaceStopped) {
    kill();
    const until = Date.now() + options.killGraceMs;
    while (Date.now() < until && !namespaceStopped) {
      await delay(5); namespaceStopped = originalProcessStopped(proof) === true;
    }
  }
  const launcherStopped = launcherClosed || (launcher ? originalProcessStopped(launcher) === true : spawnFailed);
  const terminationConfirmed = namespaceStopped && launcherStopped;
  if (!terminationConfirmed) kill();
  let unresolvedProcess: unknown = null;
  if (!namespaceStopped && proof) {
    const inspect = (operation: () => unknown) => { try { return operation(); } catch (error) { return { error: (error as NodeJS.ErrnoException).code }; } };
    unresolvedProcess = {
      observerNamespace: inspect(() => readlinkSync(`/proc/${process.pid}/ns/pid`)),
      targetNamespace: inspect(() => readlinkSync(`/proc/${proof!.pid}/ns/pid`)),
      actual: processIdentity((proof as ProcessIdentity).pid), stopped: originalProcessStopped(proof),
      fields: inspect(() => { const stat = readFileSync(`/proc/${proof!.pid}/stat`, "utf8"); return stat.slice(stat.lastIndexOf(")") + 2).trim().split(/\s+/).slice(0, 20); }),
      signalZero: inspect(() => process.kill(proof!.pid, 0)),
    };
  }
  const commandExit = finished as { code: number | null; signal: string | null } | null;
  return { stdout: Buffer.concat(stdoutChunks).toString("utf8"), stderr: stderr + Buffer.concat(stderrChunks).toString("utf8"), truncated, timedOut, cancelled, spawnFailed, admissionError, started, lingering,
    launcherExitCode: launcherCode,
    exitCode: commandExit?.code ?? launcherCode, commandSignal: commandExit?.signal ?? null,
    terminalObserved: commandExit !== null && !forcedUnknown, terminationConfirmed,
    supervisor: { executable: supervisor.path, hash: supervisor.hash, engineHash: supervisor.engineHash, namespace: proof ? namespace : null,
      namespaceInit: proof as ProcessIdentity | null, namespaceStopped, launcherStopped, commandStarted: started, killErrors, unresolvedProcess, parentNamespace, observerPid: process.pid },
  };
}
