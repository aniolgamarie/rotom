import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";

// 仅手动验证内存 Agent 发布窗口；不挂载持久化，不发送输入。
const coreVersion = "0.2.1-rc.2";
const target = "synthetic-initialization-target";
let activeCase = "bootstrap";

class ProbeError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

function report(result) {
  process.stdout.write(`${JSON.stringify({
    schema_version: 1,
    core_version: coreVersion,
    case: activeCase,
    passed: false,
    visible_before_settled: false,
    create_fulfilled: false,
    create_rejected: false,
    same_agent: false,
    registries_removed: false,
    disposed_event: false,
    failure_code: null,
    ...result,
  })}\n`);
}

function check(condition, code) {
  if (!condition) throw new ProbeError(code);
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

async function loadRuntime() {
  const args = process.argv.slice(2);
  check(args.length === 2 && args[0] === "--runtime-root"
    && isAbsolute(args[1]), "invalid_arguments");
  const require = createRequire(join(args[1], "package.json"));
  const names = [
    "cordis", "dsh-agent", "dsh-session", "dsh-session-projection",
    "dsh-llm", "dsh-system-prompt", "dsh-tools", "dsh-agent-loop",
  ];
  const modules = [];
  for (const name of names) {
    const specifier = `@deepseek-ai/${name}`;
    const metadata = JSON.parse(await readFile(
      require.resolve(`${specifier}/package.json`), "utf8"));
    check(metadata.version === (name === "cordis" ? "4.0.5" : coreVersion),
      "runtime_version_mismatch");
    // 只解析包根公开 exports，不导入实现子路径。
    modules.push(await import(pathToFileURL(require.resolve(specifier)).href));
  }
  const [cordis, agents, sessions, ...services] = modules;
  check(typeof cordis.Context === "function"
    && typeof sessions.SessionId === "function"
    && [agents, sessions, ...services].every((mod) => typeof mod.default === "function"),
  "public_export_missing");
  return {
    Context: cordis.Context,
    SessionId: sessions.SessionId,
    services: [agents, sessions, ...services].map((mod) => mod.default),
  };
}

async function runCase(runtime, shouldFail) {
  activeCase = shouldFail ? "late_failure" : "success";
  const root = new runtime.Context();
  const gate = deferred();
  const entered = deferred();
  const syntheticError = new Error("synthetic_initialization_failure");
  const id = runtime.SessionId(target);
  let observedAgent;
  let disposedAgent;
  let disposedCount = 0;
  let settled = false;
  let creation;
  let handle;
  let handleDisposed = false;
  try {
    for (const Service of runtime.services) {
      await root.plugin(Service).await();
    }
    root.on("agent/disposed", ({ agent }) => {
      if (agent.id !== id) return;
      disposedAgent = agent;
      disposedCount += 1;
    });
    root.on("agent/created", async ({ agent }) => {
      if (agent.id !== id) return;
      observedAgent = agent;
      entered.resolve();
      await gate.promise;
      if (shouldFail) throw syntheticError;
    });
    // 立即处理拒绝，避免在等待 listener 时产生未处理 rejection。
    creation = root.agents.create({ sessionId: id, agentOptions: {} }).then(
      (value) => { settled = true; return { ok: true, handle: value }; },
      (error) => { settled = true; return { ok: false, error }; },
    );
    await Promise.race([
      entered.promise,
      creation.then(() => { throw new ProbeError("settled_before_listener"); }),
    ]);
    const visibleBeforeSettled = root.agents.get(id) === observedAgent && !settled;
    check(visibleBeforeSettled, "publication_window_missing");
    gate.resolve();
    const outcome = await creation;
    handle = outcome.handle;
    if (shouldFail) {
      check(!outcome.ok && outcome.error === syntheticError, "unexpected_failure_result");
    } else {
      check(outcome.ok && handle.agent === observedAgent, "unexpected_success_result");
      await handle.dispose();
      handleDisposed = true;
    }
    const removed = root.agents.get(id) === undefined && root.sessions.get(id) === undefined;
    const disposed = disposedCount === 1 && disposedAgent === observedAgent;
    check(removed, "registry_cleanup_missing");
    check(disposed, "disposal_event_missing");
    return {
      passed: true,
      visible_before_settled: visibleBeforeSettled,
      create_fulfilled: outcome.ok,
      create_rejected: !outcome.ok,
      same_agent: shouldFail ? disposedAgent === observedAgent : handle.agent === observedAgent,
      registries_removed: removed,
      disposed_event: disposed,
      failure_code: null,
    };
  } finally {
    // 断言失败也先释放 listener，再收敛创建和根生命周期。
    gate.resolve();
    try {
      if (creation) {
        const outcome = await creation;
        if (outcome.ok && !handleDisposed) await outcome.handle.dispose();
      }
    } finally {
      await root.fiber.dispose();
    }
  }
}

// 超时只报告失败；不根据等待时长推断初始化是否提交。
const watchdog = setTimeout(() => {
  report({ passed: false, failure_code: "watchdog_timeout" });
  process.exit(1);
}, 30_000);

try {
  const runtime = await loadRuntime();
  for (const shouldFail of [false, true]) {
    const result = await runCase(runtime, shouldFail);
    report(result);
  }
  process.exitCode = 0;
} catch (error) {
  report({ passed: false, failure_code: error instanceof ProbeError ? error.code : "probe_failed" });
  process.exitCode = 1;
} finally {
  clearTimeout(watchdog);
}
