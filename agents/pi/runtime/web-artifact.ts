// PDF 可直接返回正文；显式选择落盘时复用普通写权限和同一个 supervisor。
import { randomUUID } from "node:crypto";
import { basename, isAbsolute, join, resolve } from "node:path";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";

export async function webPdfOutput(filename, content, requestedDirectory) {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")], operation = runtime?.web?.current();
  requireOrdinaryHelper(runtime, "pi-web", operation?.id ?? null);
  if (!operation || typeof content !== "string") reject("WEB_PDF_OUTPUT_INVALID", 2);
  const reference = runtime.manifest.options.web?.pdf_output_root_ref;
  if (!reference) {
    if (requestedDirectory !== undefined) reject("WEB_PDF_OUTPUT_UNBOUND", 2);
    return null;
  }
  const root = runtime.manifest.options.paths?.roots?.[reference];
  if (root?.purpose !== "write" || typeof root.path !== "string" || !isAbsolute(root.path)
      || requestedDirectory !== undefined && resolve(requestedDirectory) !== resolve(root.path)) reject("WEB_PDF_OUTPUT_UNBOUND", 2);
  if (typeof filename !== "string" || basename(filename) !== filename || !/^[A-Za-z0-9_-]{1,160}\.md$/.test(filename)) reject("WEB_PDF_OUTPUT_FILENAME", 2);
  if (Buffer.byteLength(content) > 1024 * 1024) reject("WEB_PDF_OUTPUT_LIMIT", 2);
  const path = join(root.path, filename.slice(0, -3) + "-" + randomUUID() + ".md");
  const ticket = await runtime.supervisor.call("ordinary_prepare", { operation_id: randomUUID(), role_id: "main", cwd: runtime.cwd,
    tool_name: "write", input: { path, content } });
  runtime.web.verifyExternal(async () => {
    const proof = await runtime.supervisor.call("reconcile", { lease_id: ticket.lease_id });
    return proof.lease_id === ticket.lease_id && !proof.protected && proof.termination_evidence?.verified === true;
  });
  runtime.web.cleanup(() => runtime.supervisor.call("ordinary_finish", { operation_id: ticket.operation_id }));
  await runtime.web.track(runtime.ordinaryOperations.write(ticket, content, null, operation.controller.signal));
  if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== runtime) reject("WEB_PDF_OUTPUT_STALE", 4);
  runtime.web.current();
  return path;
}
