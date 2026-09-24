import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createRequire, syncBuiltinESMExports } from "node:module";
import { dirname, join } from "node:path";
import { readFileSync, writeFileSync } from "node:fs";

/** Private Pi test process only. Cause a real OS ENOENT at the pinned backend's child spawn. */
export default function nativeSpawnError(pi: ExtensionAPI) {
  const config = JSON.parse(readFileSync(process.env.PI_TASK_KEEPER_CONFIG!, "utf8")), root = dirname(config.storage.path);
  const childProcess = createRequire(import.meta.url)("node:child_process") as typeof import("node:child_process");
  const original = childProcess.spawn, requests = new Map<string, unknown>();
  const witness: Record<string, unknown> = { attempts: [], responses: [] };
  const save = () => writeFileSync(join(root, "native-spawn-error.json"), JSON.stringify(witness), { mode: 0o600 });
  pi.events.on("prompt-template:subagent:request", (request: any) => { requests.set(request.requestId, request); });
  pi.events.on("prompt-template:subagent:response", (response: any) => {
    if (!requests.has(response.requestId)) return;
    (witness.responses as unknown[]).push({ request: requests.get(response.requestId), response }); save();
  });
  childProcess.spawn = ((command: string, args: string[], options: any) => {
    if (!Array.isArray(args) || !args.some(arg => arg.endsWith("/src/adapters/child-reporter.ts"))) return original(command, args, options);
    const missing = join(root, "intentionally-missing-child-executable");
    const child = original(missing, args, options);
    const attempt: Record<string, unknown> = { originalCommand: command, command: missing, args, pid: child.pid ?? null, spawned: false };
    (witness.attempts as unknown[]).push(attempt); save();
    child.once("spawn", () => { attempt.spawned = true; attempt.pid = child.pid; save(); });
    child.once("error", (error: NodeJS.ErrnoException) => { attempt.error = { code: error.code, errno: error.errno, syscall: error.syscall, message: error.message }; save(); });
    return child;
  }) as typeof childProcess.spawn;
  syncBuiltinESMExports();
  pi.on("session_shutdown", () => { childProcess.spawn = original; syncBuiltinESMExports(); });
}
