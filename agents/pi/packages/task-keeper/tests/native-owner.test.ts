import { test, assert } from "./recorded-test.ts";
import { createServer } from "node:http";
import { once } from "node:events";
import { setImmediate as flush } from "node:timers/promises";
import { createJiti } from "jiti";
const loader = createJiti(import.meta.url);
const { withRecoveryOwner, hasRecoveryOwner, recoveryOwnerGateHealthy } = await loader.import<any>("pi-subagents/recovery-owner");
import { installHttpTransport, fetchDelegatesTo } from "../src/adapters/http-transport.ts";
import { join } from "node:path";
import { isolatedDirectory, listenLoopback } from "./helpers.ts";

test("[A T29 T33 T67] owned parent helper cannot send HTTP; concurrent ordinary fetch remains unaffected", async (t) => {
  let requests = 0;
  const server = createServer((req, res) => { requests++; req.resume(); req.on("end", () => res.end("ok")); });
  await listenLoopback(server);
  t.after(() => { server.closeAllConnections(); server.close(); });
  const endpoint = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
  const denied = withRecoveryOwner(async () => { await flush(); assert.equal(hasRecoveryOwner(), true); await assert.rejects(fetch(endpoint, { method: "POST" })); });
  assert.equal(hasRecoveryOwner(), false);
  assert.equal((await fetch(endpoint, { method: "POST" })).status, 200);
  await denied; assert.equal(requests, 1);
});

test("[T18 T21 T24] recovery owner does not poison ordinary cached-exclusion policy", async (t) => {
  const root = isolatedDirectory(t); process.env.PI_MODEL_EXCLUSIONS_PATH = join(root, "exclusions.json");
  const fallback = await loader.import<any>("../node_modules/pi-subagents/src/runs/shared/model-fallback.ts");
  const cache = await loader.import<any>("../node_modules/pi-subagents/src/runs/shared/model-exclusions.ts");
  withRecoveryOwner(() => fallback.recordRetryableModelFailure("fixture-provider/owned", "429: fixture limit"));
  assert.equal(cache.findModelExclusion("fixture-provider/owned"), undefined);
  fallback.recordRetryableModelFailure("fixture-provider/ordinary", "429: fixture limit");
  assert.ok(cache.findModelExclusion("fixture-provider/ordinary"));
  const models = [{ id: "ordinary", provider: "fixture-provider", fullId: "fixture-provider/ordinary" }];
  assert.throws(() => fallback.resolveSubagentModelOverride("fixture-provider/ordinary", undefined, models, undefined, { source: "explicit" }));
  assert.equal(withRecoveryOwner(() => fallback.resolveSubagentModelOverride("fixture-provider/ordinary", undefined, models, undefined, { source: "explicit" })), "fixture-provider/ordinary");
});

test("[A T33] known observer wrappers preserve the real helper gate while unknown wrappers are rejected", async t => {
  let requests = 0, denied = 0, observations = 0;
  const server = createServer((req, res) => { requests++; req.resume(); req.on("end", () => res.end("ok")); });
  await listenLoopback(server);
  const baseUrl = `http://127.0.0.1:${(server.address() as {port:number}).port}/v1`, guard = globalThis.fetch;
  const hooks = { priorGuard: (method: string) => method === "POST" && hasRecoveryOwner() ? guard : null, before: () => { observations++; } };
  const first = installHttpTransport(() => ({baseUrl, model: "fixture", token: 1}), hooks);
  const second = installHttpTransport(() => ({baseUrl, model: "fixture", token: 2}), hooks);
  t.after(() => { second.dispose(); first.dispose(); server.closeAllConnections(); server.close(); });
  assert.equal(recoveryOwnerGateHealthy(), false); assert.equal(fetchDelegatesTo(guard), true);
  const request = () => fetch(`${baseUrl}/chat/completions`, { method: "POST", body: '{"model":"fixture"}' });
  await withRecoveryOwner(() => assert.rejects(request(), /unbudgeted parent helper/), () => denied++);
  assert.equal(denied, 1); assert.equal(requests, 0); assert.equal(observations, 0);
  assert.equal(await (await request()).text(), "ok"); assert.equal(requests, 1); assert.equal(observations, 2);
  const known = globalThis.fetch;
  try {
    globalThis.fetch = (...args) => known(...args);
    assert.equal(fetchDelegatesTo(guard), false);
  } finally { globalThis.fetch = known; }
  assert.equal(fetchDelegatesTo(guard), true);
});
