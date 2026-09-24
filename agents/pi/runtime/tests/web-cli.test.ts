import assert from "node:assert/strict";
import { test } from "node:test";
import { webNetworkCommand } from "../web-cli.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1");
function fixture() {
  const calls = [], cleanups = [], validators = [], timers = [];
  const operation = { id: "web-test", controller: new AbortController() };
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: { network: { routes: { direct: { mode: "direct" } } } } },
    web: { current: () => operation, route: () => "direct", cleanup: fn => cleanups.push(fn), verifyExternal: fn => validators.push(fn), track: value => value },
    supervisor: { async call(method, args) {
      calls.push({ method, args });
      if (method === "ordinary_web_cli_prepare") return { operation_id: "cli-job", lease_id: "cli-lease", kind: "command" };
      if (method === "ordinary_web_cli_authorize") return { valid: true, revoked: false };
      if (method === "reconcile") return { lease_id: "cli-lease", protected: false, termination_evidence: { verified: true } };
      if (method === "ordinary_command_finish") return { finished: true };
      throw new Error("unexpected method");
    } },
    ordinaryOperations: { async write(ticket, _content, _digest, signal, callbacks) {
      calls.push({ method: "execute", ticket, signal }); callbacks.onStarted();
      callbacks.onCapture({ stdout: Buffer.from("private bytes"), stderr: Buffer.alloc(0) });
      return { stdout: "synthetic output", terminationConfirmed: true, exitCode: 0, truncated: false };
    } },
  };
  const deps = { directoryFactory: async () => ({ path: "/private/acw-fixture", close: async () => calls.push({ method: "directory-close" }) }),
    proxyFactory: async (_runtime, name, path, options) => {
      assert.equal(name, "public"); assert.equal(options.routeName, "direct"); assert.equal(await options.authorize(), false);
      return { token: "b".repeat(64), socketPath: path, close: async () => calls.push({ method: "proxy-close" }) };
    }, setTimer(fn) { timers.push(fn); return 1; }, clearTimer(value) { calls.push({ method: "clear-timer", value }); } };
  globalThis[slot] = runtime;
  return { runtime, deps, calls, validators, cleanups, timers };
}
test("network media uses the existing supervised command and registers physical cleanup proof", async () => {
  const f = fixture();
  try {
    const result = await webNetworkCommand("youtube-info", { video_id: "abcdefghijk" }, f.deps);
    assert.equal(result.bytes.toString(), "private bytes");
    const request = f.calls.find(row => row.method === "ordinary_web_cli_prepare");
    assert.equal(request.args.token, "b".repeat(64)); assert.equal(request.args.socket_path, "/private/acw-fixture/proxy.sock");
    assert.equal(f.calls.filter(row => row.method === "execute").length, 1);
    assert.equal(await f.validators[0](), true);
    assert.equal(f.calls.some(row => row.method === "directory-close"), false);
    for (const cleanup of f.cleanups) await cleanup();
    assert.equal(f.calls.filter(row => row.method === "ordinary_command_finish").length, 1);
  } finally { delete globalThis[slot]; }
});
test("network media rejects incomplete capture and closes its proxy on preparation failure", async () => {
  for (const change of [{ terminationConfirmed: false }, { truncated: true }, { exitCode: 1 }]) {
    const f = fixture();
    try {
      f.runtime.ordinaryOperations.write = async () => ({ terminationConfirmed: true, truncated: false, exitCode: 0, ...change });
      await assert.rejects(webNetworkCommand("remote-frame", { url: "https://example.invalid/a", seconds: 1 }, f.deps), /WEB_CLI_FAILED/);
      assert.equal(f.calls.some(row => row.method === "proxy-close"), true);
    } finally { delete globalThis[slot]; }
  }
  const f = fixture();
  try {
    f.runtime.supervisor.call = async () => { throw new Error("synthetic preparation failure"); };
    await assert.rejects(webNetworkCommand("youtube-info", { video_id: "abcdefghijk" }, f.deps), /preparation failure/);
    assert.equal(f.calls.some(row => row.method === "proxy-close"), true);
    assert.equal(f.calls.some(row => row.method === "execute"), false);
  } finally { delete globalThis[slot]; }
});
test("revoked running CLI loses its existing network tunnel", async () => {
  const f = fixture();
  try {
    const original = f.runtime.supervisor.call;
    f.runtime.supervisor.call = async (method, args) => method === "ordinary_web_cli_authorize" ? { valid: false, revoked: true } : original(method, args);
    f.runtime.ordinaryOperations.write = async (_ticket, _content, _digest, _signal, callbacks) => {
      callbacks.onStarted(); f.timers[0](); await new Promise(resolve => setImmediate(resolve));
      assert.equal(f.calls.some(row => row.method === "proxy-close"), true);
      return { terminationConfirmed: true, exitCode: 1, truncated: false };
    };
    await assert.rejects(webNetworkCommand("youtube-info", { video_id: "abcdefghijk" }, f.deps), /WEB_CLI_FAILED/);
  } finally { delete globalThis[slot]; }
});

test("Git clone selects the GitHub service and publishes only the declared output root", async () => {
  const f = fixture();
  try {
    f.runtime.cwd = "/project";
    f.runtime.manifest.web_config = {};
    f.runtime.manifest.options.web = { github_clone: { root_ref: "clones" } };
    f.runtime.manifest.options.paths = { roots: { clones: { path: "/project/clones", purpose: "write" } } };
    const original = f.runtime.supervisor.call;
    f.runtime.supervisor.call = async (method, args) => {
      const result = await original(method, args);
      return method === "ordinary_web_cli_prepare" ? { ...result, destination: "/project/clones/clone-" + "a".repeat(32) } : result;
    };
    f.deps.proxyFactory = async (_runtime, service, socketPath) => {
      assert.equal(service, "github"); return { socketPath, token: "b".repeat(64), close: async () => {} };
    };
    const result = await webNetworkCommand("git-clone", { owner: "fixture", repo: "repository" }, f.deps);
    assert.equal(result.destination, "/project/clones/clone-" + "a".repeat(32));
    assert.equal(f.calls.find(row => row.method === "ordinary_web_cli_prepare").args.cwd, "/project");
    f.runtime.supervisor.call = async (method, args) => {
      const result = await original(method, args);
      return method === "ordinary_web_cli_prepare" ? { ...result, destination: "/outside/clone-" + "a".repeat(32) } : result;
    };
    await assert.rejects(webNetworkCommand("git-clone", { owner: "fixture", repo: "repository" }, f.deps), /DESTINATION_INVALID/);
  } finally { delete globalThis[slot]; }
});

test("a zero exit code cannot publish a CLI result when revocation races with completion", async () => {
  const f = fixture();
  try {
    const original = f.runtime.supervisor.call;
    f.runtime.supervisor.call = async (method, args) => method === "ordinary_web_cli_authorize" ? { valid: false, revoked: true } : original(method, args);
    await assert.rejects(webNetworkCommand("youtube-info", { video_id: "abcdefghijk" }, f.deps), /WEB_CLI_FAILED/);
  } finally { delete globalThis[slot]; }
});
