import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createRuntime, validateProviders, fileCredentials } from "../../agents/dsh/packages/ssh-subscription-auth/index.mjs";
import { runAuth, terminalAsk, cursorLogin, createCliRuntime } from "../../agents/dsh/packages/ssh-subscription-auth/cli.mjs";

// 默认测试不加载第三方宿主，不访问真实账号或网络。
globalThis.fetch = () => { throw new Error("Network is forbidden in this test"); };

function output(tty = false) {
  return { isTTY: tty, text: "", write(value) { this.text += value; } };
}

function input() {
  const stream = new EventEmitter();
  return Object.assign(stream, { isTTY: true, isRaw: false, paused: true,
    setRawMode(value) { this.isRaw = value; }, isPaused() { return this.paused; },
    pause() { this.paused = true; }, resume() { this.paused = false; } });
}

function dependencies(records) {
  class Adapter {
    constructor(options, hasCredential) { Object.assign(this, { options, hasCredential }); }
    cancelRequests() { records.push("cancelRequests"); }
  }
  return {
    buildOAuthProfile(provider) { records.push(provider); return { retryPolicy: { maxRetries: 4 } }; },
    CredentialFile: class { constructor(file) { records.push(file); } async read() { return undefined; } },
    CredentialGatedAdapter: Adapter,
    createDshAuthApi(options) { records.push(options); return {}; },
    CREDENTIAL_REF: "CURSOR_SUBSCRIPTION_OAUTH",
    CursorCredentialStore: class { constructor(credentials, ref) { records.push(ref); this.credentials = credentials; } },
    CursorAuthService: class { constructor(store) { this.store = store; } },
    CursorLoginCoordinator: class { constructor(auth, options) { this.auth = auth; this.options = options; } },
    TerminalCursorAdapter: Adapter,
  };
}

test("provider config rejects unknown fields, duplicates and empty/unknown providers", () => {
  for (const value of [undefined, {}, { providers: [] }, { providers: ["codex", "codex"] },
    { providers: ["openai"] }, { providers: ["codex"], path: "/foreign" }]) {
    assert.throws(() => validateProviders(value));
  }
  assert.deepEqual(validateProviders({ providers: ["cursor", "codex"] }), ["cursor", "codex"]);
});

test("factory selects exact providers, local credential path, and disables retries", async () => {
  const temporary = await mkdtemp(path.join(os.tmpdir(), "subscription-auth-"));
  try {
    const own = path.join(temporary, "own");
    const other = path.join(temporary, "other");
    await mkdir(own, { mode: 0o700 });
    await mkdir(other, { mode: 0o700 });
    const sentinel = path.join(other, "credentials.json");
    await writeFile(sentinel, "foreign-account-sentinel", { mode: 0o600 });
    for (const selected of [["codex"], ["cursor"], ["codex", "cursor"]]) {
      const records = [];
      const credentials = {};
      const runtime = await createRuntime({ get: key => key === "credentials" ? credentials : undefined },
        { providers: selected }, { dependencies: dependencies(records), env: { DSH_HOME: own } });
      assert.deepEqual([...runtime.routes.keys()], selected);
      if (selected.includes("codex")) {
        const route = runtime.routes.get("codex");
        assert.equal(route.provider, "openai-codex");
        assert.equal(route.profile.retryPolicy.maxRetries, 0);
        assert.ok(records.includes(path.join(own, "dsh-auth", "credentials.json")));
        assert.equal(await route.adapter.options.resolveApiKey(), undefined);
      }
      if (selected.includes("cursor")) {
        assert.equal(runtime.routes.get("cursor").provider, "cursor-subscription");
        assert.equal(runtime.routes.get("cursor").adapter.options.retryCount, 0);
        assert.deepEqual(runtime.routes.get("cursor").adapter.options.fallbackModels, []);
      }
      await runtime.dispose();
    }
    assert.equal(await readFile(sentinel, "utf8"), "foreign-account-sentinel");
  } finally { await rm(temporary, { recursive: true }); }
});

test("credential facade accepts only current official file source and delegates writes", async () => {
  let source = "env";
  const writes = [];
  const credential = { resolve: async () => ({ value: "private", source }),
    set: (...args) => writes.push(args), unset: ref => writes.push(ref) };
  const facade = fileCredentials(credential);
  assert.equal(await facade.resolve("ref"), undefined);
  source = "project-env";
  assert.equal(await facade.resolve("ref"), undefined);
  source = "file";
  assert.equal((await facade.resolve("ref")).value, "private");
  await facade.set("ref", "new");
  await facade.unset("ref");
  assert.deepEqual(writes, [["ref", "new"], "ref"]);
});

test("minimal CLI context uses only the official credential plugin and public fiber lifecycle", async () => {
  for (const fail of [false, true]) {
    const records = [];
    const LocalCredentialProvider = class {};
    let disposed = 0;
    class Context {
      fiber = { dispose: async () => { disposed++; } };
      intercept(name, config) { assert.equal(name, "logger"); assert.deepEqual(config, { level: -1 }); return this; }
      provide(key, snapshot) { assert.equal(key, "launchEnvironment"); records.push(snapshot); }
      plugin(plugin, config) {
        assert.equal(plugin, LocalCredentialProvider);
        assert.deepEqual(config, { dshHome: "/synthetic/profile", watch: false });
        return { await: async () => { records.push("awaited"); if (fail) throw new Error("private-token"); } };
      }
      get() { return {}; }
    }
    const operation = createCliRuntime({ provider: "cursor", env: { DSH_HOME: "/synthetic/profile" },
      contextDependencies: { Context, LocalCredentialProvider, DSH_LAUNCH_ENVIRONMENT_KEY: "launchEnvironment",
        createLaunchEnvironmentSnapshot: layers => {
          assert.deepEqual(layers, [{ source: "process", values: { DSH_HOME: "/synthetic/profile" } }]);
          return "process-only";
        } }, runtimeDependencies: dependencies(records) });
    if (fail) {
      await assert.rejects(operation, error => !error.message.includes("private-token"));
    } else {
      const runtime = await operation;
      assert.deepEqual([...runtime.routes.keys()], ["cursor"]);
      assert.equal(disposed, 0);
      await runtime.dispose();
    }
    assert.equal(disposed, 1);
    assert.deepEqual(records.slice(0, 2), ["process-only", "awaited"]);
  }
});

test("CLI rejects invalid argv and non-TTY login before constructing runtime", async () => {
  const stderr = output();
  let calls = 0;
  const options = { stderr, stdout: output(), stdin: { isTTY: false }, runtime: () => { calls++; } };
  for (const argv of [[], ["codex"], ["codex", "login", "extra"], ["unknown", "status"], ["cursor", "unknown"], ["codex", "login"]]) {
    assert.equal(await runAuth(argv, options), 2);
  }
  assert.equal(calls, 0);
});

test("status allowlists metadata and disposes without invoking models or login", async () => {
  for (const provider of ["codex", "cursor"]) {
    const stdout = output();
    const stderr = output();
    let disposed = false;
    const privateStatus = { provider: "openai-codex", signedIn: true, authenticated: true,
      expiresAt: 123, token: "token-sentinel", authUrl: "https://private.invalid/auth" };
    const route = { provider: "openai-codex", api: { providers: async () => [privateStatus] },
      auth: { status: async () => privateStatus } };
    const result = await runAuth([provider, "status"], { env: { DSH_HOME: "/synthetic/profile" }, stdout, stderr,
      runtime: async () => ({ routes: new Map([[provider, route]]), dispose() { disposed = true; } }) });
    assert.equal(result, 0);
    assert.equal(disposed, true);
    assert.deepEqual(JSON.parse(stdout.text), { provider, authenticated: true, expiresAt: 123 });
    assert.equal(stderr.text, "");
  }
});

test("CLI errors hide provider secrets and dispose", async () => {
  const stdout = output();
  const stderr = output();
  let disposed = false;
  const result = await runAuth(["codex", "models"], { env: { DSH_HOME: "/synthetic/profile" }, stdout, stderr,
    runtime: async () => ({ routes: new Map([["codex", { provider: "openai-codex",
      adapter: { listModels: async () => { throw new Error("token-sentinel https://private.invalid"); } } }]]),
    dispose() { disposed = true; } }) });
  assert.equal(result, 5);
  assert.equal(disposed, true);
  assert.doesNotMatch(stdout.text + stderr.text, /token-sentinel|private.invalid/u);
});

test("CLI Cursor login only selects Cursor and keeps link out of stdout", async () => {
  const stdout = output();
  const stderr = output(true);
  let cancelled = 0;
  let disposed = 0;
  const result = await runAuth(["cursor", "login"], { env: { DSH_HOME: "/synthetic/profile" },
    stdin: input(), stdout, stderr, runtime: async ({ provider }) => {
      assert.equal(provider, "cursor");
      return { routes: new Map([["cursor", { coordinator: {
        start: async () => ({ id: "cursor", phase: "authenticated", authenticated: true,
          authUrl: "https://private.invalid/authorize?code=private-code" }),
        cancel: async () => { cancelled++; },
      } }]]), dispose() { disposed++; } };
    } });
  assert.equal(result, 0);
  assert.equal(cancelled, 1);
  assert.equal(disposed, 1);
  assert.doesNotMatch(stdout.text, /private.invalid|private-code/u);
  assert.match(stderr.text, /private.invalid/u);
});

test("CLI models only lists the selected route without calling a model", async () => {
  const stdout = output();
  const result = await runAuth(["cursor", "models"], { env: { DSH_HOME: "/synthetic/profile" },
    stdout, stderr: output(), runtime: async () => ({ routes: new Map([["cursor", {
      provider: "cursor-subscription", adapter: {
        listModels: async provider => {
          assert.equal(provider, "cursor-subscription");
          return [{ id: "fake-model" }, { id: "https://private.invalid" }];
        }, stream() { assert.fail("Models must not invoke inference"); },
      },
    }]]), dispose() {} }) });
  assert.equal(result, 0);
  assert.deepEqual(JSON.parse(stdout.text), { provider: "cursor", models: ["fake-model"] });
});

test("CLI timeout aborts a pending Codex login and drains cleanup", async () => {
  const order = [];
  const result = await runAuth(["codex", "login"], { env: { DSH_HOME: "/synthetic/profile" },
    stdin: input(), stdout: output(), stderr: output(true), timeoutMs: 10,
    runtime: async () => ({ routes: new Map([["codex", { provider: "openai-codex", api: {
      login: async (provider, signal) => {
        await new Promise(resolve => signal.addEventListener("abort", resolve, { once: true }));
        order.push("drained");
      },
    } }]]), dispose() { order.push("disposed"); } }) });
  assert.equal(result, 5);
  assert.deepEqual(order, ["drained", "disposed"]);
});

test("Cursor cancellation before ready uses public session id and drains", async () => {
  const controller = new AbortController();
  let ready;
  let cancelled;
  const route = { loginSessionId: "public-id", coordinator: {
    start: () => new Promise(resolve => { ready = resolve; }),
    cancel: async id => { cancelled = id; ready({ id, phase: "cancelled" }); },
  } };
  const operation = cursorLogin(route, output(true), controller.signal);
  controller.abort();
  await assert.rejects(operation);
  assert.equal(cancelled, "public-id");
});

test("Cursor failure cleans up and authorization URL stays in private terminal", async () => {
  const terminal = output(true);
  let cancelled = false;
  await assert.rejects(cursorLogin({ coordinator: {
    start: async () => ({ id: "one", phase: "failed", authUrl: "https://private.invalid/login" }),
    cancel: async id => { assert.equal(id, "one"); cancelled = true; },
  } }, terminal, new AbortController().signal));
  assert.equal(cancelled, true);
  assert.match(terminal.text, /https:\/\/private.invalid/u);
});

test("terminal waiting panel leaves manual code input available and restores raw mode", async () => {
  const stdin = input();
  const stderr = output(true);
  const ask = terminalAsk(stdin, stderr);
  const waitingController = new AbortController();
  const waiting = ask({ questions: [{ id: "dsh-auth-waiting", question: "Wait", detail: "private-url" }], signal: waitingController.signal });
  const result = ask({ questions: [{ id: "dsh-auth-prompt", question: "Code" }], signal: new AbortController().signal });
  assert.equal(stdin.isRaw, true);
  assert.equal(stdin.listenerCount("data"), 1);
  stdin.emit("data", Buffer.from("secret-code\r"));
  assert.equal((await result).answers[0].custom, "secret-code");
  assert.doesNotMatch(stderr.text, /secret-code/u);
  assert.equal(stdin.isRaw, false);
  assert.equal(stdin.listenerCount("data"), 0);
  waitingController.abort();
  await assert.rejects(waiting);
});

test("CLI SIGTERM cancels login and drains before disposal", async () => {
  const signals = new EventEmitter();
  const order = [];
  const result = runAuth(["codex", "login"], { env: { DSH_HOME: "/synthetic/profile" },
    signals, stdin: input(), stdout: output(), stderr: output(true), runtime: async () => ({
      routes: new Map([["codex", { provider: "openai-codex", api: { login: async (provider, signal) => {
        await new Promise(resolve => { signal.addEventListener("abort", resolve, { once: true });
          queueMicrotask(() => signals.emit("SIGTERM")); });
        order.push("drained");
      } } }]]), dispose() { order.push("disposed"); },
    }) });
  assert.equal(await result, 5);
  assert.deepEqual(order, ["drained", "disposed"]);
  assert.equal(signals.listenerCount("SIGTERM"), 0);
});

test("terminal manual code displays actions and distinguishes /3 from numeric codes", async () => {
  for (const response of ["/3", "123456"]) {
    const stdin = input();
    const stderr = output(true);
    const question = { id: "dsh-auth-prompt", question: "Manual code", detail: "Private authorization link",
      options: [{ label: "Copy link" }, { label: "Reopen browser" }, { label: "Cancel login" }] };
    const operation = terminalAsk(stdin, stderr)({ questions: [question], signal: new AbortController().signal });
    assert.match(stderr.text, /\/1\. Copy link\n\/2\. Reopen browser\n\/3\. Cancel login/u);
    stdin.emit("data", Buffer.from(response + "\r"));
    const result = (await operation).answers[0];
    if (response === "/3") {
      assert.deepEqual(result.selected, ["Cancel login"]);
      assert.equal(result.custom, undefined);
    } else {
      assert.deepEqual(result.selected, []);
      assert.equal(result.custom, "123456");
      assert.doesNotMatch(stderr.text, /123456/u);
    }
    assert.equal(stdin.isRaw, false);
    assert.equal(stdin.listenerCount("data"), 0);
  }
});

test("terminal action indices use strict decimal syntax and range", async () => {
  for (const [detail, response] of [[undefined, "2"], [undefined, "1e0"], [undefined, "01"],
    [undefined, "1.0"], ["Manual", "/03"], ["Manual", "/0"], ["Manual", "/4"]]) {
    const stdin = input();
    const question = { id: "select", question: "Choose", detail,
      options: [{ label: "First" }, { label: "Second" }, { label: "Third" }] };
    const operation = terminalAsk(stdin, output(true))({ questions: [question], signal: new AbortController().signal });
    stdin.emit("data", Buffer.from(response + "\r"));
    if (response === "2") assert.deepEqual((await operation).answers[0].selected, ["Second"]);
    else await assert.rejects(operation, /Invalid authentication action/u);
    assert.equal(stdin.isRaw, false);
    assert.equal(stdin.listenerCount("data"), 0);
  }
});

test("terminal cancellation restores raw mode and removes hidden input listener", async () => {
  for (const cancellation of ["signal", "ctrl-c"]) {
    const stdin = input();
    const stderr = output(true);
    const controller = new AbortController();
    const operation = terminalAsk(stdin, stderr)({ questions: [{ id: "manual", question: "Paste code",
      detail: "Private link", options: [{ label: "Cancel" }] }], signal: controller.signal });
    stdin.emit("data", Buffer.from("hidden-partial-code"));
    if (cancellation === "signal") controller.abort();
    else stdin.emit("data", Buffer.from("\x03"));
    await assert.rejects(operation, /cancelled/u);
    assert.equal(stdin.isRaw, false);
    assert.equal(stdin.isPaused(), true);
    assert.equal(stdin.listenerCount("data"), 0);
    assert.doesNotMatch(stderr.text, /hidden-partial-code/u);
  }
});
