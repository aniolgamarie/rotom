// 工具只发送封闭文件操作；IO 在 supervisor 固定的目录句柄内完成。
import { randomUUID } from "node:crypto";
import { closed, digest, reject, sha, text } from "./managed-types.ts";

const string = { type: "string", minLength: 1 };
const object = (properties, required = Object.keys(properties)) => ({ type: "object", properties, required, additionalProperties: false });
const reply = (value, details = {}) => ({ content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value) }], details });

export function createGuardedTools({ descriptor, context, supervisor, submitResult }) {
  const request = (action, operation_id = randomUUID()) => supervisor.call("file_action", {
    lease_id: context.lease_id, grant_generation: descriptor.grant_generation, operation_id, action });
  const read = async (tool, path, offset = 0, limit = 65536) => {
    const value = await request({ tool_id: tool, operation: "read", path, offset, limit });
    closed(value, ["data_b64", "offset", "total_bytes", "content_digest"],
      ["root_ref", "relative_path", "first_line", "last_line", "artifact_id", "artifact_source", "artifact_snapshot"]);
    if (value.offset !== offset || !Number.isSafeInteger(value.total_bytes) || value.total_bytes < 0) reject("FILE_RESPONSE_INVALID", 5);
    return { ...value, bytes: Buffer.from(value.data_b64, "base64") };
  };
  const mutationReply = async (action, operation) => {
    const value = await request(action, operation);
    if (!sha(value.candidate_digest) || !Number.isSafeInteger(value.mutation_sequence) || value.mutation_sequence < 1) reject("MUTATION_EVIDENCE_MISSING", 5);
    return reply(value, { candidate_digest: value.candidate_digest, mutation_sequence: value.mutation_sequence });
  };
  const definitions = {
    tk_read: { description: "Read authorized UTF-8 text in byte ranges; use next_offset when truncated.",
      parameters: object({ path: string, offset: { type: "integer", minimum: 0 }, limit: { type: "integer", minimum: 1, maximum: 65536 } }, ["path"]),
      async execute(id, args) {
        closed(args, ["path"], ["offset", "limit"]);
        const value = await read("tk_read", args.path, args.offset ?? 0, args.limit ?? 65536);
        let content;
        try { content = new TextDecoder("utf-8", { fatal: true }).decode(value.bytes); } catch { reject("FILE_NOT_UTF8_RANGE", 2); }
        const prefix = value.artifact_id ? `Artifact ${value.artifact_id} (source=${value.artifact_source}, snapshot=${value.artifact_snapshot})\n` : "";
        return reply(prefix + content, { content_digest: value.content_digest, total_bytes: value.total_bytes,
          read: { kind: value.artifact_id ? "artifact" : "file", artifact_id: value.artifact_id ?? null,
            root_ref: value.root_ref ?? null, path: value.relative_path ?? null, first_line: value.first_line ?? null, last_line: value.last_line ?? null,
            start: value.offset, end: value.offset + value.bytes.length, total: value.total_bytes },
          next_offset: value.offset + value.bytes.length < value.total_bytes ? value.offset + value.bytes.length : null });
      } },
    tk_ls: { description: "List authorized files and directories; symbolic links and Git metadata are excluded.", parameters: object({ path: string }),
      async execute(id, args) { closed(args, ["path"]); return reply(await request({ tool_id: "tk_ls", operation: "list", path: args.path })); } },
    tk_find: { description: "Find authorized file paths containing literal text, with bounded results.", parameters: object({ path: string, query: string }),
      async execute(id, args) { closed(args, ["path", "query"]); return reply(await request({ tool_id: "tk_find", operation: "search", path: args.path, query: args.query, kind: "find" })); } },
    tk_grep: { description: "Search authorized UTF-8 files for literal text; returned lines carry path and line number.", parameters: object({ path: string, query: string }),
      async execute(id, args) { closed(args, ["path", "query"]); return reply(await request({ tool_id: "tk_grep", operation: "search", path: args.path, query: args.query, kind: "grep" })); } },
    tk_write: { description: "Write a UTF-8 file inside the granted candidate roots through the supervisor.",
      parameters: object({ path: string, content: { type: "string", maxLength: 65536 } }),
      async execute(id, args) {
        closed(args, ["path", "content"]);
        return mutationReply({ tool_id: "tk_write", operation: "write", path: args.path,
          data_b64: Buffer.from(args.content, "utf8").toString("base64"), expected_digest: null }, digest({ attempt_id: descriptor.attempt_id, tool_call_id: id, operation: "write" }));
      } },
    tk_edit: { description: "Replace one unique literal match; changed files are rejected before writing.",
      parameters: object({ path: string, old_text: string, new_text: { type: "string", maxLength: 65536 } }),
      async execute(id, args) {
        closed(args, ["path", "old_text", "new_text"]);
        if (!text(args.old_text)) reject("EDIT_MATCH_INVALID", 2);
        const chunks = []; let offset = 0, expected, total;
        do {
          const value = await read("tk_edit", args.path, offset);
          expected ??= value.content_digest; total ??= value.total_bytes;
          if (value.content_digest !== expected || value.total_bytes !== total || total > 1024 * 1024
              || !value.bytes.length && offset < total) reject("FILE_CHANGED", 4);
          chunks.push(value.bytes); offset += value.bytes.length;
        } while (offset < total);
        let content;
        try { content = new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)); } catch { reject("FILE_NOT_UTF8", 2); }
        const at = content.indexOf(args.old_text);
        if (at < 0 || content.indexOf(args.old_text, at + args.old_text.length) !== -1) reject("EDIT_MATCH_NOT_UNIQUE", 2);
        const result = content.slice(0, at) + args.new_text + content.slice(at + args.old_text.length);
        return mutationReply({ tool_id: "tk_edit", operation: "write", path: args.path,
          data_b64: Buffer.from(result, "utf8").toString("base64"), expected_digest: expected }, digest({ attempt_id: descriptor.attempt_id, tool_call_id: id, operation: "edit" }));
      } },
    structured_output: { description: "Submit structured evidence for this attempt; schema acceptance does not prove project checks passed.",
      parameters: context.result_schema,
      async execute(id, args) {
        if (typeof submitResult !== "function") reject("RESULT_REPORTER_REQUIRED", 5);
        await submitResult(args, { tool_call_id: id, value_digest: digest(args) });
        return reply("Structured result recorded.");
      } },
  };
  return descriptor.allowed_tools.map(name => {
    if (!Object.hasOwn(definitions, name)) reject("WORKER_TOOLS_MISMATCH", 5);
    return { name, label: name, ...definitions[name] };
  });
}
