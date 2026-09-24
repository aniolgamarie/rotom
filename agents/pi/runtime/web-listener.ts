// 浏览器界面只使用已声明监听地址；请求和 listener 分别归现有 manager 持有。
import { createServer } from "node:http";
import { EventEmitter } from "node:events";
import { isIP } from "node:net";
import { createRequire } from "node:module";
import { realpathSync } from "node:fs";
import { dirname, isAbsolute, join, relative, sep } from "node:path";
import { privateFile } from "./launch.ts";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { listenOwnedServer, closeOwnedListener } from "./owned-listener.ts";
import { reject } from "./managed-types.ts";
const owners = new WeakMap(), runtimes = new WeakMap();
const slot = Symbol.for("agentcfg.pi.runtime.v1");
export function webCuratorSettings(runtime = globalThis[slot]) {
  requireOrdinaryHelper(runtime, "pi-web");
  const value = runtime.manifest.options.web?.curator;
  if (value?.enabled !== true || value.browser_network !== "user-browser") reject("WEB_CURATOR_NOT_SELECTED", 4);
  const bind = value.bind ?? "127.0.0.1";
  if (!isIP(bind) || !["127.0.0.1", "::1"].includes(bind) && !value.advertised_origin) reject("WEB_CURATOR_BINDING_INVALID", 2);
  let origin;
  if (value.advertised_origin) {
    let url;
    try { url = new URL(value.advertised_origin); } catch { reject("WEB_CURATOR_BINDING_INVALID", 2); }
    if (!/^https?:$/.test(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== "/") reject("WEB_CURATOR_BINDING_INVALID", 2);
    origin = url.origin;
  }
  return { ...value, bind, ...(origin ? { advertised_origin: origin } : {}) };
}
function browserScript(runtime) {
  const root = realpathSync(runtime.runtimeRoot);
  const inside = name => {
    const path = realpathSync(name), tail = relative(root, path);
    if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep)) reject("WEB_BROWSER_ASSET_BOUNDARY", 5);
    return path;
  };
  const entry = inside(join(root, runtime.installed.entrypoint));
  const main = inside(createRequire(entry).resolve("marked"));
  const metadata = JSON.parse(privateFile(inside(join(dirname(main), "../package.json"))));
  if (metadata.name !== "marked" || metadata.version !== "18.0.5") reject("WEB_BROWSER_ASSET_VERSION", 5);
  return privateFile(inside(join(dirname(main), "marked.umd.js")));
}
export function createWebCuratorServer(handler, { runtime = globalThis[slot], serverFactory = createServer, script = browserScript } = {}) {
  const settings = webCuratorSettings(runtime), controllers = new Set(), requests = new Set();
  const asset = script(runtime);
  let stopping = false, server;
  const invoke = async (req, res) => {
    const origin = curatorOrigin(server, settings), authority = new URL(origin).host;
    if (globalThis[slot] !== runtime || stopping || req.headers.host !== authority
        || req.headers.origin && req.headers.origin !== origin) {
      res.writeHead(403); res.end("Curator request refused"); return;
    }
    res.setHeader("Referrer-Policy", "no-referrer"); res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Content-Security-Policy", "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src https: data:; connect-src 'self'; font-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'");
    const controller = new AbortController(); controllers.add(controller);
    const aborted = () => { if (!res.writableEnded) controller.abort(); };
    req.once("aborted", aborted); res.once("close", aborted);
    try {
      // 已结束的工具调用不能成为后续浏览器事件的隐藏父操作。
      await runtime.web.scope.exit(() => runtime.web.run("curator-request", controller.signal, () => handler(req, res)));
    } catch {
      if (!res.headersSent) { res.writeHead(503); res.end("Curator request unavailable"); }
      else if (!res.writableEnded) res.destroy();
    } finally {
      req.off("aborted", aborted); res.off("close", aborted); controllers.delete(controller);
    }
  };
  server = serverFactory((req, res) => {
    const pending = invoke(req, res); requests.add(pending);
    void pending.finally(() => requests.delete(pending)).catch(() => {});
  });
  class Listener extends EventEmitter {
    get listening() { return server.listening; }
    listen(port, host, done) { server.listen(port, host, done); }
    close(done) {
      stopping = true; for (const controller of controllers) controller.abort();
      server.close(error => {
        if (error) { done(error); return; }
        void Promise.allSettled([...requests]).then(() => { this.emit("close"); done(); });
      });
    }
    closeAllConnections() { server.closeAllConnections?.(); }
  }
  const listener = new Listener();
  server.on("connection", socket => listener.emit("connection", socket));
  server.on("error", () => { if (listener.listenerCount("error")) listener.emit("error", new Error("WEB_CURATOR_LISTENER_FAILED")); });
  owners.set(server, { runtime, settings, listener, asset });
  let selected = runtimes.get(runtime);
  if (!selected) runtimes.set(runtime, selected = new Set());
  selected.add(server);
  return server;
}
export function webCuratorAsset(server) {
  const owner = owners.get(server);
  if (!owner || globalThis[slot] !== owner.runtime) reject("WEB_CURATOR_UNOWNED", 4);
  return owner.asset;
}
export async function listenWebCurator(server, signal, dependencies = {}) {
  const owner = owners.get(server);
  if (!owner || globalThis[slot] !== owner.runtime) reject("WEB_CURATOR_UNOWNED", 4);
  webCuratorSettings(owner.runtime);
  await listenOwnedServer(owner.listener, { host: owner.settings.bind, port: owner.settings.port ?? 0,
    kind: "web-curator", description: "Web curator", startupSignal: signal }, owner.settings.max_seconds ?? 1800,
    { ...dependencies, runtime: owner.runtime, errorPrefix: "WEB" });
}
export async function closeWebCurator(server) {
  const owner = owners.get(server);
  if (!owner) reject("WEB_CURATOR_UNOWNED", 4);
  await closeOwnedListener(owner.listener, "WEB"); runtimes.get(owner.runtime)?.delete(server);
}
export async function closeWebCurators(runtime) {
  await Promise.all([...(runtimes.get(runtime) ?? [])].map(closeWebCurator));
}

function curatorOrigin(server, settings) {
  const address = server.address();
  if (!address || typeof address === "string") reject("WEB_CURATOR_NOT_BOUND", 4);
  return settings.advertised_origin ?? "http://" + (settings.bind === "::1" ? "[::1]" : settings.bind) + ":" + address.port;
}
export function webCuratorUrl(server, token) {
  const owner = owners.get(server);
  if (!owner || globalThis[slot] !== owner.runtime || !server.listening || typeof token !== "string" || !token || token.length > 256) reject("WEB_CURATOR_NOT_BOUND", 4);
  return curatorOrigin(server, owner.settings) + "/?session=" + encodeURIComponent(token);
}
export function webCuratorLinkAllowed(url) {
  const runtime = globalThis[slot];
  let target;
  try { target = new URL(url); } catch { return false; }
  if (target.username || target.password || target.pathname !== "/" || target.hash || [...target.searchParams.keys()].join(",") !== "session") return false;
  return [...(runtimes.get(runtime) ?? [])].some(server => server.listening && target.origin === curatorOrigin(server, owners.get(server).settings));
}
