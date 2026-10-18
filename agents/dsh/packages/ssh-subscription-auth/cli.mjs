import { setTimeout as delay } from "node:timers/promises";
import { createRuntime, currentHome } from "./index.mjs";

const FAILURE = "Subscription authentication failed or was cancelled; private details are hidden.\n";

function untilAbort(signal) {
  return new Promise((resolve, reject) => {
    const abort = () => reject(new Error("Authentication cancelled"));
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort, { once: true });
  });
}

// 所有授权提示仅写入调用者私有终端；输入始终关闭回显。
export function terminalAsk(input, output) {
  return async ({ questions, signal }) => {
    if (!input.isTTY || !output.isTTY || typeof input.setRawMode !== "function") {
      throw new Error("A private interactive terminal is required.");
    }
    if (questions.length !== 1) throw new Error("Unsupported authentication question.");
    const question = questions[0];
    const safeText = value => String(value ?? "").replace(/[\x00-\x08\x0b-\x1f\x7f]/gu, "");
    output.write(safeText(question.question) + "\n" + safeText(question.detail) + "\n");
    // 等待面板不占用 stdin，后续 manual-code 可以独立开始。
    if (question.id === "dsh-auth-waiting") return untilAbort(signal);
    const hasOptions = question.options?.length > 0;
    const selection = hasOptions && !question.detail;
    if (hasOptions) question.options.forEach((option, index) => {
      output.write(`${selection ? "" : "/"}${index + 1}. ${safeText(option.label)}\n`);
    });
    output.write(selection ? "Selection: " : hasOptions
      ? "Paste response or /number action (hidden): " : "Paste response (hidden): ");
    const text = await new Promise((resolve, reject) => {
      let value = "";
      const wasRaw = input.isRaw === true;
      const wasPaused = input.isPaused();
      const finish = (error, answer) => {
        input.removeListener("data", onData);
        signal?.removeEventListener("abort", onAbort);
        input.setRawMode(wasRaw);
        if (wasPaused) input.pause();
        output.write("\n");
        if (error) reject(error); else resolve(answer);
      };
      const onAbort = () => finish(new Error("Authentication cancelled"));
      const onData = chunk => {
        for (const char of chunk.toString("utf8")) {
          if (char === "\x03" || char === "\x04") return onAbort();
          if (char === "\r" || char === "\n") return finish(undefined, value);
          if (char === "\x7f" || char === "\b") value = value.slice(0, -1);
          else if (char >= " " && char !== "\x7f") value += char;
          if (value.length > 16384) return onAbort();
        }
      };
      if (signal?.aborted) return onAbort();
      input.setRawMode(true);
      input.on("data", onData);
      signal?.addEventListener("abort", onAbort, { once: true });
      input.resume();
    });
    let option;
    if (selection || (hasOptions && text.startsWith("/"))) {
      const index = selection ? text : text.slice(1);
      if (!/^[1-9][0-9]*$/u.test(index) || !Number.isSafeInteger(Number(index))) {
        throw new Error("Invalid authentication action selection.");
      }
      option = question.options[Number(index) - 1];
      if (!option) throw new Error("Invalid authentication action selection.");
    }
    return { answers: [{ id: question.id, selected: option ? [option.label] : [],
      ...(option ? {} : { custom: text }) }] };
  };
}

export async function createCliRuntime({ provider, env, ask, contextDependencies, runtimeDependencies }) {
  const home = currentHome(env);
  const { Context, LocalCredentialProvider, ...environment } = contextDependencies ?? Object.assign({},
    ...await Promise.all([
      import("@deepseek-ai/cordis"), import("@deepseek-ai/dsh-credentials-local"),
      import("@deepseek-ai/dsh-launch-environment"),
    ]));
  // 官方 logger 的公开 level 阈值小于 error(0)，不收集原始错误参数。
  const ctx = new Context().intercept("logger", { level: -1 });
  try {
    ctx.provide(environment.DSH_LAUNCH_ENVIRONMENT_KEY,
      environment.createLaunchEnvironmentSnapshot([{ source: "process", values: env }]));
    const fork = ctx.plugin(LocalCredentialProvider, { dshHome: home, watch: false });
    await fork.await();
    const runtime = await createRuntime(ctx, { providers: [provider] }, { env, ask, dependencies: runtimeDependencies });
    return { ...runtime, async dispose() {
      try { await runtime.dispose(); } finally { await ctx.fiber.dispose(); }
    } };
  } catch {
    await ctx.fiber.dispose();
    throw new Error("Subscription credential context could not start.");
  }
}

export async function cursorLogin(route, terminal, signal) {
  let session;
  const starting = route.coordinator.start().then(view => { session = view; return view; });
  try {
    let view = await Promise.race([starting, untilAbort(signal)]);
    if (view.authUrl) terminal.write(String(view.authUrl).replace(/[\x00-\x1f\x7f]/gu, "") + "\n");
    while (view.phase !== "authenticated") {
      if (["failed", "cancelled", "waiting_input"].includes(view.phase)) throw new Error("Cursor login failed.");
      await delay(250, undefined, { signal });
      view = await route.coordinator.read(session.id);
    }
    if (view.authenticated !== true) throw new Error("Cursor login failed.");
  } finally {
    // start 的 ready 与取消可能竞争；等公开 session 出现后仍须取消并 drain。
    if (session || route.loginSessionId) await route.coordinator.cancel(session?.id ?? route.loginSessionId);
    await starting.catch(() => undefined);
  }
}

export async function runAuth(argv, {
  runtime: runtimeFactory = createCliRuntime, env = process.env,
  stdin = process.stdin, stdout = process.stdout, stderr = process.stderr,
  signals = process, signal, timeoutMs = 300000, cleanupTimeoutMs = 5000,
} = {}) {
  if (!Array.isArray(argv) || argv.length !== 2 || !["codex", "cursor"].includes(argv[0])
      || !["login", "status", "logout", "models"].includes(argv[1])) {
    stderr.write("Usage: --subscription-auth <codex|cursor> <login|status|logout|models>\n");
    return 2;
  }
  const [provider, action] = argv;
  if (action === "login" && (!stdin.isTTY || !stderr.isTTY || typeof stdin.setRawMode !== "function")) {
    stderr.write("Subscription login requires an interactive private terminal.\n");
    return 2;
  }
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  signals.on("SIGINT", abort);
  signals.on("SIGTERM", abort);
  const timer = setTimeout(abort, timeoutMs);
  let runtime;
  let pending;
  let code = 0;
  try {
    currentHome(env);
    runtime = await runtimeFactory({ provider, env, ask: terminalAsk(stdin, stderr) });
    const route = runtime.routes.get(provider);
    pending = (async () => {
      if (action === "login") {
        if (provider === "codex") await route.api.login(route.provider, controller.signal);
        else await cursorLogin(route, stderr, controller.signal);
        controller.signal.throwIfAborted();
        stdout.write("Subscription login completed.\n");
      } else if (action === "logout") {
        if (provider === "codex") await route.api.logout(route.provider);
        else await route.coordinator.logout({ signal: controller.signal });
        controller.signal.throwIfAborted();
        stdout.write("Subscription logout completed.\n");
      } else if (action === "status") {
        const status = provider === "codex"
          ? (await route.api.providers()).find(item => item.provider === route.provider)
          : await route.auth.status({ signal: controller.signal });
        controller.signal.throwIfAborted();
        stdout.write(JSON.stringify({ provider, authenticated: status?.authenticated === true || status?.signedIn === true,
          ...(Number.isFinite(status?.expiresAt) ? { expiresAt: status.expiresAt } : {}) }) + "\n");
      } else {
        const models = await route.adapter.listModels(route.provider);
        controller.signal.throwIfAborted();
        stdout.write(JSON.stringify({ provider, models: models.map(model => model.id)
          .filter(id => typeof id === "string" && /^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,159}$/u.test(id)) }) + "\n");
      }
    })();
    await Promise.race([pending, untilAbort(controller.signal)]);
  } catch {
    stderr.write(FAILURE);
    code = 5;
  } finally {
    controller.abort();
    for (const route of runtime?.routes.values() ?? []) route.adapter?.cancelRequests?.();
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
    signals.removeListener("SIGINT", abort);
    signals.removeListener("SIGTERM", abort);
    let cleanupTimer;
    try {
      await Promise.race([(async () => {
        try { await pending?.catch(() => undefined); }
        finally { await runtime?.dispose(); }
      })(), new Promise((resolve, reject) => {
        cleanupTimer = setTimeout(() => reject(new Error("Cleanup timed out")), cleanupTimeoutMs);
      })]);
    } catch { stderr.write(FAILURE); code = 5; }
    finally { clearTimeout(cleanupTimer); }
  }
  return code;
}
