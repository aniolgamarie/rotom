# Task Keeper 来源与适配

原始来源为用户指定 starter 仓库的固定提交
`c60599df39e6350123f7fb9378cfe63dc5ed814f`，逐文件 Git 对象记录见
`agents/pi/migration/task-keeper-manifest.json`。原许可证与 THIRD_PARTY_NOTICES.md 保留。

目标版本为 `0.2.0-agentcfg.1`：通过 agentcfg 的监督者、权限和预算协议接入
`@tintinweb/pi-subagents@0.19.0-agentcfg.1`，不安装旧 `pi-subagents@0.63.0`。
适配仍在进行，迁入源码或版本号变化不表示原生组合已经验收。

- `npm test` 仅执行明确列出的隔离 mock。
- 旧真实 SDK/PTY/RPC 验证入口需 `npm run test:native -- --allow-host` 的独立授权。
- 旧 prepare/独立 launch 脚本仅保存在 migration 作行为对照；vendor 明确排除该目录。
- 模型/权限/模型调用与停止契约逐项迁移，不能依靠放宽版本匹配启用旧适配器。
