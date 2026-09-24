// 网络拦截配合 Node 权限模式；这不是对恶意同用户代码的 OS 沙箱。
import { createRequire, registerHooks, syncBuiltinESMExports } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";
import net from "node:net";
import tls from "node:tls";
import http from "node:http";
import https from "node:https";
import http2 from "node:http2";
import dns from "node:dns";
import dgram from "node:dgram";
import childProcess from "node:child_process";

// 只解析仓库内唯一的 runtime 源码；不会安装包或借用全局 node_modules。
const runtimeRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../agents/pi/runtime");
const runtimeExports = JSON.parse(readFileSync(resolve(runtimeRoot, "package.json"), "utf8")).exports;
const vendorRoot = resolve(runtimeRoot, "../packages/subagents-vendor/src") + "/";
const processesRoot = resolve(runtimeRoot, "../packages/processes-vendor") + "/";
const tooling = createRequire(new URL("./tooling/package.json", import.meta.url));
registerHooks({ resolve(specifier, context, next) {
  if (["@earendil-works/pi-coding-agent", "@earendil-works/pi-ai", "@earendil-works/pi-ai/compat", "@earendil-works/pi-tui"].includes(specifier)
      && context.parentURL?.includes("/packages/web-vendor/")) {
    return { url: new URL("./web-host-stub.mjs", import.meta.url).href, shortCircuit: true };
  }
  if (["@modelcontextprotocol/client", "@modelcontextprotocol/client/validators/ajv"].includes(specifier)
      && context.parentURL?.endsWith("/packages/mcp-vendor/elicitation-handler.ts")) {
    return { url: new URL("./mcp-elicitation-stub.mjs", import.meta.url).href, shortCircuit: true };
  }
  if (["@earendil-works/pi-coding-agent", "@earendil-works/pi-ai", "@earendil-works/pi-tui"].includes(specifier)
      && context.parentURL?.includes("/packages/smart-compact-vendor/")) {
    return { url: new URL("./helper-host-stub.mjs", import.meta.url).href, shortCircuit: true };
  }
  if (specifier.startsWith("typebox") && context.parentURL?.includes("/packages/rules-vendor/")) return { url: pathToFileURL(tooling.resolve("pi-rules-typebox" + specifier.slice("typebox".length))).href, shortCircuit: true };
  if (["ajv", "typebox", "undici", "yaml", "picomatch", "linkedom"].includes(specifier)) return { url: pathToFileURL(tooling.resolve(specifier)).href, shortCircuit: true };
  if (["unpdf", "unpdf/pdfjs"].includes(specifier)) return { url: pathToFileURL(resolve(dirname(tooling.resolve("unpdf")), specifier === "unpdf" ? "index.mjs" : "pdfjs.mjs")).href, shortCircuit: true };
  if (["@mozilla/readability", "defuddle/node", "p-limit", "promise.try", "turndown"].includes(specifier)) return { url: pathToFileURL(tooling.resolve(specifier)).href, shortCircuit: true };
  if (specifier.startsWith("@agentcfg/pi-runtime/")) {
    const entry = runtimeExports["./" + specifier.slice("@agentcfg/pi-runtime/".length)];
    const target = typeof entry === "string" ? entry : entry?.default;
    if (!target || !/^\.\/[a-z-]+\.ts$/.test(target)) throw new Error("mock runtime export not declared");
    return { url: pathToFileURL(resolve(runtimeRoot, target)).href, shortCircuit: true };
  }
  if (context.parentURL?.startsWith("file:") && specifier.startsWith(".") && specifier.endsWith(".js")) {
    const parent = fileURLToPath(context.parentURL);
    const target = resolve(dirname(parent), specifier.slice(0, -3) + ".ts");
    if (parent.startsWith(vendorRoot) && target.startsWith(vendorRoot) && existsSync(target)) {
      return { url: pathToFileURL(target).href, shortCircuit: true };
    }
  }
  if (context.parentURL?.startsWith("file:") && specifier.startsWith(".") && fileURLToPath(context.parentURL).startsWith(processesRoot)) {
    const base = resolve(dirname(fileURLToPath(context.parentURL)), specifier);
    for (const target of [base + ".ts", resolve(base, "index.ts")]) if (target.startsWith(processesRoot) && existsSync(target)) return { url: pathToFileURL(target).href, shortCircuit: true };
  }
  return next(specifier, context);
} });

const disabled = () => { throw new Error("mock network/process disabled"); };
globalThis.fetch = disabled;
process.kill = disabled;
globalThis.WebSocket = class { constructor() { disabled(); } };
for (const [module, names] of [
  [net, ["connect", "createConnection", "createServer"]], [tls, ["connect", "createServer"]],
  [http, ["request", "get", "createServer"]], [https, ["request", "get", "createServer"]],
  [http2, ["connect", "createServer", "createSecureServer"]], [dgram, ["createSocket"]],
  [dns, ["lookup", "resolve", "resolve4", "resolve6", "reverse"]],
  [childProcess, ["spawn", "spawnSync", "exec", "execSync", "execFile", "execFileSync", "fork"]],
]) for (const name of names) module[name] = disabled;
net.Socket.prototype.connect = disabled;
net.Server.prototype.listen = disabled;
for (const object of [dns, dns.promises, dns.Resolver.prototype, dns.promises.Resolver.prototype]) {
  for (const name of Object.getOwnPropertyNames(object)) {
    if ((name.startsWith("resolve") || ["lookup", "lookupService", "reverse"].includes(name))
        && typeof object[name] === "function") object[name] = disabled;
  }
}
syncBuiltinESMExports();
