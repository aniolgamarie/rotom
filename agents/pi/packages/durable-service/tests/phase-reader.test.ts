import test from "node:test";
import assert from "node:assert/strict";
import { createDurablePhaseReader } from "../src/phase-reader.ts";

const SECRET = "SYNTHETIC_PRIVATE_READER_ERROR";
function token(name) { return { definition: { name, version: 1, initial() { return { phase: "fake" }; }, abort() {}, phases: { request() {}, summarize() {}, fake() {} } } }; }
function fixture() {
  const state = { permitted: true, calls: [], listeners: new Set(), disposals: 0, onVerify: null, onSnapshot: null, onTable: null, onSubscribe: null, lastDisposer: null };
  const builtin = [token("pi.generation"), token("pi.tool"), token("pi.compaction"), token("rotom.durable.request")];
  const generationTask = token("pi.generation"), compactionTask = token("pi.compaction");
  const toolItems = [{ name: "rotom_read", execute() {}, replay: "unsafe" }, { name: "rotom_search", execute() {}, replay: "unsafe" }];
  const extension = { name: "rotom.durable.readonly", tools: toolItems, tasks: [builtin[3]] }, installed = [extension];
  class Snapshot {
    record(method, args) { state.calls.push({ method, args, receiver: this }); state.onTable?.(method, args); }
    installed() { this.record("installed", [...arguments]); return installed; }
    extension(name) { this.record("extension", [...arguments]); return name === extension.name ? extension : undefined; }
    tools() { this.record("tools", [...arguments]); return toolItems.map(tool => ({ extension, tool })); }
    sections() { this.record("sections", [...arguments]); return []; }
    tasks() { this.record("tasks", [...arguments]); return [...builtin]; }
    task(name) { this.record("task", [...arguments]); return builtin.find(item => item.definition.name === name); }
  }
  const snapshot = new Snapshot(); let current = snapshot;
  class Base {
    snapshot() { assert.equal(this, base); state.calls.push({ method: "snapshot", args: [...arguments], receiver: this }); state.onSnapshot?.(); return current; }
    subscribe(listener) { assert.equal(this, base); assert.equal(arguments.length, 1); state.listeners.add(listener);
      state.onSubscribe?.(listener); const disposer = () => { state.disposals++; state.listeners.delete(listener); }; state.lastDisposer = disposer; return disposer; }
  }
  const base = new Base(), input = { base, generationTask, compactionTask, verifyCurrent: function() { assert.equal(this, input); state.calls.push({ method: "verify", args: [...arguments], receiver: this }); state.onVerify?.(); return state.permitted; } };
  function publish() { current = new Snapshot(); for (const listener of state.listeners) listener(); }
  return { state, builtin, generationTask, compactionTask, toolItems, extension, installed, snapshot, base, input, publish, create: () => createDurablePhaseReader(input) };
}
function invalid(call) { assert.throws(call, error => { assert.equal(error.message, "phase-reader-unavailable"); assert.equal(error.code, "phase-reader-unavailable"); assert.equal(error.cause, undefined); assert.ok(!String(error.stack).includes(SECRET)); return true; }); }

test("stable front projects exact two tokens and original untouched item refs", () => {
  const f = fixture(), result = f.create(), front = result.registry.snapshot();
  assert.ok(Object.isFrozen(result) && Object.isFrozen(result.registry) && Object.isFrozen(front));
  assert.deepEqual(Object.keys(result).sort(), ["check", "close", "registry"]); assert.deepEqual(Object.keys(result.registry).sort(), ["snapshot", "subscribe"]);
  assert.deepEqual(Object.keys(front).sort(), ["extension", "installed", "sections", "task", "tasks", "tools"]);
  assert.equal(result.registry.snapshot(), front);
  assert.deepEqual(front.tasks(), [f.generationTask, f.builtin[1], f.compactionTask, f.builtin[3]]);
  for (const task of front.tasks()) assert.equal(front.task(task.definition.name), task);
  assert.equal(front.task("unknown"), undefined); assert.equal(front.extension("unknown"), undefined); assert.equal(front.extension("rotom.durable.readonly"), f.extension);
  assert.equal(front.installed()[0], f.extension); assert.equal(front.tools()[0].tool, f.toolItems[0]); assert.equal(front.tools()[1].tool, f.toolItems[1]); assert.equal(front.tools()[0].extension, f.extension);
  assert.ok(Object.isFrozen(front.tasks()) && Object.isFrozen(front.installed()) && Object.isFrozen(front.tools()) && Object.isFrozen(front.tools()[0]) && Object.isFrozen(front.sections()));
  assert.ok(!Object.isFrozen(f.extension) && !Object.isFrozen(f.toolItems[0]) && !Object.isFrozen(f.generationTask) && !Object.isFrozen(f.generationTask.definition));
});

test("original inherited methods keep exact receiver and raw parameters once per check", () => {
  const f = fixture(), result = f.create(); f.state.calls.length = 0; assert.equal(result.check(), true);
  const counts = Object.fromEntries(["verify", "snapshot", "installed", "extension", "tools", "sections", "tasks", "task"].map(name => [name, f.state.calls.filter(call => call.method === name).length]));
  assert.deepEqual(counts, { verify: 1, snapshot: 1, installed: 1, extension: 1, tools: 1, sections: 1, tasks: 1, task: 4 });
  for (const call of f.state.calls) assert.equal(call.receiver, call.method === "verify" ? f.input : call.method === "snapshot" ? f.base : f.snapshot);
  assert.deepEqual(f.state.calls.filter(call => call.method === "task").map(call => call.args), [["pi.generation"], ["pi.tool"], ["pi.compaction"], ["rotom.durable.request"]]);
});

for (const source of ["verify", "snapshot", "table"]) test(`constructor first foreign ${source} cannot change supplied token baseline`, () => {
  const f = fixture(), mutate = () => { f.generationTask.definition.phases.request = () => undefined; };
  if (source === "verify") f.state.onVerify = mutate;
  if (source === "snapshot") f.state.onSnapshot = mutate;
  if (source === "table") f.state.onTable = mutate;
  invalid(f.create);
});

for (const drift of ["input", "base-prototype", "base-shadow", "snapshot-prototype", "snapshot-method", "generation-handler", "root-handler", "extension", "tool", "installed-array", "snapshot-publication"]) test(`current ${drift} permanently fails selection`, () => {
  const f = fixture(), result = f.create(), front = result.registry.snapshot();
  if (drift === "input") f.input.verifyCurrent = () => true;
  if (drift === "base-prototype") Object.setPrototypeOf(f.base, { snapshot: f.base.snapshot, subscribe: f.base.subscribe });
  if (drift === "base-shadow") f.base.snapshot = f.base.snapshot;
  if (drift === "snapshot-prototype") Object.setPrototypeOf(f.snapshot, { installed: f.snapshot.installed });
  if (drift === "snapshot-method") f.snapshot.tasks = () => [...f.builtin];
  if (drift === "generation-handler") f.generationTask.definition.phases.request = () => undefined;
  if (drift === "root-handler") f.builtin[3].definition.phases.fake = () => undefined;
  if (drift === "extension") f.extension.name = "foreign";
  if (drift === "tool") f.toolItems[0].execute = () => undefined;
  if (drift === "installed-array") f.installed.push(f.extension);
  if (drift === "snapshot-publication") f.publish();
  invalid(() => front.task("pi.generation")); invalid(result.check); invalid(result.registry.snapshot);
});

for (const drift of ["task-order", "duplicate-task", "tool-name", "extra-tool", "sections", "wrong-lookup", "wrong-extension", "same-new-token"]) test(`closed fixed initial table ${drift}`, () => {
  const f = fixture();
  if (drift === "task-order") f.builtin.reverse();
  if (drift === "duplicate-task") f.builtin[1] = f.builtin[0];
  if (drift === "tool-name") f.toolItems[0].name = "foreign";
  if (drift === "extra-tool") f.toolItems.push({ name: "extra" });
  if (drift === "sections") f.snapshot.sections = () => [{}];
  if (drift === "wrong-lookup") f.snapshot.task = () => f.builtin[0];
  if (drift === "wrong-extension") f.snapshot.extension = () => ({});
  if (drift === "same-new-token") f.input.generationTask = f.builtin[0];
  invalid(f.create);
});

test("last SDK lookup mutation is caught by pure final source check", () => {
  const f = fixture(), result = f.create(); let armed = true;
  f.state.onTable = (name, args) => { if (armed && name === "task" && args[0] === "rotom.durable.request") { armed = false; f.input.compactionTask.definition.phases.summarize = () => undefined; } };
  invalid(result.check); invalid(result.registry.snapshot);
});

for (const method of ["verify", "table", "subscribe"]) test(`synchronous ${method} callback reentry cannot publish qualified front`, () => {
  const f = fixture(), result = f.create(); const reenter = () => { try { result.check(); } catch {} };
  if (method === "verify") f.state.onVerify = reenter;
  if (method === "table") f.state.onTable = reenter;
  if (method === "subscribe") f.state.onSubscribe = reenter;
  invalid(method === "subscribe" ? () => result.registry.subscribe(() => {}) : result.check); invalid(result.check);
});

test("original listener/disposer identity and publication survive close without synthetic notification", () => {
  const f = fixture(), result = f.create(); let notifications = 0; const listener = () => { notifications++; };
  const disposer = result.registry.subscribe(listener); assert.equal(disposer, f.state.lastDisposer); assert.ok(!Object.isFrozen(disposer)); assert.equal(f.state.listeners.has(listener), true);
  f.publish(); assert.equal(notifications, 1); invalid(result.check);
  result.close(); assert.equal(notifications, 1); disposer(); assert.equal(f.state.disposals, 1); assert.equal(f.state.listeners.size, 0);
});

test("disposer returned before post-subscribe drift is explicitly cleaned exactly once", () => {
  const f = fixture(), result = f.create(); f.state.onSubscribe = () => { f.generationTask.definition.phases.request = () => undefined; };
  invalid(() => result.registry.subscribe(() => {})); assert.equal(f.state.disposals, 1); assert.equal(f.state.listeners.size, 0); invalid(result.check); assert.equal(f.state.disposals, 1);
});

test("unknown subscribe receipt never manufactures cleanup success", () => {
  const f = fixture(); f.base.subscribe = function(listener) { f.state.listeners.add(listener); throw Error(SECRET); };
  const result = f.create(); invalid(() => result.registry.subscribe(() => {})); assert.equal(f.state.disposals, 0); assert.equal(f.state.listeners.size, 1); invalid(result.check);
});

test("all front methods refuse after close but previously returned disposer works", () => {
  const f = fixture(), result = f.create(), front = result.registry.snapshot(), disposer = result.registry.subscribe(() => {});
  result.close(); result.close();
  for (const call of [result.check, result.registry.snapshot, () => result.registry.subscribe(() => {}), front.installed, front.tools, front.sections, front.tasks, () => front.task("pi.generation"), () => front.extension("rotom.durable.readonly")]) invalid(call);
  disposer(); assert.equal(f.state.disposals, 1);
});

for (const fault of ["config-getter", "config-proxy", "method-getter", "token-getter", "token-proxy", "returned-array-getter", "returned-proxy", "extra-config"]) test(`unsafe ${fault} rejected with zero traps`, () => {
  const f = fixture(); let traps = 0; const getter = () => { traps++; throw Error(SECRET); };
  if (fault === "config-getter") Object.defineProperty(f.input, "base", { enumerable: true, get: getter });
  if (fault === "config-proxy") f.input.base = new Proxy(f.base, { get: getter });
  if (fault === "method-getter") Object.defineProperty(f.base, "snapshot", { get: getter });
  if (fault === "token-getter") Object.defineProperty(f.generationTask.definition, "initial", { enumerable: true, get: getter });
  if (fault === "token-proxy") f.input.generationTask = new Proxy(f.generationTask, { get: getter });
  if (fault === "returned-array-getter") f.snapshot.tasks = () => { const array = [...f.builtin]; Object.defineProperty(array, "0", { get: getter }); return array; };
  if (fault === "returned-proxy") f.snapshot.tasks = () => new Proxy([...f.builtin], { get: getter });
  if (fault === "extra-config") f.input.extra = true;
  invalid(f.create); assert.equal(traps, 0);
});

test("ordinary rejected Promise verify is safely observed without permission or own then read", async () => {
  const f = fixture(); let reads = 0; const promise = Promise.reject(Error(SECRET)); Object.defineProperty(promise, "then", { get() { reads++; throw Error(SECRET); } }); f.state.permitted = promise;
  invalid(f.create); assert.equal(reads, 0); await new Promise(resolve => setImmediate(resolve));
});

test("unknown thenable getter and fulfilled unsafe constructor are never read", () => {
  let reads = 0; const f = fixture(); f.state.permitted = { get then() { reads++; throw Error(SECRET); } }; invalid(f.create);
  const g = fixture(), promise = Promise.resolve(true); Object.defineProperty(promise, "constructor", { get() { reads++; throw Error(SECRET); } }); g.state.permitted = promise; invalid(g.create); assert.equal(reads, 0);
});

test("own call/apply getters on original public methods ignored, original body/receiver runs", () => {
  const f = fixture(); let reads = 0;
  for (const method of [f.base.snapshot, f.base.subscribe, f.snapshot.tasks, f.input.verifyCurrent]) Object.defineProperty(method, "call", { get() { reads++; throw Error(SECRET); } });
  const result = f.create(); assert.equal(result.check(), true); const dispose = result.registry.subscribe(() => {}); dispose(); assert.equal(f.state.disposals, 1); assert.equal(reads, 0);
});

for (const resource of ["bytes", "depth", "nodes"]) test(`complete token source ${resource} bound`, () => {
  const f = fixture();
  if (resource === "bytes") f.generationTask.definition.hooks = { ["x".repeat(1024 * 1024 + 1)]: 1 };
  if (resource === "depth") { let node = {}; f.generationTask.definition.hooks = node; for (let i = 0; i < 65; i++) node = node.next = {}; }
  if (resource === "nodes") f.generationTask.definition.hooks = Array.from({ length: 4097 }, () => ({}));
  invalid(f.create); assert.equal(f.state.calls.length, 0);
});


test("selected method owner ancestor prototype drift is captured beyond the owner", () => {
  const f = fixture(), ancestor = Object.create(null);
  Object.setPrototypeOf(Object.getPrototypeOf(f.base), ancestor);
  const result = f.create(); Object.setPrototypeOf(ancestor, { foreign: true }); invalid(result.check);
});

for (const defect of ["initial", "abort", "phases", "request", "getter-handler", "proxy-handler", "input-field", "checkpoint-field", "migrate"]) test(`provided new task exact public definition rejects ${defect}`, () => {
  const f = fixture(), def = f.generationTask.definition; let reads = 0;
  if (["initial", "abort", "phases"].includes(defect)) delete def[defect];
  if (defect === "request") delete def.phases.request;
  if (defect === "getter-handler") Object.defineProperty(def.phases, "request", { get() { reads++; throw Error(SECRET); } });
  if (defect === "proxy-handler") def.phases.request = new Proxy(() => undefined, { apply() { reads++; throw Error(SECRET); } });
  if (defect === "input-field") def.input = {};
  if (defect === "checkpoint-field") def.checkpoint = {};
  if (defect === "migrate") def.migrate = undefined;
  invalid(f.create); assert.equal(reads, 0); assert.equal(f.state.calls.length, 0);
});

test("provided optional migrate/hooks public refs retained without tightening original Root definition", () => {
  const f = fixture(); f.generationTask.definition.migrate = () => undefined; f.generationTask.definition.hooks = { beforeRequest() {} };
  delete f.builtin[3].definition.abort;
  const result = f.create(); assert.equal(result.registry.snapshot().task("pi.generation"), f.generationTask);
  assert.equal(result.registry.snapshot().task("rotom.durable.request"), f.builtin[3]);
});

test("subscribe postcheck cleanup failure is once and remains fixed unknown", () => {
  const f = fixture(); const disposer = () => { f.state.disposals++; throw Error(SECRET); };
  f.base.subscribe = function(listener) { assert.equal(this, f.base); f.state.listeners.add(listener); f.generationTask.definition.phases.request = () => undefined; return disposer; };
  const result = f.create(); invalid(() => result.registry.subscribe(() => {})); assert.equal(f.state.disposals, 1); invalid(result.check); assert.equal(f.state.disposals, 1);
});
