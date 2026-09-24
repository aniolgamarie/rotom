// 审查插件复用普通文件授权与受监督 Git；并发 UI 查询串行取得同一工作区租约。
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";
import { runTerminalCommand } from "./terminal-command.ts";

const queues = new WeakMap();
function context() {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  requireOrdinaryHelper(runtime, "pi-slopchop");
  return runtime;
}
export async function reviewGit(cwd, argv) {
  const runtime = context();
  const job = (queues.get(runtime) ?? Promise.resolve()).catch(() => {}).then(async () => {
    context();
    const ticket = await runtime.supervisor.call("ordinary_git_review_prepare", { operation_id: randomUUID(), cwd, argv });
    try {
      const result = await runtime.ordinaryOperations.write(ticket, null, null, undefined);
      const missingAllowed = argv[0] === "symbolic-ref" || argv[0] === "merge-base" || argv[0] === "rev-parse" && argv.includes("--quiet");
      if (result.truncated !== false || result.terminationConfirmed !== true || result.stderr !== ""
          || result.exitCode !== 0 && !(missingAllowed && result.exitCode === 1 && result.stdout === "")) reject("GIT_REVIEW_FAILED", 5);
      return { code: result.exitCode, stdout: result.stdout, stderr: "" };
    } finally { await runtime.supervisor.call("ordinary_command_finish", { operation_id: ticket.operation_id }); }
  });
  queues.set(runtime, job);
  try { return await job; }
  finally { if (queues.get(runtime) === job) queues.delete(runtime); }
}

async function file(path, metadata) {
  const runtime = context(), target = resolve(runtime.cwd, path);
  const ticket = await runtime.supervisor.call("ordinary_prepare", { operation_id: randomUUID(), role_id: "main", cwd: runtime.cwd,
    tool_name: "read", input: { path: target } });
  try {
    return metadata ? await runtime.supervisor.call("ordinary_stat", { operation_id: ticket.operation_id })
      : (await runtime.ordinaryOperations.read(ticket, target)).bytes;
  } finally { await runtime.supervisor.call("ordinary_finish", { operation_id: ticket.operation_id }); }
}
export function readReviewFile(path) { return file(path, false); }
export function statReviewFile(path) { return file(path, true); }

export async function runReviewEditor(path, line, cwd) {
  const runtime = context();
  const binding = runtime.manifest.options.external_tools?.[runtime.manifest.options.slopchop?.editor_tool_ref];
  const terminal = binding?.interactive === true;
  if (terminal && (!process.stdin.isTTY || !process.stdout.isTTY)) reject("EDITOR_TERMINAL_REQUIRED", 5);
  const ticket = await runtime.supervisor.call("ordinary_editor_prepare", { operation_id: randomUUID(), cwd, path, line,
    ...(terminal ? { rows: process.stdout.rows ?? 24, columns: process.stdout.columns ?? 80 } : {}) });
  try {
    if (terminal) return await runTerminalCommand(runtime, ticket);
    const result = await runtime.ordinaryOperations.write(ticket, null, null, undefined);
    if (result.terminationConfirmed !== true || result.truncated) reject("EDITOR_EXECUTION_UNVERIFIED", 5);
    return result.exitCode;
  } finally { await runtime.supervisor.call("ordinary_command_finish", { operation_id: ticket.operation_id }); }
}
