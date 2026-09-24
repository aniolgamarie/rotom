// 只替代 URL elicitation 的 SDK 错误类型；不模拟表单 schema 验证成功。
export class ProtocolError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
export const ProtocolErrorCode = { InvalidParams: -32602 };
export class AjvJsonSchemaValidator {
  constructor() { throw new Error("Form schema validation is outside this isolated URL test"); }
}
