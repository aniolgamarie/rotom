## Why

整体审查在已完成首版中复现了 6 个可靠性缺口，并发现 capture、诊断和扩展契约不足。修复异常路径，防止任务勾选和测试总数掩盖未覆盖行为。

## What Changes

- 私人配置全程安全读取；**BREAKING**：拒绝权限不安全及符号链接本地文件。
- profile 准备可恢复，损坏运行包可检查并暂存修复；pending 阻止 sync。
- 检查锁的适配器、平台和来源；OAuth 未支持的参数明确失败。
- 增加安全诊断定位、经核实的 capture 字段、依赖后端选择接口及维护技能验收计划。
- 将 review 复现转为正式回归，保留平台/账号/独立 Agent 验收的待验证状态。

## Capabilities

### New Capabilities
- `review-hardening`: 在首版设计上补充私人读取、安装恢复、诊断和扩展契约。

### Modified Capabilities
无已归档能力修改；关联未归档 build-agent-config-framework 的 CFG-06、DEP-01/05、CLI-04/06/07、LOCK-02/03/04/05。

## Impact

影响配置入口、DSH 配方解释、依赖安装/启动、capture/doctor/plan、测试与文档。保持模型依赖版本和用户账号目录不变；不添加假 Pi/Codex 适配器，不进行远端操作或自动登录。
