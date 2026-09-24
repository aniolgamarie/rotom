// Web 工具和后台抓取在同一个 manager 中持有同进程资源；不另建调度器。
import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { authenticatedWebFetch } from "./web-auth-fetch.ts";
import { createWebFetch } from "./web-http.ts";
import { reject } from "./managed-types.ts";

export class WebRuntime {
  constructor(runtime, { fetchFactory = createWebFetch } = {}) {
    this.runtime = runtime; this.fetchFactory = fetchFactory; this.scope = new AsyncLocalStorage();
    this.proxyScope = new AsyncLocalStorage(); this.operations = new Map();
  }
  current() {
    const operation = this.scope.getStore();
    if (!operation || this.operations.get(operation.id) !== operation || operation.finishing || operation.controller.signal.aborted || operation.proxyFailed) reject("WEB_OPERATION_CLOSED", 4);
    requireOrdinaryHelper(this.runtime, "pi-web", operation.id);
    return operation;
  }
  run(label, signal, callback) {
    if (this.scope.getStore()) {
      const current = this.current();
      signal?.throwIfAborted();
      return this.track(Promise.resolve().then(() => callback(AbortSignal.any([current.controller.signal, ...(signal ? [signal] : [])]))));
    }
    requireOrdinaryHelper(this.runtime, "pi-web");
    signal?.throwIfAborted();
    const entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")];
    if (!entry?.manager || !entry.pi || !entry.getContext) reject("WEB_MANAGER_REQUIRED", 5);
    const operation = { id: "web-" + randomUUID(), controller: new AbortController(), holds: 1,
      transports: new Map(), validators: new Set(), cleanups: new Set(), failed: false, canceled: false, finishing: false, closePromise: null, proxyFailed: false };
    let resolveResult, rejectResult, settle;
    const result = new Promise((resolve, reject) => { resolveResult = resolve; rejectResult = reject; });
    const completion = new Promise(resolve => { settle = resolve; });
    operation.completion = completion;
    operation.release = () => {
      operation.holds--;
      if (operation.holds === 0) void this.finish(operation).then(settle);
    };
    const cancel = async () => {
      operation.canceled = true; operation.controller.abort(); rejectResult(new Error("WEB_OPERATION_CANCELED"));
      // 立即停止网络；尚未 settle 的函数/子操作仍保留资源归属。
      await Promise.allSettled([...operation.transports.values()].map(async pending => (await pending).close()));
      if (operation.holds) return undefined;
      return this.finish(operation);
    };
    operation.cancel = cancel;
    const onAbort = () => { void cancel(); entry.manager.abort(operation.id); };
    this.operations.set(operation.id, operation);
    signal?.addEventListener("abort", onAbort, { once: true });
    try {
      entry.manager.spawnWithExecutor(entry.pi, entry.getContext(), "web", "WEB_OPERATION", {
        kind: "resource", manager_run_id: operation.id, cancel,
        execute: async () => {
          void this.scope.run(operation, async () => {
            try {
              operation.controller.signal.throwIfAborted();
              const value = await callback(AbortSignal.any([operation.controller.signal, ...(signal ? [signal] : [])]));
              operation.failed ||= value?.isError === true;
              operation.foregroundReleased = true;
              operation.release();
              if (operation.holds === 0) {
                const proof = await operation.closePromise;
                if (!proof.termination_confirmed) reject("WEB_TERMINATION_UNKNOWN", 4);
                await entry.manager.getRecord(operation.id)?.promise;
              }
              if (operation.canceled) reject("WEB_OPERATION_CANCELED", 4);
              resolveResult(value);
            } catch (error) {
              operation.failed = true;
              // callback 的 hold 只能归还一次。
              if (!operation.foregroundReleased) {
                operation.foregroundReleased = true;
                if (operation.holds > 0) operation.release();
              }
              rejectResult(error);
            }
          });
          return completion;
        },
      }, { description: label, cwd: this.runtime.cwd, isBackground: true });
      const record = entry.manager.getRecord(operation.id);
      if (record) void record.promise.then(() => {
        signal?.removeEventListener("abort", onAbort);
        entry.manager.consumeControlled(operation.id); entry.manager.removeConsumedControlled(operation.id);
        this.operations.delete(operation.id);
      }).catch(() => {});
    } catch (error) {
      signal?.removeEventListener("abort", onAbort); this.operations.delete(operation.id); throw error;
    }
    return result;
  }
  async finish(operation) {
    if (operation.closePromise) return operation.closePromise;
    operation.finishing = true;
    operation.closePromise = (async () => {
      let known = true;
      const closed = await Promise.allSettled([...operation.transports.values()].map(async pending => {
        const transport = await pending.catch(() => null);
        if (transport) await transport.close();
      }));
      if (closed.some(row => row.status === "rejected")) known = false;
      for (const verify of operation.validators) {
        try { if (await verify() !== true) known = false; } catch { known = false; }
      }
      if (known) for (const cleanup of operation.cleanups) {
        try { await cleanup(); operation.cleanups.delete(cleanup); } catch { known = false; }
      }
      const result = { terminal_status: operation.canceled ? "canceled" : operation.failed ? "failed" : "completed",
        response_text: "Web operation ended", termination_confirmed: known, external_work_empty: known };
      if (!known) operation.closePromise = null;
      return result;
    })();
    return operation.closePromise;
  }
  track(promise) {
    const operation = this.current(); operation.holds++;
    return Promise.resolve(promise).catch(error => { operation.failed = true; throw error; }).finally(() => operation.release());
  }
  cleanup(callback) {
    if (typeof callback !== "function") reject("WEB_CLEANUP_INVALID", 2);
    this.current().cleanups.add(callback);
  }
  verifyExternal(callback) {
    if (typeof callback !== "function") reject("WEB_EXTERNAL_PROOF_INVALID", 2);
    this.current().validators.add(callback);
  }
  withProxy(proxy, callback) {
    if (proxy !== undefined && typeof proxy !== "string") reject("WEB_PROXY_OVERRIDE_INVALID", 2);
    return this.proxyScope.run(proxy, callback);
  }
  proxySelection() {
    const value = this.proxyScope.getStore();
    if (value === undefined) return { specified: false, url: null };
    if (value === "") return { specified: true, url: null };
    if (value.startsWith("agentcfg:")) {
      const route = this.runtime.manifest.options.network?.routes?.[value.slice(9)];
      if (!route) reject("WEB_PROXY_OVERRIDE_INVALID", 2);
      return { specified: true, url: route.mode === "proxy" ? route.proxy_url : null };
    }
    try {
      const url = new URL(value);
      if (!/^https?:$/.test(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== "/") throw new Error();
      return { specified: true, url: url.href };
    } catch { reject("WEB_PROXY_OVERRIDE_INVALID", 2); }
  }
  route(name, override) {
    const binding = this.runtime.manifest.web_services?.[name];
    if (!binding) reject("WEB_SERVICE_NOT_SELECTED", 2);
    if (override === undefined) return binding.network_route;
    const routes = this.runtime.manifest.options.network?.routes ?? {};
    let target;
    if (override !== "" && !override.startsWith("agentcfg:")) {
      try {
        const value = new URL(override);
        if (!/^https?:$/.test(value.protocol) || value.username || value.password || value.search || value.hash || value.pathname !== "/") throw new Error();
        target = value.href;
      } catch { reject("WEB_PROXY_OVERRIDE_INVALID", 2); }
    }
    const matches = Object.entries(routes).filter(([id, value]) => value.service_ids?.includes("web:" + name)
      && (override === "agentcfg:" + id || override === "" && value.mode === "direct"
        || target && value.mode === "proxy" && new URL(value.proxy_url).href === target));
    if (matches.length !== 1) reject("WEB_ROUTE_OVERRIDE_UNBOUND", 2);
    return matches[0][0];
  }
  async fetch(name, input, init = {}) {
    const operation = this.current();
    const routeName = this.route(name, init.__proxy ?? this.proxyScope.getStore());
    const key = name + "/" + routeName;
    if (!operation.transports.has(key)) operation.transports.set(key, this.fetchFactory(this.runtime, name, {
      routeName, serviceRunId: operation.id, onProxyFailure: () => { operation.proxyFailed = true; operation.controller.abort(); },
    }));
    const transport = await operation.transports.get(key);
    this.current();
    const { __proxy, ...options } = init;
    return transport(input, { ...options, signal: AbortSignal.any([operation.controller.signal, ...(init.signal ? [init.signal] : [])]) });
  }
  authenticatedFetch(profile, input, init) { return authenticatedWebFetch(this.runtime, profile, input, init); }
  async close() {
    await Promise.all([...this.operations.values()].map(async operation => {
      let result = await operation.cancel();
      if (!result) {
        let timer;
        try { result = await Promise.race([operation.completion, new Promise(resolve => { timer = setTimeout(() => resolve(null), 5000); })]); }
        finally { clearTimeout(timer); }
      }
      if (!result?.termination_confirmed) reject("WEB_TERMINATION_UNKNOWN", 4);
    }));
  }
}
