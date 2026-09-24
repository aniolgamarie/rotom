// 保留锁定SDK的read/write/edit语义；实际IO和写入生命周期交由监督者。
import { searchText } from "./regex-search.ts";
import { createHash, randomUUID } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { privateBytes, privateFile } from "./launch.ts";
import { canonical, reject } from "./managed-types.ts";
import { isBoundWebTool } from "./web-tools.ts";
import { isBoundMcpTool } from "./mcp-tools.ts";
import { readseekToolNames } from "./readseek-controller.ts";

export class OrdinaryOperations {
  constructor(sdk, runtime, { mime = () => null, pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)) } = {}) {
    this.sdk = sdk; this.runtime = runtime; this.supervisor = runtime.supervisor; this.mime = mime; this.pause = pause;
  }
  async preflight(event, ctx, _snapshot, roleId = "main") {
    if (readseekToolNames.has(event.toolName)) {
      if (!this.runtime.readseek) reject("READSEEK_EXECUTOR_UNAVAILABLE", 5);
      return this.runtime.readseek.prepare(event, ctx, roleId);
    }
    if (isBoundMcpTool(this.runtime, event.toolName) || isBoundWebTool(this.runtime, event.toolName)) {
      if (roleId !== "main") reject("ROLE_CEILING", 4);
      return { kind: "service", tool_name: event.toolName };
    }
    const services = { kernel_task: "task-keeper", model_delegate: "model-delegate", Agent: "pi-subagents",
      get_subagent_result: "pi-subagents", steer_subagent: "pi-subagents", smart_compact: "pi-smart-compact",
      mcp: "pi-mcp", mcpScript: "pi-mcp", smart_recall: "pi-smart-compact", smart_save_memory: "pi-smart-compact", process: "pi-processes" };
    if (Object.hasOwn(services, event.toolName)) {
      if (roleId !== "main" || !this.runtime.manifest.plugins.includes(services[event.toolName])) reject("ROLE_CEILING", 4);
      if (event.toolName === "mcpScript" && this.runtime.manifest.options.mcp?.scripting?.enabled !== true) reject("MCP_SCRIPT_NOT_SELECTED", 4);
      return { kind: "service", tool_name: event.toolName };
    }
    if (["bash", "editor"].includes(event.toolName)) return this.supervisor.call("ordinary_command_prepare", {
      operation_id: randomUUID(), role_id: roleId, cwd: ctx.cwd, tool_name: event.toolName, input: event.input });
    if (!["read", "write", "edit", "rename", "ls", "find", "grep"].includes(event.toolName)) reject("ORDINARY_TOOL_NOT_BOUND", 5);
    const ticket = await this.supervisor.call("ordinary_prepare", { operation_id: randomUUID(), role_id: roleId, cwd: ctx.cwd,
      tool_name: event.toolName, input: event.input });
    return { ...ticket, kind: "file", tool_name: event.toolName };
  }
  async abort(ticket) {
    if (ticket.kind === "readseek") return this.runtime.readseek.abort(ticket);
    if (ticket.kind === "service") return;
    if (ticket.write || ticket.kind === "command") {
      const observed = await this.supervisor.call("inspect", { lease_id: ticket.lease_id });
      await this.supervisor.call(observed.state === "allocating" ? "abort_allocation" : "cancel", { lease_id: ticket.lease_id });
    }
    await this.supervisor.call(ticket.kind === "command" ? "ordinary_command_finish" : "ordinary_finish", { operation_id: ticket.operation_id }).catch(() => {});
  }
  async read(ticket, path, relativePath = null) {
    if (resolve(path) !== ticket.path) reject("ORDINARY_OPERATION_PATH", 4);
    const chunks = []; let offset = 0, total, checksum;
    do {
      const value = await this.supervisor.call("ordinary_read", { operation_id: ticket.operation_id, offset, limit: 65536, ...(relativePath === null ? {} : { relative_path: relativePath }) });
      checksum ??= value.content_digest; total ??= value.total_bytes;
      if (value.content_digest !== checksum || value.total_bytes !== total || total > 16 * 1024 * 1024) reject("FILE_CHANGED", 4);
      const bytes = Buffer.from(value.data_b64, "base64");
      if (!bytes.length && offset < total) reject("FILE_RESPONSE_INVALID", 5);
      chunks.push(bytes); offset += bytes.length;
    } while (offset < total);
    return { bytes: Buffer.concat(chunks), digest: checksum };
  }
  async write(ticket, content, expectedDigest, signal, callbacks = {}) {
    const entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")];
    if (!entry?.manager) { await this.abort(ticket); reject("CAPABILITY_MISSING", 5); }
    if (signal?.aborted) { await this.abort(ticket); reject("GRANT_REVOKED", 4); }
    if (ticket.tool_name !== "rename" && !["command", "checkpoint"].includes(ticket.kind)) await this.supervisor.call("ordinary_stage_write", { operation_id: ticket.operation_id, content, expected_digest: expectedDigest });
    const id = "file-" + randomUUID(), manager = entry.manager;
    ticket.manager_run_id = id;
    let accept, fail, canceled = false, failureSettled = false;
    const outcome = new Promise((resolve, reject) => { accept = resolve; fail = reject; });
    const cancel = async () => {
      canceled = true; await this.abort(ticket);
      const proof = await this.supervisor.call("reconcile", { lease_id: ticket.lease_id });
      if (proof.lease_id === ticket.lease_id && !proof.protected && proof.termination_evidence?.verified) {
        failureSettled = true;
        fail(new Error("ORDINARY_OPERATION_CANCELED"));
        return { terminal_status: "canceled", response_text: "", termination_confirmed: true, external_work_empty: true };
      }
      return undefined;
    };
    const execute = async () => {
      try {
        if (canceled) return cancel();
        const launched = await this.supervisor.call("start", { lease_id: ticket.lease_id, program: ticket.kind === "checkpoint" ? "checkpoint" : ticket.kind === "command" ? "ordinary-command" : "file-operation", payload: { operation_id: ticket.operation_id } });
        if (launched.state !== "running") reject("START_UNKNOWN", 4);
        if (callbacks.onStarted) await callbacks.onStarted(await this.supervisor.call("inspect", { lease_id: ticket.lease_id }));
        const deadline = Date.now() + (["command", "checkpoint"].includes(ticket.kind) ? ticket.timeout_seconds * 1000 : 30000);
        while (Date.now() < deadline) {
          const proof = await this.supervisor.call("reconcile", { lease_id: ticket.lease_id });
          if (proof.lease_id === ticket.lease_id && !proof.protected && proof.termination_evidence?.verified) {
            const root = dirname(dirname(dirname(this.supervisor.options.endpoint)));
            const exit = JSON.parse(privateFile(join(root, "activity/exits", ticket.lease_id + ".json")));
            if (ticket.kind === "command") {
              const directory = join(root, "activity/outputs", ticket.lease_id), capture = JSON.parse(privateFile(join(directory, "capture.json")));
              if (exit.lease_id !== ticket.lease_id || exit.process_identity === undefined || canonical(exit.process_identity) !== canonical(proof.process_identity)
                  || capture.complete !== true) reject("ORDINARY_OPERATION_EVIDENCE", 5);
              const stdout = privateBytes(join(directory, "stdout")), stderr = privateBytes(join(directory, "stderr"));
              for (const [name, body] of [["stdout", stdout], ["stderr", stderr]]) if (createHash("sha256").update(body).digest("hex") !== capture.streams[name].sha256) reject("ORDINARY_OPERATION_EVIDENCE", 5);
              callbacks.onCapture?.({ stdout, stderr });
              accept({ stdout: stdout.toString("utf8"), stderr: stderr.toString("utf8"), exitCode: exit.exit_code, truncated: capture.truncated, terminationConfirmed: true });
              return { terminal_status: exit.exit_code === 0 ? "completed" : "failed", response_text: "Bound command ended", termination_confirmed: true, external_work_empty: true };
            }
            const result = JSON.parse(privateFile(join(root, "activity/ordinary-results", ticket.operation_id + ".json")));
            if (ticket.kind === "checkpoint") {
              if (exit.lease_id !== ticket.lease_id || !exit.process_identity || !proof.process_identity || canonical(exit.process_identity) !== canonical(proof.process_identity)
                  || result.lease_id !== ticket.lease_id || result.operation_id !== ticket.operation_id
                  || !["completed", "partial"].includes(result.result.status)
                  || (result.result.status === "completed" ? exit.exit_code !== 0 : exit.exit_code !== 5)) reject("CHECKPOINT_EVIDENCE", 5);
              accept(result.result);
              return { terminal_status: result.result.status === "completed" ? "completed" : "failed", response_text: "Code checkpoint operation ended", termination_confirmed: true, external_work_empty: true };
            }
            if (exit.lease_id !== ticket.lease_id || exit.exit_code !== 0 || result.lease_id !== ticket.lease_id
                || result.operation_id !== ticket.operation_id) reject("ORDINARY_OPERATION_EVIDENCE", 5);
            accept(result.result);
            return { terminal_status: "completed", response_text: JSON.stringify(result.result), termination_confirmed: true, external_work_empty: true };
          }
          await this.pause(25);
        }
        await cancel(); reject("TERMINATION_UNKNOWN", 4);
      } catch (error) {
        try {
          const observed = await this.supervisor.call("inspect", { lease_id: ticket.lease_id });
          if (observed.state === "allocating") await this.supervisor.call("abort_allocation", { lease_id: ticket.lease_id });
          const proof = await this.supervisor.call("reconcile", { lease_id: ticket.lease_id });
          if (proof.lease_id === ticket.lease_id && !proof.protected && proof.termination_evidence?.verified) {
            failureSettled = true;
            return { terminal_status: "failed", response_text: "", termination_confirmed: true, external_work_empty: true };
          }
        } finally { fail(error); }
        throw error;
      }
    };
    const onAbort = () => { manager.abort(id); };
    signal?.addEventListener("abort", onAbort, { once: true });
    try {
      manager.spawnWithExecutor(entry.pi, entry.getContext(), ticket.execution_class === "service" ? "mcp-service" : "file-operation", "ORDINARY_FILE_OPERATION", { kind: ticket.execution_class === "service" ? "resource" : "external",
        ...(ticket.execution_class === "service" ? {} : { activity: "io" }), manager_run_id: id, execute, cancel },
        { description: ticket.service_name ?? ticket.tool_name, cwd: join(this.runtime.instanceRoot, "user-home"), isBackground: true });
      const result = await outcome;
      await manager.getRecord(id)?.promise;
      if (manager.getRecord(id) && !["running", "queued"].includes(manager.getRecord(id).status)) { manager.consumeControlled(id); manager.removeConsumedControlled(id); }
      return result;
    } catch (error) {
      await this.abort(ticket).catch(() => {});
      throw error;
    } finally {
      signal?.removeEventListener("abort", onAbort);
      if (failureSettled && manager.getRecord(id)) {
        await manager.getRecord(id).promise;
        manager.consumeControlled(id); manager.removeConsumedControlled(id);
      }
    }
  }
  tools(cwd, roleId = "main") {
    const factories = { read: this.sdk.createReadToolDefinition, write: this.sdk.createWriteToolDefinition, edit: this.sdk.createEditToolDefinition };
    const files = Object.entries(factories).map(([name, factory]) => {
      const definition = factory(cwd);
      return { ...definition, execute: async (id, input, signal, update, ctx) => {
        const ticket = roleId === "main" ? this.runtime.permissionAccess.take(id, name, input, ctx)
          : await this.preflight({ toolCallId: id, toolName: name, input }, ctx, this.runtime.permissionAccess.require(), roleId);
        let baseline;
        const read = async path => { const value = await this.read(ticket, path); baseline = value.digest; return value.bytes; };
        const operations = { access: async path => { if (resolve(path) !== ticket.path) reject("ORDINARY_OPERATION_PATH", 4); }, readFile: read,
          detectImageMimeType: async path => this.mime(await read(path)), mkdir: async () => {},
          writeFile: async (path, content) => { if (resolve(path) !== ticket.path) reject("ORDINARY_OPERATION_PATH", 4); await this.write(ticket, content, name === "edit" ? baseline : null, signal); } };
        try { return await factory(ctx.cwd, { operations }).execute(id, input, signal, update, ctx); }
        catch (error) { if (ticket.write) await this.abort(ticket).catch(() => {}); throw error; }
        finally { await this.supervisor.call("ordinary_finish", { operation_id: ticket.operation_id }).catch(() => {}); }
      } };
    });
    for (const name of ["bash", "editor"]) {
      const definition = name === "bash" && this.sdk.createBashToolDefinition ? this.sdk.createBashToolDefinition(cwd) : {
        name, label: "Bound editor", parameters: { type: "object", properties: { command: { type: "string", minLength: 1 }, timeout: { type: "integer", minimum: 1 } }, required: ["command"], additionalProperties: false } };
      files.push({ ...definition, description: "Execute a configured foreground command as agentcfg:COMMAND_ID (or its exact bound argv). The command needs explicit command_ref permission and declared filesystem roots; arbitrary shell expressions are rejected.",
        execute: async (id, input, signal, _update, ctx) => {
          const ticket = roleId === "main" ? this.runtime.permissionAccess.take(id, name, input, ctx)
            : await this.preflight({ toolCallId: id, toolName: name, input }, ctx, this.runtime.permissionAccess.require(), roleId);
          try {
            const result = await this.write(ticket, null, null, signal), output = result.stdout + (result.stderr ? "\n" + result.stderr : "");
            const truncated = result.truncated || output.length > 8192;
            return { content: [{ type: "text", text: output.slice(0, 8192) + (truncated ? "\n[Output truncated.]" : "") || "Command produced no output." }],
              details: { exitCode: result.exitCode, truncated, terminationConfirmed: result.terminationConfirmed }, isError: result.exitCode !== 0 };
          } catch (error) { await this.abort(ticket).catch(() => {}); throw error; }
          finally { await this.supervisor.call("ordinary_command_finish", { operation_id: ticket.operation_id }).catch(() => {}); }
        } });
    }
    files.push({ name: "rename", label: "Rename file", description: "Rename one authorized file without overwriting an existing destination. Both paths require rename permission and workspace leases.",
      parameters: { type: "object", properties: { path: { type: "string", minLength: 1 }, destination: { type: "string", minLength: 1 } }, required: ["path", "destination"], additionalProperties: false },
      execute: async (id, input, signal, _update, ctx) => {
        const ticket = roleId === "main" ? this.runtime.permissionAccess.take(id, "rename", input, ctx)
          : await this.preflight({ toolCallId: id, toolName: "rename", input }, ctx, this.runtime.permissionAccess.require(), roleId);
        try {
          await this.write(ticket, null, null, signal);
          return { content: [{ type: "text", text: "File renamed." }], details: {} };
        } catch (error) { await this.abort(ticket).catch(() => {}); throw error; }
        finally { await this.supervisor.call("ordinary_finish", { operation_id: ticket.operation_id }).catch(() => {}); }
      } });
    for (const [name, factory] of [["ls", this.sdk.createLsToolDefinition], ["find", this.sdk.createFindToolDefinition]]) {
      if (!factory) continue;
      const definition = factory(cwd);
      files.push({ ...definition, description: name === "find" ? "Find authorized files by glob, honoring local .gitignore rules; Git metadata is excluded." : definition.description, execute: async (id, input, _signal, _update, ctx) => {
        const ticket = roleId === "main" ? this.runtime.permissionAccess.take(id, name, input, ctx)
          : await this.preflight({ toolCallId: id, toolName: name, input }, ctx, this.runtime.permissionAccess.require(), roleId);
        try {
          const result = await this.supervisor.call("ordinary_list", { operation_id: ticket.operation_id });
          const text = result.entries.map(row => row.path + (row.directory ? "/" : "")).join("\n") + (result.truncated ? "\n[Results truncated; narrow the scope.]" : "");
          return { content: [{ type: "text", text: text || "No matching entries." }], details: { truncated: result.truncated } };
        } finally { await this.supervisor.call("ordinary_finish", { operation_id: ticket.operation_id }).catch(() => {}); }
      } });
    }
    if (this.sdk.createGrepToolDefinition) {
      const definition = this.sdk.createGrepToolDefinition(cwd);
      files.push({ ...definition, description: "Search authorized files using literal text or bounded JavaScript regular expressions. Narrow the path when the scan is truncated.",
        execute: async (id, input, signal, _update, ctx) => {
          const ticket = roleId === "main" ? this.runtime.permissionAccess.take(id, "grep", input, ctx)
            : await this.preflight({ toolCallId: id, toolName: "grep", input }, ctx, this.runtime.permissionAccess.require(), roleId);
          try {
            const listing = await this.supervisor.call("ordinary_list", { operation_id: ticket.operation_id });
            const result = []; const limit = input.limit ?? 100;
            for (const file of listing.entries) {
              if (signal?.aborted) reject("GRANT_REVOKED", 4);
              if (result.length >= limit) break;
              const read = await this.read(ticket, ticket.path, file.path);
              let text; try { text = new TextDecoder("utf8", { fatal: true }).decode(read.bytes); } catch { continue; }
              const matches = await searchText({ pattern: input.pattern, literal: input.literal === true, ignoreCase: input.ignoreCase === true,
                context: input.context ?? 0, limit: limit - result.length, text });
              result.push(...matches.map(match => ({ path: file.path ?? ticket.path, ...match })));
            }
            const truncated = listing.truncated || result.length >= limit;
            return { content: [{ type: "text", text: result.map(row => row.path + ":" + row.line + ": " + row.text).join("\n")
              + (truncated ? "\n[Search truncated; narrow the scope.]" : "") || "No matches." }], details: { truncated, matches: result.length } };
          } finally { await this.supervisor.call("ordinary_finish", { operation_id: ticket.operation_id }).catch(() => {}); }
        } });
    }
    return files;
  }
  install(pi, cwd) { for (const tool of this.tools(cwd)) pi.registerTool(tool); }
}
