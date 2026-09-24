import { test, assert } from "./recorded-test.ts";
import { createServer } from "node:http";
import { installHttpTransport, type HttpHooks } from "../src/adapters/http-transport.ts";
import { Store } from "../src/store/database.ts";
import { barrier, isolatedDirectory, listenLoopback } from "./helpers.ts";

for (const mode of ["allowed", "revoked-after-recheck", "cancel-after-admission", "deferred", "async", "twice"] as const)
test(`[A RTB-009] actual HTTP invocation ${mode} respects committed authority and keeps admission separate from sending`, async t => {
  const store = new Store(isolatedDirectory(t)), owner = store.claimOwner("scope", "owner"), receiver = barrier(), abort = new AbortController();
  store.prepare(owner, "intent", "model", {}); store.markSent(owner, "intent");
  let received = 0, requestId = "", replay: (() => void) | undefined; const errors: boolean[] = [], trace: string[] = [];
  const server = createServer((req, res) => { req.resume(); req.on("end", () => { received++; trace.push("receiver"); res.end("ok"); receiver.resolve(); }); });
  await listenLoopback(server); const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`;
  const hooks: HttpHooks = { before: attempt => { store.assertOwner(owner); requestId = attempt.id; store.reserveRequest(owner, "intent", attempt.id, [{ id: "budget", ceiling: 1 }]); },
    recheck: () => { trace.push("recheck"); if (mode === "revoked-after-recheck") { store.revokeOwner(owner); trace.push("revoke"); } },
    response: attempt => store.settleRequest(attempt.id, "sent"),
    error: (attempt, invoked) => { errors.push(invoked); store.settleRequest(attempt.id, invoked ? "unknown" : "not_sent"); } };
  if (mode === "async") hooks.invokeWithin = async (_attempt, invoke) => { await Promise.resolve(); invoke(); };
  else hooks.invokeWithin = (attempt, invoke) => {
    replay = invoke; if (mode === "deferred") return;
    store.transaction(() => { store.assertOwner(owner); trace.push("authorize"); store.put("request-admissions", attempt.id, { provesSend: false }); });
    trace.push("commit"); if (mode === "cancel-after-admission") abort.abort();
    trace.push("invoke"); invoke(); if (mode === "twice") invoke();
  };
  const transport = installHttpTransport(() => ({ baseUrl, model: "fixture", token: 1 }), hooks, true, false);
  t.after(() => { transport.dispose(); server.closeAllConnections(); server.close(); store.close(); });
  const pending = transport.fetch(`${baseUrl}/chat/completions`, { method: "POST", body: '{"model":"fixture"}', signal: abort.signal });
  if (mode === "allowed") {
    store.revokeOwner(owner); trace.push("revoke"); const response = await pending;
    assert.equal(await response.text(), "ok"); assert.equal(received, 1); assert.deepEqual(errors, []);
    assert.ok(trace.indexOf("commit") < trace.indexOf("invoke")); assert.ok(trace.indexOf("invoke") < trace.indexOf("revoke"));
    assert.equal(store.request(requestId)!.state, "sent"); assert.equal(store.bucket("budget")!.used, 1);
  } else {
    await assert.rejects(pending, { code: mode === "async" ? "ASYNC_HTTP_HOOK_NOT_SUPPORTED" : mode === "deferred" ? "HTTP_INVOCATION_NOT_PERFORMED"
      : mode === "twice" ? "HTTP_INVOCATION_SCOPE_CLOSED" : mode === "cancel-after-admission" ? "REQUEST_CANCELLED_BEFORE_SEND" : "CONTROL_REVOKED" });
    if (mode === "twice") await receiver.promise;
    assert.equal(received, mode === "twice" ? 1 : 0); assert.deepEqual(errors, [mode === "twice"]);
    assert.equal(store.request(requestId)!.state, mode === "twice" ? "unknown" : "not_sent");
    assert.equal(store.bucket("budget")!.used, 0); assert.equal(store.bucket("budget")!.reserved, mode === "twice" ? 1 : 0);
  }
  if (mode === "cancel-after-admission") { assert.ok(store.get("request-admissions", requestId)); assert.equal(received, 0); }
  if (replay) { assert.throws(replay, { code: "HTTP_INVOCATION_SCOPE_CLOSED" }); assert.equal(received, mode === "allowed" || mode === "twice" ? 1 : 0); }
});
