import assert from "node:assert/strict";
import test from "node:test";
import http from "node:http";
import { gzipSync } from "node:zlib";
import { once } from "node:events";
import { getGlobalDispatcher, setGlobalDispatcher } from "undici";
import { beginRound, finishRound } from "./diagnostics.mjs";
import { installOpenAIProxy, getProxyDiagnostics, getProxyStatus } from "./routing.mjs";

test("real local HTTP proxy counts streamed compressed bodies once, survives reload and dispatcher reset", async () => {
  const originalFetch = globalThis.fetch;
  const originalDispatcher = getGlobalDispatcher();
  const originalUrl = process.env.PI_OPENAI_PROXY;
  const responseText = 'data: {"text":"你好"}\n\ndata: [DONE]\n\n';
  const responseBytes = gzipSync(responseText);
  const uploadBytes = gzipSync("diagnostic request 中文".repeat(200));
  const received = [];
  const sockets = new Set();
  const server = http.createServer(async (req, res) => {
    const parts = [];
    for await (const part of req) parts.push(part);
    received.push(Buffer.concat(parts));
    res.writeHead(200, { "content-type": "text/event-stream", "content-encoding": "gzip" });
    res.write(responseBytes.subarray(0, 12));
    setImmediate(() => res.end(responseBytes.subarray(12)));
  });
  // Undici uses forward-proxy form for plain HTTP, CONNECT for HTTPS.
  const proxy = http.createServer((req, res) => {
    assert.equal(new URL(req.url).hostname, "api.openai.com");
    const upstream = http.request({
      hostname: "127.0.0.1", port: server.address().port,
      path: new URL(req.url).pathname, method: req.method, headers: req.headers,
    }, response => {
      res.writeHead(response.statusCode, response.headers);
      response.pipe(res);
    });
    upstream.on("error", () => res.destroy());
    req.pipe(upstream);
  });
  for (const listener of [server, proxy]) listener.on("connection", socket => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
  });
  let state;
  try {
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    proxy.listen(0, "127.0.0.1");
    await once(proxy, "listening");
    process.env.PI_OPENAI_PROXY = `http://127.0.0.1:${proxy.address().port}`;
    installOpenAIProxy({ reload: true });
    state = globalThis[Symbol.for("starter.pi.openai-proxy")];
    const diagnostics = getProxyDiagnostics();
    for (let run = 0; run < 2; run++) {
      if (run) {
        installOpenAIProxy({ reload: true });
        setGlobalDispatcher(originalDispatcher); // Pi's startup reconfiguration.
      }
      beginRound(diagnostics);
      const response = await globalThis.fetch("http://api.openai.com/events", {
        method: "POST", body: uploadBytes, headers: { "content-encoding": "gzip" },
        signal: AbortSignal.timeout(5000),
      });
      assert.equal(await response.text(), responseText);
      const stats = finishRound(diagnostics);
      assert.equal(stats.requests, 1);
      assert.equal(stats.completed, 1);
      assert.equal(stats.failures, 0);
      assert.equal(stats.uploadBytes, uploadBytes.length);
      assert.equal(stats.downloadBytes, responseBytes.length);
      assert.deepEqual(received[run], uploadBytes);
    }
    assert.equal(getProxyStatus().total.requests, 2);
    assert.equal(getProxyStatus().total.uploadBytes, uploadBytes.length * 2);
    assert.equal(getProxyStatus().total.downloadBytes, responseBytes.length * 2);
  } finally {
    globalThis.fetch = originalFetch;
    setGlobalDispatcher(originalDispatcher);
    if (originalUrl === undefined) delete process.env.PI_OPENAI_PROXY;
    else process.env.PI_OPENAI_PROXY = originalUrl;
    delete globalThis[Symbol.for("starter.pi.openai-proxy")];
    for (const socket of sockets) socket.destroy();
    await state?.rawProxy.close();
    for (const listener of [server, proxy]) if (listener.listening) await new Promise(resolve => listener.close(resolve));
  }
});
