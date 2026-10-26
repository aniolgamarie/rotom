import assert from "node:assert/strict";
import test from "node:test";
import { observeBinding } from "../fixtures/dsh-session-observer-probe/index.mjs";

function harness(overrides = {}, onRead = () => {}) {
  const state = { version: 1, ready: true, startupFailure: undefined, status: "idle",
    sessionRef: { backendId: "dsh", sessionId: "actual-session" }, sessionId: "actual-session",
    cwd: "/synthetic/actual", agentBindingGeneration: 1, ...overrides };
  const tasks = [];
  const observations = [];
  let listener;
  let unsubscribed = 0;
  let live = true;
  const reads = [];
  const channel = {};
  for (const key of Object.keys(state)) Object.defineProperty(channel, key, { get() {
    reads.push(key);
    onRead(key, state);
    if (!live) throw Error("synthetic-private-owner-ended");
    return state[key];
  } });
  for (const key of ["rows", "trace", "body", "agent", "history"]) {
    Object.defineProperty(channel, key, { get() { throw Error(`forbidden ${key}`); } });
  }
  channel.subscribe = callback => {
    listener = callback;
    return () => { unsubscribed++; };
  };
  const schedule = callback => { tasks.push(callback); };
  const start = () => observeBinding(channel, value => observations.push(value), { schedule });
  function drain() {
    let count = 0;
    while (tasks.length) {
      assert.ok(count++ < 30, "retry must be bounded");
      tasks.shift()();
    }
  }
  return { state, channel, reads, tasks, observations, schedule, start, drain,
    notify: () => listener(), revoke: () => { live = false; },
    unsubscribed: () => unsubscribed };
}

test("subscribes before reading and only emits deferred copied metadata", () => {
  const h = harness();
  let subscribed = false;
  const subscribe = h.channel.subscribe;
  h.channel.subscribe = fn => { subscribed = true; assert.deepEqual(h.reads, []); return subscribe(fn); };
  const dispose = h.start();
  assert.equal(subscribed, true);
  assert.deepEqual(h.observations, []);
  h.drain();
  const result = h.observations[0];
  assert.equal(result.kind, "foreground-observed");
  assert.equal(result.sessionRef.sessionId, "actual-session");
  assert.equal(result.cwd, "/synthetic/actual");
  assert.equal(result.observer_sequence, 1);
  assert.equal(Object.isFrozen(result), true);
  assert.equal(Object.isFrozen(result.sessionRef), true);
  for (const forbidden of ["loaded", "load_confirmed", "restored", "input_ready", "seal", "rows", "trace", "body"]) {
    assert.equal(Object.hasOwn(result, forbidden), false);
  }
  h.state.sessionRef.sessionId = "mutated-after-publication";
  assert.equal(result.sessionRef.sessionId, "actual-session");
  dispose();
});

test("change during subscribe and before first sample is included", () => {
  const h = harness();
  const subscribe = h.channel.subscribe;
  h.channel.subscribe = fn => {
    const unsubscribe = subscribe(fn);
    h.state.version = 2;
    h.state.sessionRef = { backendId: "dsh", sessionId: "during-subscribe" };
    h.state.sessionId = "during-subscribe";
    fn();
    return unsubscribe;
  };
  h.start();
  h.state.cwd = "/synthetic/before-sample";
  h.state.version = 3;
  h.notify();
  h.drain();
  assert.equal(h.observations.length, 1);
  assert.equal(h.observations[0].version, 3);
  assert.equal(h.observations[0].sessionRef.sessionId, "during-subscribe");
});

test("adoption tail rollback before deferred sample never confirms", () => {
  const h = harness();
  h.start();
  h.notify();
  h.revoke();
  h.drain();
  assert.deepEqual(h.observations.map(x => x.kind), ["unknown"]);
  assert.equal(JSON.stringify(h.observations).includes("synthetic-private"), false);
});

test("revocation between initial sample and final deferred read never confirms", () => {
  const h = harness();
  h.start();
  h.tasks.shift()();
  assert.equal(h.observations.length, 0);
  h.revoke();
  h.drain();
  assert.equal(h.observations[0].kind, "unknown");
});

for (const [name, changes, kind, reason] of [
  ["waiting", { ready: false, sessionId: "", sessionRef: { backendId: "dsh", sessionId: "" } }, "waiting", "not-ready"],
  ["starting", { status: "starting" }, "waiting", "not-ready"],
  ["disposed", { status: "disposed" }, "unknown", "binding-disposed"],
  ["failure", { startupFailure: "synthetic-private-error" }, "unknown", "startup-failed"],
]) test(`${name} is never foreground success`, () => {
  const h = harness(changes);
  h.start(); h.drain();
  assert.equal(h.observations[0].kind, kind);
  assert.equal(h.observations[0].reason, reason);
  assert.equal(JSON.stringify(h.observations).includes("synthetic-private"), false);
});

test("dispose cancels scheduled and late notifications and unsubscribes once", () => {
  const h = harness();
  const dispose = h.start();
  dispose(); dispose();
  h.notify(); h.drain();
  assert.equal(h.unsubscribed(), 1);
  assert.deepEqual(h.observations, []);
});

test("default microtask scheduler emits only after synchronous tail", async () => {
  const h = harness();
  const result = [];
  const dispose = observeBinding(h.channel, item => result.push(item));
  assert.equal(result.length, 0);
  h.revoke();
  await new Promise(resolve => queueMicrotask(() => queueMicrotask(resolve)));
  assert.equal(result[0].kind, "unknown");
  dispose();
});

test("changes between deferred cuts retry to one current snapshot", () => {
  const h = harness(); h.start();
  h.tasks.shift()();
  h.state.version++; h.state.agentBindingGeneration++;
  h.state.cwd = "/synthetic/new";
  h.notify(); h.drain();
  assert.equal(h.observations.length, 1);
  assert.equal(h.observations[0].cwd, "/synthetic/new");
});

test("continuous races exhaust finite retries with unknown", () => {
  const h = harness(); h.start();
  let steps = 0;
  while (h.tasks.length) {
    assert.ok(steps++ < 15);
    h.state.version++;
    h.tasks.shift()();
  }
  assert.deepEqual(h.observations.map(x => x.kind), ["unknown"]);
});

for (const [name, change] of [
  ["version rollback", h => { h.state.version = 0; }],
  ["generation rollback", h => { h.state.version++; h.state.agentBindingGeneration = 0; }],
  ["same-version identity contradiction", h => { h.state.cwd = "/synthetic/contradiction"; }],
]) test(name, () => {
  const h = harness(); h.start(); h.drain();
  change(h); h.notify(); h.drain();
  assert.equal(h.observations.at(-1).kind, "unknown");
  assert.equal(h.observations.at(-1).reason, "inconsistent-binding");
});

for (const [name, changes] of [
  ["unsafe version", { version: Number.NaN }],
  ["noninteger generation", { agentBindingGeneration: 1.5 }],
  ["contradictory ID", { sessionId: "different" }],
  ["invalid cwd", { cwd: {} }],
  ["unknown status", { status: "invented" }],
]) test(`invalid ${name} is unknown`, () => {
  const h = harness(changes); h.start(); h.drain();
  assert.equal(h.observations[0].kind, "unknown");
});

test("self-observation epochs differ and sequence describes snapshots only", () => {
  const h = harness(); const other = harness();
  h.start(); other.start(); h.drain(); other.drain();
  assert.notEqual(h.observations[0].observer_epoch, other.observations[0].observer_epoch);
  h.state.version += 4; h.notify(); h.notify(); h.drain();
  assert.equal(h.observations.at(-1).observer_sequence, 2);
  assert.equal(h.observations.at(-1).version, 5);
});


test("version and generation mutation during a read cannot publish a mixed snapshot", () => {
  let mutate = true;
  const h = harness({}, (key, state) => {
    if (key === "cwd" && mutate) {
      mutate = false;
      state.version++; state.agentBindingGeneration++;
      state.sessionRef = { backendId: "dsh", sessionId: "new-session" };
      state.sessionId = "new-session";
      state.cwd = "/synthetic/new-cut";
    }
  });
  h.start(); h.drain();
  assert.equal(h.observations.length, 1);
  assert.equal(h.observations[0].sessionRef.sessionId, "new-session");
  assert.equal(h.observations[0].cwd, "/synthetic/new-cut");
});

test("continually changing getters terminate as unknown", () => {
  const h = harness({}, (key, state) => { if (key === "cwd") state.version++; });
  h.start(); h.drain();
  assert.deepEqual(h.observations.map(x => x.kind), ["unknown"]);
});

test("failed subscription cannot leave a queued successful sample", () => {
  const h = harness();
  h.channel.subscribe = callback => { callback(); throw Error("synthetic-private-subscribe"); };
  h.start(); h.drain();
  assert.deepEqual(h.observations.map(x => x.kind), ["unknown"]);
  assert.equal(JSON.stringify(h.observations).includes("synthetic-private"), false);
});

test("disposed observer ignores late callbacks after a successful sample", () => {
  const h = harness(); const dispose = h.start(); h.drain();
  dispose(); h.revoke(); h.notify(); h.drain();
  assert.equal(h.observations.length, 1);
  assert.equal(h.unsubscribed(), 1);
});

test("unchanged snapshots are deduplicated without promising event delivery", () => {
  const h = harness(); h.start(); h.drain();
  h.notify(); h.notify(); h.drain();
  assert.equal(h.observations.length, 1);
});

for (const field of ["version", "agentBindingGeneration"]) {
  test(`${field} rollback inside a torn read remains unknown`, () => {
    let rollback = true;
    const h = harness({}, (key, state) => {
      if (key === "cwd" && rollback) { rollback = false; state[field] = 0; }
    });
    h.start(); h.drain();
    assert.deepEqual(h.observations.map(x => x.kind), ["unknown"]);
    assert.equal(h.observations[0].reason, "inconsistent-binding");
  });
}

// 纯内存事务模型；不是实际 Core、native writer 或上游回执的通过证据。
class FakeNativeHost {
  constructor(store, view, { readHistory = async stored => [...stored.history], drain = Promise.resolve() } = {}) {
    this.store = store;
    this.view = view;
    this.readHistory = readHistory;
    this.drain = drain;
    this.closing = undefined;
    this.trace = [];
    this.key = undefined;
    this.closed = false;
    this.bound = false;
  }

  async start(request) {
    if (this.closed || this.key !== undefined) throw Error("host-already-used");
    const key = request.sessionId;
    if (this.store.writers.has(key)) throw Error("writer-conflict");
    // writer 属于宿主；父观察者既不 acquire，也不接收可转移的锁证据。
    this.key = key;
    this.store.writers.set(key, this);
    this.trace.push("writer-acquired");
    try {
      this.trace.push("strict-open");
      const stored = this.store.sessions.get(key);
      if (!stored) throw Error("session-not-found");
      this.trace.push("history-read");
      await this.readHistory(stored);
      if (this.closed || this.store.writers.get(key) !== this) throw Error("writer-lost");
      // 仅合成宿主知道 history 完成；公开 Channel probe 不能替它作此证明。
      const receipt = Object.freeze({ kind: "synthetic-host-history-publication",
        sessionId: stored.sessionId, cwd: stored.cwd });
      this.trace.push("publication");
      Object.assign(this.view.state, {
        version: this.view.state.version + 1,
        agentBindingGeneration: this.view.state.agentBindingGeneration + 1,
        sessionRef: { backendId: "dsh", sessionId: stored.sessionId },
        sessionId: stored.sessionId, cwd: stored.cwd, ready: true, status: "idle",
      });
      this.bound = true;
      this.trace.push("foreground");
      this.view.notify();
      return receipt;
    } catch (error) {
      if (!this.closed) this.releaseWriter();
      throw error;
    }
  }

  releaseWriter() {
    if (this.store.writers.get(this.key) === this) {
      this.store.writers.delete(this.key);
      this.trace.push("release");
    }
  }

  close() {
    if (this.closing) return this.closing;
    this.closed = true;
    if (this.bound) {
      this.view.state.version++;
      this.view.state.ready = false;
      this.view.state.status = "disposed";
      this.view.notify();
    }
    this.closing = Promise.resolve().then(() => this.drain).finally(() => this.releaseWriter());
    return this.closing;
  }
}

function nativeFixture() {
  const store = {
    sessions: new Map([["target", { sessionId: "target", cwd: "/synthetic/stored", history: ["synthetic-event"] }]]),
    writers: new Map(), createCalls: 0,
    create() { this.createCalls++; throw Error("creating a replacement is forbidden"); },
  };
  const makeHost = options => {
    const view = harness({ ready: false, status: "starting", sessionId: "",
      sessionRef: { backendId: "dsh", sessionId: "" }, cwd: "/synthetic/launch" });
    view.start(); view.drain();
    return new FakeNativeHost(store, view, options);
  };
  return { store, makeHost };
}

test("fake host keeps writer after publication until explicit close and allows reopening", async () => {
  const { store, makeHost } = nativeFixture();
  const first = makeHost(); const second = makeHost();
  const receipt = await first.start({ sessionId: "target", cwd: "/synthetic/request" });
  assert.equal(receipt.kind, "synthetic-host-history-publication");
  assert.deepEqual(first.trace, ["writer-acquired", "strict-open", "history-read", "publication", "foreground"]);
  assert.equal(store.writers.get("target"), first);
  await assert.rejects(second.start({ sessionId: "target" }), /writer-conflict/);
  assert.equal(second.trace.includes("history-read"), false);
  await first.close(); await first.close();
  assert.equal(store.writers.has("target"), false);
  await second.start({ sessionId: "target" });
  assert.equal(store.writers.get("target"), second);
  await second.close();
});

test("fake external writer prevents entering strict history load", async () => {
  const { store, makeHost } = nativeFixture();
  const externalWriter = Object.freeze({ source: "synthetic-external" });
  store.writers.set("target", externalWriter);
  let reads = 0;
  const host = makeHost({ readHistory: async () => { reads++; return []; } });
  await assert.rejects(host.start({ sessionId: "target" }), /writer-conflict/);
  assert.equal(reads, 0);
  assert.deepEqual(host.trace, []);
  await host.close();
  assert.equal(store.writers.get("target"), externalWriter);
});

test("fake competing host cannot acquire while history read is pending", async () => {
  const { store, makeHost } = nativeFixture();
  let releaseHistory;
  let enteredHistory;
  const entered = new Promise(resolve => { enteredHistory = resolve; });
  const history = new Promise(resolve => { releaseHistory = resolve; });
  const first = makeHost({ readHistory: async () => { enteredHistory(); return history; } });
  const opening = first.start({ sessionId: "target" });
  await entered;
  assert.equal(store.writers.get("target"), first);
  assert.equal(first.view.state.ready, false);
  assert.equal(first.trace.includes("publication"), false);
  const competitor = makeHost();
  await assert.rejects(competitor.start({ sessionId: "target" }), /writer-conflict/);
  releaseHistory(["synthetic-event"]);
  await opening;
  assert.equal(store.writers.get("target"), first);
  await first.close();
});

test("fake missing target does not create, bind or become ready", async () => {
  const { store, makeHost } = nativeFixture(); const host = makeHost();
  await assert.rejects(host.start({ sessionId: "missing" }), /session-not-found/);
  assert.equal(store.createCalls, 0);
  assert.equal(store.sessions.has("missing"), false);
  assert.equal(store.writers.has("missing"), false);
  assert.equal(host.view.state.ready, false);
  assert.equal(host.view.state.sessionId, "");
  assert.equal(host.trace.includes("history-read"), false);
  assert.equal(host.trace.includes("foreground"), false);
});

test("fake failed history read releases only its writer and never binds", async () => {
  const { store, makeHost } = nativeFixture();
  const host = makeHost({ readHistory: async () => { throw Error("synthetic-history-failure"); } });
  await assert.rejects(host.start({ sessionId: "target" }), /synthetic-history-failure/);
  assert.equal(store.writers.has("target"), false);
  assert.equal(store.createCalls, 0);
  assert.equal(host.view.state.ready, false);
  assert.equal(host.view.state.sessionId, "");
  assert.equal(host.trace.includes("publication"), false);
  assert.equal(host.trace.includes("foreground"), false);
  const retry = makeHost(); await retry.start({ sessionId: "target" }); await retry.close();
});

test("fake host publication and probe foreground metadata remain independent", async () => {
  const { store, makeHost } = nativeFixture();
  // 请求值不是实际观测；此模型不含恢复协调器，不会把身份不匹配判成 restored。
  store.sessions.set("lookup-target", { sessionId: "actual-native-id", cwd: "/synthetic/actual-native", history: [] });
  const host = makeHost();
  const receipt = await host.start({ sessionId: "lookup-target", cwd: "/synthetic/requested" });
  host.view.drain();
  const metadata = host.view.observations.at(-1);
  assert.equal(receipt.kind, "synthetic-host-history-publication");
  assert.equal(metadata.kind, "foreground-observed");
  assert.equal(metadata.sessionRef.sessionId, "actual-native-id");
  assert.equal(metadata.cwd, "/synthetic/actual-native");
  assert.notEqual(metadata, receipt);
  for (const key of ["loaded", "history", "restored", "input_ready", "seal"]) assert.equal(Object.hasOwn(metadata, key), false);
  await host.close();
});

test("fake close retains writer throughout drain and memoizes completion", async () => {
  const { store, makeHost } = nativeFixture();
  let finishDrain;
  const drain = new Promise(resolve => { finishDrain = resolve; });
  const host = makeHost({ drain });
  await host.start({ sessionId: "target" });
  const closing = host.close();
  assert.equal(host.close(), closing);
  assert.equal(host.view.state.ready, false);
  await assert.rejects(host.start({ sessionId: "target" }), /host-already-used/);
  assert.equal(store.writers.get("target"), host);
  const competitor = makeHost();
  await assert.rejects(competitor.start({ sessionId: "target" }), /writer-conflict/);
  finishDrain(); await closing;
  assert.equal(store.writers.has("target"), false);
  await competitor.start({ sessionId: "target" });
  await competitor.close();
  assert.equal(host.trace.filter(value => value === "release").length, 1);
});

test("fake drain rejection cleans its owner but never publishes late history or seal", async () => {
  const { store, makeHost } = nativeFixture();
  let failDrain;
  let finishHistory;
  const drain = new Promise((resolve, reject) => { failDrain = reject; });
  const history = new Promise(resolve => { finishHistory = resolve; });
  const host = makeHost({ drain, readHistory: async () => history });
  const opening = host.start({ sessionId: "target" });
  const closing = host.close();
  assert.equal(host.close(), closing);
  const rejectedClose = assert.rejects(closing, /synthetic-drain-failure/);
  finishHistory([]);
  await assert.rejects(opening, /writer-lost/);
  assert.equal(store.writers.get("target"), host);
  assert.equal(host.trace.includes("publication"), false);
  assert.equal(host.trace.includes("foreground"), false);
  failDrain(Error("synthetic-drain-failure"));
  await rejectedClose;
  assert.equal(store.writers.has("target"), false);
  assert.equal(host.close(), closing);
  await assert.rejects(host.close(), /synthetic-drain-failure/);
  host.view.drain();
  assert.equal(host.view.observations.some(value => value.kind === "foreground-observed"), false);
  assert.equal(host.trace.some(value => ["loaded", "seal", "persisted"].includes(value)), false);
  assert.equal(host.trace.filter(value => value === "release").length, 1);
});
