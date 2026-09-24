// 固定 openai-completions 的实际 fetch 边界；SDK 与 provider 两层重试均关闭。
import { randomUUID } from "node:crypto";
import { digest, reject } from "./managed-types.ts";

const requestMethods = ["stream", "streamSimple"];
const forbiddenMethods = ["complete", "completeSimple", "fetchDeferred", "cancelDeferred", "login", "logout", "refresh", "refreshModels"];

async function requestBody(request) {
  const reader = request.body?.getReader();
  if (!reader) reject("TRANSPORT_PAYLOAD_REQUIRED", 5);
  const chunks = []; let size = 0;
  try {
    for (;;) {
      const item = await reader.read();
      if (item.done) break;
      size += item.value.byteLength;
      if (size > 8 * 1024 * 1024) reject("TRANSPORT_PAYLOAD_LIMIT", 5);
      chunks.push(item.value);
    }
    return Buffer.concat(chunks).toString("utf8");
  } finally { reader.releaseLock(); }
}

export class ManagedHttpTransport {
  constructor({ descriptor, route, ledger, fetchRoute, bounds = () => ({ input_tokens: null, output_tokens: null, cost: null }), report = async () => {}, observePayload = async () => {} }) {
    if (typeof fetchRoute !== "function" || route.id !== descriptor.route_id) reject("UNSUPPORTED_TRANSPORT", 5);
    this.api = "openai-completions"; this.certified = true;
    this.model_digest = descriptor.model_digest; this.route_id = route.id;
    this.descriptor = descriptor; this.route = route; this.ledger = ledger; this.fetchRoute = fetchRoute;
    this.bounds = bounds; this.report = report; this.observePayload = observePayload; this.pending = new Set(); this.unknown = false; this.observed_model = null;
    this.turns = 0; this.bound = false; this.budgetExhausted = false; this.denialReport = Promise.resolve();
  }
  async bind(runtime, { authorize }) {
    if (this.bound) reject("TRANSPORT_ALREADY_BOUND", 4);
    if (requestMethods.some(name => typeof runtime[name] !== "function")) reject("UNSUPPORTED_TRANSPORT", 5);
    this.bound = true;
    const originals = new Map();
    const replace = (name, fn) => { originals.set(name, runtime[name]); runtime[name] = fn; };
    for (const name of requestMethods) {
      if (typeof runtime[name] !== "function") reject("UNSUPPORTED_TRANSPORT", 5);
      const original = runtime[name].bind(runtime);
      replace(name, (model, context, options = {}) => {
        if (model.provider !== this.descriptor.provider_id || model.id !== this.descriptor.model_id || model.api !== this.api
            || new URL(model.baseUrl).href.replace(/\/$/, "") !== new URL(this.route.base_url).href.replace(/\/$/, "")) reject("MODEL_ROUTE_MISMATCH", 4);
        const turn = ++this.turns, turn_id = "turn-" + turn;
        if (this.turns > this.descriptor.turn_ceiling) {
          this.budgetExhausted = true;
          // SDK 会把同步拒绝转成普通 assistant error；独立保存原因，finish 等待其落盘。
          this.denialReport = this.denialReport.then(() => this.report({ request_id: randomUUID(), ordinal: null, phase: "request_denied", code: "BUDGET_EXHAUSTED" }));
          void this.denialReport.catch(() => {});
          reject("BUDGET_EXHAUSTED", 4);
        }
        return original(model, context, { ...options, maxRetries: 0, transport: "sse",
          fetch: (resource, init) => this.send(resource, init, { turn_id, reason: ["second-opinion", "second-view"].includes(this.descriptor.step_id) ? "second-view"
            : turn === 1 ? (this.descriptor.continuation_of === null ? "initial" : "retry")
            : context.messages?.some(message => message.role === "toolResult" && message.isError && message.toolName === "structured_output") ? "schema-repair" : "tool-continuation", model, authorize }) });
      });
    }
    for (const name of forbiddenMethods) if (typeof runtime[name] === "function") replace(name, () => reject("UNMETERED_HELPER_FORBIDDEN", 5));
    return { finish: () => this.finish(), close: async () => {
      for (const [name, original] of originals) runtime[name] = original;
      this.bound = false;
      this.fetchRoute.close?.();
      await this.finish();
    } };
  }
  async finish() {
    await this.denialReport;
    if (this.pending.size || this.unknown) reject("TRANSPORT_OUTCOME_UNKNOWN", 5);
  }
  async send(resource, init, { turn_id, reason, model, authorize }) {
    await authorize();
    const request = new Request(resource, init);
    const endpoint = new URL(this.route.base_url.replace(/\/$/, "") + "/chat/completions").href;
    if (request.method !== "POST" || request.url !== endpoint) reject("MODEL_ROUTE_MISMATCH", 4);
    const body = await requestBody(request);
    let payload;
    try { payload = JSON.parse(body); } catch { reject("TRANSPORT_PAYLOAD_INVALID", 5); }
    if (!payload || payload.model !== this.descriptor.model_id || payload.stream !== true) reject("MODEL_ROUTE_MISMATCH", 4);
    const bound = this.bounds(payload, model);
    const request_id = randomUUID();
    const reservation = { task_id: this.descriptor.task_id, attempt_id: this.descriptor.attempt_id, request_id, reason, turn_id,
      route_id: this.route_id, grant_digest: digest(this.descriptor), payload_digest: digest(payload),
      reserved_input_tokens: bound.input_tokens, reserved_output_tokens: bound.output_tokens, reserved_cost: bound.cost };
    let saved;
    try {
      saved = await this.ledger.reserve(reservation);
      await authorize();
      await this.ledger.mark_sent(request_id);
    } catch (error) {
      if (error.code === "BUDGET_EXHAUSTED") this.budgetExhausted = true;
      const safe = new Set(["BUDGET_EXHAUSTED", "UNBOUNDED_REQUEST", "BUDGET_SCOPE_MISMATCH", "DEADLINE_EXCEEDED", "GRANT_STALE", "CONTROL_REVOKED", "REQUEST_ALREADY_SENT_OR_UNKNOWN"]);
      await this.report({ request_id, ordinal: null, phase: "request_denied", code: safe.has(error.code) ? error.code : "REQUEST_ADMISSION_FAILED" });
      throw error;
    }
    this.pending.add(request_id);
    const unknown = async () => {
      this.unknown = true; this.pending.delete(request_id);
      await this.ledger.mark_unknown(request_id);
    };
    let response;
    try {
      await this.report({ request_id, ordinal: saved.ordinal, phase: "request_committed" });
      await authorize();
      response = await this.fetchRoute(endpoint, { method: "POST", headers: request.headers, body,
        signal: request.signal, redirect: "error" }, this.route);
      const headers = Object.fromEntries(["date", "retry-after", "x-ratelimit-reset-requests", "x-ratelimit-remaining-requests", "x-ratelimit-reset-tokens"]
        .filter(name => response.headers.has(name)).map(name => [name, response.headers.get(name)]));
      await this.report({ request_id, ordinal: saved.ordinal, phase: "response_headers", status: response.status, headers });
    } catch { await unknown(); reject("TRANSPORT_OUTCOME_UNKNOWN", 5); }
    if (!response.ok || !response.body) { await unknown(); return response; }
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = "", usage = null, done = false, settled = false;
    const observe = line => {
      if (!line.startsWith("data:")) return;
      const raw = line.slice(5).trim();
      if (done && raw) reject("TRANSPORT_EVENT_AFTER_FINAL", 5);
      if (raw === "[DONE]") { done = true; return; }
      if (!raw) return;
      let event;
      try { event = JSON.parse(raw); } catch { reject("TRANSPORT_EVENT_INVALID", 5); }
      if (typeof event.model === "string") {
        if (event.model !== this.descriptor.model_id) reject("OBSERVED_MODEL_MISMATCH", 4);
        this.observed_model = { provider_id: this.descriptor.provider_id, model_id: event.model };
      }
      if (event.usage) {
        const input = event.usage.prompt_tokens, output = event.usage.completion_tokens;
        if (![input, output].every(value => Number.isSafeInteger(value) && value >= 0)) reject("TRANSPORT_USAGE_INVALID", 5);
        usage = { usage_id: request_id + ":usage", input_tokens: input, output_tokens: output, cost: null };
      }
    };
    const output = new ReadableStream({
      pull: async controller => {
        try {
          const item = await reader.read();
          buffer += item.done ? decoder.decode() : decoder.decode(item.value, { stream: true });
          if (Buffer.byteLength(buffer) > 1024 * 1024) reject("TRANSPORT_EVENT_LIMIT", 5);
          let end;
          while ((end = buffer.indexOf("\n")) !== -1) { observe(buffer.slice(0, end).replace(/\r$/, "")); buffer = buffer.slice(end + 1); }
          if (item.done && buffer.trim()) observe(buffer);
          // OpenAI SDK 在 [DONE] 后会取消 reader；必须在转交该事件前提交结算。
          if (done && !settled) {
            await this.ledger.settle(request_id, usage ?? { usage_id: null, input_tokens: null, output_tokens: null, cost: null });
            await this.observePayload({ request_id, ordinal: saved.ordinal, payload });
            this.pending.delete(request_id); settled = true;
            await this.report({ request_id, ordinal: saved.ordinal, phase: "request_settled", usage_id: usage?.usage_id ?? null, observed_model: this.observed_model });
          }
          if (item.done) {
            if (!done) reject("TRANSPORT_EVENT_INCOMPLETE", 5);
            controller.close();
          } else controller.enqueue(item.value);
        } catch {
          if (!settled) await unknown();
          await reader.cancel().catch(() => {});
          controller.error(new Error("TRANSPORT_OUTCOME_UNKNOWN"));
        }
      },
      cancel: async () => { if (!settled) await unknown(); await reader.cancel(); },
    });
    return new Response(output, { status: response.status, statusText: response.statusText, headers: response.headers });
  }
}
