// 完整正文仅保留在私有内存中作相等比较；不生成摘要、日志或执行授权。
import { types } from "node:util";
const LIMIT = 1024 * 1024;
class InputError extends Error {
  constructor(capacity = false) {
    super(capacity ? "OPERATION_CAPACITY" : "OPERATION_INPUT_INVALID");
    this.exitCode = capacity ? 4 : 2;
  }
}
const invalid = () => { throw new InputError(); };

function codePointOrder(left, right) {
  const a = left[Symbol.iterator](), b = right[Symbol.iterator]();
  while (true) {
    const x = a.next(), y = b.next();
    if (x.done || y.done) return x.done === y.done ? 0 : x.done ? -1 : 1;
    const difference = x.value.codePointAt(0) - y.value.codePointAt(0);
    if (difference) return difference;
  }
}

function encoding(input, maxBytes, copy, allowFiniteNumbers) {
  let size = 0;
  const add = count => { size += count; if (size > maxBytes) throw new InputError(true); };
  const stringSize = text => {
    add(2);
    for (const char of text) {
      const code = char.codePointAt(0);
      if (code >= 0xd800 && code <= 0xdfff) invalid();
      add('"\\\b\f\n\r\t'.includes(char) ? 2 : code < 32 ? 6 : code < 128 ? 1 : code < 2048 ? 2 : code < 65536 ? 3 : 4);
    }
  };
  const visit = (value, depth) => {
    if (depth > 32) invalid();
    if (value === null || typeof value === "boolean" || typeof value === "number") {
      if (typeof value === "number" && !(allowFiniteNumbers ? Number.isFinite(value) : Number.isSafeInteger(value))) invalid();
      const normalized = Object.is(value, -0) ? 0 : value;
      const text = JSON.stringify(normalized); add(text.length);
      return copy ? { value: normalized, text } : undefined;
    }
    if (typeof value === "string") {
      stringSize(value);
      return copy ? { value, text: JSON.stringify(value) } : undefined;
    }
    if (!value || typeof value !== "object" || types.isProxy(value)) invalid();
    const array = Array.isArray(value), prototype = Object.getPrototypeOf(value);
    if (array ? prototype !== Array.prototype : prototype !== Object.prototype && prototype !== null) invalid();
    let length;
    if (array) {
      const descriptor = Object.getOwnPropertyDescriptor(value, "length");
      if (!descriptor || !Object.hasOwn(descriptor, "value") || !Number.isSafeInteger(descriptor.value) || descriptor.value < 0) invalid();
      length = descriptor.value; add(2 + Math.max(0, length - 1));
    }
    const keys = Reflect.ownKeys(value);
    if (keys.some(key => typeof key !== "string")) invalid();
    if (array && (keys.length !== length + 1 || keys.some(key => key !== "length" && (!/^(0|[1-9][0-9]*)$/.test(key) || Number(key) >= length)))) invalid();
    if (!array) add(2 + Math.max(0, keys.length - 1) + keys.length);
    const names = array ? keys.filter(key => key !== "length").sort((a, b) => Number(a) - Number(b)) : keys.sort(codePointOrder);
    const result = copy ? array ? [] : Object.create(prototype) : undefined;
    const parts = copy ? [] : undefined;
    for (const key of names) {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (!descriptor || !Object.hasOwn(descriptor, "value") || !descriptor.enumerable) invalid();
      if (!array) stringSize(key);
      const child = visit(descriptor.value, depth + 1);
      if (copy) {
        Object.defineProperty(result, key, { value: child.value, enumerable: true, writable: true, configurable: true });
        parts.push(array ? child.text : JSON.stringify(key) + ":" + child.text);
      }
    }
    return copy ? { value: Object.freeze(result), text: (array ? "[" : "{") + parts.join(",") + (array ? "]" : "}") } : undefined;
  };
  return visit(input, 0);
}

export function captureOperationInput(input, { maxBytes = LIMIT, allowFiniteNumbers = false } = {}) {
  if (typeof allowFiniteNumbers !== "boolean" || !Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > LIMIT) invalid();
  const capture = other => {
    try {
      // 第一遍只校验并计量UTF-8规范JSON，容量通过之后才分配完整编码及独立副本。
      encoding(other, maxBytes, false, allowFiniteNumbers);
      return encoding(other, maxBytes, true, allowFiniteNumbers);
    } catch (error) {
      if (error instanceof InputError) throw error;
      invalid();
    }
  };
  const captured = capture(input);
  return Object.freeze({ value: captured.value, matches: other => capture(other).text === captured.text });
}
