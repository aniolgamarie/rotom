import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";
import sessionControl, { createBridge } from "../../agents/pi/templates/session-control.mjs";

const SESSION = "12345678-1234-4234-8234-123456789abc";
const NEXT = "87654321-4321-4321-8321-cba987654321";
const context = () => ({ state_root: "/synthetic/state", instance: "/synthetic/instance", profile: "pi-test",
  binding: { machine: "fixture", local: "/synthetic/local.toml", profile: "pi-test" },
  run_id: "a".repeat(32), initial_session: SESSION, lease_fd: null });
const environment = value => ({ ROTOM_PI_CONTROL_PYTHON: "/synthetic/python",
  ROTOM_PI_CONTROL_HELPER: "/synthetic/helper.py", ROTOM_PI_CONTROL_CONTEXT: JSON.stringify(value),
  PROVIDER_SECRET: "synthetic-private-canary", PYTHONPATH: "/synthetic/injected" });
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };
const unavailable = promise => assert.rejects(promise, { message: "pi_session_control_unavailable" });

function fixture({ config = context(), autoExit = true, spawnError = false } = {}) {
  const child = new EventEmitter();
  const stdin = new EventEmitter(), stdout = new EventEmitter();
  const state = { child, requests: [], writes: [], spawns: [], ended: 0, unavailable: 0, unrefs: [],
    timers: new Map(), nextTimer: 1, environment: environment(config) };
  child.stdin = stdin;
  child.stdout = stdout;
  child.unref = () => state.unrefs.push("child");
  child.kill = () => assert.fail("extension must not signal processes");
  stdin.unref = () => state.unrefs.push("stdin");
  stdout.unref = () => state.unrefs.push("stdout");
  stdin.write = line => {
    state.writes.push(line);
    state.requests.push(JSON.parse(line));
    return false;
  };
  stdin.end = () => {
    state.ended += 1;
    if (autoExit) { child.emit("exit", 0); child.emit("close", 0); }
  };
  state.emit = raw => stdout.emit("data", Buffer.isBuffer(raw) ? raw : Buffer.from(raw));
  state.reply = (seq = state.requests.at(-1).seq, ok = true) => state.emit(JSON.stringify({ seq, ok }) + "\n");
  state.options = {
    spawn: (...args) => {
      state.spawns.push(args);
      if (spawnError) throw Error("synthetic-private-spawn-error");
      return child;
    },
    setTimeout: (callback, duration) => {
      assert.equal(duration, 5000);
      const id = state.nextTimer++;
      state.timers.set(id, callback);
      return id;
    },
    clearTimeout: id => state.timers.delete(id),
    environment: state.environment,
    onUnavailable: () => { state.unavailable += 1; },
  };
  state.fire = id => {
    const callback = state.timers.get(id);
    assert.ok(callback, "expected active deadline");
    state.timers.delete(id);
    callback();
  };
  state.bridge = () => createBridge(config, state.options);
  return state;
}

function host(options = {}) {
  const state = fixture(options);
  state.events = new Map();
  state.notices = [];
  state.shutdowns = 0;
  state.exits = [];
  state.failureOrder = [];
  state.managerReads = [];
  state.current = { session: SESSION, file: "/synthetic/session.jsonl", cwd: "/synthetic/project" };
  state.ctx = {
    mode: "tui",
    hasUI: true,
    ui: {
      notify: (...args) => state.notices.push(args),
      custom: factory => {
        state.failureOrder.push("custom");
        return Promise.resolve(factory({ stop: () => { state.failureOrder.push("stop"); } }));
      },
    },
    abort: () => { state.failureOrder.push("abort"); return Promise.resolve(); },
    shutdown: () => { state.shutdowns += 1; },
    sessionManager: {
      getSessionId: () => { state.managerReads.push("id"); return state.current.session; },
      getSessionFile: () => { state.managerReads.push("file"); return state.current.file; },
      getCwd: () => { state.managerReads.push("cwd"); return state.current.cwd; },
    },
  };
  sessionControl({ on: (name, handler) => { assert.equal(state.events.has(name), false); state.events.set(name, handler); } }, {
    ...state.options,
    exit: code => { state.failureOrder.push("exit"); state.exits.push(code); },
  });
  state.event = (name, value = {}) => state.events.get(name)({ type: name, ...value }, state.ctx);
  state.start = async () => {
    const started = state.event("session_start", { reason: "startup" });
    await tick();
    state.reply();
    await started;
  };
  return state;
}

function terminated(state) {
  assert.deepEqual(state.exits, [4]);
  assert.deepEqual(state.failureOrder, ["abort", "custom", "stop", "exit"]);
  assert.equal(state.shutdowns, 0);
  assert.deepEqual(state.notices, []);
}

test("helper argv, minimal environment, shell=false and inherited lease fd mapping are exact", async () => {
  for (const fd of [null, 0, 17]) {
    const config = context();
    config.lease_fd = fd;
    const state = fixture({ config });
    const bridge = state.bridge();
    const [python, argv, options] = state.spawns[0];
    assert.equal(python, "/synthetic/python");
    assert.deepEqual(argv, ["-I", "/synthetic/helper.py"]);
    assert.equal(options.shell, false);
    assert.deepEqual(options.stdio, fd === null ? ["pipe", "pipe", "inherit"] : ["pipe", "pipe", "inherit", fd]);
    assert.deepEqual(options.env, { ROTOM_PI_CONTROL_CONTEXT: JSON.stringify({ ...config, lease_fd: fd === null ? null : 3 }),
      PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" });
    assert.equal(config.lease_fd, fd);
    assert.equal(JSON.stringify(options).includes("private-canary"), false);
    await bridge.close();
  }
});

test("initial claim waits for helper and only projects public session metadata", async () => {
  const state = host();
  assert.deepEqual([...state.events.keys()], ["session_start", "session_before_switch", "session_before_fork", "session_shutdown"]);
  let interactive = false;
  const started = state.event("session_start", { reason: "startup" }).then(() => { interactive = true; });
  await tick();
  assert.equal(interactive, false);
  assert.deepEqual(state.requests, [{ seq: 1, op: "claim", session: SESSION,
    file: "/synthetic/session.jsonl", cwd: "/synthetic/project" }]);
  assert.deepEqual(state.managerReads, ["id", "file", "cwd"]);
  state.reply();
  await started;
  assert.equal(interactive, true);
  assert.equal(state.shutdowns, 0);
  assert.deepEqual(state.exits, []);
  await state.event("session_shutdown", { reason: "quit" });
});

test("resume prepare completes before native open is allowed", async () => {
  const state = host();
  await state.start();
  const order = [];
  const switching = state.event("session_before_switch", { reason: "resume", targetSessionFile: "/synthetic/next.jsonl" })
    .then(result => { assert.equal(result, undefined); order.push("native-open"); });
  await tick();
  order.push("prepare-requested");
  assert.deepEqual(state.requests.at(-1), { seq: 2, op: "prepare", file: "/synthetic/next.jsonl" });
  assert.deepEqual(order, ["prepare-requested"]);
  state.reply();
  await switching;
  assert.deepEqual(order, ["prepare-requested", "native-open"]);
  state.current = { ...state.current, session: NEXT, file: "/synthetic/next.jsonl" };
  const started = state.event("session_start", { reason: "resume" });
  await tick();
  assert.deepEqual(state.requests.at(-1), { seq: 3, op: "claim", session: NEXT,
    file: "/synthetic/next.jsonl", cwd: "/synthetic/project" });
  state.reply();
  await started;
  await state.event("session_shutdown");
});

test("new and fork ping before allowing, and new unsaved session claims a null file", async () => {
  const state = host();
  await state.start();
  for (const [name, event] of [["session_before_switch", { reason: "new" }], ["session_before_fork", { entryId: "synthetic-entry", position: "at" }]]) {
    const operation = state.event(name, event);
    await tick();
    assert.deepEqual(state.requests.at(-1), { seq: state.requests.length, op: "ping" });
    state.reply();
    assert.equal(await operation, undefined);
  }
  state.current = { ...state.current, session: NEXT, file: undefined };
  const started = state.event("session_start", { reason: "new" });
  await tick();
  assert.equal(state.requests.at(-1).file, null);
  state.reply();
  await started;
  await state.event("session_shutdown");
});

for (const operation of ["claim", "resume", "new", "fork"]) {
  test(operation + " denial cancels and synchronously stops the TUI before exiting once", async () => {
    const state = host();
    if (operation !== "claim") await state.start();
    const request = operation === "claim" ? state.event("session_start")
      : operation === "fork" ? state.event("session_before_fork")
      : state.event("session_before_switch", { reason: operation, targetSessionFile: "/synthetic/target.jsonl" });
    await tick();
    state.reply(undefined, false);
    assert.deepEqual(await request, operation === "claim" ? undefined : { cancel: true });
    terminated(state);
    const count = state.requests.length;
    assert.deepEqual(await state.event("session_before_switch", { reason: "new" }), { cancel: true });
    assert.equal(state.requests.length, count);
    assert.equal(state.spawns.length, 1);
    terminated(state);
  });
}

test("queued requests are strictly sequential, even when stdin reports backpressure", async () => {
  const state = fixture();
  const bridge = state.bridge();
  const first = bridge.ping();
  const second = bridge.prepare("/synthetic/target.jsonl");
  const third = bridge.claim({ session: NEXT, file: null, cwd: "/synthetic/project" });
  await tick();
  assert.equal(state.requests.length, 1);
  state.reply();
  await first;
  await tick();
  assert.equal(state.requests.length, 2);
  state.reply();
  await second;
  await tick();
  assert.equal(state.requests.length, 3);
  state.reply();
  await third;
  assert.deepEqual(state.requests.map(row => row.seq), [1, 2, 3]);
  assert.equal(state.timers.size, 0);
  await bridge.close();
});

test("request timeout permanently refuses queued and future work without helper restart", async () => {
  const state = fixture({ autoExit: false });
  const bridge = state.bridge();
  const first = bridge.ping(), second = bridge.ping();
  await tick();
  state.fire([...state.timers.keys()][0]);
  await unavailable(first);
  await unavailable(second);
  await unavailable(bridge.ping());
  assert.equal(state.requests.length, 1);
  assert.equal(state.spawns.length, 1);
  assert.equal(state.unavailable, 1);
  assert.equal(bridge.available, false);
  state.reply(1);
  assert.equal(bridge.available, false);
});

const invalidReplies = [
  ["bad-json", "{synthetic-private-body}\n"],
  ["wrong-sequence", '{"seq":2,"ok":true}\n'],
  ["extra-field", '{"seq":1,"ok":true,"private":"synthetic-private-body"}\n'],
  ["duplicate-field", '{"seq":1,"seq":1,"ok":true}\n'],
  ["float-sequence", '{"seq":1.0,"ok":true}\n'],
  ["string-sequence", '{"seq":"1","ok":true}\n'],
  ["not-boolean", '{"seq":1,"ok":1}\n'],
  ["empty-line", "\n"],
  ["two-frames", '{"seq":1,"ok":true}\n{"seq":2,"ok":true}\n'],
  ["oversized-line", " ".repeat(16385)],
  ["invalid-utf8", Buffer.from([0xff, 10])],
];
for (const [name, raw] of invalidReplies) {
  test(name + " reply fails closed and never echoes raw output", async () => {
    const state = fixture();
    const bridge = state.bridge();
    const request = bridge.ping();
    await tick();
    state.emit(raw);
    await unavailable(request);
    await unavailable(bridge.ping());
    assert.equal(state.unavailable, 1);
    assert.equal(state.requests.length, 1);
  });
}

test("fragmented bounded JSON reply and reversed fields are accepted", async () => {
  const state = fixture();
  const bridge = state.bridge();
  const request = bridge.ping();
  await tick();
  state.emit('{"ok":true,');
  assert.equal(state.timers.size, 1);
  state.emit(' "seq":1}\n');
  await request;
  assert.equal(state.timers.size, 0);
  await bridge.close();
});

test("unsolicited output is refused before any request", async () => {
  const state = fixture();
  const bridge = state.bridge();
  state.reply(1);
  await unavailable(bridge.ping());
  assert.equal(state.requests.length, 0);
  assert.equal(state.unavailable, 1);
});

for (const event of ["exit", "close", "error", "stdout-end", "stdout-error", "stdin-error"]) {
  test(event + " helper failure stops the TUI before exiting once", async () => {
    const state = host({ autoExit: false });
    await state.start();
    if (event === "stdout-end") state.child.stdout.emit("end");
    else if (event === "stdout-error") state.child.stdout.emit("error", Error("synthetic-private-error"));
    else if (event === "stdin-error") state.child.stdin.emit("error", Error("synthetic-private-error"));
    else state.child.emit(event, event === "error" ? Error("synthetic-private-error") : 1);
    terminated(state);
    assert.deepEqual(await state.event("session_before_fork"), { cancel: true });
    assert.equal(state.spawns.length, 1);
  });
}

test("shutdown closes stdin, drains the active reply, refuses queued work, then waits for exit", async () => {
  const state = fixture({ autoExit: false });
  const bridge = state.bridge();
  const active = bridge.ping(), queued = bridge.ping();
  await tick();
  let closed = false;
  const closing = bridge.close().then(() => { closed = true; });
  assert.equal(state.ended, 1);
  assert.equal(closed, false);
  state.reply();
  await active;
  await unavailable(queued);
  assert.equal(state.requests.length, 1);
  assert.equal(closed, false);
  state.child.emit("exit", 0);
  state.child.emit("close", 0);
  await closing;
  assert.equal(state.timers.size, 0);
  assert.equal(state.unavailable, 0);
  assert.equal(state.ended, 1);
});

test("shutdown timeout only abandons waiting and never signals or restarts", async () => {
  const state = fixture({ autoExit: false });
  const bridge = state.bridge();
  const closing = bridge.close();
  assert.equal(bridge.close(), closing);
  state.fire([...state.timers.keys()][0]);
  await closing;
  assert.deepEqual(state.unrefs, ["child", "stdin", "stdout"]);
  assert.equal(state.spawns.length, 1);
  assert.equal(state.unavailable, 0);
  await unavailable(bridge.ping());
});

test("normal public session_shutdown closes helper without a failure notice", async () => {
  const state = host();
  await state.start();
  await state.event("session_shutdown", { reason: "quit" });
  assert.equal(state.ended, 1);
  assert.equal(state.shutdowns, 0);
  assert.deepEqual(state.exits, []);
  assert.deepEqual(state.failureOrder, []);
  assert.deepEqual(state.notices, []);
  assert.equal(state.timers.size, 0);
});

test("spawn failure and invalid configuration never expose environment or error body", async () => {
  const state = host({ spawnError: true });
  await state.event("session_start");
  terminated(state);
  await state.event("session_start");
  assert.equal(state.spawns.length, 1);
  const invalid = host();
  invalid.environment.ROTOM_PI_CONTROL_CONTEXT = "{synthetic-private-config}";
  await invalid.event("session_start");
  assert.equal(invalid.spawns.length, 0);
  terminated(invalid);
});

for (const [name, change] of [
  ["unknown-context-field", value => { value.extra = true; }],
  ["invalid-lease-fd", value => { value.lease_fd = -1; }],
  ["invalid-initial-session", value => { value.initial_session = "latest"; }],
  ["scope-profile-mismatch", value => { value.binding.profile = "other"; }],
  ["unsafe-helper-path", (_value, env) => { env.ROTOM_PI_CONTROL_HELPER = "relative"; }],
  ["oversized-context", value => { value.instance = "/" + "x".repeat(16384); }],
]) {
  test(name + " fails before spawning", () => {
    const value = context();
    const state = fixture({ config: value });
    change(value, state.environment);
    assert.throws(() => state.bridge(), { message: "pi_session_control_unavailable" });
    assert.equal(state.spawns.length, 0);
  });
}

test("invalid or oversized requests fail before writing and remain unavailable", async () => {
  for (const bad of ["relative", "/synthetic/../target", "/synthetic/target\0", "/" + "x".repeat(16384)]) {
    const state = fixture();
    const bridge = state.bridge();
    await unavailable(bridge.prepare(bad));
    assert.equal(state.requests.length, 0);
    await unavailable(bridge.ping());
    assert.equal(state.unavailable, 1);
  }
});


test("repeated child errors remain handled without printing exception bodies", async () => {
  const state = host({ autoExit: false });
  await state.start();
  state.child.emit("error", Error("synthetic-private-first"));
  state.child.emit("error", Error("synthetic-private-second"));
  terminated(state);
});

test("stdin write exception rejects the active and queued requests once", async () => {
  const state = fixture();
  const bridge = state.bridge();
  state.child.stdin.write = () => { throw Error("synthetic-private-write-error"); };
  const first = bridge.ping(), second = bridge.ping();
  await unavailable(first);
  await unavailable(second);
  assert.equal(state.unavailable, 1);
  assert.equal(state.spawns.length, 1);
  assert.equal(state.timers.size, 0);
});

test("claim unknown fields are refused without dropping them or sending a request", async () => {
  const state = fixture();
  const bridge = state.bridge();
  await unavailable(bridge.claim({ session: SESSION, file: null, cwd: "/synthetic/project", extra: true }));
  assert.equal(state.requests.length, 0);
  assert.equal(state.unavailable, 1);
});
