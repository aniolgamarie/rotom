# Model Delegate V2

统一的 Pi/Codex 委托技能，唯一来源为此目录。实际执行使用当前 agentcfg 实例的冻结运行包、
既有 AgentManager 和实例 supervisor。来源及迁移边界见 [NOTICE.md](NOTICE.md)。

- [SKILL.md](SKILL.md)：模型工具、用途模板、用户显式 CLI、权限及证据使用规则。
- [API.md](API.md)：V2 请求、状态、进度、结果和反馈。
- [USAGE.md](USAGE.md)：显式实例的操作流程。
- [presets](presets/)：general/context/challenge/plan/research/review/scout 的用途与输出要求。
- [schemas](schemas/)：V2 closed schemas；V1 仅保留为历史数据格式参考。

默认验证只运行 `tests/test-contract-v2.sh`、`tests/test-lifecycle-v2.sh` 和仓库新 mock。
其余导入的 V1 测试是移植来源，不属于当前验证入口，不把原测试计数当作新版通过。
当前实现进度与 native/live 缺口以仓库 tasks.md 和 acceptance 记录为准。
