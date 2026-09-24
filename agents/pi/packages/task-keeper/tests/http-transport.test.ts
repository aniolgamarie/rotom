import { isolatedDirectory, listenLoopback } from "./helpers.ts";
import { test, assert } from "./recorded-test.ts";
import { createServer } from "node:http";
import { once } from "node:events";
import { Store } from "../src/store/database.ts";
import { installHttpTransport } from "../src/adapters/http-transport.ts";

test("[A] HTTP response observation preserves error headers and does not consume the response body", async (t) => {
  const server = createServer((_req, res) => { res.writeHead(429, { "retry-after": "3600", "set-cookie": "not-for-ledger" }); res.end("original-body"); });
  await listenLoopback(server);
  const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`;
  let observed: { status: number; headers: Record<string, string> } | null = null;
  const transport = installHttpTransport(() => ({ baseUrl, model: "fixture", token: 1 }), { response: (_attempt, response) => { observed = response; } });
  t.after(() => { transport.dispose(); server.closeAllConnections(); server.close(); });
  const response = await fetch(`${baseUrl}/chat/completions`, { method: "POST", body: JSON.stringify({ model: "fixture" }) });
  assert.equal(await response.text(), "original-body");
  assert.equal(observed!.status, 429); assert.equal(observed!.headers["retry-after"], "3600");
  assert.equal(observed!.headers["set-cookie"], undefined);
});

test("[A RTB-009 T33] final gate denial means zero receiver calls, allowed calls receive distinct attempt identities", async (t) => {
  let received = 0, allowed = false;
  const server = createServer((_req, res) => { received++; res.end("ok"); });
  await listenLoopback(server);
  const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`, identities: string[] = [], errors: boolean[] = [];
  const transport = installHttpTransport(() => ({ baseUrl, model: "fixture", token: 1 }), {
    before: (attempt) => { identities.push(attempt.id); },
    recheck: () => { if (!allowed) throw new Error("denied"); },
    error: (_attempt, invoked) => { errors.push(invoked); },
  }, true);
  t.after(() => { transport.dispose(); server.closeAllConnections(); server.close(); });
  const request = () => fetch(`${baseUrl}/chat/completions`, { method: "POST", body: JSON.stringify({ model: "fixture" }) });
  await assert.rejects(request()); assert.equal(received, 0); assert.deepEqual(errors, [false]);
  allowed = true; assert.equal(await (await request()).text(), "ok"); assert.equal(received, 1);
  assert.equal(new Set(identities).size, 2);
  await assert.rejects(fetch(`${baseUrl}/unapproved`, { method: "POST" })); assert.equal(received, 1);
});

test("[A] bounded error observation retains numeric service codes, scrub credentials and preserve SDK bodies", async t => {
  const secret = "synthetic-sensitive-marker";
  const bodies = [JSON.stringify({ code: 429002, message: `TPM ${secret}` }), "x".repeat(10000)]; let index = 0;
  const server = createServer((_req, res) => { res.writeHead(429); res.end(bodies[index++]); });
  await listenLoopback(server);
  const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`;
  const observations: Array<{errorBody?: string}> = [];
  const transport = installHttpTransport(() => ({baseUrl, model: "fixture", token: 1}), { response: (_attempt, response) => observations.push(response) }, false, false);
  t.after(() => { transport.dispose(); server.closeAllConnections(); server.close(); });
  for (const original of bodies) {
    const response = await transport.fetch(`${baseUrl}/chat/completions`, { method: "POST", headers: { authorization: `Bearer ${secret}` }, body: '{"model":"fixture"}' });
    assert.equal(await response.text(), original);
  }
  assert.ok(observations[0].errorBody?.includes('429002'));
  assert.equal(observations[0].errorBody?.includes(secret), false);
  assert.equal(observations[1].errorBody, undefined);
});

test("[A RTB-009] protected redirects cannot hide an additional model POST behind one fetch permit", async t => {
  let initial = 0, redirected = 0;
  const server = createServer((req, res) => { req.resume(); req.on("end", () => {
    if (req.url === "/v1/chat/completions") { initial++; res.writeHead(307, { location: "/other" }); res.end(); }
    else { redirected++; res.end("unexpected model endpoint"); }
  }); });
  await listenLoopback(server);
  const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`;
  const transport = installHttpTransport(() => ({ baseUrl, model: "fixture", token: 1 }), {}, true, false);
  t.after(() => { transport.dispose(); server.closeAllConnections(); server.close(); });
  await assert.rejects(transport.fetch(`${baseUrl}/chat/completions`, { method: "POST", body: '{"model":"fixture"}', redirect: "follow" }));
  assert.equal(initial, 1); assert.equal(redirected, 0);
});
test("[A] incomplete error details do not hold the SDK response open indefinitely", async t => {
  const server = createServer((_req, res) => { res.writeHead(429); res.flushHeaders(); res.write('{"message":"unfinished'); });
  await listenLoopback(server);
  const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`;
  let detail: string | undefined;
  const transport = installHttpTransport(() => ({ baseUrl, model: "fixture", token: 1 }), { response: (_attempt, response) => { detail = response.errorBody; } }, false, false);
  t.after(() => { transport.dispose(); server.closeAllConnections(); server.close(); });
  const abort = new AbortController(), start = performance.now();
  const response = await transport.fetch(`${baseUrl}/chat/completions`, { method: "POST", body: '{"model":"fixture"}', signal: abort.signal });
  assert.ok(performance.now() - start < 5000); assert.equal(detail, undefined);
  abort.abort(); await assert.rejects(response.text());
});

for (const cut of ["before", "recheck"] as const) test(`[A RTB-009] cancellation at ${cut} proves no transport invocation or receiver effect`, async t => {
  let received = 0; const invoked: boolean[] = []; const abort = new AbortController();
  const server = createServer((_req, res) => { received++; res.end("unexpected"); }); await listenLoopback(server);
  const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`;
  const transport = installHttpTransport(() => ({ baseUrl, model: "fixture", token: 1 }), { [cut]: () => abort.abort(), error: (_attempt, sent) => { invoked.push(sent); } }, true, false);
  t.after(() => { transport.dispose(); server.closeAllConnections(); server.close(); });
  await assert.rejects(transport.fetch(`${baseUrl}/chat/completions`, { method: "POST", body: '{"model":"fixture"}', signal: abort.signal }));
  assert.equal(received, 0); assert.deepEqual(invoked, [false]);
});

test("[A RTB-011] cancel after actual receiver acceptance preserves unknown budget across owner replacement", async t => {
  const store = new Store(isolatedDirectory(t)), owner = store.claimOwner("scope", "owner"); store.prepare(owner, "intent", "model", {}); store.markSent(owner, "intent");
  let acknowledge!: () => void, received = 0, requestId = "";
  const accepted = new Promise<void>(resolve => { acknowledge = resolve; });
  const server = createServer((req, _res) => { req.resume(); req.on("end", () => { received++; acknowledge(); }); }); await listenLoopback(server);
  const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`;
  const transport = installHttpTransport(() => ({ baseUrl, model: "fixture", token: 1 }), {
    before: attempt => { requestId = attempt.id; store.reserveRequest(owner, "intent", requestId, [{ id: "work", ceiling: 1 }]); },
    response: attempt => store.settleRequest(attempt.id, "sent"),
    error: (attempt, invoked) => { store.settleRequest(attempt.id, invoked ? "unknown" : "not_sent"); },
  }, true, false);
  t.after(() => { transport.dispose(); server.closeAllConnections(); server.close(); store.close(); });
  const abort = new AbortController();
  const pending = transport.fetch(`${baseUrl}/chat/completions`, { method: "POST", body: '{"model":"fixture"}', signal: abort.signal });
  const rejected = assert.rejects(pending); await accepted; abort.abort(); await rejected;
  assert.equal(received, 1); assert.equal(store.request(requestId)?.state, "unknown");
  assert.equal(store.bucket("work")?.reserved, 1); assert.equal(store.bucket("work")?.used, 0);
  store.revokeOwner(owner); const next = store.claimOwner("scope", "next"); store.prepare(next, "next-intent", "model", {});
  assert.throws(() => store.reserveRequest(next, "next-intent", "another-request", [{ id: "work", ceiling: 1 }]), { code: "BUDGET_DENIED" });
  assert.equal(received, 1);
});


test("[A] native automatic scope rejects a changed endpoint and cannot revive a retired guarded fetch", async t => {
  let automatic = false, received = 0;
  const server = createServer((req, res) => { received++; req.resume(); req.on("end", () => res.end("ok")); });
  await listenLoopback(server);
  const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}/v1`;
  const transport = installHttpTransport(() => ({ baseUrl, model: "fixture", token: 1 }), {}, () => automatic, false);
  t.after(() => { transport.dispose(); server.closeAllConnections(); server.close(); });
  const payload = { method: "POST", body: '{"model":"fixture"}' };
  assert.equal((await transport.fetch(`${baseUrl}/ordinary`, payload)).status, 200); assert.equal(received, 1);
  automatic = true;
  await assert.rejects(transport.fetch(`${baseUrl}/changed-endpoint`, payload), { code: "UNAPPROVED_HTTP_ROUTE" }); assert.equal(received, 1);
  assert.equal((await transport.fetch(`${baseUrl}/chat/completions`, payload)).status, 200); assert.equal(received, 2);
  transport.dispose(); automatic = false;
  await assert.rejects(transport.fetch(`${baseUrl}/chat/completions`, payload), { code: "RETIRED_HTTP_SCOPE" }); assert.equal(received, 2);
});

test("[A] opt-in metering is lazy and forwards split Unicode SSE bytes without changing the response", async t=>{
  const bytes=Buffer.from('data: {"choices":[{"delta":{"content":"汉🙂"}}]}\n\ndata: {"usage":{"prompt_tokens":0,"completion_tokens":0}}\n\ndata: [DONE]\n\n');
  const server=createServer((req,res)=>{req.resume();res.writeHead(200,{"content-type":"text/event-stream","x-fixture":"preserved"});const split=bytes.indexOf(Buffer.from("🙂"))+1;res.write(bytes.subarray(0,split));res.end(bytes.subarray(split));});
  await listenLoopback(server);t.after(()=>{server.closeAllConnections();server.close();});const baseUrl=`http://127.0.0.1:${(server.address() as {port:number}).port}`;
  const metering:boolean[]=[];const transport=installHttpTransport(()=>({baseUrl,model:"fixture",token:1}),{metering:(_attempt,zero)=>metering.push(zero)},false,false);t.after(()=>transport.dispose());
  const response=await transport.fetch(`${baseUrl}/chat/completions`,{method:"POST",body:'{"model":"fixture"}'});
  assert.deepEqual(metering,[]);assert.equal(response.headers.get("x-fixture"),"preserved");assert.equal(response.url,`${baseUrl}/chat/completions`);
  assert.deepEqual(Buffer.from(await response.arrayBuffer()),bytes);assert.deepEqual(metering,[true]);
});
