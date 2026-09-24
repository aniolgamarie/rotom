import { EventEmitter } from "node:events";
import { createInterface } from "node:readline";
const channel = new EventEmitter();
const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
let initialized = false;
const workerData = await new Promise((resolve, reject) => {
  input.on("line", line => {
    try {
      if (Buffer.byteLength(line) > 1024 * 1024) throw Error("MCP_SCRIPT_FRAME_LIMIT");
      const message = JSON.parse(line);
      if (message?.jsonrpc !== "2.0") throw Error("MCP_SCRIPT_PROTOCOL");
      if (!initialized) {
        if (message.type !== "init" || typeof message.code !== "string" || !message.code.trim()) throw Error("MCP_SCRIPT_INIT");
        initialized = true; resolve({ code: message.code });
      } else if (message.type === "result") channel.emit("message", message);
      else throw Error("MCP_SCRIPT_PROTOCOL");
    } catch { process.stderr.write("MCP_SCRIPT_PROTOCOL\n"); process.exit(5); }
  });
  input.once("close", () => { if (!initialized) reject(Error("MCP_SCRIPT_INIT_MISSING")); });
});
const parentPort = {
  on: (...args) => channel.on(...args),
  postMessage(message) {
    const line = JSON.stringify({ ...message, jsonrpc: "2.0" }) + "\n";
    if (Buffer.byteLength(line) > 1024 * 1024) throw Error("MCP_SCRIPT_FRAME_LIMIT");
    process.stdout.write(line);
  },
};
import { formatWithOptions } from "node:util";
import vm from "node:vm";

const TOOLS_ENUMERATION_ERROR = "tools is not enumerable — use tools.search({ query })";
const RESERVED_TOOL_PROPS = new Set(["then", "catch", "finally", "toJSON", "toString", "valueOf"]);

// Keep this formatting logic in sync with mcp-code.ts; the standalone worker cannot import the TypeScript host module.
function needsInspectableFormatting(value, stack = new WeakSet()) {
  if (value === undefined || typeof value === "bigint" || typeof value === "function" || typeof value === "symbol") return true;
  if (typeof value !== "object" || value === null) return false;
  if (stack.has(value)) return true;
  if (value instanceof Map || value instanceof Set || value instanceof WeakMap || value instanceof WeakSet) return true;
  stack.add(value);
  try {
    return Object.values(value).some((entry) => needsInspectableFormatting(entry, stack));
  } finally {
    stack.delete(value);
  }
}

function formatValue(value) {
  if (typeof value === "string") return value;
  try {
    if (!needsInspectableFormatting(value)) {
      const json = JSON.stringify(value, null, 2);
      if (json !== undefined) return json;
    }
    return formatWithOptions({ colors: false, depth: 6 }, value);
  } catch {
    return "[unserializable value]";
  }
}

function toContentBlock(value) {
  if (typeof value === "object" && value !== null) {
    if (value.type === "text" && typeof value.text === "string") {
      return { type: "text", text: value.text };
    }
    if (value.type === "image" && typeof value.data === "string" && typeof value.mimeType === "string") {
      return { type: "image", data: value.data, mimeType: value.mimeType };
    }
  }
  return { type: "text", text: formatValue(value) };
}

let nextRequestId = 0;
const pending = new Map();

parentPort.on("message", (message) => {
  if (message?.type !== "result" || typeof message.id !== "number") return;
  const resolve = pending.get(message.id);
  if (!resolve) return;
  pending.delete(message.id);
  resolve(message.envelope);
});

function request(type, payload) {
  return new Promise((resolve) => {
    const id = ++nextRequestId;
    pending.set(id, resolve);
    parentPort.postMessage({ type, id, ...payload });
  });
}

const tools = new Proxy(Object.create(null), {
  get(_target, property) {
    if (property === "search") {
      return async (input) => request("search", { input });
    }
    if (property === "call") {
      return async (path, args) => {
        // Invalid paths never reach dispatch and therefore never appear in the call trace.
        if (typeof path !== "string" || path.trim() === "") {
          return {
            ok: false,
            error: {
              code: "invalid_tool_path",
              message: "tools.call(path, args) requires a non-empty tool path.",
            },
          };
        }
        return request("call", { path, args });
      };
    }
    if (property === "describe") {
      return async (input) => request("describe", { input });
    }
    if (typeof property !== "string" || RESERVED_TOOL_PROPS.has(property)) return undefined;
    return (args) => request("call", { path: property, args });
  },
  ownKeys() {
    throw new Error(TOOLS_ENUMERATION_ERROR);
  },
});

const emit = (value) => {
  parentPort.postMessage({ type: "emit", block: toContentBlock(value) });
};

const capturedConsole = Object.freeze({
  log: (...args) => emit(`[console.log] ${formatWithOptions({ colors: false, depth: 4 }, ...args)}`),
  info: (...args) => emit(`[console.info] ${formatWithOptions({ colors: false, depth: 4 }, ...args)}`),
  warn: (...args) => emit(`[console.warn] ${formatWithOptions({ colors: false, depth: 4 }, ...args)}`),
  error: (...args) => emit(`[console.error] ${formatWithOptions({ colors: false, depth: 4 }, ...args)}`),
  debug: (...args) => emit(`[console.debug] ${formatWithOptions({ colors: false, depth: 4 }, ...args)}`),
});

void (async () => {
  try {
    const context = vm.createContext(Object.assign(Object.create(null), {
      tools,
      emit,
      console: capturedConsole,
    }), {
      codeGeneration: { strings: false, wasm: false },
      name: "mcpScript",
    });
    const script = new vm.Script(`(async () => {\n${workerData.code}\n})()`, { filename: "mcpScript.js" });
    const returnValue = await Promise.resolve(script.runInContext(context));
    parentPort.postMessage(returnValue === undefined
      ? { type: "done" }
      : { type: "done", returnBlock: toContentBlock(returnValue) });
  } catch (error) {
    parentPort.postMessage({
      type: "error",
      message: error instanceof Error ? error.message : String(error),
    });
  }
})().finally(() => { input.close(); process.stdin.destroy(); });
