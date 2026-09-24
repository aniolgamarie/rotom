import assert from "node:assert/strict";
import { test } from "node:test";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { createRouteFetch } from "../route-fetch.ts";

test("explicit HTTP transport uses only the selected proxy and refuses redirects and fallback", async () => {
  const calls = [], route = { id: "proxy", type: "proxy", base_url: "https://fixture.invalid/v1", proxy_url: "http://proxy.invalid:8080" };
  let failed = false, redirect = false, destroyed = false;
  const agent = { destroy() { destroyed = true; } };
  const fetch = await createRouteFetch(route, { proxyAgent: async (url, protocol) => {
    assert.equal(url, route.proxy_url); assert.equal(protocol, "https:"); return agent;
  }, httpRequest: () => { throw Error("unexpected direct transport"); }, httpsRequest(url, options, done) {
    calls.push({ url, options });
    const request = new EventEmitter();
    request.end = () => {
      if (failed) { request.emit("error", new Error("synthetic private detail")); return; }
      const response = new PassThrough();
      response.statusCode = redirect ? 302 : 200; response.headers = { "content-type": "text/plain" };
      done(response); response.end("fixture response");
    };
    return request;
  } });
  const options = { method: "POST", body: "fixture payload", headers: {}, redirect: "error" };
  assert.equal(await (await fetch(route.base_url + "/chat/completions", options, route)).text(), "fixture response");
  assert.equal(calls[0].options.agent, agent);
  failed = true;
  await assert.rejects(fetch(route.base_url + "/chat/completions", options, route), /ROUTE_TRANSPORT_FAILED/);
  assert.equal(calls.length, 2);
  failed = false; redirect = true;
  await assert.rejects(fetch(route.base_url + "/chat/completions", options, route), /REDIRECT_FORBIDDEN/);
  assert.equal(calls.length, 3);
  fetch.close(); assert.equal(destroyed, true);
  await assert.rejects(fetch(route.base_url, options, route), /MODEL_ROUTE_MISMATCH/);
});
