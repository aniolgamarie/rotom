// 纯 JSON 持久值比较：忽略允许的对象 prototype，不省略任何字段或类型。
import { types } from "node:util";

const MAX_BYTES = 8 * 1024 * 1024;
const MAX_NODES = 65536;
const MAX_DEPTH = 128;
function invalid() {
  const error = new Error("probe-json-invalid");
  Object.defineProperty(error, "code", Object.assign(Object.create(null), { value: "probe-json-invalid", enumerable: true }));
  throw error;
}
export function canonicalProbeJson(value) {
  let bytes = 0, nodes = 0, pending = "";
  const fragments = [], ancestors = new Set();
  function emit(fragment) {
    bytes += Buffer.byteLength(fragment, "utf8");
    if (bytes > MAX_BYTES) invalid();
    pending += fragment;
    if (pending.length >= 4096) { fragments.push(pending); pending = ""; }
  }
  function quoted(text) {
    // 原字符串已大于剩余输出上界时，先拒绝，不能先造整条转义字符串。
    if (Buffer.byteLength(text, "utf8") + 2 > MAX_BYTES - bytes) invalid();
    emit('"');
    let start = 0;
    for (let index = 0; index < text.length; index++) {
      const code = text.charCodeAt(index);
      if (code >= 0xd800 && code <= 0xdbff) {
        const next = text.charCodeAt(index + 1);
        if (!(next >= 0xdc00 && next <= 0xdfff)) invalid();
        index++;
      } else if (code >= 0xdc00 && code <= 0xdfff) invalid();
      if (code < 32 || code === 34 || code === 92) {
        if (start < index) emit(text.slice(start, index));
        if (code === 34) emit('\\"');
        else if (code === 92) emit("\\\\");
        else if (code === 8) emit("\\b");
        else if (code === 9) emit("\\t");
        else if (code === 10) emit("\\n");
        else if (code === 12) emit("\\f");
        else if (code === 13) emit("\\r");
        else emit("\\u" + code.toString(16).padStart(4, "0"));
        start = index + 1;
      } else if (index - start >= 4094) {
        emit(text.slice(start, index + 1)); start = index + 1;
      }
    }
    if (start < text.length) emit(text.slice(start));
    emit('"');
  }
  function visit(current, depth) {
    if (++nodes > MAX_NODES || depth > MAX_DEPTH) invalid();
    if (current === null) { emit("null"); return; }
    if (typeof current === "string") { quoted(current); return; }
    if (typeof current === "boolean") { emit(current ? "true" : "false"); return; }
    if (typeof current === "number") {
      if (!Number.isFinite(current)) invalid();
      emit(JSON.stringify(current)); return;
    }
    if (typeof current !== "object" || types.isProxy(current)) invalid();
    if (ancestors.has(current)) invalid();
    const prototype = Object.getPrototypeOf(current), array = Array.isArray(current);
    if (array ? prototype !== Array.prototype : prototype !== Object.prototype && prototype !== null) invalid();
    const keys = Reflect.ownKeys(current);
    if (keys.some(key => typeof key !== "string" || key === "toJSON")) invalid();
    ancestors.add(current);
    try {
      if (array) {
        const length = Object.getOwnPropertyDescriptor(current, "length").value;
        if (length > MAX_NODES - nodes || keys.length !== length + 1) invalid();
        emit("[");
        for (let index = 0; index < length; index++) {
          const descriptor = Object.getOwnPropertyDescriptor(current, String(index));
          if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) invalid();
          if (index) emit(","); visit(descriptor.value, depth + 1);
        }
        emit("]");
      } else {
        if (keys.length > MAX_NODES - nodes) invalid();
        keys.sort(); emit("{");
        for (let index = 0; index < keys.length; index++) {
          const key = keys[index], descriptor = Object.getOwnPropertyDescriptor(current, key);
          if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) invalid();
          if (index) emit(","); quoted(key); emit(":"); visit(descriptor.value, depth + 1);
        }
        emit("}");
      }
    } finally { ancestors.delete(current); }
  }
  visit(value, 0);
  if (pending) fragments.push(pending);
  return fragments.join("");
}
