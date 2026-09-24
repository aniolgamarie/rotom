# 来源与替换说明

完整来源为 starter 的 `skill/model-delegate`，冻结提交
`c60599df39e6350123f7fb9378cfe63dc5ed814f`。48 个原始文件的 Git blob、执行位与导入摘要见
仓库 `agents/pi/migration/model-delegate-manifest.json`。许可证保留在 LICENSE。

agentcfg 的目标版本为协议 V2：共享实例 supervisor、显式 route 与隔离账号、受管进程身份、
跨实例工作区写租约、readiness/观察/控制/结构化上下文与反馈。
旧 codex-delegate 的高级控制语义按新契约实现，不复制或调用它的 runner，也不注册旧工具。
七个历史角色只保留用途映射，最终调用同一 model_delegate 工具的 preset。

此目录正在迁移。V1 脚本与测试目前保留作移植来源；不能据此执行原生验收或宣称完整替换。
默认验证只运行 `test-contract-v2.sh`、`test-lifecycle-v2.sh` 与新桥接 mock。
