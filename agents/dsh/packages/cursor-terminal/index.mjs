// 仅使用固定上游的公开认证与 Provider API；不复制登录协议。
import path from "node:path";
import fs from "node:fs";
import { randomUUID } from "node:crypto";
import { QuestionBridge } from "@deepseek-harness-tui/dsh-tui/oauth";
import { AsyncLocalStorage } from "node:async_hooks";
import {
  AgentRun, CREDENTIAL_REF, CursorAdapter, CursorAuthService, assertCursorAuthUrl,
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

export class LoginLinkStore {
  #owned;
  constructor(file) { this.file = file; }

  #parent() {
    if (!this.file || !path.isAbsolute(this.file)) throw new Error("Cursor link directory is not private");
    const parent = path.dirname(this.file);
    let current = path.parse(parent).root;
    for (const part of parent.slice(current.length).split(path.sep).filter(Boolean)) {
      current = path.join(current, part);
      const info = fs.lstatSync(current);
      if (!info.isDirectory() || info.isSymbolicLink() || ![0, process.getuid()].includes(info.uid)
          || ((info.mode & 0o022) !== 0 && (info.mode & 0o1000) === 0)) throw new Error("Cursor link directory is not private");
    }
    const info = fs.lstatSync(parent);
    if (info.uid !== process.getuid() || (info.mode & 0o777) !== 0o700) throw new Error("Cursor link directory is not private");
    return parent;
  }

  #read() {
    const fd = fs.openSync(this.file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    try {
      const info = fs.fstatSync(fd);
      if (!info.isFile() || info.nlink !== 1 || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o600) {
        throw new Error("Cursor link file is not owned");
      }
      return { info, body: fs.readFileSync(fd, "utf8") };
    } finally { fs.closeSync(fd); }
  }

  save(url) {
    assertCursorAuthUrl(url);
    if (typeof url !== "string" || /[\r\n\0]/u.test(url)) throw new Error("Cursor link is invalid");
    const parent = this.#parent();
    if (this.#owned) {
      const current = this.#read();
      if (current.info.dev === this.#owned.dev && current.info.ino === this.#owned.ino && current.body === url + "\n" && this.#owned.url === url) return;
      throw new Error("Cursor link file changed; retained");
    }
    const temporary = path.join(parent, ".cursor-login-url-" + randomUUID());
    let created = false;
    try {
      const fd = fs.openSync(temporary, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY | fs.constants.O_NOFOLLOW, 0o600);
      created = true;
      try { fs.writeFileSync(fd, url + "\n"); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
      // 首次发布只允许缺失目标；不覆盖同名文件或链接。
      fs.linkSync(temporary, this.file);
    } finally { if (created) fs.unlinkSync(temporary); }
    const current = this.#read();
    this.#owned = { dev: current.info.dev, ino: current.info.ino, url };
  }

  remove(url) {
    if (!this.#owned || this.#owned.url !== url) return true;
    try {
      this.#parent();
      const current = this.#read();
      const latest = fs.lstatSync(this.file);
      if (current.info.dev !== this.#owned.dev || current.info.ino !== this.#owned.ino || current.body !== url + "\n"
          || latest.dev !== current.info.dev || latest.ino !== current.info.ino || latest.isSymbolicLink()) return false;
      fs.unlinkSync(this.file);
      this.#owned = undefined;
      return true;
    } catch (error) {
      if (error?.code === "ENOENT") { this.#owned = undefined; return true; }
      return false;
    }
  }
}

const TERMINAL_PHASES = new Set(["authenticated", "failed", "cancelled"]);
const usage = "Usage: /cursor-login [start|url|status|cancel|logout|models]";

export function createLoginHandler(coordinator, adapter, options = {}) {
  const linkStore = options.linkStore ?? new LoginLinkStore(process.env.DSH_HOME ? path.join(process.env.DSH_HOME, "cursor-login-url.txt") : undefined);
  const bridgeFactory = options.bridgeFactory ?? ((ask, abort) => new QuestionBridge(ask, abort));
  let active; let disposed = false; let retainedLink = false; let requestsPaused = false; let serial = Promise.resolve();
  const close = (record, cancel) => {
    if (record.ending) return record.ending;
    clearTimeout(record.timer);
    record.release();
    record.ending = (async () => {
      let failed = false;
      try { if (cancel) await coordinator.cancel(record.id); } catch { failed = true; }
      record.panel?.release();
      try { await record.panel?.bridge.settle(); } catch { failed = true; }
      if (record.url && !linkStore.remove(record.url)) { record.drift = true; retainedLink = true; }
      if (!cancel && record.phase === "authenticated" && record.authenticated && record.explicitStart && requestsPaused) {
        adapter.resumeRequests();
        requestsPaused = false;
      }
      if (active === record) active = undefined;
      if (failed) throw new Error("Cursor login cleanup failed; provider details are hidden");
    })();
    return record.ending;
  };
  const observe = record => {
    record.timer = setTimeout(() => {
      if (active !== record || record.ending || disposed) return;
      try {
        if (performance.now() >= record.deadline) { record.abort.abort(); return; }
        const view = coordinator.read(record.id);
        record.phase = view.phase;
        record.authenticated = view.authenticated === true;
        if (TERMINAL_PHASES.has(view.phase)) {
          void close(record, false).catch(() => {});
        } else observe(record);
      } catch { void close(record, true).catch(() => {}); }
    }, Math.min(300, Math.max(0, record.deadline - performance.now())));
    record.timer.unref?.();
  };
  const panel = async (record, invocation) => {
    const ask = options.resolveAsk?.(invocation);
    if (!ask || !record.url) return false;
    record.panel?.release();
    await record.panel?.bridge.settle();
    if (active !== record || record.ending || disposed || record.abort.signal.aborted) return false;
    const popup = { abort: new AbortController() };
    const cancel = () => { if (record.panel === popup && !record.ending) record.abort.abort(); };
    popup.abort.signal.addEventListener("abort", cancel, { once: true });
    popup.release = () => popup.abort.signal.removeEventListener("abort", cancel);
    popup.bridge = bridgeFactory(ask, popup.abort);
    record.panel = popup;
    popup.bridge.notify({ type: "auth_url", url: record.url,
      instructions: "Copy or reopen this complete link in your browser. Cancel ends this login." });
    return true;
  };
  const run = async invocation => {
    const words = invocation.rawInput.trim().split(/\s+/u).filter(Boolean);
    if (words.length > 1) return { kind: "error", text: usage };
    const verb = words[0] ?? "start";
    let recordToClose;
    try {
      if (disposed) return { kind: "error", text: "Cursor login handler is closed." };
      invocation.signal?.throwIfAborted();
      if (verb === "start" || verb === "url") {
        if (active) {
          const view = coordinator.read(active.id);
          active.phase = view.phase;
          active.authenticated = view.authenticated === true;
          if (TERMINAL_PHASES.has(view.phase)) await close(active, false);
        }
        if (verb === "url" && !active) return { kind: "error", text: "No pending Cursor login. Use /cursor-login start." };
        if (!active) {
          const view = await coordinator.start();
          const record = { id: view.id, url: view.authUrl, phase: view.phase, authenticated: view.authenticated === true, explicitStart: true,
            abort: new AbortController(), deadline: performance.now() + 600000, release: () => {} };
          recordToClose = record;
          active = record;
          const cancel = () => { void close(record, true).catch(() => {}); };
          record.abort.signal.addEventListener("abort", cancel, { once: true });
          invocation.signal?.addEventListener("abort", cancel, { once: true });
          record.release = () => {
            record.abort.signal.removeEventListener("abort", cancel);
            invocation.signal?.removeEventListener("abort", cancel);
          };
          if (disposed || invocation.signal?.aborted) { await close(record, true); return { kind: "error", text: "Cursor login cancelled." }; }
          if (TERMINAL_PHASES.has(view.phase)) { await close(record, false); return { kind: "success", text: "Cursor login ended. Use /cursor-login status." }; }
          if (record.url) {
            try { linkStore.save(record.url); } catch { record.drift = true; retainedLink = true; }
          }
          observe(record);
        }
        const record = active;
        const shown = await panel(record, invocation);
        if (active !== record || record.ending) return { kind: "error", text: "No pending Cursor login. Use /cursor-login start." };
        if (!record.url) return { kind: "success", text: "Cursor login is preparing. Use /cursor-login status or /cursor-login cancel." };
        const heading = shown ? "Cursor login pending. /cursor-login url reopens the auth panel." : "Cursor login pending; auth panel unavailable.";
        const location = typeof linkStore.file === "string" ? heading + " Full link file: " + linkStore.file : undefined;
        return { kind: "success", text: record.drift
          ? "Cursor link file conflict retained. /cursor-login url reopens the auth panel." : location && location.length <= 200 ? location
          : heading + " Complete URL saved in this instance's private cursor-login-url.txt." };
      }
      if (verb === "status") {
        const status = await coordinator.accountStatus({ signal: invocation.signal });
        const expired = typeof status.expiresAt === "number" && status.expiresAt <= Date.now();
        const phase = active ? coordinator.read(active.id).phase : "none";
        const knownPhase = ["none", "starting", "waiting_browser", "waiting_input", "authenticated", "failed", "cancelled"].includes(phase) ? phase : "unknown";
        return { kind: "success", text: `Cursor: ${expired ? "expired; login required" : status.authenticated ? "signed in" : "not signed in"}; login ${knownPhase}; expiry ${expired ? "expired" : typeof status.expiresAt === "number" ? "valid" : "unknown"}; requests ${requestsPaused ? "paused" : "ready"}; usage unknown.${retainedLink ? " Changed link file retained." : ""}` };
      }
      if (verb === "cancel") {
        const record = active;
        if (record) await close(record, true);
        return { kind: "success", text: record?.drift ? "Cursor login cancelled; changed link file retained." : "Cursor login cancelled; stored account unchanged." };
      }
      if (verb === "logout") {
        const record = active;
        adapter.cancelRequests();
        requestsPaused = true;
        try {
          if (record) await close(record, true);
          await coordinator.logout({ signal: invocation.signal });
        } catch {
          return { kind: "error", text: "Cursor logout not confirmed; model requests paused. Use /cursor-login start to sign in again, or /cursor-login status." };
        }
        let refreshed = true;
        try { await adapter.listModelsForRpc({ force: true, signal: invocation.signal }); } catch { refreshed = false; }
        adapter.resumeRequests();
        requestsPaused = false;
        return { kind: "success", text: record?.drift ? "Cursor signed out; changed link file retained."
          : refreshed ? "Cursor signed out in this DSH instance." : "Cursor signed out; catalog refresh pending. Use /model after your next sign-in." };
      }
      if (verb === "models") {
        const models = await adapter.listModelsForRpc({ force: true, signal: invocation.signal });
        return { kind: "success", text: models.length
          ? `Cursor: ${models.length} discovered models; live calls unverified. Use /model for the complete account catalog.`
          : "Cursor account catalog unavailable; no fallback models are marked usable" };
      }
    } catch {
      if (recordToClose) await close(recordToClose, true).catch(() => {});
      return { kind: "error", text: "Cursor operation failed or was cancelled. Provider details are hidden; use /cursor-login status." };
    }
    return { kind: "error", text: usage };
  };
  const handler = invocation => {
    const next = serial.then(() => run(invocation));
    serial = next.catch(() => {});
    return next;
  };
  handler.dispose = async () => {
    disposed = true;
    await serial;
    if (active) await close(active, true);
  };
  return handler;
}

export function resolveLoginAsk(ctx, invocation) {
  const questions = ctx.get("userQuestions");
  return questions && invocation.agent ? request => questions.ask({ ...request, agent: invocation.agent }) : undefined;
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
  const handler = createLoginHandler(coordinator, adapter, { resolveAsk: invocation => resolveLoginAsk(ctx, invocation) });
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
