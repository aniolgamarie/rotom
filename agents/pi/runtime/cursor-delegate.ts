// Cursor 的委托进程只注册一个模型；HTTP/2 必须发生在已授权的模型调用中。
import { AsyncLocalStorage } from "node:async_hooks";
import { reject } from "./managed-types.ts";

export async function cursorDelegateTransport({ plugin, modelRuntime, http2, createStream, selected, endpoint, accessToken }) {
  const scope = new AsyncLocalStorage(), sessions = new Set(), cleanup = [];
  const connect = http2.connect;
  const address = new URL(endpoint);
  let registered = false, closed = false, wireRequests = 0, wireResponses = 0, wireBytes = 0, failed = false;
  http2.connect = function (authority, options, ...rest) {
    const permit = scope.getStore();
    if (closed || !permit || permit.closed || new URL(authority).href !== address.href || options !== undefined || rest.length) reject("CURSOR_ROUTE_UNBOUND", 4);
    if (++permit.connections > 1) reject("CURSOR_RETRY_FORBIDDEN", 4);
    const client = connect.call(this, authority);
    sessions.add(client);
    client.once("close", () => sessions.delete(client));
    const request = client.request.bind(client);
    client.request = (headers, ...args) => {
      const active = scope.getStore();
      if (closed || !active || active.closed || headers[":method"] !== "POST" || headers[":path"] !== "/agent.v1.AgentService/Run"
          || headers.authorization !== "Bearer " + accessToken) reject("CURSOR_REQUEST_UNBOUND", 4);
      if (++active.requests > 1) reject("CURSOR_RETRY_FORBIDDEN", 4);
      wireRequests++;
      const stream = request(headers, ...args);
      stream.on("response", value => { if (Number(value[":status"]) === 200) wireResponses++; });
      stream.on("data", value => { wireBytes += value.byteLength; });
      return stream;
    };
    return client;
  };
  try {
    await plugin({
      on(name, callback) { if (name === "session_shutdown") cleanup.push(callback); },
      registerCommand() {},
      registerProvider(id, value) {
        if (registered || id !== "cursor" || value.api !== "cursor-native" || new URL(value.baseUrl).href !== address.href) reject("CURSOR_PROVIDER_UNBOUND", 5);
        const models = value.models.filter(model => model.id === selected.model_id);
        if (models.length !== 1) reject("DELEGATE_MODEL_UNBOUND", 5);
        const { oauth, refreshModels, ...configuration } = value;
        modelRuntime.registerProvider(id, { ...configuration, models, apiKey: "cursor-native" });
        registered = true;
      },
    });
    if (!registered) reject("CURSOR_PROVIDER_UNBOUND", 5);
  } catch (error) { http2.connect = connect; throw error; }
  return {
    api: "cursor-native",
    invoke(invoke, model, context, options, authorize, observations) {
      const output = createStream(), observation = { done: false, failed: false, model: null };
      observations.push(observation);
      const permit = { closed: false, connections: 0, requests: 0 };
      void scope.run(permit, async () => {
        try {
          await authorize();
          const stream = invoke(model, context, { ...options, maxRetries: 0, maxIdleRetries: 0, recoverBeforeRetry: false });
          for await (const event of stream) {
            if (observation.done) throw Error("CURSOR_STREAM_REPLAY");
            if (event.type === "done" || event.type === "error") { observation.done = true; observation.failed = event.type === "error"; }
            if (event.type === "error") { failed = true; output.push({ ...event, error: { ...event.error, errorMessage: "CURSOR_DELEGATE_FAILED" } }); }
            else output.push(event);
          }
          if (!observation.done) throw Error("CURSOR_STREAM_INCOMPLETE");
        } catch {
          failed = true; observation.failed = true; observation.done = true;
          output.push({ type: "error", reason: "error", error: { role: "assistant", content: [], api: "cursor-native", provider: "cursor", model: selected.model_id,
            usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
            stopReason: "error", timestamp: Date.now(), errorMessage: "CURSOR_DELEGATE_FAILED" } });
        } finally { permit.closed = true; output.end(); }
      });
      return output;
    },
    verify() { if (failed || !wireRequests || !wireResponses || !wireBytes) reject("CURSOR_EXECUTION_UNVERIFIED", 5); },
    async close(sessionManager) {
      closed = true;
      try {
        for (const callback of cleanup) { try { await callback({}, { sessionManager }); } catch { failed = true; } }
        const waiting = [...sessions].map(client => new Promise(resolve => { client.once("close", resolve); client.destroy(); }));
        let deadline;
        try { await Promise.race([Promise.all(waiting), new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error("CURSOR_CLOSE_UNKNOWN")), 5000); })]); }
        finally { clearTimeout(deadline); }
      } finally { http2.connect = connect; }
    },
  };
}
