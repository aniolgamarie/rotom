import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

const NOTICE = "Pi 会话写入保护不可用；请核验运行归属后重新启动。";
const extension = new URL("../../agents/pi/templates/session-control.mjs", import.meta.url).href;

// 真实子进程执行仓库扩展；helper 和宿主上下文均为假对象，不启动第三方宿主。
const script = String.raw`
import { EventEmitter } from "node:events";
import { writeSync } from "node:fs";
const [scenario, mode, extension, cleanup] = process.argv.slice(1);
const { default: sessionControl } = await import(extension);
const mark = value => writeSync(1, value + "\n");
const continuation = () => mark("CONTINUED");
const extensionMessage = () => mark("EXTENSION_MESSAGE");
const handlers = new Map();
const child = new EventEmitter();
child.stdin = new EventEmitter();
child.stdout = new EventEmitter();
let ended = false;
child.stdin.end = () => {
  if (ended) return;
  ended = true;
  mark("HELPER_CLOSED");
  child.emit("exit", 0);
  child.emit("close", 0);
};
child.stdin.write = line => {
  const request = JSON.parse(line);
  if (scenario !== "request-timeout") {
    queueMicrotask(() => {
      if (scenario === "claim-denied") queueMicrotask(extensionMessage);
      child.stdout.emit("data", Buffer.from(JSON.stringify({ seq: request.seq, ok: scenario !== "claim-denied" }) + "\n"));
    });
  }
  return true;
};
const context = {
  state_root: "/synthetic/state", instance: "/synthetic-private-context", profile: "pi-test",
  binding: { machine: "fixture", local: "/synthetic/local.toml", profile: "pi-test" },
  run_id: "a".repeat(32), initial_session: null, lease_fd: null,
};
const environment = {
  ROTOM_PI_CONTROL_CONTEXT: JSON.stringify(context), ROTOM_PI_CONTROL_PYTHON: "/synthetic/python",
  ROTOM_PI_CONTROL_HELPER: "/synthetic/helper.py", PROVIDER_SECRET: "synthetic-private-secret",
};
const ctx = {
  ui: {
    notify() {},
    custom(factory) {
      mark("CUSTOM_ENTERED");
      if (cleanup === "custom-throws") throw Error("synthetic-private-custom-error");
      if (cleanup === "custom-rejects") return Promise.reject(Error("synthetic-private-custom-rejection"));
      // 假 stop 只验证同步清理顺序；真实终端恢复由独立原生探针核验。
      const component = factory({ stop() {
        mark("TUI_STOP_REQUESTED");
        if (cleanup === "stop-throws") throw Error("synthetic-private-stop-error");
        mark("TUI_STOP_COMPLETED");
      } });
      return Promise.resolve(component);
    },
  },
  abort() { mark("ABORT_REQUESTED"); },
  shutdown() { mark("SHUTDOWN_REQUESTED"); },
  sessionManager: {
    getSessionId: () => "12345678-1234-4234-8234-123456789abc",
    getSessionFile: () => null,
    getCwd: () => "/synthetic/project",
  },
};
if (mode !== "unknown") {
  ctx.mode = mode;
  ctx.hasUI = mode === "rpc" || mode === "tui";
}
sessionControl({ on: (name, handler) => handlers.set(name, handler) }, {
  environment,
  spawn() {
    if (scenario === "spawn-error") {
      queueMicrotask(extensionMessage);
      throw Error("synthetic-private-spawn-error");
    }
    return child;
  },
  setTimeout(callback, duration) {
    if (duration !== 5000) throw Error("unexpected deadline");
    if (scenario === "request-timeout") {
      queueMicrotask(() => {
        queueMicrotask(extensionMessage);
        callback();
      });
    }
    return 1;
  },
  clearTimeout() {},
});
await handlers.get("session_start")({ type: "session_start", reason: "startup" }, ctx);
if (scenario === "normal") {
  await handlers.get("session_shutdown")({ type: "session_shutdown", reason: "quit" }, ctx);
  mark("NORMAL_COMPLETION");
} else {
  if (scenario === "helper-exit") {
    queueMicrotask(extensionMessage);
    child.emit("exit", 1);
  }
  continuation();
}
`;

function run(scenario, mode, cleanup = "normal") {
  const home = mkdtempSync(path.join(tmpdir(), "rotom-pi-guard-failure-"));
  try {
    return spawnSync(process.execPath, ["--input-type=module", "--eval", script, scenario, mode, extension, cleanup], {
      cwd: home,
      env: { HOME: home, XDG_CONFIG_HOME: home, XDG_CACHE_HOME: home, XDG_DATA_HOME: home },
      encoding: "utf8",
      timeout: 10000,
    });
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
}

function failed(result) {
  assert.equal(result.error, undefined);
  assert.equal(result.signal, null);
  assert.equal(result.status, 4);
  assert.equal(result.stderr, NOTICE + "\n");
  assert.equal(result.stdout.includes("CONTINUED"), false);
  assert.equal(result.stdout.includes("EXTENSION_MESSAGE"), false);
  assert.equal(result.stdout.includes("SHUTDOWN_REQUESTED"), false);
  assert.equal(result.stdout.match(/ABORT_REQUESTED/g)?.length, 1);
  assert.equal((result.stdout + result.stderr).includes("synthetic-private"), false);
}

for (const mode of ["tui", "print", "json", "rpc", "unknown"]) {
  for (const scenario of ["spawn-error", "claim-denied", "request-timeout", "helper-exit"]) {
    test(`${scenario} in ${mode} mode terminates before prompt or extension continuation`, () => {
      const result = run(scenario, mode);
      failed(result);
      if (scenario !== "spawn-error") assert.equal(result.stdout.match(/HELPER_CLOSED/g)?.length, 1);
      assert.equal(result.stdout.includes("CUSTOM_ENTERED"), mode === "tui");
      assert.equal(result.stdout.includes("TUI_STOP_COMPLETED"), mode === "tui");
      if (mode === "tui") {
        assert.ok(result.stdout.indexOf("ABORT_REQUESTED") < result.stdout.indexOf("CUSTOM_ENTERED"));
        assert.ok(result.stdout.indexOf("CUSTOM_ENTERED") < result.stdout.indexOf("TUI_STOP_REQUESTED"));
      }
    });
  }

  test(`normal startup and shutdown in ${mode} mode succeeds without forced exit`, () => {
    const result = run("normal", mode);
    assert.equal(result.error, undefined);
    assert.equal(result.signal, null);
    assert.equal(result.status, 0);
    assert.equal(result.stderr, "");
    assert.equal(result.stdout, "HELPER_CLOSED\nNORMAL_COMPLETION\n");
  });
}

for (const cleanup of ["custom-throws", "custom-rejects", "stop-throws"]) {
  test(`TUI ${cleanup} still terminates without reporting successful TUI cleanup`, () => {
    const result = run("claim-denied", "tui", cleanup);
    failed(result);
    assert.equal(result.stdout.match(/CUSTOM_ENTERED/g)?.length, 1);
    assert.equal(result.stdout.includes("TUI_STOP_REQUESTED"), cleanup === "stop-throws");
    assert.equal(result.stdout.includes("TUI_STOP_COMPLETED"), false);
  });
}
