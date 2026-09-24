// 宿主内监听器复用唯一 manager；端点授权由具体能力先完成。
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { reject } from "./managed-types.ts";
export const listeners = new WeakMap();
export async function listenOwnedServer(server, options, seconds, { runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")],
    entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")], errorPrefix = "MCP", setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  if (!entry?.manager || !entry.pi || !entry.getContext || listeners.has(server)) reject(errorPrefix + "_LISTENER_MANAGER_REQUIRED", 5);
  if (options.signal?.aborted || options.startupSignal?.aborted) reject(errorPrefix + "_CALLBACK_CANCELED", 4);
  const id = "listener-" + randomUUID(), sockets = new Set();
  let started = false, bound = false, closed = false, serverClosed = false, stopping = false, failed = false, binding, closing, timer;
  let ready, notReady, ended, consumed = false;
  const readiness = new Promise((resolve, reject) => { ready = resolve; notReady = reject; });
  const completion = new Promise(resolve => { ended = resolve; });
  const outcome = () => ({ terminal_status: failed ? "failed" : stopping ? "canceled" : "completed", response_text: "Owned listener closed",
    termination_confirmed: true, external_work_empty: true });
  const onConnection = socket => { sockets.add(socket); socket.once("close", () => { sockets.delete(socket); if (serverClosed) onClose(); }); };
  const onClose = () => { serverClosed = true; if (sockets.size === 0) { closed = true; ended(); clearTimer(timer); } };
  server.on("connection", onConnection); server.on("close", onClose);
  async function stopResources() {
    if (closed) return;
    if (closing) return closing;
    closing = (async () => {
      if (!started) { closed = true; ended(); return; }
      await binding?.catch(() => {});
      if (closed) return;
      await new Promise((resolve, fail) => {
        try {
          server.close(error => {
            if (error && !(error.code === "ERR_SERVER_NOT_RUNNING" && !bound && sockets.size === 0)) { fail(new Error(errorPrefix + "_LISTENER_TERMINATION_UNKNOWN")); return; }
            if (sockets.size !== 0) { fail(new Error(errorPrefix + "_LISTENER_TERMINATION_UNKNOWN")); return; }
            closed = true; ended(); resolve();
          });
          server.closeAllConnections?.();
          for (const socket of sockets) socket.destroy();
        } catch { fail(new Error(errorPrefix + "_LISTENER_TERMINATION_UNKNOWN")); }
      });
    })();
    return closing;
  }
  async function cancel() {
    stopping = true; notReady(new Error(errorPrefix + "_CALLBACK_CANCELED"));
    await stopResources();
    return outcome();
  }
  const onAbort = () => { if (closed) return; void cancel().catch(() => {}); entry.manager.abort(id); };
  const onError = () => { failed = true; notReady(new Error(errorPrefix + "_CALLBACK_BIND_FAILED")); void stopResources().catch(() => {}); };
  server.on("error", onError);
  const detach = () => {
    options.signal?.removeEventListener("abort", onAbort);
    options.startupSignal?.removeEventListener("abort", onAbort);
    clearTimer(timer);
    server.off("connection", onConnection); server.off("error", onError); server.off("close", onClose);
  };
  const consume = () => {
    if (!closed || consumed) return;
    if (entry.manager.getRecord(id)) { entry.manager.consumeControlled(id); entry.manager.removeConsumedControlled(id); }
    consumed = true;
    detach();
  };
  const close = async () => {
    try { await cancel(); }
    catch (error) { entry.manager.abort(id); throw error; }
    const record = entry.manager.getRecord(id);
    if (record) {
      if (!started) entry.manager.abort(id);
      await record.promise;
      consume();
    }
    detach();
  };
  listeners.set(server, { close, closed: () => closed });
  try {
    entry.manager.spawnWithExecutor(entry.pi, entry.getContext(), options.kind ?? "mcp-callback", options.kind ?? "owned-listener", {
      kind: "resource", manager_run_id: id,
      async execute() {
        if (stopping) return outcome();
        started = true;
        binding = new Promise((resolve, fail) => {
          const bindError = () => fail(new Error(errorPrefix + "_CALLBACK_BIND_FAILED"));
          server.once("error", bindError);
          try { server.listen(options.port, options.host, () => { server.off("error", bindError); bound = true; resolve(); }); }
          catch { server.off("error", bindError); fail(new Error(errorPrefix + "_CALLBACK_BIND_FAILED")); }
        });
        try {
          await binding;
          if (stopping) { await stopResources(); return outcome(); }
          ready(); await completion; return outcome();
        } catch { failed = true; notReady(new Error(errorPrefix + "_CALLBACK_BIND_FAILED")); await stopResources(); return outcome(); }
      }, cancel,
    }, { description: options.description ?? "MCP OAuth callback", cwd: join(runtime.instanceRoot, "user-home"), isBackground: true });
    const record = entry.manager.getRecord(id);
    if (record) void record.promise.then(consume).catch(() => {});
    options.signal?.addEventListener("abort", onAbort, { once: true });
    options.startupSignal?.addEventListener("abort", onAbort, { once: true });
    timer = setTimer(onAbort, seconds * 1000); timer?.unref?.();
    if (options.signal?.aborted || options.startupSignal?.aborted) onAbort();
    await readiness;
    if (stopping) reject(errorPrefix + "_CALLBACK_CANCELED", 4);
    options.startupSignal?.removeEventListener("abort", onAbort);
  } catch (error) {
    await close(); throw error;
  }
}

export async function closeOwnedListener(server, errorPrefix = "MCP") {
  const owner = listeners.get(server);
  if (!owner) {
    if (server.listening) reject(errorPrefix + "_LISTENER_UNOWNED", 4);
    return;
  }
  await owner.close();
}
