// 等级来自原受信prepared；human仅证明UI确认应答，模式由自有工厂固定。
import { randomUUID } from "node:crypto";
import { isAbsolute, resolve } from "node:path";
import { captureOperationInput } from "./private-operation-input.ts";
import { canonical, closed, digest, sha, reject, isProtocolError } from "./managed-types.ts";
import { validateOfficialFileResolution } from "./official-file-resolution.ts";

const errors = new Set(["OPERATION_ADMISSION_REQUIRED", "OPERATION_REQUEST_REPLAY", "OPERATION_CAPACITY", "OPERATION_CANCELED",
  "OPERATION_EXPIRED", "OPERATION_CONTEXT_STALE", "OPERATION_CONTROL_INVALID", "OPERATION_CONTROL_UNAVAILABLE",
  "OPERATION_BINDING_INVALID", "OPERATION_CONSUME_UNKNOWN", "OPERATION_INPUT_INVALID", "OPERATION_ADMISSION_FAILED", "PERMISSION_DENIED"]);
const tools = new Set(["read", "write", "edit", "rename", "ls", "find", "grep"]);
const text = value => typeof value === "string" && value.length > 0 && value.length <= 4096 && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
const identityKeys = ["operation_id", "write", "path", "request_digest"];
const identity = ticket => canonical(Object.fromEntries(identityKeys.map(key => [key, ticket[key]])));
function fileTicketShape(value) {
  closed(value, [...identityKeys, "lease_id", "state"]);
  if (!text(value.operation_id) || !text(value.path) || !sha(value.request_digest) || typeof value.write !== "boolean") reject("OPERATION_BINDING_INVALID", 4);
}

const shellIdentityKeys = ["operation_id", "kind", "tool_name", "write", "timeout_seconds", "command_ref", "request_digest"];
const absolute = value => text(value) && isAbsolute(value) && resolve(value) === value;
const positive = value => Number.isSafeInteger(value) && value > 0;
const reference = value => typeof value === "string" && /^tool:[a-z][a-z0-9_-]{0,63}$/.test(value);
function shellTicketShape(value) {
  closed(value, [...shellIdentityKeys, "lease_id", "state"]);
  if (!/^[a-f0-9]{32}$/.test(value.operation_id) || value.kind !== "command" || value.tool_name !== "bash"
      || typeof value.write !== "boolean" || !positive(value.timeout_seconds) || !reference(value.command_ref)
      || !sha(value.request_digest)) reject("OPERATION_BINDING_INVALID", 4);
}
function shellResolution(prepared, context, policyDigest) {
  const r = prepared.resolution;
  closed(r, ["kind", "tool_name", "target", "read_roots", "write_roots", "workspace_keys", "network", "services", "backend", "policy"]);
  closed(r.target, ["command_ref", "executable", "timeout_ms"]);
  closed(r.target.executable, ["path", "device", "inode", "uid", "sha256"]);
  if (r.policy === null || typeof r.policy !== "object") reject("OPERATION_BINDING_INVALID", 4);
  const graded = Object.hasOwn(r.policy, "approval");
  closed(r.policy, ["generation", "policy_digest", "ceiling_digest", "hard_policy", "requires_human", ...(graded ? ["approval"] : [])]);
  const approval = graded ? r.policy.approval : "human";
  if (r.kind !== "shell-command" || r.tool_name !== "bash" || r.backend !== "linux-bwrap-v1" || r.network !== "deny"
      || !Array.isArray(r.services) || r.services.length !== 0 || r.policy.hard_policy !== "allow"
      || !["human", "reviewer", "deterministic-policy"].includes(approval) || r.policy.requires_human !== (approval === "human")
      || r.policy.generation !== context.policy_generation || r.policy.policy_digest !== policyDigest || !sha(r.policy.policy_digest) || !sha(r.policy.ceiling_digest)
      || !reference(r.target.command_ref) || !positive(r.target.timeout_ms) || r.target.timeout_ms % 1000 !== 0
      || !absolute(r.target.executable.path) || !sha(r.target.executable.sha256)
      || !["device", "inode", "uid"].every(key => Number.isSafeInteger(r.target.executable[key]) && r.target.executable[key] >= 0)
      || !Array.isArray(r.read_roots) || r.read_roots.length === 0 || !Array.isArray(r.write_roots)
      || !Array.isArray(r.workspace_keys) || !r.workspace_keys.every(sha) || new Set(r.workspace_keys).size !== r.workspace_keys.length
      || Boolean(r.write_roots.length) !== Boolean(r.workspace_keys.length)) reject("OPERATION_BINDING_INVALID", 4);
  for (const root of [...r.read_roots, ...r.write_roots]) {
    closed(root, ["path", "identity"]);
    if (!absolute(root.path) || !sha(root.identity)) reject("OPERATION_BINDING_INVALID", 4);
  }
  return approval;
}
const mcpActions = { list_resources: "list_mcp_resources", list_templates: "list_mcp_resource_templates",
  read_resource: "read_mcp_resource", tool_search: "tool_search" };
const mcpName = value => typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value) && !value.includes("__");
function mcpTicketShape(value) {
  closed(value, ["operation_id", "kind", "state"]);
  if (!/^[a-f0-9]{32}$/.test(value.operation_id) || value.kind !== "mcp") reject("OPERATION_BINDING_INVALID", 4);
}
function mcpResolution(prepared, context, policyDigest, input, manifest) {
  const r = prepared.resolution;
  closed(r, ["kind", "tool_name", "target", "read_roots", "write_roots", "workspace_keys", "network", "services", "backend", "policy"]);
  closed(r.target, ["server_names", "action", "name", "binding_digest"]);
  closed(r.policy, ["generation", "policy_digest", "ceiling_digest", "hard_policy", "requires_human", "approval"]);
  const names = r.target.server_names, selected = Object.keys(manifest.native_mcp?.bindings ?? {}).sort();
  const expected = input.server_name === null ? selected : [input.server_name];
  if (r.kind !== "mcp" || r.tool_name !== "mcp" || r.backend !== "native-mcp-v1"
      || !Array.isArray(names) || !names.length || names.length > 64 || !names.every(mcpName)
      || canonical(names) !== canonical(expected) || names.some(name => !selected.includes(name))
      || r.target.action !== input.action || r.target.name !== input.name || !sha(r.target.binding_digest)
      || !["tool", ...Object.keys(mcpActions)].includes(input.action)
      || input.action === "tool" && (names.length !== 1 || !manifest.native_mcp.allowed_tools[names[0]]?.includes(input.name))
      || input.action !== "tool" && input.name !== mcpActions[input.action]
      || input.action === "read_resource" && names.length !== 1
      || canonical(r.read_roots) !== "[]" || canonical(r.write_roots) !== "[]" || canonical(r.workspace_keys) !== "[]"
      || canonical(r.services) !== canonical(names.map(name => "mcp:" + name))
      || r.network !== (names.every(name => manifest.native_mcp.bindings[name].transport === "stdio") ? "deny" : "managed-route")
      || r.policy.hard_policy !== "allow" || !["human", "reviewer", "deterministic-policy"].includes(r.policy.approval)
      || r.policy.requires_human !== (r.policy.approval === "human") || r.policy.generation !== context.policy_generation
      || r.policy.policy_digest !== policyDigest || !sha(r.policy.ceiling_digest)) reject("OPERATION_BINDING_INVALID", 4);
  return r.policy.approval;
}
export function createOfficialFileAdmission(options) { return createOfficialAdmission(options, "file"); }
export function createOfficialShellAdmission(options) { return createOfficialAdmission(options, "shell"); }
export function createOfficialMcpAdmission(options) {
  const admission = createOfficialAdmission(options, "mcp");
  return Object.freeze({ retire: admission.retire, drain: admission.drain,
    invoke(request, execute) {
      if (typeof execute !== "function") reject("OPERATION_ADMISSION_REQUIRED", 4);
      return admission.admit({ id: request.id, toolName: "mcp", signal: request.signal, ctx: request.ctx,
        input: { server_name: request.server_name, action: request.action, name: request.name, arguments: request.input } }, execute);
    } });
}
function createOfficialAdmission({ supervisor, owner, manifest, sessionManager, cwd,
  configurationSnapshot, policySnapshot, timeoutMs = 60000, now = Date.now, monotonic = () => performance.now() }, mode) {
  const shell = mode === "shell", mcp = mode === "mcp";
  const ticketShape = mcp ? mcpTicketShape : shell ? shellTicketShape : fileTicketShape;
  const ticketIdentity = mcp ? value => value.operation_id : shell ? value => canonical(Object.fromEntries(shellIdentityKeys.map(key => [key, value[key]]))) : identity;
  if (typeof supervisor?.call !== "function" || !text(owner?.manager_activation_id) || !sha(owner?.runtime_identity)
      || !["pi-base", "pi-full"].includes(manifest?.profile_id) || typeof sessionManager?.getSessionId !== "function"
      || !text(cwd) || !isAbsolute(cwd) || resolve(cwd) !== cwd || typeof configurationSnapshot !== "function"
      || typeof policySnapshot !== "function" || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 300000
      || typeof now !== "function" || typeof monotonic !== "function") reject("OPERATION_CONTROL_INVALID", 2);
  const sessionId = sessionManager.getSessionId(), profile = manifest.profile_id;
  if (!text(sessionId)) reject("OPERATION_CONTROL_INVALID", 2);
  const activation = owner.manager_activation_id, runtime = owner.runtime_identity, controlId = randomUUID();
  const entries = new Map(), cleanups = new Set();
  let epoch = 0, retired = false, totalBytes = 0, opened, cleanupFailed = false;
  const raw = async (method, args, entry) => {
    let timer;
    try {
      // 完整系统树核验沿用原operation剩余预算，仍受30s transport界限；不重置deadline。
      const rpcLimit = shell && entry ? Math.max(1, Math.min(30000, timeoutMs, entry.deadline - now(), entry.monotonicDeadline - monotonic())) : Math.min(timeoutMs, 5000);
      return await Promise.race([Promise.resolve().then(() => supervisor.call(method, args)),
        new Promise((_, fail) => { timer = setTimeout(() => fail(new Error("timeout")), rpcLimit); })]);
    } catch (error) {
      // 原权威已经拒绝的操作，与未取得控制回执分开；其他内部错误仍只给固定失败。
      if (isProtocolError(error) && error.code === "PERMISSION_DENIED" && error.exitCode === 4) throw error;
      reject("OPERATION_CONTROL_UNAVAILABLE", 4);
    }
    finally { clearTimeout(timer); }
  };
  const track = promise => {
    const pending = promise.catch(() => { cleanupFailed = true; }).finally(() => cleanups.delete(pending));
    cleanups.add(pending);
  };
  const cancelRequest = entry => {
    if (entry.cancelQueued) return;
    entry.cancelQueued = true;
    track(raw("ordinary_admission_cancel_request", { control_id: controlId, request_id: entry.requestId }).then(result => {
      closed(result, ["request_id", "state"]);
      if (result.request_id !== entry.requestId || result.state !== "canceled") reject("OPERATION_CONTROL_UNAVAILABLE", 4);
    }));
  };
  const check = entry => {
    if (retired || entry.epoch !== epoch || entry.signal.aborted || entry.dialog.signal.aborted) reject("OPERATION_CANCELED", 4);
    if (now() >= entry.deadline || monotonic() >= entry.monotonicDeadline) reject("OPERATION_EXPIRED", 4);
    if (entry.ctx.cwd !== cwd || sessionManager.getSessionId() !== sessionId || entry.ctx.sessionManager?.getSessionId?.() !== sessionId) reject("OPERATION_CONTEXT_STALE", 4);
  };
  const wait = async (entry, promise) => {
    check(entry);
    let timer, abort;
    try {
      const value = await Promise.race([promise, new Promise((_, fail) => {
        timer = setTimeout(() => fail(new Error("OPERATION_EXPIRED")), Math.max(1, Math.min(entry.deadline - now(), entry.monotonicDeadline - monotonic())));
        abort = () => fail(new Error("OPERATION_CANCELED"));
        entry.dialog.signal.addEventListener("abort", abort, { once: true });
      })]);
      check(entry); return value;
    } finally { clearTimeout(timer); entry.dialog.signal.removeEventListener("abort", abort); }
  };
  const current = async entry => {
    const snapshot = await wait(entry, Promise.resolve().then(() => configurationSnapshot()));
    const policy = policySnapshot(); check(entry);
    if (!sha(snapshot?.configIdentity) || snapshot?.runtimeIdentity !== runtime || !sha(snapshot?.projectConstraintsDigest) || !sha(snapshot?.policyDigest)
        || !Number.isSafeInteger(policy?.generation) || policy.generation < 1 || policy.policy_digest !== snapshot.policyDigest) reject("OPERATION_CONTEXT_STALE", 4);
    return { activation_id: activation, profile, session_id: sessionId, role_id: "main", cwd,
      user_intent_ref: entry.intent, restrictions_digest: snapshot.projectConstraintsDigest, policy_generation: policy.generation,
      cancel_epoch: entry.epoch, runtime_identity: runtime, config_identity: snapshot.configIdentity,
      reviewer_identity: null, deadline_ms: entry.deadline };
  };
  const binding = (status, prepared, consumed) => {
    closed(status, ["admission", "execution"]); closed(status.admission, ["operation_id", "state"]);
    if (status.admission.operation_id !== prepared.operation_id || status.admission.state !== (consumed ? "consumed" : "prepared")) reject("OPERATION_CONSUME_UNKNOWN", 4);
    ticketShape(status.execution);
    if (!consumed && (status.execution.state !== "prepared" || !mcp && status.execution.lease_id !== null)) reject("OPERATION_BINDING_INVALID", 4);
    return status.execution;
  };
  const consumedTicket = (observed, expected) => {
    ticketShape(observed);
    if (observed.state !== "consumed" || !mcp && !text(observed.lease_id) || shell && !/^[a-f0-9]{32}$/.test(observed.lease_id) || ticketIdentity(observed) !== ticketIdentity(expected)) reject("OPERATION_CONSUME_UNKNOWN", 4);
    return mcp || shell ? { ...observed } : { ...observed, kind: "file" };
  };
  const cleanupKnown = async entry => {
    if (!entry.ticket) return;
    const ticket = entry.ticket;
    if (mcp) return; // cancel_request已经撤销同一账本；MCP没有独立Writer lease。
    if (!shell && !ticket.write) { await raw("ordinary_finish", { operation_id: ticket.operation_id }); return; }
    const observed = await raw("inspect", { lease_id: ticket.lease_id });
    if (observed?.lease_id !== ticket.lease_id) reject("OPERATION_CONSUME_UNKNOWN", 4);
    await raw(observed.state === "allocating" && observed.spawn_committed === false ? "abort_allocation" : "cancel", { lease_id: ticket.lease_id });
  };
  const admit = async ({ id, toolName, input, signal, ctx }, execute) => {
    if (retired) reject("OPERATION_CANCELED", 4);
    if (!text(id) || !(mcp ? toolName === "mcp" : shell ? toolName === "bash" : tools.has(toolName)) || !(signal instanceof AbortSignal)
        || ctx?.cwd !== cwd || ctx.sessionManager?.getSessionId?.() !== sessionId) reject("OPERATION_ADMISSION_REQUIRED", 4);
    if (entries.has(id)) reject("OPERATION_REQUEST_REPLAY", 4);
    if (entries.size >= 4096) reject("OPERATION_CAPACITY", 4);
    const captured = captureOperationInput(input, { allowFiniteNumbers: mcp }), bytes = Buffer.byteLength(JSON.stringify(captured.value), "utf8");
    if (mcp) {
      closed(captured.value, ["server_name", "action", "name", "arguments"]);
      if (!(captured.value.server_name === null || mcpName(captured.value.server_name)) || !mcpName(captured.value.name)
          || !captured.value.arguments || Object.getPrototypeOf(captured.value.arguments) !== Object.prototype) reject("OPERATION_INPUT_INVALID", 2);
    }
    if (shell && (typeof captured.value?.command !== "string" || captured.value.command.length === 0
        || captured.value.command.includes("\0") || /[\p{Cs}]/u.test(captured.value.command)
        || Buffer.byteLength(captured.value.command, "utf8") > 65536)) reject("OPERATION_INPUT_INVALID", 2);
    if (totalBytes + bytes > 32 * 1024 * 1024) reject("OPERATION_CAPACITY", 4);
    const entry = { requestId: randomUUID(), intent: randomUUID(), epoch, signal, ctx, dialog: new AbortController(),
      deadline: now() + timeoutMs, monotonicDeadline: monotonic() + timeoutMs };
    if (!Number.isSafeInteger(entry.deadline) || !Number.isFinite(entry.monotonicDeadline)) reject("OPERATION_CONTROL_INVALID", 2);
    let done; entry.done = new Promise(resolve => { done = resolve; }); entries.set(id, entry); totalBytes += bytes;
    const abort = () => { entry.dialog.abort(); cancelRequest(entry); };
    signal.addEventListener("abort", abort, { once: true });
    try {
      check(entry);
      const context = await current(entry);
      opened ??= raw("ordinary_admission_open", { control_id: controlId, session_id: sessionId }).then(result => {
        closed(result, ["control_id", "session_id", "state"]);
        if (result.control_id !== controlId || result.session_id !== sessionId || result.state !== "open") reject("OPERATION_CONTROL_UNAVAILABLE", 4);
      });
      await wait(entry, opened);
      const received = await wait(entry, raw("ordinary_admission_prepare", { control_id: controlId, request_id: entry.requestId, context, tool_name: toolName, input: captured.value }, entry));
      let prepared;
      try { prepared = captureOperationInput(received).value; }
      catch { reject("OPERATION_BINDING_INVALID", 4); }
      closed(prepared, ["schema_version", "operation_id", "request_id", "context", "resolution", "private_input_ref", "operation_digest"]);
      if (prepared.schema_version !== 1 || !text(prepared.operation_id) || prepared.request_id !== entry.requestId || !sha(prepared.operation_digest)
          || canonical(prepared.context) !== canonical(context)) reject("OPERATION_BINDING_INVALID", 4);
      let approval = "human";
      if (mcp) approval = mcpResolution(prepared, context, policySnapshot().policy_digest, captured.value, manifest);
      else if (shell) approval = shellResolution(prepared, context, policySnapshot().policy_digest);
      else {
        // 缺approval只兼容完整旧human投影；其它旧字段同样闭合核验，不能静默丢弃。
        approval = validateOfficialFileResolution(prepared.resolution, { toolName,
          policyGeneration: context.policy_generation, policyDigest: policySnapshot().policy_digest });
      }
      if (Object.hasOwn(prepared.resolution.policy, "approval")) {
        const { operation_digest, ...bound } = prepared;
        if (!/^[0-9a-f]{32}$/.test(prepared.operation_id) || typeof prepared.private_input_ref !== "string"
            || !/^[0-9a-f]{32}$/.test(prepared.private_input_ref)
            || operation_digest !== digest(bound)) reject("OPERATION_BINDING_INVALID", 4);
      }
      const expected = { ...binding(await wait(entry, raw("ordinary_admission_status", { operation_id: prepared.operation_id }, entry)), prepared, false) };
      let summary;
      if (mcp) {
        if (expected.operation_id !== prepared.operation_id) reject("OPERATION_BINDING_INVALID", 4);
        summary = "MCP servers: " + JSON.stringify(prepared.resolution.target.server_names)
          + "\nAction: " + captured.value.action + "\nName: " + captured.value.name
          + "\nArguments: " + JSON.stringify(captured.value.arguments) + "\nCwd: " + cwd;
      } else if (shell) {
        const r = prepared.resolution;
        if (expected.operation_id !== prepared.operation_id || expected.request_digest !== prepared.operation_digest
            || expected.command_ref !== r.target.command_ref || expected.timeout_seconds * 1000 !== r.target.timeout_ms
            || expected.write !== Boolean(r.write_roots.length)) reject("OPERATION_BINDING_INVALID", 4);
        // 正文仅用于本次受信确认，转义控制字符；不写入ticket或公开摘要。
        summary = "Tool: bash\nCommand: " + JSON.stringify(captured.value.command) + "\nCwd: " + cwd
          + "\nRead roots: " + JSON.stringify(r.read_roots.map(root => root.path))
          + "\nWrite roots: " + JSON.stringify(r.write_roots.map(root => root.path)) + "\nTimeout seconds: " + expected.timeout_seconds;
      } else {
        if (expected.path !== prepared.resolution.target.path || expected.write !== ["write", "edit", "rename"].includes(toolName)) reject("OPERATION_BINDING_INVALID", 4);
        summary = "Tool: " + toolName + "\nPath: " + prepared.resolution.target.path + "\nCwd: " + cwd
          + (prepared.resolution.target.destination === null ? "" : "\nDestination: " + prepared.resolution.target.destination);
      }
      const deterministic = approval === "deterministic-policy";
      if (!deterministic) {
        // reviewer自动资格尚未在此工厂接线；只接受原可信UI的human确认。
        if (ctx.hasUI !== true || typeof ctx.ui?.confirm !== "function") reject("OPERATION_ADMISSION_REQUIRED", 4);
        const confirmed = await wait(entry, Promise.resolve().then(() => ctx.ui.confirm(mcp ? "Approve MCP operation" : shell ? "Approve Shell operation" : "Approve file operation", summary,
          { signal: entry.dialog.signal, timeout: Math.max(1, Math.min(entry.deadline - now(), entry.monotonicDeadline - monotonic())) })));
        if (confirmed !== true) reject("OPERATION_CANCELED", 4);
      }
      let latest = await current(entry);
      if (canonical(latest) !== canonical(context)) reject("OPERATION_CONTEXT_STALE", 4);
      const expectedSource = deterministic ? "deterministic-policy" : "human";
      const permit = await wait(entry, raw(deterministic ? "ordinary_admission_issue_deterministic" : "ordinary_admission_issue",
        { operation_id: prepared.operation_id, context: latest }, entry));
      closed(permit, ["schema_version", "permit_id", "operation_id", "operation_digest", "source", "reviewer_identity", "context"]);
      if (permit.schema_version !== 1 || !text(permit.permit_id) || permit.operation_id !== prepared.operation_id || permit.operation_digest !== prepared.operation_digest
          || permit.source !== expectedSource || permit.reviewer_identity !== null || canonical(permit.context) !== canonical(context)) reject("OPERATION_BINDING_INVALID", 4);
      latest = await current(entry);
      if (canonical(latest) !== canonical(context)) reject("OPERATION_CONTEXT_STALE", 4);
      let observed;
      try { observed = await wait(entry, raw("ordinary_admission_consume", { permit, context: latest }, entry)); }
      catch {
        // consume只发送一次；丢回执甚至取消后也只读对账，unknown不能清理Writer。
        observed = binding(await raw("ordinary_admission_status", { operation_id: prepared.operation_id }), prepared, true);
      }
      entry.ticket = { ...consumedTicket(observed, expected), tool_name: toolName };
      const finalContext = await current(entry);
      if (canonical(finalContext) !== canonical(context)) reject("OPERATION_CONTEXT_STALE", 4);
      if (mcp) {
        // 派发槽先在原账本烧掉；丢ACK绝不执行或重发。参数来自已确认的独立副本。
        const dispatched = await wait(entry, raw("ordinary_admission_mcp_dispatch", {
          operation_id: entry.ticket.operation_id, context: finalContext, input: captured.value }));
        closed(dispatched, ["operation_id", "state"]);
        if (dispatched.operation_id !== entry.ticket.operation_id || dispatched.state !== "sending") reject("OPERATION_CONSUME_UNKNOWN", 4);
        entry.dispatched = true;
        latest = await current(entry);
        if (canonical(latest) !== canonical(context)) reject("OPERATION_CONTEXT_STALE", 4);
        const execution = Promise.resolve().then(() => { check(entry); return execute(captured.value.arguments); });
        let value;
        try { value = await wait(entry, execution); }
        catch (error) {
          // 原执行Promise仍有拒绝处理；取消后不接纳迟到结果，也不重试服务调用。
          const outcome = entry.signal.aborted || entry.dialog.signal.aborted || retired
            || ["OPERATION_EXPIRED", "OPERATION_CANCELED", "OPERATION_CONTEXT_STALE"].includes(error?.message) ? "unknown" : "failed";
          entry.completed = true;
          track(raw("ordinary_admission_mcp_complete", { operation_id: entry.ticket.operation_id, outcome }));
          throw error;
        }
        latest = await current(entry);
        if (canonical(latest) !== canonical(context)) reject("OPERATION_CONTEXT_STALE", 4);
        entry.completed = true;
        const outcome = value?.isError === true ? "failed" : "succeeded";
        const completed = await wait(entry, raw("ordinary_admission_mcp_complete", { operation_id: entry.ticket.operation_id, outcome }));
        closed(completed, ["operation_id", "state"]);
        if (completed.operation_id !== entry.ticket.operation_id || completed.state !== outcome) reject("OPERATION_CONSUME_UNKNOWN", 4);
        latest = await current(entry);
        if (canonical(latest) !== canonical(context)) reject("OPERATION_CONTEXT_STALE", 4);
        return value;
      }
      return { ticket: entry.ticket, input: captured.value };
    } catch (error) {
      entry.dialog.abort();
      cancelRequest(entry);
      if (mcp && entry.dispatched && !entry.completed) {
        entry.completed = true;
        track(raw("ordinary_admission_mcp_complete", { operation_id: entry.ticket.operation_id, outcome: "unknown" }));
      }
      if (entry.ticket) track(cleanupKnown(entry));
      // 通用闭合器默认配置错误码2；此处是受管响应绑定失败，统一归为4。
      if (error?.message === "PROTOCOL_INVALID") reject("OPERATION_BINDING_INVALID", 4);
      reject(errors.has(error?.message) ? error.message : "OPERATION_ADMISSION_FAILED", error?.exitCode === 2 ? 2 : 4);
    } finally { signal.removeEventListener("abort", abort); done(); }
  };
  const retire = () => {
    if (retired) return;
    retired = true; epoch++;
    for (const entry of entries.values()) { entry.dialog.abort(); cancelRequest(entry); }
    track(raw("ordinary_admission_retire", { control_id: controlId }).then(result => {
      closed(result, ["control_id", "state"]);
      if (result.control_id !== controlId || result.state !== "retired") reject("OPERATION_CONTROL_UNAVAILABLE", 4);
    }));
  };
  const drain = async () => {
    await Promise.all([...entries.values()].map(entry => entry.done));
    while (cleanups.size) await Promise.all([...cleanups]);
    if (cleanupFailed) reject("OPERATION_CONTROL_UNAVAILABLE", 4);
  };
  return Object.freeze({ admit, retire, drain });
}
