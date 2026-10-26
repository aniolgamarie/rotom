import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter, once } from "node:events";
import { fork } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { PassThrough } from "node:stream";
import { createAttempt, createEmitter } from "../fixtures/dsh-session-observer-probe/attempt.mjs";

const target = () => ({ sessionRef: { agent: "dsh", backend: "dsh", native_home_ref: "synthetic-home", native_ref: "synthetic-session" },
  cwd: "/synthetic/project", scope: "synthetic-scope", profile: "synthetic-profile", runtimeIdentity: "synthetic-runtime", previousRunId: "a".repeat(32) });
const observation = (changes = {}) => ({ kind: "foreground-observed", version: 1, agentBindingGeneration: 1,
  status: "idle", sessionRef: { backendId: "dsh", sessionId: "synthetic-session" }, sessionId: "synthetic-session",
  cwd: "/synthetic/project", observer_epoch: 1, observer_sequence: 1, ...changes });
const waiting = changes => ({ kind: "waiting", reason: "not-ready", observer_epoch: 1, observer_sequence: 1, ...changes });

class PrivateChild extends EventEmitter {
  connected = true;
  sent = [];
  send(value, callback) { this.sent.push(value); callback?.(); }
}
function wire(options) {
  const attempt = createAttempt(target(), options);
  const child = new PrivateChild();
  attempt.attach(child);
  const messages = [];
  const emit = createEmitter(attempt.request, message => { messages.push(message); child.emit("message", message); });
  return { attempt, child, messages, emit };
}
function unknown(value, reason) { assert.deepEqual(value.attempt.snapshot(), { kind: "unknown", reason }); }

// 状态名称有意只到 foreground-matched；这些都是仓库自有协议模型。
test("new run and nonce are fresh and target snapshots are independent", () => {
  const input = target(); const first = createAttempt(input); const second = createAttempt(input);
  assert.match(first.request.run_id, /^[a-f0-9]{32}$/);
  assert.match(first.request.nonce, /^[a-f0-9]{64}$/);
  assert.notEqual(first.request.run_id, input.previousRunId);
  assert.notEqual(first.request.run_id, second.request.run_id);
  assert.notEqual(first.request.nonce, second.request.nonce);
  input.sessionRef.native_ref = "mutated";
  assert.equal(first.request.sessionRef.native_ref, "synthetic-session");
  assert.equal(Object.isFrozen(first.request.sessionRef), true);
  assert.equal(Object.isFrozen(first.request), true);
  first.close(); second.close();
});

for (const [name, change] of [
  ["extra target field", input => { input.extra = true; }],
  ["wrong agent", input => { input.sessionRef.agent = "pi"; }],
  ["wrong backend", input => { input.sessionRef.backend = "claude"; }],
  ["relative cwd", input => { input.cwd = "relative"; }],
  ["empty scope", input => { input.scope = ""; }],
  ["blank scope", input => { input.scope = "   "; }],
  ["extra ref field", input => { input.sessionRef.loaded = true; }],
]) test(`rejects ${name} with constant request error`, () => {
  const input = target(); change(input);
  assert.throws(() => createAttempt(input), { message: "invalid resume probe request" });
});

test("launch removes inherited retry/handoff and fixes explicit backend and target", () => {
  const value = createAttempt(target());
  const env = { HOME: "/synthetic/home", DSH_TUI_RESUME_RETRY: "private-retry", DSH_TUI_BACKEND_HANDOFF: "private-handoff",
    DSH_TUI_HOST_ENTRY_PATH: "private-entry", DSH_TUI_BACKEND: "claude", DSH_TUI_RESUME_BACKEND: "claude",
    DSH_TUI_RESUME_SESSION: "wrong", DSH_TUI_HOST_ENTRY: "1" };
  const launch = value.launch(env, { backend: "dsh", sessionId: "synthetic-session" });
  for (const key of ["DSH_TUI_RESUME_RETRY", "DSH_TUI_BACKEND_HANDOFF", "DSH_TUI_HOST_ENTRY_PATH"]) assert.equal(Object.hasOwn(launch.env, key), false);
  assert.equal(launch.env.DSH_TUI_BACKEND, "dsh");
  assert.equal(launch.env.DSH_TUI_RESUME_BACKEND, "dsh");
  assert.equal(launch.env.DSH_TUI_RESUME_SESSION, "synthetic-session");
  assert.equal(launch.env.DSH_TUI_HOST_ENTRY, "0");
  assert.equal(launch.tuiConfig.backend, "dsh");
  assert.equal(launch.cwd, target().cwd);
  assert.deepEqual(launch.args, []);
  assert.equal(env.DSH_TUI_BACKEND, "claude");
  value.close();
});

for (const [config, args] of [[{ backend: "claude" }, []], [{ backend: "dsh", sessionId: "wrong" }, []], [{ backend: "dsh" }, ["--resume", "wrong"]]]) {
  test(`rejects competing launch selector ${JSON.stringify([config, args])}`, () => {
    const value = createAttempt(target());
    assert.throws(() => value.launch({}, config, args), { message: "invalid resume probe request" }); value.close();
  });
}

test("private message matching actual foreground stays explicitly native-unproven", () => {
  const value = wire(); value.emit(observation());
  const snapshot = value.attempt.snapshot();
  assert.equal(snapshot.kind, "foreground-matched");
  assert.equal(snapshot.native_load, "unproven");
  assert.equal(snapshot.launch_binding, "unproven");
  assert.equal(snapshot.binding_source, "parent-request-context");
  assert.deepEqual(snapshot.sessionRef, target().sessionRef);
  for (const forbidden of ["loaded", "restored", "seal", "input_ready"]) assert.equal(Object.hasOwn(snapshot, forbidden), false);
  value.attempt.close();
});

for (const [name, changes] of [
  ["native ID", { sessionRef: { backendId: "dsh", sessionId: "wrong" } }],
  ["backend", { sessionRef: { backendId: "claude", sessionId: "synthetic-session" } }],
  ["binding ID", { sessionId: "wrong" }], ["cwd", { cwd: "/synthetic/wrong" }],
]) test(`actual ${name} mismatch never matches`, () => {
  const value = wire(); value.emit(observation(changes)); unknown(value, "target-mismatch");
});

for (const field of ["run_id", "nonce"]) test(`old ${field} replay is rejected`, () => {
  const value = wire(); const old = createAttempt(target());
  const envelope = [];
  createEmitter(value.attempt.request, item => envelope.push(item))(observation());
  value.child.emit("message", { ...envelope[0], [field]: old.request[field] });
  unknown(value, "invalid-envelope"); old.close();
});

test("identical envelope replay is idempotent", () => {
  let changes = 0; const value = wire({ onChange() { changes++; } });
  value.emit(observation()); const before = value.attempt.snapshot();
  value.child.emit("message", structuredClone(value.messages[0]));
  assert.equal(value.attempt.snapshot(), before); assert.equal(changes, 1); value.attempt.close();
});

for (const [name, change] of [
  ["conflicting duplicate", message => ({ ...message, observation: observation({ status: "running" }) })],
  ["gap", message => ({ ...message, sequence: 3 })],
  ["epoch change", message => ({ ...message, sequence: 2, emitter_epoch: "f".repeat(32) })],
]) test(`envelope ${name} becomes unknown`, () => {
  const value = wire(); value.emit(observation()); value.child.emit("message", change(value.messages[0]));
  unknown(value, "observation-sequence-conflict");
});

for (const changes of [
  { observer_sequence: 1, version: 2 }, { observer_sequence: 2, observer_epoch: 2, version: 2 },
  { observer_sequence: 2, version: 0 }, { observer_sequence: 2, version: 2, agentBindingGeneration: 2 },
]) test(`observation binding change ${JSON.stringify(changes)} is rejected`, () => {
  const value = wire(); value.emit(observation()); value.emit(observation(changes)); unknown(value, changes.observer_sequence === 1 || changes.observer_epoch === 2 ? "observer-sequence-conflict" : "binding-changed");
});

test("unexpected loaded field is rejected instead of upgrading evidence", () => {
  const value = wire(); value.emit(observation({ loaded: true })); unknown(value, "invalid-observation");
});

test("waiting then exact foreground is accepted, but becoming unready later is unknown", () => {
  const value = wire(); value.emit(waiting());
  assert.equal(value.attempt.snapshot().kind, "waiting");
  value.emit(observation({ observer_sequence: 2 }));
  assert.equal(value.attempt.snapshot().kind, "foreground-matched");
  value.emit(waiting({ observer_sequence: 3 })); unknown(value, "binding-became-unready");
});

test("observer epoch cannot change between waiting and initial foreground", () => {
  const value = wire(); value.emit(waiting());
  value.emit(observation({ observer_epoch: 2, observer_sequence: 2 }));
  unknown(value, "observer-sequence-conflict");
});

for (const event of ["exit", "disconnect", "error"]) test(`private IPC ${event} invalidates current observation`, () => {
  const value = wire(); value.emit(observation());
  value.child.emit(event, event === "error" ? Error("synthetic-private-error") : 0);
  unknown(value, "observation-channel-lost");
  assert.equal(value.child.listenerCount("message"), 0);
});

test("onChange sync and async failures never disclose or escape", async () => {
  for (const onChange of [() => { throw Error("synthetic-private-sync"); }, async () => { throw Error("synthetic-private-async"); }]) {
    const value = wire({ onChange }); value.emit(observation());
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(value.attempt.snapshot().kind, "foreground-matched");
    assert.equal(JSON.stringify(value.attempt.snapshot()).includes("synthetic-private"), false);
    value.attempt.close();
  }
});

for (const failure of ["throw", "callback"]) test(`IPC send ${failure} is sanitized`, () => {
  const value = createAttempt(target()); const child = new PrivateChild();
  child.send = (request, callback) => { if (failure === "throw") throw Error("synthetic-private-send"); callback(Error("synthetic-private-send")); };
  value.attach(child); assert.deepEqual(value.snapshot(), { kind: "unknown", reason: "observation-channel-lost" });
});

test("close detaches listeners and ignores delayed messages", () => {
  const value = wire(); value.attempt.close(); value.emit(observation());
  unknown(value, "closed-before-observation"); assert.equal(value.child.listenerCount("message"), 0);
});

const fakeHost = fileURLToPath(new URL("../fixtures/dsh-session-observer-probe/fake-host.mjs", import.meta.url));
function readJsonLine(stream) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const cleanup = () => {
      stream.removeListener("data", data); stream.removeListener("end", end); stream.removeListener("error", error);
    };
    function parse(line) {
      cleanup();
      try { resolve(JSON.parse(line)); } catch { reject(Error("invalid fake stdout frame")); }
    }
    function error() { cleanup(); reject(Error("fake stdout unavailable")); }
    function data(chunk) {
      buffer += chunk;
      if (buffer.length > 16384) { error(); return; }
      const newline = buffer.indexOf("\n");
      if (newline >= 0) parse(buffer.slice(0, newline));
    }
    function end() { parse(buffer); }
    stream.setEncoding("utf8");
    stream.on("data", data); stream.once("end", end); stream.once("error", error);
  });
}

async function withFakeHost(mode, run, { managed = false } = {}) {
  const home = mkdtempSync(path.join(tmpdir(), "rotom-private-attempt-"));
  const environment = { HOME: home, DSH_HOME: path.join(home, "dsh"), XDG_CONFIG_HOME: path.join(home, "config"),
    XDG_DATA_HOME: path.join(home, "data"), XDG_CACHE_HOME: path.join(home, "cache"),
    XDG_STATE_HOME: path.join(home, "state"), PATH: "/usr/bin:/bin" };
  let entry = fakeHost;
  let args = [mode];
  let cwd;
  let attempt;
  let env = environment;
  let patch;
  if (managed) {
    cwd = path.join(home, "synthetic-project"); mkdirSync(cwd, { mode: 0o700 });
    const runtime = path.join(home, "runtime"); mkdirSync(runtime, { mode: 0o700 });
    writeFileSync(path.join(runtime, "package.json"), '{"private":true}');
    const module = (name, exports) => {
      const directory = path.join(runtime, "node_modules", name);
      mkdirSync(directory, { recursive: true, mode: 0o700 });
      const mapping = {};
      for (const [subpath, body] of Object.entries(exports)) {
        const filename = `${Object.keys(mapping).length}.mjs`;
        mapping[subpath] = `./${filename}`; writeFileSync(path.join(directory, filename), body);
      }
      writeFileSync(path.join(directory, "package.json"), JSON.stringify({ name, exports: mapping }));
    };
    module("@deepseek-ai/dsh", { "./profile-boot": `
      import { startFakeHost } from ${JSON.stringify(pathToFileURL(fakeHost).href)};
      export async function runProfile(options) {
        const layer = options.environment[0]; const values = layer.values;
        process.stdout.write(JSON.stringify({ profile: options.profile, args: options.args,
          patchFiles: options.patchFiles, source: layer.source, cwd: process.cwd(),
          backend: values.DSH_TUI_BACKEND, resumeBackend: values.DSH_TUI_RESUME_BACKEND,
          session: values.DSH_TUI_RESUME_SESSION, workspace: values.DSH_TUI_WORKSPACE_TARGET,
          hostEntry: values.DSH_TUI_HOST_ENTRY,
          inherited: ["DSH_TUI_RESUME_RETRY", "DSH_TUI_BACKEND_HANDOFF", "DSH_TUI_HOST_ENTRY_PATH"].some(key => key in values),
          packageArgs: options.packageManager.args.slice(1) }) + "\\n");
        startFakeHost({ actualCwd: process.cwd() });
      }
    ` });
    module("@deepseek-ai/dsh-launch-environment", { ".": "export function createLaunchEnvironmentSnapshot(layers) { return layers; }" });
    module("rotom-dsh-execution-environment", { "./environment": "export function mcpArguments() { return []; }" });
    patch = path.join(home, "synthetic.patch.yml"); writeFileSync(patch, "# synthetic fixture only\n");
    attempt = createAttempt({ ...target(), cwd });
    const prepared = attempt.launch({ ...environment, DSH_TUI_RESUME_RETRY: "synthetic-retry",
      DSH_TUI_BACKEND_HANDOFF: "synthetic-handoff", DSH_TUI_HOST_ENTRY_PATH: "synthetic-entry" }, { backend: "dsh" });
    env = prepared.env;
    entry = fileURLToPath(new URL("../../agents/dsh/templates/launch.mjs", import.meta.url));
    args = [runtime, patch, "--profile", "agentcfg", ...prepared.args];
  }
  const child = fork(entry, args, { execPath: process.execPath, execArgv: [], env, cwd,
    stdio: ["ignore", "pipe", "pipe", "ipc"] });
  const facts = managed ? readJsonLine(child.stdout) : undefined;
  facts?.catch(() => {});
  const exited = new Promise(resolve => child.once("exit", (code, signal) => resolve({ code, signal })));
  let stderr = ""; child.stderr.on("data", chunk => { stderr += chunk; });
  let timer;
  try {
    await Promise.race([run(child, { attempt, facts, cwd, patch }), new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(Error("offline fake IPC timed out")), 5000);
    })]);
  } finally {
    clearTimeout(timer);
    attempt?.close();
    let finishFailed = false;
    const disconnect = () => {
      try { if (child.connected) child.disconnect(); } catch { finishFailed = true; }
    };
    if (child.connected) {
      try { child.send({ control: "finish" }, error => {
        if (error) { finishFailed = true; disconnect(); }
      }); } catch { finishFailed = true; disconnect(); }
    }
    let exitTimer;
    const result = await Promise.race([exited, new Promise(resolve => {
      exitTimer = setTimeout(() => resolve(undefined), 3000);
    })]);
    clearTimeout(exitTimer);
    if (!result) {
      writeFileSync(path.join(home, "cleanup-status.json"), '{"status":"cleanup-incomplete"}', { mode: 0o600 });
      throw Error("offline fake cleanup incomplete");
    }
    rmSync(home, { recursive: true });
    assert.equal(result.signal, null);
    assert.equal(result.code, 0, "fake host must exit gracefully without signaling");
    assert.equal(stderr, "");
    if (finishFailed) throw Error("offline fake finish send failed");
  }
}

test("private child IPC uses public scene plus emitter and explicit graceful finish", { timeout: 10000 }, async () => {
  await withFakeHost("scene", async child => {
    let changed;
    const change = new Promise(resolve => { changed = resolve; });
    const value = createAttempt(target(), { onChange: changed });
    value.attach(child); await change;
    assert.equal(value.snapshot().kind, "foreground-matched");
    assert.equal(value.snapshot().native_load, "unproven");
    value.close();
  });
});

test("stdout forged receipt cannot replace private child message channel", { timeout: 10000 }, async () => {
  await withFakeHost("stdout-only", async child => {
    const output = readJsonLine(child.stdout); const value = createAttempt(target());
    value.attach(child); const frame = await output;
    assert.equal(frame.observation.kind, "foreground-observed");
    assert.equal(value.snapshot().kind, "waiting"); value.close();
  });
});

for (const mode of ["exit", "disconnect"]) test(`real private child ${mode} remains unknown`, { timeout: 10000 }, async () => {
  await withFakeHost(mode, async child => {
    let changed; const change = new Promise(resolve => { changed = resolve; });
    const value = createAttempt(target(), { onChange: changed }); value.attach(child); await change;
    assert.deepEqual(value.snapshot(), { kind: "unknown", reason: "observation-channel-lost" }); value.close();
  });
});

for (const changes of [{ observer_sequence: 3 }, { observer_epoch: 2, observer_sequence: 2 }]) {
  test(`waiting observer continuity ${JSON.stringify(changes)} fails closed`, () => {
    const value = wire(); value.emit(waiting()); value.emit(observation(changes));
    unknown(value, "observer-sequence-conflict");
  });
}

test("same-version contradictory agent status is rejected", () => {
  const value = wire(); value.emit(observation());
  value.emit(observation({ status: "running", observer_sequence: 2 })); unknown(value, "binding-changed");
});

test("requires-action is foreground metadata and never input-ready", () => {
  const value = wire(); value.emit(observation({ status: "requires-action" }));
  assert.equal(value.attempt.snapshot().kind, "foreground-matched");
  assert.equal(value.attempt.snapshot().native_load, "unproven");
  assert.equal(value.attempt.snapshot().launch_binding, "unproven");
  assert.equal(Object.hasOwn(value.attempt.snapshot(), "input_ready"), false); value.attempt.close();
});

test("cyclic envelopes fail without escaping the receiver", () => {
  const value = wire(); const messages = [];
  createEmitter(value.attempt.request, item => messages.push(item))(observation());
  messages[0].observation.self = messages[0];
  assert.doesNotThrow(() => value.child.emit("message", messages[0])); unknown(value, "invalid-envelope");
});

for (const member of ["on", "removeListener"]) test(`attach requires public ${member} method`, () => {
  const value = createAttempt(target()); const child = new PrivateChild(); child[member] = undefined;
  value.attach(child); assert.deepEqual(value.snapshot(), { kind: "unknown", reason: "invalid-observation-channel" });
});

test("fake initialized-later Agent counterexample never proves native load", { timeout: 10000 }, async () => {
  // 合成反例模型，不声称运行了真实 Core/TUI 的初始化或恢复路径。
  await withFakeHost("late-init-failure", async child => {
    const states = [];
    let ended; const end = new Promise(resolve => { ended = resolve; });
    const value = createAttempt(target(), { onChange(state) {
      states.push(state); if (state.kind === "unknown") ended();
    } });
    value.attach(child); await end;
    assert.equal(states[0].kind, "foreground-matched");
    assert.equal(states[0].native_load, "unproven");
    assert.equal(states[0].launch_binding, "unproven");
    assert.equal(states.at(-1).kind, "unknown");
    for (const state of states) {
      assert.equal(["loaded", "restored"].includes(state.kind), false);
      assert.equal(Object.hasOwn(state, "loaded"), false);
      assert.equal(Object.hasOwn(state, "restored"), false);
    }
    value.close();
  });
});

test("repository launcher reaches private IPC fake via temporary public runProfile stub", { timeout: 10000 }, async () => {
  // 只验证仓库 launcher 的假模块接线；没有实际官方配置解析或 native 恢复。
  await withFakeHost("scene", async (child, { attempt, facts, cwd, patch }) => {
    const message = once(child, "message"); attempt.attach(child); await message;
    assert.equal(attempt.snapshot().kind, "foreground-matched");
    assert.equal(attempt.snapshot().native_load, "unproven");
    assert.equal(attempt.snapshot().launch_binding, "unproven");
    assert.deepEqual(await facts, { profile: "agentcfg", args: [], patchFiles: [patch], source: "process", cwd,
      backend: "dsh", resumeBackend: "dsh", session: "synthetic-session", workspace: cwd,
      hostEntry: "0", inherited: false, packageArgs: ["--deny-package-operation"] });
    attempt.close();
  }, { managed: true });
});

test("stdout framing accepts fragmented JSON through newline or end", async () => {
  for (const newline of [true, false]) {
    const stream = new PassThrough(); const result = readJsonLine(stream);
    stream.write('{"observation":'); stream.write('{"kind":"foreground-');
    stream.end(`observed"}}${newline ? "\n" : ""}`);
    assert.deepEqual(await result, { observation: { kind: "foreground-observed" } });
  }
});

test("failed finish send still disconnects and cleans the offline fake child", { timeout: 10000 }, async () => {
  await assert.rejects(withFakeHost("scene", async child => {
    let changed; const change = new Promise(resolve => { changed = resolve; });
    const value = createAttempt(target(), { onChange: changed }); value.attach(child); await change;
    value.close();
    const send = child.send.bind(child);
    child.send = (message, ...args) => {
      if (message?.control === "finish") throw Error("synthetic-private-finish-failure");
      return send(message, ...args);
    };
  }), { message: "offline fake finish send failed" });
});
