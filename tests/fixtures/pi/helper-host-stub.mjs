// 只用于插件登记／路由测试；任何实际宿主或 UI 执行都明确失败。
const unavailable = () => { throw new Error("mock host execution disabled"); };
class Widget { constructor() { unavailable(); } }
export const Container = Widget, DynamicBorder = Widget, ScrollView = Widget, SelectList = Widget;
export const SettingsList = Widget, Text = Widget, VStack = Widget, Input = Widget;
export const Key = {}, matchesKey = unavailable, truncateToWidth = unavailable, visibleWidth = unavailable;
export const convertToLlm = unavailable, serializeConversation = unavailable, getSettingsListTheme = unavailable;
export const StringEnum = (values, options = {}) => ({ type: "string", enum: values, ...options });
