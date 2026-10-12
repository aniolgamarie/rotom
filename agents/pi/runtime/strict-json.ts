// 受管配置的有界JSON解析；拒绝所有层级重复键，不输出原始文本。
const fail = () => { throw new Error("pi-json-invalid"); };

export function strictJson(text) {
  try {
    if (typeof text !== "string" || Buffer.byteLength(text, "utf8") > 1024 * 1024) fail();
    text = text.replace(/^\uFEFF/, "");
    const value = JSON.parse(text);
    // JSON.parse会丢掉重复字段，另外扫描结构以拒绝覆盖前的未知/敏感值。
    let offset = 0;
    const spaces = () => { while (/\s/.test(text[offset] ?? "") && offset < text.length) offset++; };
    const token = () => {
      const start = offset++;
      while (offset < text.length) { if (text[offset] === "\\") offset += 2; else if (text[offset++] === "\"") break; }
      return JSON.parse(text.slice(start, offset));
    };
    const walk = () => {
      spaces();
      if (text[offset] === "{") {
        offset++; spaces(); const keys = new Set();
        while (text[offset] !== "}") {
          const key = token(); if (keys.has(key)) fail(); keys.add(key); spaces(); offset++; walk(); spaces();
          if (text[offset] !== ",") break; offset++; spaces();
        }
        offset++;
      } else if (text[offset] === "[") {
        offset++; spaces(); while (text[offset] !== "]") { walk(); spaces(); if (text[offset] !== ",") break; offset++; } offset++;
      } else if (text[offset] === "\"") token();
      else { while (offset < text.length && !/[\s,}\]]/.test(text[offset])) offset++; }
    };
    walk(); return value;
  } catch { fail(); }
}

