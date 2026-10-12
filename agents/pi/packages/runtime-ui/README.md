# Minimal selected UI runtime

这是仓库自有的 `@agentcfg/pi-runtime` 2.0.0 适配包，无第三方依赖。它只提供两个公开入口：

- `./capability-policy`：`mayTransformHistory(runtime)`，仅 manager 且不在受管请求作用域中允许 UI 历史变换。
- `./plugin-settings`：`pluginSettings(capability, key)`，从当前选定 manager 的非秘密 manifest 读取所选插件选项，并返回独立 JSON 副本。未选择返回固定 `CAPABILITY_NOT_SELECTED` / exitCode 5；非法配置返回固定配置错误 / exitCode 2。

全局运行上下文由现代 launcher 建立，本包只读，不寻找替代上下文，也不授予文件或工具执行权限。未提供配置值沿用空对象语义。

本包不是旧完整 runtime 的替代兼容层。没有根 export，也不提供 controller、worker、文件 IO、SDK 或网络接口。后续 Full 组合需要显式实现和验收其额外接口。当前测试使用自有假对象，不表示原生 UI 扩展已经验收。
