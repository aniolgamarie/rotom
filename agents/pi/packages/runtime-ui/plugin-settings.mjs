// 只读所选manager的非秘密部署选项；返回独立JSON副本，不修改全局上下文。
function reject(code, exitCode) {
  const error = new Error(code);
  error.code = code; error.exitCode = exitCode;
  Object.defineProperty(error, Symbol.for("agentcfg.pi.protocol-error.v1"), { value: true });
  throw error;
}

function clone(value) {
  const seen = new Set();
  const encode = item => {
    if (item === null || typeof item === "string" || typeof item === "boolean"
        || typeof item === "number" && Number.isFinite(item)) return JSON.stringify(item);
    if (!item || typeof item !== "object" || seen.has(item)) reject("PROTOCOL_INVALID", 2);
    seen.add(item);
    try {
      if (Array.isArray(item)) {
        const values = [];
        for (let index = 0; index < item.length; index++) {
          const field = Object.getOwnPropertyDescriptor(item, String(index));
          if (!field || !Object.hasOwn(field, "value")) reject("PROTOCOL_INVALID", 2);
          values.push(encode(field.value));
        }
        return "[" + values.join(",") + "]";
      }
      if (Object.getPrototypeOf(item) !== Object.prototype || Object.getOwnPropertySymbols(item).length) reject("PROTOCOL_INVALID", 2);
      const fields = Object.getOwnPropertyDescriptors(item);
      if (Object.values(fields).some(field => !field.enumerable || !Object.hasOwn(field, "value"))) reject("PROTOCOL_INVALID", 2);
      return "{" + Object.keys(fields).sort().map(key => JSON.stringify(key) + ":" + encode(fields[key].value)).join(",") + "}";
    } finally { seen.delete(item); }
  };
  try { return JSON.parse(encode(value)); }
  catch { reject("PROTOCOL_INVALID", 2); }
}

export function pluginSettings(capability, key) {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  const plugins = runtime?.manifest?.plugins;
  if (!runtime || runtime.owner?.role !== "manager" || !Array.isArray(plugins) || !plugins.includes(capability)) reject("CAPABILITY_NOT_SELECTED", 5);
  const options = runtime.manifest.options;
  if (!options || typeof options !== "object" || Array.isArray(options)) reject("PLUGIN_CONFIG_INVALID", 2);
  const value = options[key] ?? {};
  if (!value || typeof value !== "object" || Array.isArray(value)) reject("PLUGIN_CONFIG_INVALID", 2);
  return clone(value);
}
