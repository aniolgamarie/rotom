// 复用原stdio协议/分块；服务进程由原supervisor账本负责，不依赖Task Keeper manager。
import { dirname, isAbsolute, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { BoundStdioTransport } from "./mcp-stdio.ts";
import { verifyCommandOutput } from "./shell-operation-executor.ts";
import { captureOperationInput } from "./private-operation-input.ts";

const errors = new WeakSet();
const fail = (code = "MCP_STDIO_UNAVAILABLE") => { const error = new Error(code); error.code = code; error.exitCode = 4; errors.add(error); throw error; };
const id = value => typeof value === "string" && /^[A-Za-z0-9_-]{1,200}$/.test(value);
const copy = value => captureOperationInput(value).value;
const identity = value => {
  const keys = ["platform", "boot_id", "pid", "ppid", "pgid", "start_time", "namespace", "uid"];
  if (!value || !isDeepStrictEqual(Object.keys(value).sort(), keys.sort()) || !["linux", "darwin"].includes(value.platform)
      || !["boot_id", "start_time"].every(key => typeof value[key] === "string" && value[key])
      || !["pid", "pgid"].every(key => Number.isSafeInteger(value[key]) && value[key] > 0)
      || !["ppid", "uid"].every(key => Number.isSafeInteger(value[key]) && value[key] >= 0)
      || value.namespace !== null && (typeof value.namespace !== "string" || !value.namespace)) fail("MCP_STDIO_START_UNVERIFIED");
  return copy(value);
};

export function createOfficialMcpStdioTransport({ runtime, serverName, check }) {
  if (typeof runtime?.supervisor?.call !== "function" || typeof check !== "function" || !id(serverName)
      || typeof runtime.instanceRoot !== "string" || !isAbsolute(runtime.instanceRoot) || resolve(runtime.instanceRoot) !== runtime.instanceRoot) fail();
  const supervisor = runtime.supervisor, originalCall = supervisor.call, originalCheck = check;
  const endpoint = supervisor.options?.endpoint;
  if (typeof endpoint !== "string" || !isAbsolute(endpoint) || resolve(endpoint) !== endpoint
      || /[\u0000-\u001f\u007f]/.test(endpoint) || !endpoint.endsWith("/activity/control/control.json")) fail("MCP_STDIO_SUPERVISOR_UNBOUND");
  const activityRoot = dirname(dirname(dirname(endpoint)));
  const listeners = Object.fromEntries(["Message", "Error", "Close"].map(name => [name, new Set()]));
  let bound, closed = false, starting, closing, preparing, launching, prepareAttempted = false, closeEmitted = false, jobError;
  const records = new Map();
  const current = () => {
    if (closed) fail("MCP_STDIO_CLOSED");
    try { const value = originalCheck(); if (value && typeof value.then === "function") { if (value instanceof Promise) value.catch(() => {}); fail(); } }
    catch (error) { if (errors.has(error)) throw error; fail("MCP_STDIO_CONTEXT_INVALID"); }
  };
  const normalize = (error, code) => errors.has(error) ? error : (() => { try { fail(code); } catch (fixed) { return fixed; } })();
  const ticket = (value, execution = true) => {
    if (!value || value.kind !== "command" || !id(value.operation_id) || !id(value.lease_id)
        || execution && (value.execution_class !== "service" || value.service_name !== serverName || value.tool_name !== "bash"
          || value.command_ref !== bound.binding().selected.command_ref || !Number.isSafeInteger(value.timeout_seconds) || value.timeout_seconds < 1)) fail("MCP_STDIO_TICKET_INVALID");
    let record = records.get(value.lease_id);
    if (!record) { record = { ticket: value, generation: undefined, process: null, cancelAttempted: false, settling: undefined }; records.set(value.lease_id, record); }
    if (record.ticket.operation_id !== value.operation_id) fail("MCP_STDIO_TICKET_INVALID");
    return record;
  };
  const done = proof => proof.protected === false && proof.termination_evidence?.verified === true
    && proof.termination_evidence.execution_lease_id === proof.lease_id
    && proof.termination_evidence.kind === (proof.spawn_committed ? "terminated" : "never-started");
  const observe = (record, value, revoke = false) => {
    if (value?.lease_id !== record.ticket.lease_id || value.attempt_id !== record.ticket.operation_id || value.task_id !== null
        || !Number.isSafeInteger(value.grant_generation) || value.grant_generation < 1 || typeof value.spawn_committed !== "boolean"
        || typeof value.protected !== "boolean") fail("MCP_STDIO_TERMINATION_UNKNOWN");
    record.generation ??= value.grant_generation;
    record.initialGeneration ??= value.grant_generation;
    if (value.grant_generation !== record.generation) {
      if (!revoke || value.grant_generation !== record.initialGeneration + 1 || record.generation !== record.initialGeneration || value.state !== "cancel_requested" && !done(value)) fail("MCP_STDIO_TERMINATION_UNKNOWN");
      record.generation = value.grant_generation;
    }
    if (value.process_identity !== null) {
      const process = identity(value.process_identity);
      if (record.process && !isDeepStrictEqual(record.process, process)) fail("MCP_STDIO_TERMINATION_UNKNOWN");
      record.process ??= process;
    } else if (record.process || value.spawn_committed) fail("MCP_STDIO_TERMINATION_UNKNOWN");
    return value;
  };
  const rpc = async (method, args, cleanup = false) => {
    if (!cleanup) current();
    if (!cleanup && method === "ordinary_command_stdin") {
      const record = ticket(bound.ticket), proof = observe(record, await rpc("inspect", { lease_id: record.ticket.lease_id }));
      if (proof.state !== "running" || proof.spawn_committed !== true || proof.process_status !== "alive") fail("MCP_STDIO_TERMINATION_UNKNOWN");
    }
    try {
      const pending = Promise.resolve(originalCall.call(supervisor, method, args));
      if (method === "ordinary_mcp_stdio_prepare") { prepareAttempted = true; preparing = pending; }
      if (method === "start") launching = pending;
      const value = await pending;
      // prepare回执在取消/检查之前登记，close能等待并清理迟到lease。
      if (method === "ordinary_mcp_stdio_prepare") bound.ticket = copy(value);
      if (!cleanup) current();
      return value;
    } catch (error) {
      if (method === "ordinary_command_stdin" && error?.message === "ORDINARY_STDIN_BACKPRESSURE") throw Error("ORDINARY_STDIN_BACKPRESSURE");
      throw normalize(error, "MCP_STDIO_SUPERVISOR_FAILED");
    }
  };
  const receipts = (record, proof) => {
    if (!proof.spawn_committed) return null; // 原never-started分配无进程退出/capture收据。
    try { return verifyCommandOutput(activityRoot, record.ticket.lease_id, proof); }
    catch { fail("MCP_STDIO_EVIDENCE_INVALID"); }
  };
  const settle = value => {
    const record = ticket(value, false);
    if (record.settling) return record.settling;
    record.settling = (async () => {
      let proof = observe(record, await rpc("reconcile", { lease_id: value.lease_id }, true), true);
      if (!done(proof)) {
        record.cancelAttempted = true;
        const method = proof.state === "allocating" && proof.spawn_committed === false ? "abort_allocation" : "cancel";
        try { await rpc(method, { lease_id: value.lease_id }, true); } catch {} // 不重发；只由同lease事实对账。
        for (let count = 0; count < 100; count++) {
          proof = observe(record, await rpc("reconcile", { lease_id: value.lease_id }, true), true);
          if (done(proof)) break;
          if (proof.state === "unknown") fail("MCP_STDIO_TERMINATION_UNKNOWN");
          await bound.pause(50);
        }
      }
      if (!done(proof)) fail("MCP_STDIO_TERMINATION_UNKNOWN");
      receipts(record, proof);
      await rpc("ordinary_command_finish", { operation_id: value.operation_id }, true);
      return proof;
    })();
    return record.settling;
  };
  const operations = { abort: settle, async write(value, _content, _digest, _signal, callbacks) {
    const record = ticket(value);
    try {
      let proof = observe(record, await rpc("inspect", { lease_id: value.lease_id }));
      if (proof.state !== "allocating" || proof.spawn_committed !== false || proof.process_identity !== null) fail("MCP_STDIO_START_UNVERIFIED");
      try {
        const ack = await rpc("start", { lease_id: value.lease_id, program: "ordinary-command", payload: { operation_id: value.operation_id } });
        if (ack?.lease_id !== value.lease_id || ack.state !== "running") fail("MCP_STDIO_START_UNVERIFIED");
      } catch {} // 一次start已尝试，丢ACK仅inspect，不能重发。
      proof = observe(record, await rpc("inspect", { lease_id: value.lease_id }));
      if (proof.state !== "running" || proof.spawn_committed !== true || proof.process_status !== "alive" || !proof.process_identity) fail("MCP_STDIO_START_UNVERIFIED");
      callbacks.onStarted(proof);
      const deadline = Date.now() + value.timeout_seconds * 1000;
      while (!closed && Date.now() < deadline) {
        proof = observe(record, await rpc("reconcile", { lease_id: value.lease_id }));
        if (done(proof)) { const result = receipts(record, proof); if (!result) fail("MCP_STDIO_EVIDENCE_INVALID"); return result; }
        await bound.pause(50);
      }
      proof = await settle(value); const result = receipts(record, proof);
      if (!result) fail("MCP_STDIO_CLOSED"); return result;
    } catch (error) {
      jobError = normalize(error, "MCP_STDIO_SERVICE_FAILED");
      try { await settle(value); } catch (cleanup) { jobError = normalize(cleanup, "MCP_STDIO_TERMINATION_UNKNOWN"); }
      throw jobError;
    }
  } };
  class NativeBound extends BoundStdioTransport {
    binding() {
      current();
      if (runtime.owner?.role !== "manager" || !["pi-base", "pi-full"].includes(runtime.manifest?.profile_id)
          || runtime.manifest.bootstrap !== false || runtime.manifest.native_mcp?.schema_version !== 1
          || runtime.managedRequestScope?.getStore()) fail("MCP_STDIO_CONTEXT_INVALID");
      const selected = runtime.manifest.options.mcp?.servers?.[serverName], command = runtime.manifest.options.external_tools?.[selected?.command_ref];
      const root = runtime.manifest.options.paths?.roots?.[command?.project_root];
      if (selected?.transport !== "stdio" || !selected.command_ref || command?.interactive !== true || root?.purpose !== "project"
          || typeof root.path !== "string" || !isAbsolute(root.path) || resolve(root.path) !== root.path) fail("MCP_STDIO_BINDING_INVALID");
      return { selected, cwd: root.path };
    }
    async stop() {
      // 不等待this.start/readiness（会与stop循环等待）；只等实际创建/启动RPC的迟到回执。
      await preparing?.catch(() => {}); await launching?.catch(() => {});
      if (this.ticket) await settle(this.ticket);
      else if (prepareAttempted) fail("MCP_STDIO_TERMINATION_UNKNOWN");
      if (!closeEmitted) { closeEmitted = true; this.onclose?.(); }
    }
  }
  bound = new NativeBound({ ...runtime, supervisor: { call: rpc }, ordinaryOperations: operations }, serverName);
  const dispatch = (name, args, receiver) => {
    if (closed && name !== "Close") return;
    for (const listener of listeners[name]) listener.apply(receiver, args);
  };
  bound.onmessage = function (...args) { dispatch("Message", args, this); };
  bound.onerror = function (error) {
    dispatch("Error", [jobError ?? normalize(null, error?.message === "MCP_SERVICE_FAILED" ? "MCP_STDIO_SERVICE_FAILED" : "MCP_STDIO_OUTPUT_INVALID")], this);
  };
  bound.onclose = function () { dispatch("Close", [], this); };
  const close = () => {
    if (closing) return closing;
    closed = true;
    closing = bound.close().catch(error => { throw normalize(error, "MCP_STDIO_TERMINATION_UNKNOWN"); });
    return closing;
  };
  const facade = { async start() {
    current(); if (starting) fail("MCP_STDIO_ALREADY_STARTED");
    starting = bound.start();
    try { await starting; current(); }
    catch (error) { try { await close(); } catch (cleanup) { throw normalize(cleanup, "MCP_STDIO_TERMINATION_UNKNOWN"); } throw normalize(error, "MCP_STDIO_START_UNVERIFIED"); }
  }, async send(message) {
    current();
    try { await bound.send(captureOperationInput(message, { allowFiniteNumbers: true, maxBytes: 1024 * 1024 - 1 }).value); current(); }
    catch (error) { throw normalize(error, "MCP_STDIO_SEND_FAILED"); }
  }, close };
  for (const name of ["Message", "Error", "Close"]) facade["on" + name] = listener => {
    current(); if (typeof listener !== "function") fail(); listeners[name].add(listener); return () => listeners[name].delete(listener);
  };
  return Object.freeze(facade);
}
