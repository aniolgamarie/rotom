// 默认 Web 端到端测试只使用工具注册结构，禁止真实宿主/UI/图像原生模块和模型调用。
const unavailable = () => { throw new Error("mock web host execution disabled"); };
export class Box { constructor() { unavailable(); } }
export class Text { constructor() { unavailable(); } }
export const resizeImage = unavailable, truncateToWidth = unavailable, complete = unavailable, completeSimple = unavailable;
export const StringEnum = (values, options = {}) => ({ type: "string", enum: values, ...options });
export const clampThinkingLevel = (_model, value) => value;
