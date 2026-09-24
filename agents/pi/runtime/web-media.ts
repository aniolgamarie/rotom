// 本地 FFmpeg/ffprobe 不在 Pi 进程中直接启动；使用已有命令队列和终止证明。
import { randomUUID } from "node:crypto";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";
import { webLocalFile } from "./web-files.ts";
export async function webMedia(operation, path, seconds) {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  const owner = runtime?.web?.current(); requireOrdinaryHelper(runtime, "pi-web", owner?.id ?? null);
  if (!owner) reject("WEB_OPERATION_CLOSED", 4);
  const input = await webLocalFile(path);
  owner.controller.signal.throwIfAborted();
  const ticket = await runtime.supervisor.call("ordinary_web_media_prepare", { operation_id: randomUUID(), file_id: input.file_id,
    operation, ...(seconds !== undefined ? { seconds } : {}) });
  let stdout;
  runtime.web.verifyExternal(async () => {
    const proof = await runtime.supervisor.call("reconcile", { lease_id: ticket.lease_id });
    return proof.lease_id === ticket.lease_id && !proof.protected && proof.termination_evidence?.verified === true;
  });
  const result = await runtime.web.track(runtime.ordinaryOperations.write(ticket, null, null, owner.controller.signal,
    { onCapture(value) { stdout = value.stdout; } }));
  if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== runtime) reject("WEB_MEDIA_STALE", 4);
  runtime.web.current();
  if (!result.terminationConfirmed || result.truncated || result.exitCode !== 0) reject("WEB_MEDIA_FAILED", 5);
  if (operation === "duration") {
    const text = result.stdout.trim();
    if (text.length > 128 || !/^[0-9]+(?:\.[0-9]+)?$/.test(text)) reject("WEB_MEDIA_DURATION_INVALID", 5);
    const duration = Number(text);
    if (!Number.isFinite(duration)) reject("WEB_MEDIA_DURATION_INVALID", 5);
    return duration;
  }
  if (!Buffer.isBuffer(stdout) || stdout.length < 4 || stdout.length > 5 * 1024 * 1024
      || stdout[0] !== 0xff || stdout[1] !== 0xd8 || stdout.at(-2) !== 0xff || stdout.at(-1) !== 0xd9) reject("WEB_MEDIA_FRAME_INVALID", 5);
  return { data: stdout.toString("base64"), mimeType: "image/jpeg" };
}
