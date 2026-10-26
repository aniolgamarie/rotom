/** Pi 公开扩展事件桥；会话租约和持久归属只由受信 Python helper 核验。 */
import { spawn as nativeSpawn } from "node:child_process";
import path from "node:path";

const LIMIT = 16384;
const DEADLINE = 5000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const NOTICE = "Pi 会话写入保护不可用；请核验运行归属后重新启动。";
const unavailable = () => new Error("pi_session_control_unavailable");
const absolute = value => typeof value === "string" && value.startsWith("/")
  && !value.startsWith("//") && !value.includes("\0") && path.posix.normalize(value) === value;
const exact = (value, names) => value !== null && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).sort().join("\0") === [...names].sort().join("\0");

function configuration(context, environment) {
  if (!exact(context, ["state_root", "instance", "profile", "binding", "run_id", "initial_session", "lease_fd"])
      || !absolute(context.state_root) || !absolute(context.instance)
      || typeof context.profile !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(context.profile)
      || !exact(context.binding, ["machine", "local", "profile"]) || !absolute(context.binding.local)
      || context.binding.profile !== context.profile || typeof context.binding.machine !== "string"
      || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(context.binding.machine)
      || typeof context.run_id !== "string" || !/^[0-9a-f]{32}$/.test(context.run_id)
      || context.initial_session !== null && (typeof context.initial_session !== "string" || !UUID.test(context.initial_session))
      || context.lease_fd !== null && (!Number.isSafeInteger(context.lease_fd) || context.lease_fd < 0)
      || !absolute(environment.ROTOM_PI_CONTROL_PYTHON) || !absolute(environment.ROTOM_PI_CONTROL_HELPER)) {
    throw unavailable();
  }
  const value = { ...context, lease_fd: context.lease_fd === null ? null : 3 };
  const encoded = JSON.stringify(value);
  if (Buffer.byteLength(encoded) > LIMIT) throw unavailable();
  return { encoded, python: environment.ROTOM_PI_CONTROL_PYTHON, helper: environment.ROTOM_PI_CONTROL_HELPER };
}

export function createBridge(context, {
  spawn = nativeSpawn, setTimeout = globalThis.setTimeout, clearTimeout = globalThis.clearTimeout,
  environment = process.env, onUnavailable = () => {},
} = {}) {
  const config = configuration(context, environment);
  let child, failed = false, closing = false, exited = false, pending = null, sequence = 0;
  let buffer = Buffer.alloc(0), queue = Promise.resolve(), closePromise;
  let resolveExit;
  const exit = new Promise(resolve => { resolveExit = resolve; });
  const fail = () => {
    if (failed) return;
    failed = true;
    if (pending) {
      const request = pending;
      pending = null;
      clearTimeout(request.timer);
      request.reject(unavailable());
    }
    try { child?.stdin.end(); } catch {}
    if (!closing) {
      try { onUnavailable(); } catch {}
    }
  };
  const finish = () => {
    exited = true;
    resolveExit();
    if (!closing) fail();
    else if (pending) fail();
  };
  const receive = chunk => {
    if (failed) return;
    if (!Buffer.isBuffer(chunk)) { fail(); return; }
    const newline = chunk.indexOf(10);
    const length = newline === -1 ? chunk.length : newline;
    if (buffer.length + length + (newline === -1 ? 0 : 1) > LIMIT
        || newline !== -1 && newline + 1 !== chunk.length) {
      fail(); return;
    }
    buffer = Buffer.concat([buffer, chunk.subarray(0, length)]);
    if (newline === -1) return;
    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(buffer);
      buffer = Buffer.alloc(0);
      // 固定两字段协议也拒绝重复字段、浮点序号和额外输出，不回显原始行。
      const ws = "[ \\t\\r]*";
      const seq = '"seq"' + ws + ":" + ws + "[1-9][0-9]*";
      const ok = '"ok"' + ws + ":" + ws + "(?:true|false)";
      if (!new RegExp("^" + ws + "\\{" + ws + "(?:" + seq + ws + "," + ws + ok
          + "|" + ok + ws + "," + ws + seq + ")" + ws + "\\}" + ws + "$").test(text)) throw unavailable();
      const value = JSON.parse(text);
      if (!pending || !Number.isSafeInteger(value.seq) || value.seq !== pending.seq || value.ok !== true) throw unavailable();
      const request = pending;
      pending = null;
      clearTimeout(request.timer);
      request.resolve();
    } catch { fail(); }
  };
  try {
    child = spawn(config.python, ["-I", config.helper], {
      shell: false,
      stdio: context.lease_fd === null ? ["pipe", "pipe", "inherit"] : ["pipe", "pipe", "inherit", context.lease_fd],
      env: { ROTOM_PI_CONTROL_CONTEXT: config.encoded, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" },
    });
    child.on("error", fail);
    child.once("exit", finish);
    child.once("close", finish);
    child.stdin.on("error", fail);
    child.stdout.on("error", fail);
    child.stdout.on("end", () => { if (!closing) fail(); });
    child.stdout.on("data", receive);
  } catch { fail(); }

  const request = payload => {
    const operation = queue.then(() => {
      if (failed || closing || !child) throw unavailable();
      let line;
      try {
        line = JSON.stringify({ seq: ++sequence, ...payload }) + "\n";
        if (Buffer.byteLength(line) > LIMIT || !Number.isSafeInteger(sequence)) throw unavailable();
      } catch { fail(); throw unavailable(); }
      return new Promise((resolve, reject) => {
        pending = { seq: sequence, resolve, reject, timer: setTimeout(fail, DEADLINE) };
        try { child.stdin.write(line); } catch { fail(); }
      });
    });
    queue = operation.catch(() => {});
    return operation;
  };
  const invalid = () => { fail(); return Promise.reject(unavailable()); };
  return {
    claim(value) {
      if (!exact(value, ["session", "file", "cwd"])) return invalid();
      const { session, file, cwd } = value;
      if (typeof session !== "string" || !UUID.test(session) || file !== null && !absolute(file) || !absolute(cwd)) return invalid();
      return request({ op: "claim", session, file, cwd });
    },
    prepare(file) {
      return absolute(file) ? request({ op: "prepare", file }) : invalid();
    },
    ping() { return request({ op: "ping" }); },
    get available() { return !failed && !closing; },
    close() {
      if (closePromise) return closePromise;
      closing = true;
      try { child?.stdin.end(); } catch { fail(); }
      closePromise = !child || exited ? Promise.resolve() : new Promise(resolve => {
        const timer = setTimeout(() => {
          // 只放弃等待自己的 helper；不发送信号，也不重启。
          child.unref?.();
          child.stdin.unref?.();
          child.stdout.unref?.();
          resolve();
        }, DEADLINE);
        exit.then(() => { clearTimeout(timer); resolve(); });
      });
      return closePromise;
    },
  };
}

export default function sessionControl(pi, options = {}) {
  const environment = options.environment ?? process.env;
  let bridge, current, stopped = false;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    try { current?.ui.notify(NOTICE, "error"); } catch {}
    try { current?.shutdown(); } catch {}
  };
  pi.on("session_start", async (_event, ctx) => {
    current = ctx;
    if (stopped) return;
    try {
      if (!bridge) {
        const raw = environment.ROTOM_PI_CONTROL_CONTEXT;
        if (typeof raw !== "string" || Buffer.byteLength(raw) > LIMIT) throw unavailable();
        bridge = createBridge(JSON.parse(raw), { ...options, environment, onUnavailable: stop });
      }
      await bridge.claim({ session: ctx.sessionManager.getSessionId(),
        file: ctx.sessionManager.getSessionFile() ?? null, cwd: ctx.sessionManager.getCwd() });
    } catch { stop(); }
  });
  pi.on("session_before_switch", async (event, ctx) => {
    current = ctx;
    try {
      if (!bridge || stopped) throw unavailable();
      if (event.reason === "resume") await bridge.prepare(event.targetSessionFile);
      else if (event.reason === "new") await bridge.ping();
      else throw unavailable();
    } catch { stop(); return { cancel: true }; }
  });
  pi.on("session_before_fork", async (_event, ctx) => {
    current = ctx;
    try {
      if (!bridge || stopped) throw unavailable();
      await bridge.ping();
    } catch { stop(); return { cancel: true }; }
  });
  pi.on("session_shutdown", async (_event, ctx) => {
    current = ctx;
    await bridge?.close();
  });
}
