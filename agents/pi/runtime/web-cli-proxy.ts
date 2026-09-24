// CLI 使用普通 HTTP CONNECT 代理；每条连接先核对所属操作和明确的目标范围。
import { timingSafeEqual, randomBytes } from "node:crypto";
import { lookup as dnsLookup } from "node:dns/promises";
import { connect as netConnect, isIP } from "node:net";
import { connect as tlsConnect } from "node:tls";
import { createServer } from "node:http";
import { dirname, isAbsolute } from "node:path";
import { lstat, realpath, chmod } from "node:fs/promises";
import { addressPolicy, checkWebHostname } from "./web-address.ts";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1");
async function cancelable(promise, signal) {
  let stop;
  const canceled = new Promise((_, fail) => {
    stop = () => fail(new Error("WEB_CLI_ABORTED"));
    signal.addEventListener("abort", stop, { once: true });
    if (signal.aborted) stop();
  });
  try { return await Promise.race([promise, canceled]); }
  finally { signal.removeEventListener("abort", stop); }
}
async function privateSocketPath(path, bound = false) {
  const parent = dirname(path), info = await lstat(parent);
  if (!info.isDirectory() || info.isSymbolicLink() || (info.mode & 0o077) || info.uid !== process.getuid?.()
      || await realpath(parent) !== parent) reject("WEB_CLI_SOCKET_PRIVATE_REQUIRED", 4);
  if (bound) {
    const socket = await lstat(path);
    if (!socket.isSocket() || socket.uid !== info.uid) reject("WEB_CLI_SOCKET_CHANGED", 4);
    await chmod(path, 0o600);
  }
}

export async function cliProxyTarget(runtime, name, authority, { lookup = dnsLookup, signal = new AbortController().signal } = {}) {
  const binding = runtime.manifest.web_services?.[name];
  if (!binding || !["api", "public"].includes(binding.type) || typeof authority !== "string") reject("WEB_CLI_TARGET_UNBOUND", 2);
  let url;
  try { url = new URL("https://" + authority); } catch { reject("WEB_CLI_TARGET_INVALID", 2); }
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash || url.port && url.port !== "443") reject("WEB_CLI_TARGET_INVALID", 2);
  if (binding.type === "api" && !binding.origins?.includes(url.origin)) reject("WEB_CLI_ORIGIN_DENIED", 4);
  const hostname = checkWebHostname(url, binding), check = addressPolicy(binding.allow_ranges);
  signal.throwIfAborted();
  let stop;
  const aborted = new Promise((_, fail) => { stop = () => fail(new Error("WEB_CLI_ABORTED")); signal.addEventListener("abort", stop, { once: true }); });
  let addresses;
  try { addresses = isIP(hostname) ? [{ address: hostname, family: isIP(hostname) }]
    : await Promise.race([lookup(hostname, { all: true, verbatim: true }), aborted]); }
  finally { signal.removeEventListener("abort", stop); }
  signal.throwIfAborted();
  if (!Array.isArray(addresses) || !addresses.length || addresses.length > 64) reject("WEB_CLI_DNS_FAILED", 5);
  for (const entry of addresses) {
    if (isIP(entry.address) !== entry.family) reject("WEB_CLI_DNS_FAILED", 5);
    // 已声明的 API origin 可为机器私有服务；public 始终核验地址。
    if (binding.type === "public") check(entry.address);
  }
  return { hostname, address: addresses[0].address, port: 443 };
}

function waitConnect(socket, event, signal) {
  return new Promise((resolve, fail) => {
    const stop = () => { socket.destroy(); finish(new Error("WEB_CLI_ABORTED")); };
    const error = () => finish(new Error("WEB_CLI_CONNECT_FAILED"));
    const done = () => finish();
    const finish = failure => {
      socket.off(event, done); socket.off("error", error); signal.removeEventListener("abort", stop);
      failure ? fail(failure) : resolve(socket);
    };
    socket.once(event, done); socket.once("error", error); signal.addEventListener("abort", stop, { once: true });
    if (signal.aborted) stop();
  });
}

export async function connectCliTarget(target, route, { signal, authorization, connect = netConnect, secureConnect = tlsConnect } = {}) {
  signal.throwIfAborted();
  if (route.mode === "direct") {
    const socket = connect({ host: target.address, port: target.port });
    return waitConnect(socket, "connect", signal);
  }
  if (route.mode !== "proxy") reject("WEB_CLI_ROUTE_INVALID", 2);
  const proxy = new URL(route.proxy_url);
  if (!/^https?:$/.test(proxy.protocol) || proxy.username || proxy.password || proxy.pathname !== "/" || proxy.search || proxy.hash) reject("WEB_CLI_PROXY_INVALID", 2);
  const socket = proxy.protocol === "https:" ? secureConnect({ host: proxy.hostname, port: Number(proxy.port || 443), servername: proxy.hostname })
    : connect({ host: proxy.hostname, port: Number(proxy.port || 80) });
  await waitConnect(socket, proxy.protocol === "https:" ? "secureConnect" : "connect", signal);
  if (authorization && /[\x00-\x1f\x7f]/.test(authorization)) { socket.destroy(); reject("WEB_CLI_PROXY_AUTH_INVALID", 3); }
  const authority = (isIP(target.address) === 6 ? "[" + target.address + "]" : target.address) + ":" + target.port;
  return new Promise((resolve, fail) => {
    let buffer = Buffer.alloc(0);
    const close = () => finish(new Error("WEB_CLI_PROXY_FAILED"));
    const abort = () => finish(new Error("WEB_CLI_ABORTED"));
    const finish = error => {
      socket.off("data", data); socket.off("error", close); socket.off("close", close); signal.removeEventListener("abort", abort);
      if (error) { socket.destroy(); fail(error); } else { socket.pause(); resolve(socket); }
    };
    const data = chunk => {
      buffer = Buffer.concat([buffer, chunk]);
      const end = buffer.indexOf("\r\n\r\n");
      if (end > 32764 || end < 0 && buffer.length > 32768) { finish(new Error("WEB_CLI_PROXY_FAILED")); return; }
      if (end < 0) return;
      if (!/^HTTP\/1\.[01] 200(?: |\r)/.test(buffer.toString("latin1", 0, end))) { finish(new Error("WEB_CLI_PROXY_FAILED")); return; }
      const rest = buffer.subarray(end + 4); finish(); if (rest.length) socket.unshift(rest);
    };
    socket.on("data", data); socket.once("error", close); socket.once("close", close); signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) { abort(); return; }
    socket.write("CONNECT " + authority + " HTTP/1.1\r\nHost: " + authority + "\r\n" + (authorization ? "Proxy-Authorization: " + authorization + "\r\n" : "") + "\r\n");
  });
}

export async function createCliProxy(runtime, name, socketPath, { authorize, lookup = dnsLookup, connector = connectCliTarget, serverFactory = createServer, routeName, authorization, validateSocketPath = privateSocketPath } = {}) {
  if (typeof socketPath !== "string" || !isAbsolute(socketPath) || Buffer.byteLength(socketPath) > 100 || /[\x00-\x1f\x7f]/.test(socketPath)) reject("WEB_CLI_SOCKET_INVALID", 2);
  const operation = runtime.web.current(); requireOrdinaryHelper(runtime, "pi-web", operation.id);
  if (typeof authorize !== "function") reject("WEB_CLI_AUTHORIZER_REQUIRED", 2);
  const binding = runtime.manifest.web_services?.[name]; routeName ??= binding?.network_route;
  const route = runtime.manifest.options.network?.routes?.[routeName];
  if (!route?.service_ids?.includes("web:" + name)) reject("WEB_CLI_ROUTE_UNBOUND", 2);
  await validateSocketPath(socketPath);
  const token = randomBytes(32).toString("hex"), expected = Buffer.from("Basic " + Buffer.from("agentcfg:" + token).toString("base64"));
  const sockets = new Set(), pending = new Set(), controller = new AbortController(); let closed = false, failure = false, sent = 0, received = 0, connections = 0;
  const maxSent = binding.max_request_bytes ?? 8 * 1024 * 1024, maxReceived = binding.max_response_bytes ?? 128 * 1024 * 1024;
  const maxConnections = binding.max_requests ?? 1024;
  if (![maxSent, maxReceived, maxConnections].every(value => Number.isSafeInteger(value) && value > 0)) reject("WEB_CLI_LIMIT_INVALID", 2);
  const signal = AbortSignal.any([operation.controller.signal, controller.signal, AbortSignal.timeout(binding.timeout_ms ?? 120000)]);
  const check = () => {
    if (closed || failure || globalThis[slot] !== runtime) reject("WEB_CLI_PROXY_CLOSED", 4);
    signal.throwIfAborted(); requireOrdinaryHelper(runtime, "pi-web", operation.id);
  };
  const server = serverFactory({ maxHeaderSize: 16384, headersTimeout: 10000, requestTimeout: 10000 }, (_req, res) => {
    res.writeHead(405, { connection: "close" }); res.end("CONNECT required");
  });
  server.maxConnections = 64;
  server.setTimeout?.(30000, socket => socket.destroy());
  const own = socket => {
    sockets.add(socket); socket.once("close", () => sockets.delete(socket)); socket.on("error", () => {}); return socket;
  };
  server.on("connection", own);
  const handle = async (request, client, head) => {
    own(client); let remote, attempted = false;
    try {
      check(); const provided = Buffer.from(request.headers["proxy-authorization"] ?? "");
      if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) reject("WEB_CLI_PROXY_DENIED", 4);
      if (++connections > maxConnections) reject("WEB_CLI_REQUEST_LIMIT", 4);
      if (await cancelable(authorize(), signal) !== true) reject("WEB_CLI_EXECUTION_REVOKED", 4);
      const target = await cliProxyTarget(runtime, name, request.url, { lookup, signal }); check();
      if (await cancelable(authorize(), signal) !== true) reject("WEB_CLI_EXECUTION_REVOKED", 4);
      attempted = true;
      remote = own(await connector(target, route, { signal, authorization })); check();
      const count = (direction, bytes) => {
        if (direction === "sent") sent += bytes; else received += bytes;
        if (sent > maxSent || received > maxReceived) { failure = true; controller.abort(); }
      };
      client.on("data", chunk => count("sent", chunk.length)); remote.on("data", chunk => count("received", chunk.length));
      count("sent", head.length); check();
      client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
      if (head.length) remote.write(head);
      client.pipe(remote); remote.pipe(client); remote.resume();
      client.once("close", () => remote.destroy()); remote.once("close", () => client.destroy());
    } catch {
      remote?.destroy(); client.destroy();
      if (attempted && route.mode === "proxy") { failure = true; operation.proxyFailed = true; operation.controller.abort(); controller.abort(); for (const socket of sockets) socket.destroy(); }
    }
  };
  server.on("connect", (request, socket, head) => { const task = handle(request, socket, head); pending.add(task); void task.finally(() => pending.delete(task)).catch(() => {}); });
  const abort = () => { for (const socket of sockets) socket.destroy(); };
  signal.addEventListener("abort", abort, { once: true });
  server.on("error", () => { failure = true; controller.abort(); });
  let closing, bindingPromise;
  const proxy = { token, socketPath, close() {
    if (closing) return closing;
    closing = (async () => {
      closed = true; controller.abort();
      await bindingPromise?.catch(() => {});
      await new Promise((resolve, fail) => { server.close(error => error && error.code !== "ERR_SERVER_NOT_RUNNING" ? fail(new Error("WEB_CLI_PROXY_CLOSE_UNKNOWN")) : resolve()); });
      await Promise.allSettled([...pending]);
      if (sockets.size) reject("WEB_CLI_PROXY_CLOSE_UNKNOWN", 4);
      signal.removeEventListener("abort", abort);
    })().catch(error => { closing = null; throw error; });
    return closing;
  } };
  operation.transports.set("cli-proxy:" + socketPath, Promise.resolve(proxy));
  // 先登记再 bind；绑定失败或取消也必须由所属操作完成清理。
  bindingPromise = new Promise((resolve, fail) => {
    const error = () => { server.off("error", error); fail(new Error("WEB_CLI_PROXY_BIND_FAILED")); };
    server.once("error", error);
    try { server.listen(socketPath, () => { server.off("error", error); resolve(); }); }
    catch { error(); }
  });
  try {
    await bindingPromise; check(); await validateSocketPath(socketPath, true); check();
    return proxy;
  } catch (error) { await proxy.close(); throw error; }
}
