// 仅使用固定上游的公开认证与 Provider API；不复制登录协议。
import path from "node:path";
import { AsyncLocalStorage } from "node:async_hooks";
import {
  AgentRun, CREDENTIAL_REF, CursorAdapter, CursorAuthService,
  CursorCredentialStore, CursorLoginCoordinator, PROVIDER,
} from "dsh-cursor-subscription";

export const name = "rotom-cursor-terminal";
export const inject = ["llm", "credentials", "commands"];
const FAILURE_CODES = new Set(["AUTH", "RATE_LIMIT", "INVALID_REQUEST", "TIMEOUT", "SERVER", "TRANSPORT", "CURSOR_ERROR", "ABORTED", "UNSUPPORTED_OPTION", "MISSING_CREDENTIAL", "INVALID_CREDENTIAL", "AUTH_FAILED"]);
const failure = code => ({ code: FAILURE_CODES.has(code) ? code : "CURSOR_ERROR",
  message: "Cursor request failed or was cancelled; provider error details are hidden. Check login status." });

export class TerminalCursorAdapter extends CursorAdapter {
  #requests = new AbortController();
  #scope = new AsyncLocalStorage();
  #runs = new Set();

  constructor(options) {
    super({ ...options, retryCount: 0, createAgentRun: access => {
      const signal = this.#scope.getStore();
      if (!signal) throw new Error("Cursor request has no managed cancellation scope");
      signal.throwIfAborted();
      for (const run of this.#runs) if (run.finished) this.#runs.delete(run);
      const run = (options.createAgentRun ?? (token => new AgentRun(token)))(access);
      this.#runs.add(run);
      return run;
    } });
  }

  cancelRequests() {
    this.#requests.abort();
    for (const run of this.#runs) run.close();
    this.#runs.clear();
  }

  resumeRequests() {
    this.#requests = new AbortController();
  }

  async prepareCall(provider, model, signal) {
    const bound = AbortSignal.any([this.#requests.signal, ...(signal ? [signal] : [])]);
    const resolved = await this.resolveModel(provider, model, bound);
    bound.throwIfAborted();
    return { model: resolved, stream: options => this.stream({ ...options,
      signal: AbortSignal.any([bound, ...(options.signal ? [options.signal] : [])]) }) };
  }

  stream(options) {
    // 在惰性 iterator 创建时捕获本代 signal；每次 next/return 在公开异步作用域内执行。
    const signal = AbortSignal.any([this.#requests.signal, ...(options.signal ? [options.signal] : [])]);
    const iterator = super.stream({ ...options, signal });
    const scope = this.#scope;
    return (async function* () {
      try {
        while (true) {
          const step = await scope.run(signal, () => { signal.throwIfAborted(); return iterator.next(); });
          if (step.done) break;
          const chunk = step.value;
          yield chunk.type === "finish" && ["error", "aborted"].includes(chunk.reason?.kind)
            ? { type: "finish", reason: { kind: chunk.reason.kind, failure: failure(chunk.reason.failure?.code) } }
            : chunk;
        }
      } catch {
        yield { type: "finish", reason: { kind: signal.aborted ? "aborted" : "error", failure: failure(signal.aborted ? "ABORTED" : undefined) } };
      } finally {
        try { await scope.run(signal, () => iterator.return?.()); }
        catch { throw new Error("Cursor request cleanup failed; provider details are hidden."); }
      }
    })();
  }
  // Provider 内部和宿主 recovery 都只尝试一次，不重发未知处理状态的 POST。
  providerRetryPolicy() {
    return { mode: "normal", maxRetries: 0, retryableCodes: [],
      initialDelayMs: 500, maxDelayMs: 10000, jitterRatio: 0 };
  }

  async resolveModel(provider, model, signal) {
    signal?.throwIfAborted();
    const models = await this.listModels(provider);
    if (!models.some(item => item.id === model)) {
      throw new Error("Cursor account model catalog is unavailable or does not contain this model; use /cursor-login models after login");
    }
    return super.resolveModel(provider, model, signal);
  }
}

export function createLoginHandler(coordinator, adapter) {
  let loginId;
  let releaseAbort = () => {};
  const handler = async invocation => {
    const words = invocation.rawInput.trim().split(/\s+/u).filter(Boolean);
    if (words.length > 1) return { kind: "error", text: "Usage: /cursor-login [start|status|cancel|logout|models]" };
    const verb = words[0] ?? "start";
    try {
      invocation.signal?.throwIfAborted();
      if (verb === "start") {
        const view = await coordinator.start();
        loginId = view.id;
        releaseAbort();
        const onAbort = () => { void coordinator.cancel(view.id).catch(() => {}); };
        invocation.signal?.addEventListener("abort", onAbort, { once: true });
        releaseAbort = () => invocation.signal?.removeEventListener("abort", onAbort);
        if (invocation.signal?.aborted) {
          await coordinator.cancel(loginId);
          return { kind: "error", text: "Cursor login cancelled" };
        }
        return { kind: "success", text: view.authUrl
          ? `Open this Cursor login URL in your browser:\n${view.authUrl}\nUse /cursor-login status or /cursor-login cancel. No localhost forwarding is required; upstream polls Cursor.`
          : `Cursor login: ${view.phase}. Use /cursor-login status.` };
      }
      if (verb === "status") {
        const status = await coordinator.accountStatus({ signal: invocation.signal });
        const expired = typeof status.expiresAt === "number" && status.expiresAt <= Date.now();
        const phase = loginId ? coordinator.read(loginId).phase : "not started";
        return { kind: "success", text: `Cursor Provider ${PROVIDER}: ${expired ? "expired; login required" : status.authenticated ? "signed in" : "not signed in"}; login ${phase}; account usage unknown. Use /cursor-login models to discover the account catalog.` };
      }
      if (verb === "cancel") {
        releaseAbort();
        if (loginId) await coordinator.cancel(loginId);
        return { kind: "success", text: "Cursor login cancelled; stored account unchanged" };
      }
      if (verb === "logout") {
        releaseAbort();
        adapter.cancelRequests();
        await coordinator.logout({ signal: invocation.signal });
        await adapter.listModelsForRpc({ force: true, signal: invocation.signal });
        adapter.resumeRequests();
        return { kind: "success", text: "Cursor signed out in this DSH instance" };
      }
      if (verb === "models") {
        const models = await adapter.listModelsForRpc({ force: true, signal: invocation.signal });
        return { kind: "success", text: models.length
          ? `Cursor account catalog (discovered, live calls not verified):\n${models.map(item => item.id).join("\n")}`
          : "Cursor account catalog unavailable; no fallback models are marked usable" };
      }
    } catch {
      // 上游异常可能附带 HTTP 正文，终端不回显原始异常。
      return { kind: "error", text: "Cursor operation failed or was cancelled; check login status. Credentials and provider error body are hidden." };
    }
    return { kind: "error", text: "Usage: /cursor-login [start|status|cancel|logout|models]" };
  };
  handler.dispose = async () => {
    releaseAbort();
    if (loginId) await coordinator.cancel(loginId);
  };
  return handler;
}

export function apply(ctx) {
  const store = new CursorCredentialStore(ctx.credentials, CREDENTIAL_REF);
  const auth = new CursorAuthService(store);
  const coordinator = new CursorLoginCoordinator(auth);
  const adapter = new TerminalCursorAdapter({
    auth, fallbackModels: [], retryCount: 0,
    hangTracePath: path.join(process.env.DSH_HOME, "cursor-hang-trace.log"),
    resolveAttachments: () => ctx.get("attachments"),
  });
  ctx.effect(() => ctx.llm.registerAdapter([PROVIDER], adapter));
  const handler = createLoginHandler(coordinator, adapter);
  ctx.effect(() => ctx.commands.register({
    name: "cursor-login", description: "Cursor Provider browser login, status, cancellation and account models",
    handler,
  }));
  // 仅关闭本插件创建的连接；注销由用户显式命令执行。
  ctx.effect(() => async () => {
    adapter.cancelRequests();
    await handler.dispose();
  });
}
