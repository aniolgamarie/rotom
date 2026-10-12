// 公开SDK仅提供工具声明；准入、执行及有界输出由自有受管接口完成。
import { isAbsolute, resolve } from "node:path";
import { closed, isProtocolError, reject, sha } from "./managed-types.ts";
import { executeShellOperation } from "./shell-operation-executor.ts";

const limit = 8192, notice = "[Output truncated]\n";
const identifier = value => typeof value === "string" && /^[0-9a-f]{32}$/.test(value);
function validateAdmission(value) {
  try {
    closed(value, ["ticket", "input"]);
    const ticket = value.ticket;
    closed(ticket, ["operation_id", "lease_id", "kind", "tool_name", "write", "state", "timeout_seconds", "command_ref", "request_digest"]);
    if (ticket.kind !== "command" || ticket.tool_name !== "bash" || ticket.state !== "consumed"
        || !identifier(ticket.operation_id) || !identifier(ticket.lease_id) || typeof ticket.write !== "boolean"
        || !sha(ticket.request_digest) || typeof ticket.command_ref !== "string" || !/^tool:[a-z][a-z0-9_-]{0,63}$/.test(ticket.command_ref)
        || !Number.isSafeInteger(ticket.timeout_seconds) || ticket.timeout_seconds < 1 || ticket.timeout_seconds > Math.floor(Number.MAX_SAFE_INTEGER / 1000)
        || !value.input || !Object.isFrozen(value.input) || typeof value.input.command !== "string" || !value.input.command.length) throw Error();
    return ticket;
  } catch { reject("ORDINARY_SHELL_TICKET", 4); }
}
function display(text, retainedTruncated) {
  const bytes = Buffer.from(text, "utf8"), truncated = retainedTruncated || bytes.length > limit;
  const room = limit - (truncated ? Buffer.byteLength(notice, "utf8") : 0);
  // 保留构建日志末尾；UTF-8起点移到下一个完整字符边界，提示也计入显示上限。
  let start = Math.max(0, bytes.length - room);
  while (start < bytes.length && (bytes[start] & 0xc0) === 0x80) start++;
  const tail = new TextDecoder().decode(bytes.subarray(start));
  return { text: (truncated ? notice : "") + tail, truncated };
}
export function createOfficialShellTool({ sdk, cwd, admission, supervisor }) {
  if (typeof sdk?.createBashToolDefinition !== "function" || typeof admission?.admit !== "function"
      || typeof supervisor?.call !== "function" || typeof cwd !== "string" || !isAbsolute(cwd) || resolve(cwd) !== cwd
      || /[\u0000-\u001f\u007f]/.test(cwd)) reject("ORDINARY_SHELL_UNAVAILABLE", 5);
  let definition;
  try {
    definition = sdk.createBashToolDefinition(cwd, { operations: { async exec() { reject("ORDINARY_SHELL_FALLBACK_FORBIDDEN", 5); } }, exposeSessionEnvironment: false });
    if (!definition || definition.name !== "bash" || !definition.parameters) throw Error();
  } catch { reject("ORDINARY_SHELL_UNAVAILABLE", 5); }
  return {
    ...definition,
    description: "Run a Bash script after approval in allowed roots, with restricted access and networking disabled.",
    async execute(id, input, signal, update, ctx) {
      if (update !== undefined && typeof update !== "function") reject("ORDINARY_SHELL_UNAVAILABLE", 5);
      try {
        const captured = await admission.admit({ id, toolName: "bash", input, signal, ctx });
        const ticket = validateAdmission(captured);
        // 不传正文，也不调用原SDK execute，避免独立临时日志与非受管执行。
        const result = await executeShellOperation({ supervisor, ticket, signal, onUpdate: update ? preview => {
          const bounded = display(preview.text, preview.truncated);
          update({ content: [{ type: "text", text: bounded.text }], details: { truncated: bounded.truncated, terminationConfirmed: false } });
        } : undefined });
        if (result.terminationConfirmed !== true || !Number.isInteger(result.exitCode) || typeof result.output !== "string") reject("ORDINARY_SHELL_EVIDENCE", 5);
        const bounded = display(result.output, result.truncated);
        return { content: [{ type: "text", text: bounded.text }], isError: result.exitCode !== 0,
          details: { exitCode: result.exitCode, truncated: bounded.truncated, terminationConfirmed: true } };
      } catch (error) {
        if (isProtocolError(error)) throw error;
        reject("ORDINARY_SHELL_FAILED", 5);
      }
    },
  };
}
