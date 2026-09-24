// 状态解析不把截断、命令失败或不完整终止证据当作干净仓库。
import { randomUUID } from "node:crypto";
import { assertSessionBoundary } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";

export function parseGitStatus(result) {
  if (result.exitCode !== 0 || result.truncated !== false || result.terminationConfirmed !== true
      || typeof result.stdout !== "string" || typeof result.stderr !== "string" || result.stderr !== "") reject("GIT_STATUS_FAILED", 5);
  if (result.stdout === "") return { status: "clean", changedFiles: 0 };
  if (!result.stdout.endsWith("\0")) reject("GIT_STATUS_INVALID", 5);
  const records = result.stdout.slice(0, -1).split("\0");
  let count = 0;
  for (let index = 0; index < records.length; index++) {
    const record = records[index], code = record.slice(0, 2);
    if (record.length < 4 || record[2] !== " " || !/^(?:\?\?|[ MADRCUT]{2})$/.test(code) || code === "  ") reject("GIT_STATUS_INVALID", 5);
    if (/[RC]/.test(code) && !records[++index]) reject("GIT_STATUS_INVALID", 5);
    count++;
  }
  return { status: "dirty", changedFiles: count };
}

export async function inspectGitStatus(runtime, context) {
  if (runtime?.owner?.role !== "manager" || runtime.managedRequestScope?.getStore()
      || !Object.hasOwn(runtime.manifest.resource_ids?.extensions ?? {}, "dirty-repo-guard")) reject("GIT_STATUS_CONTEXT_UNAVAILABLE", 4);
  await assertSessionBoundary(runtime);
  const ticket = await runtime.supervisor.call("ordinary_git_status_prepare", { operation_id: randomUUID(), cwd: context.cwd });
  if (ticket.status === "not-repository") return { status: "not-repository", changedFiles: 0 };
  try {
    const result = parseGitStatus(await runtime.ordinaryOperations.write(ticket, null, null, undefined));
    await assertSessionBoundary(runtime);
    return result;
  } finally {
    await runtime.supervisor.call("ordinary_command_finish", { operation_id: ticket.operation_id });
  }
}
