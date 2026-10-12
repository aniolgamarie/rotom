// 有界Base组件探针；默认import只提供自有plan/fake helpers，不加载SDK或启动进程。
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDeepStrictEqual, types } from "node:util";

export const CASES = Object.freeze(Array.from({ length: 12 }, (_, index) => "B" + String(index + 1).padStart(2, "0")));
export const LIMITS = Object.freeze({ total_timeout_ms: 120000, case_timeout_ms: 8000, source_bytes: 33554432, source_files: 4096,
  fixture_bytes: 262144, result_bytes: 65536, sender_calls: 48, starts: 24, rpc_calls: 1024, operations_per_scene: 64 });
const ENV = { HOME: "/work/home", PWD: "/work", PATH: "/work/empty-bin", PI_PROBE_NATIVE: "1", PI_OFFLINE: "1", OTEL_SDK_DISABLED: "true", TMPDIR: "/work/tmp",
  XDG_CONFIG_HOME: "/work/config", XDG_DATA_HOME: "/work/data", XDG_CACHE_HOME: "/work/cache", XDG_STATE_HOME: "/work/state", LC_ALL: "C.UTF-8" };
const fail = () => { throw Error("BASE_PRODUCT_PROBE_INVALID"); };
const hash = value => createHash("sha256").update(value).digest("hex");
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const digest = value => hash(JSON.stringify(canonical(value)) + "\n");
const exact = (left, right) => { if (!isDeepStrictEqual(left, right)) fail(); };
const closed = (value, keys) => {
  if (!value || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype || !isDeepStrictEqual(Reflect.ownKeys(value).sort(), [...keys].sort())
    || Object.values(Object.getOwnPropertyDescriptors(value)).some(row => !row.enumerable || !Object.hasOwn(row, "value"))) fail();
};
const relative = value => typeof value === "string" && value && !path.isAbsolute(value) && !/[\\\p{Cc}\p{Cf}]/u.test(value) && value.split("/").every(part => part && part !== "." && part !== "..");
export function validatePlan(input, { requireFrozen = false } = {}) {
  closed(input, ["schema_version", "probe_id", "state", "versions", "cases", "limits", "source_inventory", "candidate_inventory", "links", "packages", "base_runtime_seed", "b12"]);
  if (input.schema_version !== 1 || input.probe_id !== "base-product-sdk-components" || !["prepared-only", "frozen-pending-separate-authorization"].includes(input.state)) fail();
  if (requireFrozen && input.state !== "frozen-pending-separate-authorization") fail();
  exact(input.versions, { node: "24.14.0", pi: "1.0.1", pi_ai: "1.0.2" }); exact(input.cases, CASES); exact(input.limits, LIMITS);
  exact(input.packages, ["todo-vendor", "colorful-footer", "loop-guard", "runtime-ui"]);
  exact(input.links, [{ path: "node_modules/@agentcfg/pi-runtime", target: "../../agents/pi/packages/runtime-ui" },
    { path: "node_modules/@earendil-works", target: "/candidate/node_modules/@earendil-works" }]);
  if (!Array.isArray(input.base_runtime_seed) || input.base_runtime_seed.length !== 35 || new Set(input.base_runtime_seed).size !== 35
    || input.base_runtime_seed.some(name => !relative(name) || !name.startsWith("agents/pi/runtime/") || !name.endsWith(".ts"))) fail();
  exact(input.b12, { status: "public-manager-script-frozen", execute: true });
  if (!Array.isArray(input.source_inventory) || input.source_inventory.length > LIMITS.source_files) fail();
  let bytes = 0; const names = new Set();
  for (const row of input.source_inventory) {
    closed(row, ["path", "bytes", "sha256"]);
    if (!relative(row.path) || names.has(row.path) || !/^[a-f0-9]{64}$/.test(row.sha256) || !Number.isSafeInteger(row.bytes) || row.bytes < 0 || row.bytes > 4 * 1024 * 1024
      || !(row.path.startsWith("agents/pi/runtime/") && row.path.endsWith(".ts") || input.packages.some(pkg => row.path.startsWith("agents/pi/packages/" + pkg + "/")))) fail();
    names.add(row.path); bytes += row.bytes;
  }
  if (bytes > LIMITS.source_bytes) fail();
  if (input.candidate_inventory !== null) {
    closed(input.candidate_inventory, ["fixture", "sha256", "receipt_root_name", "entries", "file_count", "bytes"]);
    const row = input.candidate_inventory;
    if (row.fixture !== "candidate-inventory.json" || !/^[a-f0-9]{64}$/.test(row.sha256) || !relative(row.receipt_root_name) || row.receipt_root_name.includes("/")
      || !Number.isSafeInteger(row.entries) || row.entries < 1 || row.entries > 65536 || !Number.isSafeInteger(row.file_count) || row.file_count < 1 || row.file_count > row.entries
      || !Number.isSafeInteger(row.bytes) || row.bytes < 0 || row.bytes > 536870912) fail();
  }
  if (input.state !== "prepared-only") {
    if (!input.candidate_inventory || !input.base_runtime_seed.every(name => names.has(name)) || input.packages.some(pkg => !names.has(`agents/pi/packages/${pkg}/package.json`))) fail();
  }
  return structuredClone(input);
}

// 只准备外层argv；与现Main runner相同的readonly mount/env pattern，不spawn。
export function buildInvocation({ plan, sourceRoot, candidateRoot, nodeRoot, workRoot, worker, fixtureRoot }) {
  validatePlan(plan, { requireFrozen: true });
  const paths = [sourceRoot, candidateRoot, nodeRoot, workRoot, worker, fixtureRoot];
  if (paths.some(value => typeof value !== "string" || !path.isAbsolute(value) || path.normalize(value) !== value || /[\p{Cc}\p{Cf}]/u.test(value) || value === "/")
    || new Set(paths).size !== paths.length || !/^\/(tmp|data)\//.test(workRoot) || [sourceRoot, candidateRoot, nodeRoot, fixtureRoot].some(value => workRoot.startsWith(value + "/"))) fail();
  const argv = ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
    "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    "--ro-bind", sourceRoot, "/source", "--ro-bind", candidateRoot, "/candidate", "--ro-bind", nodeRoot, "/node", "--dir", "/probe",
    "--ro-bind", worker, "/probe/worker.mjs", "--ro-bind", fixtureRoot, "/probe/fixture", "--symlink", "/candidate/node_modules", "/probe/node_modules", "--bind", workRoot, "/work"];
  for (const [name, value] of Object.entries(ENV)) argv.push("--setenv", name, value);
  argv.push("--chdir", "/work", "/node/bin/node", "--max-old-space-size=512", "/probe/worker.mjs", "--native-base-product-sdk-probe"); return { argv, env: {} };
}
// 冻结函数仅读取已由Root staged的完整OWN包/精确runtime闭包；不复制SDK或启动native。
export async function prepareFrozenPlan({ plan, sourceRoot, candidateRoot, receiptPath, receiptSha256 }) {
  const fixed = validatePlan(plan), helper = new URL("../tests/fixtures/pi/base-product-sdk-probe/candidate-inventory.mjs", import.meta.url);
  const { verifyCandidateInventory } = await import(helper.href);
  const measured = verifyCandidateInventory({ candidateRoot, receiptPath, receiptSha256 });
  fixed.candidate_inventory = { fixture: "candidate-inventory.json", receipt_root_name: path.basename(candidateRoot), ...measured };
  fixed.source_inventory = [];
  const walk = (relativePath, depth = 0) => {
    if (depth > 64) fail(); const directory = path.join(sourceRoot, relativePath);
    for (const name of fs.readdirSync(directory).sort()) {
      const rel = relativePath + "/" + name, file = path.join(sourceRoot, rel), info = fs.lstatSync(file); if (info.isSymbolicLink()) fail();
      if (info.isDirectory()) walk(rel, depth + 1); else { if (!info.isFile() || info.size > 4 * 1024 * 1024) fail(); fixed.source_inventory.push({ path: rel, bytes: info.size, sha256: hash(fs.readFileSync(file)) }); }
    }
  };
  walk("agents/pi/runtime"); for (const pkg of fixed.packages) walk("agents/pi/packages/" + pkg);
  const closure = new Set(), pending = [...fixed.base_runtime_seed];
  while (pending.length) {
    const rel = pending.pop(); if (closure.has(rel)) continue; closure.add(rel);
    const text = fs.readFileSync(path.join(sourceRoot, rel), "utf8");
    for (const match of text.matchAll(/(?:from\s+|import\s*\(\s*)["'](\.[^"']+)["']/g)) {
      const child = path.posix.normalize(path.posix.join(path.posix.dirname(rel), match[1]));
      if (!child.startsWith("agents/pi/runtime/") || !child.endsWith(".ts")) fail(); pending.push(child);
    }
  }
  exact(fixed.source_inventory.filter(row => row.path.startsWith("agents/pi/runtime/")).map(row => row.path).sort(), [...closure].sort());
  for (const row of fixed.links) if (fs.readlinkSync(path.join(sourceRoot, row.path)) !== row.target) fail();
  fixed.state = "frozen-pending-separate-authorization"; return validatePlan(fixed, { requireFrozen: true });
}

// 仅synthetic receipt emulator，不代表Python authority/Writer/OS进程事实。
export function createFakeSupervisor({ cwd, stateRoot, serviceRoot = stateRoot, budget, limits = LIMITS }) {
  if (![cwd, stateRoot].every(value => typeof value === "string" && path.isAbsolute(value) && path.normalize(value) === value) || !budget) fail();
  const records = new Map(), leases = new Map(), calls = []; let next = 0;
  const write = (name, data) => { const file = path.join(stateRoot, name); fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 }); fs.writeFileSync(file, typeof data === "string" || Buffer.isBuffer(data) ? data : JSON.stringify(data), { mode: 0o600 }); };
  const target = name => { const value = path.resolve(cwd, name); if (value !== cwd && !value.startsWith(cwd + "/")) fail(); return value; };
  const get = id => { const row = records.get(id); if (!row) fail(); return row; };
  const identity = { platform: "linux", boot_id: "synthetic-boot", pid: 123, ppid: 1, pgid: 123, start_time: "synthetic-start", namespace: "synthetic-ns", uid: process.getuid() };
  const state = { failRead: false, shellExit: 0, deny: false };
  const serviceReceipts = row => {
    const save = (name, value) => { const file = path.join(serviceRoot, "activity", name); fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 }); fs.writeFileSync(file, Buffer.isBuffer(value) ? value : JSON.stringify(value), { mode: 0o600 }); };
    save(`exits/${row.ticket.lease_id}.json`, { schema_version: 1, lease_id: row.ticket.lease_id, process_identity: identity, exit_code: 0 });
    const stdout = Buffer.from(row.stdout), stderr = Buffer.alloc(0); save(`outputs/${row.ticket.lease_id}/stdout`, stdout); save(`outputs/${row.ticket.lease_id}/stderr`, stderr);
    save(`outputs/${row.ticket.lease_id}/capture.json`, { schema_version: 1, complete: true, truncated: false, streams: Object.fromEntries([["stdout", stdout], ["stderr", stderr]].map(([name, bytes]) => [name, { path: name, sha256: hash(bytes), bytes: bytes.length, truncated: false, failed: false }])) });
  };
  const supervisor = { options: { endpoint: path.join(stateRoot, "activity/control/control.json") }, async call(method, args) {
    if (++budget.rpc > limits.rpc_calls) fail(); calls.push({ method, args: structuredClone(args) });
    if (method === "ordinary_admission_open") return { ...args, state: "open" };
    if (method === "ordinary_admission_retire") return { control_id: args.control_id, state: "retired" };
    if (method === "ordinary_admission_cancel_request") return { request_id: args.request_id, state: "canceled" };
    if (method === "ordinary_mcp_stdio_prepare") {
      if (records.size >= limits.operations_per_scene || args.server_name !== "docs") fail();
      const lease = (++next).toString(16).padStart(32, "0"), ticket = { operation_id: args.operation_id, lease_id: lease, kind: "command", execution_class: "service", service_name: "docs", tool_name: "bash", command_ref: "docs", timeout_seconds: 20, write: false };
      const row = { ticket, service: true, starts: 0, generation: 1, stdin: "", stdout: "", frames: [] }; records.set(args.operation_id, row); leases.set(lease, row); return { ...ticket };
    }
    if (method === "ordinary_command_stdin") {
      const row = get(args.operation_id); if (!row.service || !row.started || row.ended || typeof args.data !== "string" || Buffer.byteLength(args.data) > 512) fail();
      row.stdin += args.data; if (Buffer.byteLength(row.stdin) > 65536) fail(); let end;
      while ((end = row.stdin.indexOf("\n")) !== -1) {
        const message = JSON.parse(row.stdin.slice(0, end)); row.stdin = row.stdin.slice(end + 1); if (message.jsonrpc !== "2.0") fail();
        if (message.id === undefined) continue;
        let response;
        if (message.method === "initialize") response = { protocolVersion: message.params.protocolVersion, capabilities: { tools: {}, resources: {} }, serverInfo: { name: "own-fake-docs", version: "1" } };
        else if (message.method === "tools/list") response = { tools: [{ name: "query", description: "own synthetic query", inputSchema: { type: "object", properties: { q: { type: "string" } }, additionalProperties: false } }] };
        else if (message.method === "tools/call" && message.params.name === "query") response = { content: [{ type: "text", text: message.params.arguments.q === "fail" ? "own nested failure" : "own query success" }], ...(message.params.arguments.q === "fail" ? { isError: true } : {}) };
        else if (message.method === "resources/list") response = { resources: [{ uri: "own://sentinel", name: "own synthetic resource" }] };
        else if (message.method === "resources/templates/list") response = { resourceTemplates: [] };
        else if (message.method === "ping") response = {};
        else fail();
        const frame = JSON.stringify({ jsonrpc: "2.0", id: message.id, result: response }) + "\n"; row.stdout += frame; if (Buffer.byteLength(row.stdout) > limits.fixture_bytes) fail(); row.frames.push(frame);
      }
      return { accepted_bytes: Buffer.byteLength(args.data), stdin_closed: false };
    }
    if (method === "ordinary_command_output") {
      const row = get(args.operation_id); if (!row.service) fail(); const frames = row.frames.slice(args.cursor, args.cursor + 4);
      return { events: frames.map(frame => ({ stream: "stdout", data_b64: Buffer.from(frame).toString("base64") })), next_cursor: args.cursor + frames.length,
        dropped: false, has_more: args.cursor + frames.length < row.frames.length, complete: Boolean(row.ended) };
    }
    if (method === "ordinary_command_finish") return { finished: true };
    if (method === "ordinary_admission_prepare") {
      if (records.size >= limits.operations_per_scene || state.deny) fail();
      const id = (++next).toString(16).padStart(32, "0"), shell = args.tool_name === "bash", mcp = args.tool_name === "mcp";
      const writes = shell || ["write", "edit", "rename"].includes(args.tool_name), root = { path: cwd, identity: "3".repeat(64) };
      const file = mcp ? null : target(shell ? "." : args.input.path ?? ".");
      const policy = { generation: 1, policy_digest: "c".repeat(64), ceiling_digest: "e".repeat(64), hard_policy: "allow", approval: "deterministic-policy", requires_human: false };
      const resolution = { kind: shell ? "shell-command" : mcp ? "mcp" : "file", tool_name: args.tool_name,
        target: shell ? { command_ref: "tool:shell", executable: { path: "/synthetic/bash", device: 1, inode: 1, uid: process.getuid(), sha256: "a".repeat(64) }, timeout_ms: 1000 }
          : mcp ? { server_names: ["docs"], action: args.input.action, name: args.input.name, binding_digest: "e".repeat(64) } : { path: file, destination: args.tool_name === "rename" ? target(args.input.destination) : null },
        read_roots: mcp ? [] : [root], write_roots: writes ? [root] : [], workspace_keys: writes ? ["4".repeat(64)] : [], network: "deny",
        services: mcp ? ["mcp:docs"] : [], backend: shell ? "linux-bwrap-v1" : mcp ? "native-mcp-v1" : "guarded-files-v1", policy };
      const prepared = { schema_version: 1, operation_id: id, request_id: args.request_id, context: structuredClone(args.context), resolution, private_input_ref: "2".repeat(32) };
      prepared.operation_digest = digest(prepared);
      const ticket = shell ? { operation_id: id, kind: "command", tool_name: "bash", write: true, timeout_seconds: 1, command_ref: "tool:shell", request_digest: prepared.operation_digest, lease_id: null, state: "prepared" }
        : mcp ? { operation_id: id, kind: "mcp", state: "prepared" } : { operation_id: id, path: file, write: writes, request_digest: digest(args.input), lease_id: null, state: "prepared" };
      records.set(id, { prepared, ticket, input: structuredClone(args.input), state: "prepared", starts: 0, body: null, shell, mcp }); return structuredClone(prepared);
    }
    if (method === "ordinary_admission_status") { const row = get(args.operation_id); return { admission: { operation_id: args.operation_id, state: row.state }, execution: { ...row.ticket } }; }
    if (method === "ordinary_admission_issue_deterministic") { const row = get(args.operation_id); exact(args.context, row.prepared.context); return { schema_version: 1, permit_id: "permit-" + args.operation_id,
      operation_id: args.operation_id, operation_digest: row.prepared.operation_digest, source: "deterministic-policy", reviewer_identity: null, context: structuredClone(args.context) }; }
    if (method === "ordinary_admission_consume") {
      const row = get(args.permit.operation_id); if (row.state !== "prepared") fail(); exact(args.context, row.prepared.context);
      row.state = row.ticket.state = "consumed"; if (!row.mcp) { row.ticket.lease_id = row.ticket.write ? row.ticket.operation_id : "synthetic-parent"; leases.set(row.ticket.lease_id, row); }
      return { ...row.ticket };
    }
    if (method === "ordinary_admission_mcp_dispatch") { const row = get(args.operation_id); if (row.state !== "consumed") fail(); row.state = "sending"; return { operation_id: args.operation_id, state: "sending" }; }
    if (method === "ordinary_admission_mcp_complete") { const row = get(args.operation_id); row.state = args.outcome; return { operation_id: args.operation_id, state: args.outcome }; }
    if (method === "ordinary_read") {
      if (state.failRead) fail(); const row = get(args.operation_id), file = args.relative_path ? target(path.join(path.relative(cwd, row.ticket.path), args.relative_path)) : row.ticket.path;
      const data = fs.readFileSync(file); if (data.length > limits.fixture_bytes) fail(); return { data_b64: data.subarray(args.offset, args.offset + args.limit).toString("base64"), total_bytes: data.length, content_digest: hash(data) };
    }
    if (method === "ordinary_list") {
      const row = get(args.operation_id), entries = []; const walk = (directory, prefix = "") => { for (const name of fs.readdirSync(directory).sort()) {
        if (name.startsWith(".") || name === "ignored.txt") continue; const file = path.join(directory, name), info = fs.lstatSync(file); if (info.isSymbolicLink()) continue;
        const rel = prefix + name; if (info.isDirectory()) { if (row.prepared.resolution.tool_name === "ls") entries.push({ path: rel, directory: true }); else walk(file, rel + "/"); }
        else if (row.prepared.resolution.tool_name !== "find" || name.endsWith(".txt")) entries.push({ path: rel, directory: false });
      } }; walk(row.ticket.path); return { entries, truncated: false };
    }
    if (method === "ordinary_stage_write") { const row = get(args.operation_id); if (row.state !== "consumed" || !row.ticket.write || typeof args.content !== "string" || Buffer.byteLength(args.content) > limits.fixture_bytes) fail(); row.body = args.content; row.expected = args.expected_digest; return { staged: true }; }
    if (method === "ordinary_shell_take_input") { const row = get(args.operation_id); return structuredClone(row.input); }
    if (method === "start") {
      const row = get(args.payload.operation_id); if (args.program !== (row.service ? "ordinary-command" : row.shell ? "ordinary-shell" : "file-operation") || row.ticket.lease_id !== args.lease_id || ++row.starts !== 1 || ++budget.starts > limits.starts) fail();
      row.started = true; row.ended = !row.service;
      if (row.service) return { lease_id: args.lease_id, state: "running" };
      if (row.shell) {
        const stdout = Buffer.from("synthetic shell output\n"), stderr = Buffer.alloc(0);
        write(`activity/exits/${args.lease_id}.json`, { schema_version: 1, lease_id: args.lease_id, process_identity: identity, exit_code: state.shellExit });
        write(`activity/outputs/${args.lease_id}/stdout`, stdout); write(`activity/outputs/${args.lease_id}/stderr`, stderr);
        write(`activity/outputs/${args.lease_id}/capture.json`, { schema_version: 1, complete: true, truncated: false, streams: Object.fromEntries([["stdout", stdout], ["stderr", stderr]].map(([name, bytes]) => [name, { path: name, sha256: hash(bytes), bytes: bytes.length, truncated: false, failed: false }])) });
      } else {
        if (row.body === null || typeof row.body !== "string") fail(); const before = fs.existsSync(row.ticket.path) ? hash(fs.readFileSync(row.ticket.path)) : null;
        if (row.expected !== null && row.expected !== before) fail(); fs.writeFileSync(row.ticket.path, row.body, { mode: 0o600 });
        write(`activity/exits/${args.lease_id}.json`, { lease_id: args.lease_id, exit_code: 0, process_identity: identity });
        write(`activity/ordinary-results/${row.ticket.operation_id}.json`, { schema_version: 1, operation_id: row.ticket.operation_id, lease_id: args.lease_id, result: { changed: true } });
      }
      return { lease_id: args.lease_id, state: "running" };
    }
    if (method === "ordinary_shell_output") { const row = get(args.operation_id), bytes = Buffer.from("synthetic shell output\n"); return { events: args.cursor ? [] : [{ seq: 1, stream: "stdout", data_b64: bytes.toString("base64") }], next_cursor: 1, dropped: false, has_more: false, complete: row.ended }; }
    if (method === "inspect" || method === "reconcile") { const row = leases.get(args.lease_id); if (!row) fail(); return { lease_id: args.lease_id,
      ...(row.service ? { attempt_id: row.ticket.operation_id, task_id: null, grant_generation: row.generation, process_status: row.started && !row.ended ? "alive" : "dead" } : {}),
      state: row.ended ? "reclaimed" : row.started ? "running" : "allocating", spawn_committed: Boolean(row.started), protected: !row.ended, process_identity: row.started ? identity : null,
      termination_evidence: row.ended ? { verified: true, ...(row.service ? { kind: row.started ? "terminated" : "never-started", execution_lease_id: args.lease_id } : {}) } : null }; }
    if (method === "cancel" || method === "abort_allocation") { const row = leases.get(args.lease_id); if (row) { row.ended = true; if (row.service) { if (method === "cancel") row.generation++; if (row.started) serviceReceipts(row); } } return {}; }
    if (method === "ordinary_finish") return { finished: true };
    fail();
  } };
  return { supervisor, calls, records, state };
}

const bounded = async (promise, ms) => { let timer; try { return await Promise.race([promise, new Promise((_resolve, reject) => { timer = setTimeout(() => reject(Error("BASE_PRODUCT_TIMEOUT")), ms); })]); } finally { clearTimeout(timer); } };
async function runNative() {
  exact(process.argv.slice(2), ["--native-base-product-sdk-probe"]); exact(Object.keys(process.env).sort(), Object.keys(ENV).sort()); for (const [key, value] of Object.entries(ENV)) assert.equal(process.env[key], value); assert.equal(process.platform, "linux"); assert.equal(process.version, "v24.14.0");
  const planFile = "/probe/fixture/plan.json"; assert(fs.statSync(planFile).size <= 65536);
  const plan = validatePlan(JSON.parse(fs.readFileSync(planFile, "utf8")), { requireFrozen: true });
  const { verifyCandidateInventory } = await import("./fixture/candidate-inventory.mjs");
  const expected = plan.candidate_inventory;
  exact(verifyCandidateInventory({ candidateRoot: "/candidate", receiptPath: "/probe/fixture/" + expected.fixture, receiptSha256: expected.sha256, receiptRootName: expected.receipt_root_name }),
    { sha256: expected.sha256, entries: expected.entries, file_count: expected.file_count, bytes: expected.bytes });
  for (const row of plan.source_inventory) { const file = "/source/" + row.path, info = fs.lstatSync(file); assert(info.isFile() && !info.isSymbolicLink() && fs.realpathSync(file) === file && info.size === row.bytes); assert.equal(hash(fs.readFileSync(file)), row.sha256); }
  const measured = new Set();
  const walkSource = (directory, depth = 0) => { assert(depth <= 64); for (const name of fs.readdirSync("/source/" + directory)) {
    const rel = directory + "/" + name, info = fs.lstatSync("/source/" + rel); assert(!info.isSymbolicLink());
    if (info.isDirectory()) walkSource(rel, depth + 1); else { assert(info.isFile()); measured.add(rel); assert(measured.size <= LIMITS.source_files); }
  } };
  walkSource("agents/pi/runtime"); for (const pkg of plan.packages) walkSource("agents/pi/packages/" + pkg);
  exact([...measured].sort(), plan.source_inventory.map(row => row.path).sort());
  for (const row of plan.links) assert.equal(fs.readlinkSync("/source/" + row.path), row.target);
  const sdk = await import("@earendil-works/pi-coding-agent"), ai = await import("@earendil-works/pi-ai"); assert.equal(sdk.VERSION, "1.0.1"); assert.equal(JSON.parse(fs.readFileSync("/candidate/node_modules/@earendil-works/pi-ai/package.json", "utf8")).version, "1.0.2");
  const own = name => import(pathToFileURL("/source/agents/pi/runtime/" + name + ".ts").href);
  const { createOfficialFileRuntime } = await own("official-file-runtime"), { createOfficialModels } = await own("official-models"), { createOfficialModelScope } = await own("official-model-scope");
  const result = { schema_version: 1, probe_id: plan.probe_id, status: "failed", sdk_abi_only: true, actual_python_or_os_authority: false, cases: [] };
  const budget = { sender: 0, starts: 0, rpc: 0 }; let scene = 0, phase = "fixture-enter";
  const diagnostic = error => ({ phase, error_type: ["Error", "TypeError", "RangeError", "AssertionError"].includes(error?.name) ? error.name : "Error",
    synthetic_message: String(error?.message ?? "unknown").replace(/[\p{Cc}\p{Cf}]/gu, " ").slice(0, 192) });
  async function fixture(id) {
    const root = "/work/scene-" + id + "-" + ++scene, cwd = root + "/project", instanceRoot = root + "/instance", stateRoot = root + "/state";
    for (const dir of [cwd, instanceRoot + "/pi-home", stateRoot, root + "/sessions"]) fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(cwd + "/source.txt", "alpha\nneedle 中文\nomega\n", { mode: 0o600 }); fs.writeFileSync(cwd + "/ignored.txt", "ignored sentinel", { mode: 0o600 });
    for (const name of ["AGENTS.md", "APPEND_SYSTEM.md"]) fs.writeFileSync(instanceRoot + "/pi-home/" + name, "Own synthetic Base component probe\n", { mode: 0o600 });
    phase = "synthetic-provider";
    const faux = ai.fauxProvider({ provider: "synthetic-base", api: "synthetic-base", models: [{ id: "main", input: ["text"], contextWindow: 16384, maxTokens: 2048 }] });
    const model = { ...faux.getModel(), baseUrl: "https://synthetic.invalid/unused" };
    const provider = ai.createProvider({ id: model.provider, models: [model], auth: { apiKey: { name: "synthetic", check: async () => ({ type: "api_key" }), resolve: async () => ({ auth: { apiKey: "synthetic" } }) } },
      api: { stream: (...args) => { if (++budget.sender > LIMITS.sender_calls) fail(); return faux.provider.stream(...args); }, streamSimple: (...args) => { if (++budget.sender > LIMITS.sender_calls) fail(); return faux.provider.streamSimple(...args); } } });
    const raw = await sdk.ModelRuntime.create({ credentials: new ai.InMemoryCredentialStore(), modelsStore: new ai.InMemoryModelsStore(), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false }); raw.registerNativeProvider(provider);
    await raw.refresh({ providers: [model.provider], allowNetwork: false });
    const config = { api: model.api, baseUrl: model.baseUrl, models: [{ id: "main", input: ["text"], contextWindow: 16384, maxTokens: 2048 }] }, binding = { logical_id: "synthetic", auth_kind: "api-key", owner: "pi-environment" };
    const groups = ["extensions", "skills", "prompts", "themes", "roles"];
    const manifest = { schema_version: 1, profile_id: "pi-base", engine: "node", bootstrap: false, cost_reporting: "unmetered", plugins: ["pi-todo", "loop-guard", "colorful-footer"],
      plugin_capabilities: { "pi-todo": { capability_id: "todo", model_tools: ["todo"] }, "loop-guard": { capability_id: "loop-protection", model_tools: [] }, "colorful-footer": { capability_id: "footer", model_tools: [] } },
      resources: Object.fromEntries(groups.map(k => [k, []])), resource_ids: Object.fromEntries(groups.map(k => [k, {}])),
      options: { discovery: { project_resources: false }, todo: {}, ui: { footer: {} }, loop_guard: { enforcementMode: id === "B10" ? "enforce" : "off", advisoryMode: "off", repeatLimit: 1 },
        paths: { roots: { project: { path: cwd, purpose: "project" } } }, external_tools: { shell: { executable: "/synthetic/bash", args: [] } } },
      provider_bindings: { [model.provider]: binding }, model_configuration: { schema_version: 1, providers: { [model.provider]: { ...binding, credential_ref: "secret:SYNTHETIC", config } } },
      model_bindings: { main: { provider: model.provider, model: "main" } }, allowed_models: [{ provider: model.provider, model: "main" }] };
    if (["B07", "B08", "B12"].includes(id)) manifest.native_mcp = { schema_version: 1, loaded_config: { servers: [{ name: "docs", source: "agentcfg:registry/mcp/docs", scope: "extension",
      config: { type: "stdio", command: "/synthetic/docs", args: [], cwd, env: {}, exposure: "hidden", toolExposure: { query: "codemode" } } }], errors: [], autoEnableCodemode: false },
      bindings: { docs: { transport: "stdio", command_ref: "docs", authentication: "none" } }, allowed_tools: { docs: ["query"] } };
    const modelPath = instanceRoot + "/pi-home/models.json"; fs.writeFileSync(modelPath, JSON.stringify({ providers: { [model.provider]: { ...config, apiKey: "$AGENTCFG_PI_CREDENTIAL_" + hash("synthetic").slice(0, 16).toUpperCase() } } }), { mode: 0o600 });
    phase = "model-scope";
    const models = createOfficialModels({ manifest, path: modelPath, modelRuntime: raw }), scope = createOfficialModelScope({ modelRuntime: raw, manifest, describe: models.describe });
    const settingsValue = { packages: [], extensions: [], skills: [], prompts: [], themes: [], defaultProjectTrust: "never", enableInstallTelemetry: false, enableAnalytics: false, cacheWarming: "off", compaction: { enabled: false }, retry: { enabled: false, maxRetries: 0, provider: { maxRetries: 0 } } };
    const settings = { settingsManager: sdk.SettingsManager.inMemory(settingsValue, { projectTrusted: false }), snapshot: () => structuredClone(settingsValue) };
    const installed = { profile_id: "pi-base", lock_identity: "b".repeat(64), slice_identity: "c".repeat(64), runtime_identity: "d".repeat(64),
      resources: Object.fromEntries(groups.map(k => [k, k === "extensions" ? [{ id: "pi-todo", capability_id: "todo", path: "agents/pi/packages/todo-vendor/index.ts" },
        { id: "loop-guard", capability_id: "loop-protection", path: "agents/pi/packages/loop-guard/index.ts" }, { id: "colorful-footer", capability_id: "footer", path: "agents/pi/packages/colorful-footer/index.ts" }] : []])) };
    if (id === "B12") {
      manifest.options.mcp = { servers: { docs: { transport: "stdio", command_ref: "docs" } } };
      manifest.options.external_tools.docs = { executable: "/synthetic/docs", args: [], interactive: true, project_root: "project" };
    }
    const fake = createFakeSupervisor({ cwd, stateRoot, serviceRoot: instanceRoot, budget });
    const globalKey = Symbol.for("agentcfg.pi.runtime.v1"), prior = Object.getOwnPropertyDescriptor(globalThis, globalKey);
    Object.defineProperty(globalThis, globalKey, { configurable: true, value: { owner: { role: "manager" }, manifest, instanceRoot, runtimeRoot: "/source", installed } });
    const errors = [], events = []; let actualContext, runtime;
    const observation = pi => { pi.on("tool_call", (_event, ctx) => { actualContext = ctx; }); };
    try {
      const manager = sdk.SessionManager.inMemory(cwd);
      phase = "file-runtime-create";
      runtime = await createOfficialFileRuntime({ sdk, manifest, installed, instanceRoot, runtimeRoot: "/source", engine: "node", settings, supervisor: fake.supervisor,
        owner: { role: "manager", manager_activation_id: "synthetic-activation", runtime_identity: installed.runtime_identity }, policySnapshot: () => ({ generation: 1, policy_digest: "c".repeat(64) }),
        runtimeHandle: { modelRuntime: scope.modelRuntime, check: scope.check, configurationDigest: models.declarationDigest },
        configuration: () => ({ policyDigest: "c".repeat(64), projectConstraintsDigest: "b".repeat(64) }), extensionFactories: [{ name: "own-probe-observer", factory: observation }] }, { cwd, sessionManager: manager });
      phase = "bind-extensions";
      await runtime.session.bindExtensions({ mode: "json", onError: () => { errors.push("extension-error"); } });
      const subscribe = () => runtime.session.subscribe(event => { if (event.type.startsWith("tool_execution_")) events.push(event); }); let unsubscribe = subscribe();
      let callId = 0;
      const script = async steps => { const before = events.length;
        faux.setResponses([...steps.map(([name, args]) => ai.fauxAssistantMessage(ai.fauxToolCall(name, args, { id: "call-" + ++callId }))), ai.fauxAssistantMessage("synthetic end")]);
        await bounded(runtime.session.prompt("own synthetic tool request", { expandPromptTemplates: false }), LIMITS.case_timeout_ms); assert.equal(errors.length, 0);
        return events.slice(before).filter(event => event.type === "tool_execution_end"); };
      const turn = async (name, args) => { const event = (await script([[name, args]])).find(event => event.toolName === name); assert(event); return event; };
      return { root, cwd, manager, manifest, runtime, fake, faux, events, errors, turn, script, context: () => actualContext,
        rebind: async () => { unsubscribe(); await runtime.session.bindExtensions({ mode: "json", onError: () => { errors.push("extension-error"); } }); unsubscribe = subscribe(); },
        async close() { try { unsubscribe(); await runtime.dispose(); } finally { if (prior) Object.defineProperty(globalThis, globalKey, prior); else delete globalThis[globalKey]; } } };
    } catch (error) { try { await runtime?.dispose(); } finally { if (prior) Object.defineProperty(globalThis, globalKey, prior); else delete globalThis[globalKey]; } throw error; }
  }
  const count = (f, name) => f.fake.calls.filter(row => row.method === name).length;
  async function run(id, body) {
    let f; try { f = await fixture(id); phase = "case-body-" + id; const observations = await bounded(body(f), LIMITS.case_timeout_ms); assert.equal(f.errors.length, 0); result.cases.push({ case_id: id, outcome: "observed", observations }); }
    catch (error) { result.cases.push({ case_id: id, outcome: "failed", observations: diagnostic(error) }); throw Error("BASE_PRODUCT_CASE_FAILED"); }
    finally { await f?.close(); }
  }
  try {
    await run("B01", async f => { const snapshot = await f.runtime.resourceSnapshot(), tools = f.runtime.session.getActiveToolNames(); assert(tools.includes("todo") && tools.includes("read") && tools.includes("bash"));
      assert(!tools.some(name => ["kernel_task", "model_delegate", "Agent"].includes(name))); assert.equal(snapshot.observation.resources.extensions.length, 3); assert.equal(f.manifest.cost_reporting, "unmetered"); return { current_three_extensions: true, todo_active: true, cost_reporting_unmetered: true, headless_source_load_only: true, footer_render_verified: false }; });
    await run("B02", async f => { const event = await f.turn("read", { path: "source.txt", offset: 2, limit: 1 }); assert.equal(event.isError, false, JSON.stringify(event.result).slice(0, 192)); assert(event.result.content.some(row => row.text?.includes("needle 中文"))); assert.equal(count(f, "ordinary_admission_consume"), 1); return { sdk_read_semantics: true, authentic_sdk_ctx: true }; });
    await run("B03", async f => { for (const [name, args] of [["ls", { path: "." }], ["find", { pattern: "*.txt" }], ["grep", { pattern: "needle", literal: true }]]) {
      const event = await f.turn(name, args); assert.equal(event.isError, false, name + ":" + JSON.stringify(event.result).slice(0, 170)); const text = event.result.content.map(row => row.text ?? "").join(); assert(text.includes("source.txt")); assert(!text.includes("ignored.txt")); }
      return { ls_find_grep: true, synthetic_list_policy_only: true }; });
    await run("B04", async f => { assert.equal((await f.turn("write", { path: "new.txt", content: "owned new\n" })).isError, false);
      assert.equal((await f.turn("edit", { path: "source.txt", oldText: "alpha", newText: "edited" })).isError, false);
      assert.equal(fs.readFileSync(f.cwd + "/new.txt", "utf8"), "owned new\n"); assert(fs.readFileSync(f.cwd + "/source.txt", "utf8").startsWith("edited\n")); assert.equal(count(f, "start"), 2); return { actual_own_temp_bytes: true, real_sdk_edit: true, python_writer_proven: false }; });
    await run("B05", async f => { const missing = await f.turn("edit", { path: "source.txt", oldText: "ABSENT", newText: "replacement" }); assert.equal(missing.isError, true); assert.equal(count(f, "start"), 0);
      f.fake.state.failRead = true; assert.equal((await f.turn("read", { path: "source.txt" })).isError, true); assert.equal(count(f, "ordinary_stage_write"), 0); return { edit_failure: true, read_failure: true, no_started_writer: true }; });
    await run("B06", async f => { const ok = await f.turn("bash", { command: "synthetic only" }); assert.equal(ok.isError, false); f.fake.state.shellExit = 7;
      const bad = await f.turn("bash", { command: "synthetic nonzero" }); assert.equal(bad.isError, true); assert.equal(count(f, "start"), 2); return { real_bash_definition: true, synthetic_capture_nonzero: true, actual_shell_executed: false }; });
    await run("B07", async f => { const names = f.runtime.session.getAllTools().map(row => row.name); assert(names.includes("codemode"), JSON.stringify(names)); assert(!names.some(name => name.startsWith("mcp__") || ["list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource"].includes(name)));
      assert.equal(count(f, "ordinary_mcp_stdio_prepare"), 0); const event = await f.turn("codemode", { code: "return 1;" }); assert.equal(event.isError, false); assert.equal(count(f, "ordinary_mcp_stdio_prepare"), 0); return { native_factories: true, disabled_no_service: true }; });
    await run("B08", async f => { const before = f.events.length; const event = await f.turn("codemode", { code: "return await tools.read({path:'source.txt'});" }); assert.equal(event.isError, false);
      assert(f.events.slice(before).some(row => row.toolName === "read" && row.parentToolCallId)); f.fake.state.deny = true;
      const denied = await f.turn("codemode", { code: "return await tools.read({path:'source.txt'});" }); assert.equal(denied.isError, true); return { actual_nested_sdk_events: true, inner_failure_propagated: true }; });
    await run("B09", async f => { assert.equal((await f.turn("todo", { action: "create", subject: "own unfinished sentinel" })).isError, false);
      const listed = await f.turn("todo", { action: "list" }); assert.equal(listed.isError, false); assert(JSON.stringify(listed.result.details).includes("own unfinished sentinel"));
      assert(f.manager.getBranch().some(entry => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === "todo")); assert.equal(count(f, "ordinary_admission_prepare"), 0); return { actual_todo_session_result: true, no_business_writer: true }; });
    await run("B10", async f => { f.manager.appendCustomMessageEntry("own-unfinished", "own unfinished task reference", true, { status: "unfinished" });
      const events = await f.script([["read", { path: "source.txt" }], ["read", { path: "source.txt" }]]);
      assert(events.some(event => event.toolName === "read" && event.isError === false)); assert.equal(count(f, "ordinary_admission_prepare"), 1);
      const branch = f.manager.getBranch(); assert(branch.some(entry => entry.type === "message" && entry.message.role === "toolResult" && entry.message.isError));
      assert(branch.some(entry => entry.type === "custom_message" && entry.customType === "own-unfinished"));
      return { current_loop_repeat_block: true, failed_and_unfinished_references_retained: true, no_extra_inference: true }; });
    await run("B11", async f => { await f.turn("read", { path: "source.txt" }); const old = f.runtime.session.getToolDefinition("read"), context = f.context(), previous = f.runtime.session;
      await f.runtime.newSession(); await f.rebind(); assert.notEqual(f.runtime.session, previous); const before = count(f, "ordinary_admission_consume");
      await assert.rejects(old.execute("late", { path: "source.txt" }, new AbortController().signal, undefined, context)); assert.equal(count(f, "ordinary_admission_consume"), before);
      assert.equal((await f.turn("read", { path: "source.txt" })).isError, false); await f.runtime.resourceSnapshot(); return { old_definition_retired: true, new_bindings_valid: true }; });
    await run("B12", async f => {
      sdk.initTheme("dark", false); const tui = await import("@earendil-works/pi-tui"); let component, customCalls = 0, settled = "pending"; const notices = [];
      const ui = { notify(message) { notices.push(String(message).slice(0, 100)); }, setStatus() {}, setFooter() {}, setWidget() {}, setWorkingMessage() {}, setTitle() {}, setHeader() {},
        async custom(factory) { customCalls++; return new Promise(async (resolve, reject) => {
          try { component = await factory({ requestRender() {} }, { fg: (_color, text) => text, bg: (_color, text) => text, bold: text => text }, tui.getKeybindings(), resolve); }
          catch { reject(Error("BASE_PRODUCT_PUBLIC_UI_FAILED")); }
        }); } };
      await f.runtime.session.bindExtensions({ mode: "tui", uiContext: ui, onError: () => { f.errors.push("extension-error"); } });
      phase = "B12-manager-open"; const opening = f.runtime.session.prompt("/mcp"); opening.then(() => { settled = "done"; }, error => { settled = String(error.message).slice(0, 100); });
      const waitFor = async check => { const until = performance.now() + LIMITS.case_timeout_ms - 1000; while (!check()) { if (performance.now() >= until) throw Error(JSON.stringify({ customCalls, settled, notices })); await new Promise(resolve => setTimeout(resolve, 10)); } };
      await waitFor(() => component?.handleInput && component.render(100).join("\n").includes("docs")); component.handleInput("\r");
      phase = "B12-enable-menu"; await waitFor(() => component.render(100).join("\n").includes("Enable")); component.handleInput("\r");
      phase = "B12-callable-after-enable"; await waitFor(() => f.runtime.session.getCallableToolNames().includes("mcp__docs__query") && component.render(100).join("\n").includes("Disable"));
      // 固定公开菜单：Tools、Reconnect、Exposure；仅render/handleInput。
      phase = "B12-public-exposure"; component.handleInput("\x1b[B"); component.handleInput("\x1b[B"); component.handleInput("\r");
      await waitFor(() => component.render(100).join("\n").includes("Exposure of docs")); component.handleInput("\r");
      await waitFor(() => f.runtime.session.getCallableToolNames().includes("list_mcp_resources") && component.render(100).join("\n").includes("Disable")); component.handleInput("\x1b");
      phase = "B12-manager-return"; await waitFor(() => component.render(100).join("\n").includes("MCP servers")); component.handleInput("\x1b");
      await bounded(opening, LIMITS.case_timeout_ms); assert.equal(customCalls, 1); assert.equal(count(f, "ordinary_mcp_stdio_prepare"), 1);
      phase = "B12-resource-calls";
      const resources = await f.turn("codemode", { code: "return await tools.list_mcp_resources({server:'docs'});" });
      assert.equal(resources.isError, false, JSON.stringify(resources.result).slice(0, 192)); assert(JSON.stringify(resources.result).includes("own://sentinel"));
      const beforeOutside = count(f, "ordinary_admission_consume");
      const outside = await f.turn("codemode", { code: "return await tools.list_mcp_resources({server:'outside'});" });
      assert.equal(outside.isError, true); assert.equal(count(f, "ordinary_admission_consume"), beforeOutside);
      const ok = await f.turn("codemode", { code: "return await tools.mcp__docs__query({q:'ok'});" }); assert.equal(ok.isError, false);
      const bad = await f.turn("codemode", { code: "return await tools.mcp__docs__query({q:'fail'});" }); assert.equal(bad.isError, true);
      await f.runtime.dispose(); assert.equal(count(f, "ordinary_command_finish"), 1);
      return { public_manager_enable: true, public_sdk_synthetic_query: true, public_resource_list: true, outside_server_rejected: true, inner_failure: true, synthetic_receipt_close: true, actual_service_or_tui: false };
    }); result.status = "observed-components-only";
  } finally {
    for (const id of CASES) if (!result.cases.some(row => row.case_id === id)) result.cases.push({ case_id: id, outcome: "not-run", observations: {} });
    result.synthetic_budget = budget; const output = JSON.stringify(result) + "\n"; if (Buffer.byteLength(output) > LIMITS.result_bytes) fail();
    fs.writeFileSync("/work/probe-result.json", output, { mode: 0o600, flag: "wx" }); process.stdout.write(output);
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv[2] !== "--native-base-product-sdk-probe") { process.stderr.write("BASE_PRODUCT_REQUIRES_FROZEN_INPUTS_AND_SEPARATE_AUTHORIZATION\n"); process.exitCode = 2; }
  else { const timer = setTimeout(() => { process.stderr.write("BASE_PRODUCT_TIMEOUT\n"); process.exit(2); }, LIMITS.total_timeout_ms);
    try { await runNative(); } catch { process.stderr.write("BASE_PRODUCT_FAILED\n"); process.exitCode = 2; } finally { clearTimeout(timer); } }
}
