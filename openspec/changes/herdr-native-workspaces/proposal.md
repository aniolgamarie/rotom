## Why

服务器上的普通终端需要按实际 checkout 组织，便于持续编辑、编译、调试和使用 Agent。采用未修改、经过验收的较新 Herdr 稳定版作为终端复用器，Rotom 补充项目选择、稳定用途入口和少量配置所有权；Agent 状态只提供提示。2026-10-18 重新核实的最新稳定版仍为 0.9.5，作为当前候选；首次安装及每次升级前重新选版，不永久固定在该版本。

本机已有 Herdr 入口，但元信息检查返回 0.8.0，不能作为本轮基线。版本、磁盘资产、运行中 server、配置及检测规则必须分别核验。真实 SSH 客户端、Avalon 和 Agent 交互尚未验收。

## What Changes

- 在 `termcfg` 中增加显式选择的 Herdr 组件，只部署声明的配置文件，沿用现有 plan/apply、冲突、备份和恢复机制。
- 新增基于仓库 Python 环境的 `work enter PATH`、`work open ROLE [--new]`。项目身份为所选 Herdr server 内 checkout 的规范路径；用途终端默认只聚焦，缺失时创建。
- 首阶段只支持 Git checkout。非 Git 目录使用原生临时工作区；用途标记冷恢复后身份未知时默认拒绝自动创建，需原生导航或显式 `--new`。同一 server 的工作区焦点为客户端共享。
- 使用私有机器配置中的 Avalon launcher 和明确的 Agent profile；DSH/Pi 继续通过现有 `agentcfg run --cwd` 启动，独立 Codex 使用显式 daemon 策略。
- 先完成 tagged API 契约核实和离线实现，再安排独立 server、真实 SSH、人工终端验收。最后逐项启用可选 Agent 状态集成。
- 记录并发创建、结果不明超时、移动后身份重查和冷重启的能力边界。接口缺口不能用标题、动态 cwd、最近会话或宿主补丁掩盖。
- 建立版本化合成工作负载、机器可读结果与同机 A/B 升级基准，比较最后通过版本和较新稳定候选；按公开协议、能力及验收记录判断兼容，不在入口硬编码精确等于 0.9.5。

## Capabilities

### New Capabilities

- `herdr-terminal`: 可选、版本受约束、逐文件管理的 Herdr 配置与分阶段验收。
- `project-work-entry`: 不依赖 Agent 状态的项目进入和用途终端复用。

### Modified Capabilities

无已归档能力修改。实现会扩展现有 termcfg 组件枚举及相应 schema，并在现有机器配置中增加可选工作入口设置。

## Impact

影响 `src/termcfg/`、相关 schema/catalog、仓库 `work` 入口及小型 Python 模块、机器配置的非秘密字段、隔离测试和终端文档。Avalon 只登记现有 launcher；Agent 锁和资源仅在后续单独验收对应增强时变更。

### Non-goals

不新增终端数据库、守护进程、调度器、任务完成判定、侧栏、市场插件体系或跨平台包管理器。不随终端迁移修改编辑器功能、Agent HOME、账号或现有会话。不替换上游源码，不自动停止 server、Codex daemon 或 tmux 长任务，不自动联网安装或重放历史命令。

详见 [设计](design.md)、[任务](tasks.md)、[证据](evidence.md)、[验收计划](acceptance.md) 和 [升级基准](upgrade-benchmarks.md)。本轮交付为评审与实施准备，未实现运行时代码或执行性能基准。
