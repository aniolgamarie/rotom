// 仅验证wire候选；不核验真实来源/current、签发许可或执行操作。
import { types } from "node:util";

const code = "PI_RISK_REVIEW_PROTOCOL_INVALID";
const bindingKeys = ["request_id", "operation_digest", "context_digest", "reviewer_identity"];
const wireKeys = ["schema_version", ...bindingKeys, "decision", "reason_code"];
const reasons = {
  allow: ["authorized-in-scope"],
  ask: ["ambiguous-intent", "unverifiable-input", "needs-human"],
  deny: ["outside-user-scope", "destructive-change", "untrusted-authorization"],
};
const unicode = value => !/[\p{Cs}]/u.test(value);
const bound = (key, value) => typeof value === "string" && (key === "request_id" ? /^[0-9a-f]{32}$/ : /^[0-9a-f]{64}$/).test(value);
function fail() {
  const error = new Error(code); error.code = code; throw error;
}
function expectedValues(value) {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) fail();
  const keys = Reflect.ownKeys(value);
  if (keys.length !== bindingKeys.length || keys.some(key => !bindingKeys.includes(key))) fail();
  const result = {};
  for (const key of bindingKeys) {
    const property = Object.getOwnPropertyDescriptor(value, key);
    if (!property || !property.enumerable || !Object.hasOwn(property, "value") || !bound(key, property.value)) fail();
    result[key] = property.value;
  }
  return result;
}
function flatObject(raw) {
  let position = 0;
  const whitespace = () => { while (position < raw.length && /[ \t\r\n]/.test(raw[position])) position++; };
  const character = wanted => { if (raw[position] !== wanted) fail(); position++; };
  const stringToken = () => {
    const start = position; character('"');
    while (position < raw.length) {
      if (raw[position] === '"') {
        position++;
        // 只解析单个string token，不让通用JSON.parse吞掉重复对象键。
        const value = JSON.parse(raw.slice(start, position));
        if (!unicode(value)) fail();
        return value;
      }
      if (raw[position] === "\\") position += 2;
      else position++;
    }
    fail();
  };
  const valueToken = () => {
    if (raw[position] === '"') return stringToken();
    // 唯一数字字段是版本；直接匹配literal，避免非整数经浮点舍入变成1。
    character("1");
    return 1;
  };
  whitespace(); character("{"); whitespace();
  const result = {}, seen = new Set();
  while (true) {
    const key = stringToken();
    if (!wireKeys.includes(key) || seen.has(key)) fail();
    seen.add(key); whitespace(); character(":"); whitespace();
    result[key] = valueToken(); whitespace();
    if (raw[position] === "}") { position++; break; }
    character(","); whitespace();
  }
  whitespace();
  if (position !== raw.length || seen.size !== wireKeys.length) fail();
  return result;
}
export function parseReviewResponse(raw, expectedBinding) {
  try {
    if (typeof raw !== "string" || !raw.length || raw.length > 8192 || !unicode(raw) || Buffer.byteLength(raw, "utf8") > 8192) fail();
    const expected = expectedValues(expectedBinding), value = flatObject(raw);
    if (value.schema_version !== 1 || typeof value.decision !== "string" || !Object.hasOwn(reasons, value.decision)
        || typeof value.reason_code !== "string" || !reasons[value.decision].includes(value.reason_code)) fail();
    for (const key of bindingKeys) if (!bound(key, value[key]) || value[key] !== expected[key]) fail();
    // 所有值都是primitive；复制结果冻结，不保留或修改caller的绑定对象。
    return Object.freeze({ ...value, source: "reviewer" });
  } catch { fail(); }
}
