import assert from "node:assert/strict";
import test from "node:test";
import { beginRound, createDiagnostics, finishRound, formatSummary, MeteredProxyDispatcher, snapshot } from "./diagnostics.mjs";

function fixture() {
  const requests = [];
  const diagnostics = createDiagnostics();
  const proxy = { dispatch(options, handler) { requests.push({ options, handler }); return false; } };
  return { diagnostics, requests, meter: new MeteredProxyDispatcher(proxy, diagnostics) };
}

test("counts UTF-8 upload chunks and raw response chunks; forwards handler receivers and backpressure", () => {
  const { diagnostics, requests, meter } = fixture();
  beginRound(diagnostics);
  const controller = { pause() {}, resume() {} };
  const calls = [];
  const handler = {
    onRequestStart(c) { assert.equal(this, handler); assert.equal(c, controller); },
    onResponseData(c, chunk) { calls.push(chunk.toString()); c.pause(); return 123; },
    onResponseEnd() { calls.push("end"); },
  };
  assert.equal(meter.dispatch({ origin: "https://chatgpt.com", body: "must-not-read" }, handler), false);
  const h = requests[0].handler;
  h.onRequestStart(controller);
  h.onBodySent(Buffer.from("中文"));
  h.onBodySent(Buffer.from("abc"));
  h.onResponseStart(controller, 200, {});
  assert.equal(h.onResponseData(controller, Buffer.from("data: OK\n\n")), 123);
  h.onResponseEnd(controller, {});
  const round = finishRound(diagnostics);
  assert.equal(round.uploadBytes, 9);
  assert.equal(round.downloadBytes, 10);
  assert.equal(round.requests, 1);
  assert.equal(round.completed, 1);
  assert.equal(round.pending, 0);
  assert.deepEqual(round.statuses, { 200: 1 });
  assert.deepEqual(calls, ["data: OK\n\n", "end"]);
  assert.equal(diagnostics.total.uploadBytes, 9);
});

test("retries, HTTP errors, partial downloads and cancellation count once per dispatch", () => {
  const { diagnostics, requests, meter } = fixture();
  beginRound(diagnostics);
  meter.dispatch({ origin: "https://auth.openai.com" }, {});
  const first = requests[0].handler;
  first.onResponseStart({}, 403, {});
  first.onResponseData({}, Buffer.alloc(6));
  first.onResponseEnd({}, {});
  first.onResponseError({}, Object.assign(new Error("contains a credential"), { code: "ECONNRESET" }));
  meter.dispatch({ origin: "https://chatgpt.com" }, {});
  const second = requests[1].handler;
  second.onBodySent(Buffer.alloc(10));
  second.onResponseStart({}, 200, {});
  second.onResponseData({}, Buffer.alloc(3));
  second.onResponseError({}, new Error("secret", { cause: Object.assign(new Error("also secret"), { code: "UND_ERR_ABORTED" }) }));
  const round = finishRound(diagnostics);
  assert.equal(round.requests, 2);
  assert.equal(round.failures, 1);
  assert.equal(round.cancellations, 1);
  assert.equal(round.downloadBytes, 9);
  assert.equal(round.lastError, null);
  assert.equal(JSON.stringify(round).includes("secret"), false);
});

test("normal SSE reader cancellation is not falsely reported as a network failure", () => {
  const { diagnostics, requests, meter } = fixture();
  beginRound(diagnostics);
  meter.dispatch({ origin: "https://chatgpt.com" }, {});
  const h = requests[0].handler;
  h.onResponseStart({}, 200, {});
  h.onResponseData({}, Buffer.from("data: completed\n\n"));
  h.onResponseError({}, new DOMException("The operation was aborted.", "AbortError"));
  const stats = finishRound(diagnostics);
  assert.equal(stats.completed, 1);
  assert.equal(stats.cancellations, 1);
  assert.equal(stats.failures, 0);
  assert.equal(stats.lastError, null);
  assert.doesNotMatch(formatSummary(stats), /失败|NETWORK_ERROR/);
});

test("late callbacks stay in their original round and background traffic is total-only", () => {
  const { diagnostics, requests, meter } = fixture();
  meter.dispatch({ origin: "https://auth.openai.com" }, {});
  const firstRound = beginRound(diagnostics);
  meter.dispatch({ origin: "https://chatgpt.com" }, {});
  const round = finishRound(diagnostics);
  assert.equal(round.pending, 1);
  beginRound(diagnostics);
  requests[0].handler.onBodySent(Buffer.alloc(4));
  requests[0].handler.onResponseEnd({}, {});
  requests[1].handler.onResponseData({}, Buffer.alloc(8));
  requests[1].handler.onResponseEnd({}, {});
  assert.equal(firstRound.downloadBytes, 8);
  assert.equal(diagnostics.active.requests, 0);
  assert.equal(diagnostics.active.downloadBytes, 0);
  assert.equal(diagnostics.total.requests, 2);
  assert.equal(diagnostics.total.uploadBytes, 4);
  assert.equal(diagnostics.total.downloadBytes, 8);
  assert.equal(round.downloadBytes, 0); // Published summaries are immutable snapshots.
});

test("multiple agent starts keep a round; settled finishes once; zero traffic is explicit", () => {
  const diagnostics = createDiagnostics();
  const first = beginRound(diagnostics);
  assert.equal(beginRound(diagnostics), first);
  assert.match(formatSummary(finishRound(diagnostics)), /未观测到代理请求/);
  assert.equal(finishRound(diagnostics), null);
});

test("synchronous dispatch failure records only a safe code and never consumes request data", () => {
  const diagnostics = createDiagnostics();
  const error = Object.assign(new Error("password"), { code: "bad-token-secret" });
  const meter = new MeteredProxyDispatcher({ dispatch() { throw error; } }, diagnostics);
  beginRound(diagnostics);
  assert.throws(() => meter.dispatch({ origin: "https://api.openai.com" }, {}), e => e === error);
  const round = finishRound(diagnostics);
  assert.equal(round.uploadBytes, 0);
  assert.equal(round.failures, 1);
  assert.equal(round.lastError, "NETWORK_ERROR");
  assert.match(formatSummary(round), /未收到 HTTP 响应/);
  assert.equal(JSON.stringify(round).includes("password"), false);
});

test("WebSocket upgrade is explicitly excluded from body accounting", () => {
  const { diagnostics, requests, meter } = fixture();
  beginRound(diagnostics);
  let upgraded = false;
  meter.dispatch({ origin: "https://chatgpt.com" }, { onRequestUpgrade() { upgraded = true; } });
  requests[0].handler.onRequestUpgrade({}, 101, {}, {});
  const round = finishRound(diagnostics);
  assert.equal(upgraded, true);
  assert.equal(round.pending, 0);
  assert.match(formatSummary(round), /WebSocket 帧流量未计入/);
  const copy = snapshot(diagnostics.total);
  copy.hosts.push("must-not-mutate-original");
  assert.equal(diagnostics.total.hosts.includes("must-not-mutate-original"), false);
});
