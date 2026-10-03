import { afterEach, expect, test } from "bun:test";
import { createReviewOnce } from "../src/permission-control/review-services";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
function setup(api = "openai-completions", modelId = "cheap") {
  const model = { provider: "fictional", id: modelId, api, baseUrl: "https://api.example.invalid/v1" };
  let auth = 0;
  const registry = { find: () => model, isUsingOAuth: () => false,
    getApiKey: async () => { auth++; return "PRIVATE_KEY_SENTINEL"; },
    permissionReviewAuthIsPassive: () => true,
    resolveModelHeaders: () => { throw new Error("GENERAL_HEADER_RESOLVER_FORBIDDEN"); },
    resolvePermissionReviewHeaders: () => ({ "x-test": "host-header" }) };
  return { model, registry, auth: () => auth, service: createReviewOnce(registry as any, "session-1",
    { ...request("request-1", modelId).call, deadline: performance.now() + 30_000 }) };
}
function request(id = "request-1", model = "cheap") {
  let starts = 0;
  const controller = new AbortController();
  return { starts: () => starts, controller, call: { requestId: id,
    model: { provider: "fictional", model }, input: "synthetic review input",
    maxOutputTokens: 512, maxOutputBytes: 4096, deadline: performance.now() + 25_000,
    signal: controller.signal, onInferenceStarted: () => { starts++; } } };
}

test("Kimi Code review disables thinking without changing fixed output limits", async () => {
  const host = setup("openai-completions", "kimi-for-coding");
  const r = request("request-1", "kimi-for-coding");
  globalThis.fetch = (async (_url: any, init: any) => {
    expect(JSON.parse(init.body)).toEqual({ model: "kimi-for-coding",
      messages: [{ role: "user", content: "synthetic review input" }], max_tokens: 512,
      stream: false, thinking: { type: "disabled" } });
    return Response.json(answer("openai-completions"));
  }) as unknown as typeof fetch;
  expect((await host.service(r.call)).status).toBe("ok");
  expect(r.starts()).toBe(1);
  const anthropic = setup("anthropic-messages", "kimi-for-coding");
  const anthropicRequest = request("request-1", "kimi-for-coding");
  globalThis.fetch = (async (_url: any, init: any) => {
    expect(JSON.parse(init.body)).toEqual({ model: "kimi-for-coding",
      messages: [{ role: "user", content: "synthetic review input" }], max_tokens: 512, stream: false });
    return Response.json(answer("anthropic-messages"));
  }) as unknown as typeof fetch;
  expect((await anthropic.service(anthropicRequest.call)).status).toBe("ok");
});
function answer(api: string) {
  return api === "anthropic-messages" ? { stop_reason: "end_turn", content: [{ type: "text", text: "{}" }], usage: { output_tokens: 2 } } :
    { choices: [{ finish_reason: "stop", message: { content: "{}" } }], usage: { completion_tokens: 2 } };
}

for (const api of ["openai-completions", "anthropic-messages"]) {
  test(`single direct ${api} call binds configured model, host credentials and limits`, async () => {
    const host = setup(api); const r = request(); let calls = 0;
    globalThis.fetch = (async (url: any, init: any) => {
      calls++;
      expect(String(url)).toBe(`https://api.example.invalid/v1/${api === "anthropic-messages" ? "messages" : "chat/completions"}`);
      const body = JSON.parse(init.body);
      expect(body).toEqual({ model: "cheap", messages: [{ role: "user", content: "synthetic review input" }], max_tokens: 512, stream: false });
      expect(init.redirect).toBe("error");
      expect(init.headers.get(api === "anthropic-messages" ? "x-api-key" : "authorization")).toContain("PRIVATE_KEY_SENTINEL");
      return Response.json(answer(api));
    }) as unknown as typeof fetch;
    const reply = await host.service(r.call);
    expect(reply).toEqual({ status: "ok", text: "{}", outputTokens: 2, toolCalls: [] });
    expect(JSON.stringify(reply)).not.toContain("PRIVATE_KEY_SENTINEL");
    expect((await host.service({ ...r.call })).status).toBe("cancelled");
    expect(calls).toBe(1); expect(r.starts()).toBe(1); expect(host.auth()).toBe(1);
  });
}

test("HTTP failure, invalid output, redirects and thrown errors never retry or expose body", async () => {
  for (const response of [() => new Response("PRIVATE_KEY_SENTINEL", { status: 429 }),
    () => Response.json({ choices: [{ finish_reason: "tool_calls", message: { tool_calls: [{}] } }] }),
    () => { throw new Error("PRIVATE_KEY_SENTINEL"); },
    () => Response.json({ ...answer("openai-completions"), usage: { completion_tokens: 513 } })]) {
    const host = setup(); const r = request(); let calls = 0;
    globalThis.fetch = (async () => { calls++; return response(); }) as unknown as typeof fetch;
    const reply = await host.service(r.call);
    expect(reply.status).toBe("service-failure");
    expect(calls).toBe(1); expect(r.starts()).toBe(1);
    expect(JSON.stringify(reply)).not.toContain("PRIVATE_KEY_SENTINEL");
  }
});

test("unsupported API, OAuth and cancelled input perform zero authentication or inference", async () => {
  for (const kind of ["transport", "oauth", "cancel"]) {
    const host = setup(); const r = request(); let calls = 0;
    if (kind === "transport") host.model.api = "openai-responses";
    if (kind === "oauth") host.registry.isUsingOAuth = () => true;
    if (kind === "cancel") r.controller.abort();
    globalThis.fetch = (async () => { calls++; throw new Error("NETWORK_DISABLED"); }) as unknown as typeof fetch;
    expect((await host.service(r.call)).status).toBe(kind === "cancel" ? "cancelled" : "unsupported");
    expect(calls).toBe(0); expect(host.auth()).toBe(0); expect(r.starts()).toBe(0);
  }
});

test("cancellation while resolving auth and excessive response bytes cannot produce a late success", async () => {
  const host = setup(); const r = request(); let calls = 0;
  host.registry.getApiKey = async () => { r.controller.abort(); return "PRIVATE_KEY_SENTINEL"; };
  globalThis.fetch = (async () => { calls++; return Response.json(answer("openai-completions")); }) as unknown as typeof fetch;
  expect((await host.service(r.call)).status).toBe("cancelled");
  expect(calls).toBe(0); expect(r.starts()).toBe(0);
  globalThis.fetch = (async () => new Response("x".repeat(65 * 1024))) as unknown as typeof fetch;
  expect((await setup().service(request().call)).status).toBe("service-failure");
});

test("host binding rejects substituted input/model and remains cancellable with a different caller signal", async () => {
  const host = setup(); const r = request(); let calls = 0;
  const original = new AbortController();
  const service = createReviewOnce(host.registry as any, "session-1", { ...r.call, signal: original.signal });
  globalThis.fetch = (async () => { calls++; return Response.json(answer("openai-completions")); }) as unknown as typeof fetch;
  expect((await service({ ...r.call, input: "substituted" })).status).toBe("cancelled");
  expect((await service({ ...r.call, model: { provider: "other", model: "cheap" } })).status).toBe("cancelled");
  original.abort();
  expect((await service(r.call)).status).toBe("cancelled");
  expect(calls).toBe(0); expect(host.auth()).toBe(0);
});

test("transport timeout aborts the only fetch and permits no late success", async () => {
  const host = setup(); const r = request(); r.call.deadline = performance.now() + 30;
  const service = createReviewOnce(host.registry as any, "session-1", r.call); let calls = 0;
  globalThis.fetch = ((_url: any, init: any) => {
    calls++;
    return new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(new Error("timeout")), { once: true }));
  }) as unknown as typeof fetch;
  expect((await service(r.call)).status).toBe("timeout");
  expect(calls).toBe(1); expect(r.starts()).toBe(1);
});

test("endpoint drift during auth never sends a newly resolved credential to the old endpoint", async () => {
  const host = setup(); const r = request(); let calls = 0;
  host.registry.getApiKey = async () => { host.model.baseUrl = "https://changed.example.invalid/v1"; return "NEW_PRIVATE_KEY"; };
  globalThis.fetch = (async () => { calls++; throw new Error("NETWORK_DISABLED"); }) as unknown as typeof fetch;
  expect((await host.service(r.call)).status).toBe("cancelled");
  expect(calls).toBe(0); expect(r.starts()).toBe(0);
});

test("prepare resolves credentials once before binding the redacted envelope", async () => {
  const { prepareReviewOnce } = await import("../src/permission-control/review-services");
  const host = setup(); const r = request(); let calls = 0; let headers = 0;
  host.registry.resolvePermissionReviewHeaders = () => { headers++; return { "x-test": "HEADER_SECRET_SENTINEL" }; };
  globalThis.fetch = (async (_url: any, init: any) => {
    calls++; expect(init.body).not.toContain("PRIVATE_KEY_SENTINEL");
    expect(init.body).not.toContain("HEADER_SECRET_SENTINEL");
    return Response.json(answer("openai-completions"));
  }) as unknown as typeof fetch;
  const prepared = await prepareReviewOnce(host.registry as any, "session-1", r.call);
  expect(prepared.status).toBe("ready"); expect(calls).toBe(0); expect(r.starts()).toBe(0);
  if (prepared.status !== "ready") throw new Error("expected ready");
  expect(prepared.knownSecrets).toEqual(["PRIVATE_KEY_SENTINEL", "HEADER_SECRET_SENTINEL"]);
  expect(Object.isFrozen(prepared.knownSecrets)).toBe(true);
  const service = prepared.bind(r.call.input);
  expect((await prepared.bind("second")(r.call)).status).toBe("cancelled");
  expect((await service({ ...r.call, input: "changed" })).status).toBe("cancelled");
  expect((await service(r.call)).status).toBe("ok");
  expect((await service(r.call)).status).toBe("cancelled");
  expect(host.auth()).toBe(1); expect(headers).toBe(1); expect(calls).toBe(1);
});

test("prepared authentication is cancelled by endpoint drift or original signal before binding", async () => {
  const { prepareReviewOnce } = await import("../src/permission-control/review-services");
  for (const kind of ["endpoint", "cancel"]) {
    const host = setup(); const r = request(); let calls = 0;
    globalThis.fetch = (async () => { calls++; throw new Error("NETWORK_DISABLED"); }) as unknown as typeof fetch;
    const prepared = await prepareReviewOnce(host.registry as any, "session-1", r.call);
    if (prepared.status !== "ready") throw new Error("expected ready");
    if (kind === "endpoint") host.model.baseUrl = "https://changed.example.invalid/v1";
    else r.controller.abort();
    expect((await prepared.bind(r.call.input)({ ...r.call, signal: new AbortController().signal })).status).toBe("cancelled");
    expect(calls).toBe(0); expect(r.starts()).toBe(0); expect(host.auth()).toBe(1);
  }
});

test("noncooperative authentication remains bounded and preparation errors never disclose secrets", async () => {
  const { prepareReviewOnce } = await import("../src/permission-control/review-services");
  for (const kind of ["timeout", "cancelled", "service-failure"] as const) {
    const host = setup(); const r = request(); let calls = 0;
    globalThis.fetch = (async () => { calls++; throw new Error("NETWORK_DISABLED"); }) as unknown as typeof fetch;
    host.registry.getApiKey = async () => {
      if (kind === "service-failure") throw new Error("PRIVATE_KEY_SENTINEL");
      if (kind === "cancelled") setTimeout(() => r.controller.abort(), 5);
      return new Promise<string>(() => {});
    };
    const prepared = await prepareReviewOnce(host.registry as any, "session-1", { ...r.call, deadline: performance.now() + 25 });
    expect(prepared).toEqual({ status: kind });
    expect(calls).toBe(0); expect(r.starts()).toBe(0);
  }
});


test("command-backed or unproven authentication never reaches auth/header resolvers or inference", async () => {
  for (const kind of ["command-key", "command-header", "unknown-resolver", "missing-proof"]) {
    const host = setup(); const r = request(); let headers = 0; let calls = 0;
    host.registry.permissionReviewAuthIsPassive = () => false;
    if (kind === "missing-proof") delete (host.registry as any).permissionReviewAuthIsPassive;
    host.registry.resolvePermissionReviewHeaders = () => { headers++; return { "x-test": "never" }; };
    globalThis.fetch = (async () => { calls++; throw new Error("NETWORK_DISABLED"); }) as unknown as typeof fetch;
    expect((await host.service(r.call)).status).toBe("unsupported");
    expect(host.auth()).toBe(0); expect(headers).toBe(0); expect(calls).toBe(0); expect(r.starts()).toBe(0);
  }
});
