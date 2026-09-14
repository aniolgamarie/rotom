## Why

个人 Agent 的规则、技能、模型与工具配置分散在不同机器，手工复制容易丢失定制、泄露私有信息或覆盖本地登录和会话。rotom 需要提供可审查的配置来源与统一管理入口，先完整支持 DSH，再复用公共管理能力接入 Pi、Codex 等工具。

## What Changes

- 使用 Python 3.11+ 实现根入口 `./agentcfg`，提供配置校验、生成、差异计划、依赖锁定与安装、部署、启动、诊断、捕获提案、恢复及 OpenSpec 项目初始化。
- 分离 Git 中的公共资料与工具配方、仓库外的机器覆盖和密钥、原生工具拥有的登录与会话。设计带版本的本地 TOML 格式，覆盖机器路径、编辑器、显式环境传递、私有 provider/model 与多个 profile；按 schema 合并配置，记录来源并默认脱敏。
- 首版仅实现采用 `ccch1mneyyy/dsh-TUI` 的真实 DSH 适配器。核实并锁定 host、TUI、Codex 订阅认证、Cursor 社区认证和 OpenSpec 的接口与完整依赖；未经核实的原生字段不作为事实写入配方。
- 以工具和 profile 为边界管理独立实例；固定原生 home，按文件/字段所有权部署，使用三方合并保留原生变化。
- 按用户在设计讨论中的补充，简化原设计的多代回滚：每个实例仅保留上一次成功变更前的受管配置备份，使用 `rollback` 恢复；操作期间另有临时恢复记录，成功后清理。无变化和失败操作不轮换旧备份，不备份凭据、会话或整个原生 home。
- 保留公共适配接口，为未来 Pi、Codex 接入准备契约与测试方法，不创建空适配器或宣称已支持。
- 交付完整的 `maintain-agent-config` 技能包，指导 Agent 更新配置来源和模板、编写合法本地 TOML、验证合并及生成结果，并在用户授权范围内通过管理器部署。
- 提供隔离离线测试、独立无账号 smoke、Linux/macOS CI 和清晰的 live 验收记录；真实模型调用仅在用户明确授权且提供可用登录态后执行。

## Capabilities

### New Capabilities

- `config-resolution`: 配置 schema、分层合并、选择与来源、秘密引用、确定性渲染和完整技能包。
- `managed-deployment`: 独立实例、所有权、三方合并、上一版备份、恢复、并发和文件边界。
- `locked-dependencies`: 管理器与工具依赖的完整锁、版本证据、暂存安装及锁消费。
- `agent-cli-runtime`: 统一命令契约、启动环境、部署绑定、脱敏诊断与捕获提案。
- `dsh-integration`: 真实 DSH 配方、原生映射、认证路线、主题、检索和 MCP。
- `openspec-project-integration`: 锁定 OpenSpec CLI 对指定项目的显式集成与产物验收。
- `adapter-extensibility`: 多工具扩展接口、能力声明、独立实例与跨适配器契约。
- `configuration-maintenance-skill`: 面向配置维护任务的可分发技能及行为验证。

### Modified Capabilities

无。当前仓库没有已发布的 capability specs；本 change 为初次实现。

## Impact

- 新增 `src/agentcfg/`、`schemas/`、`shared/`、`profiles/`、`agents/dsh/`、`locks/dsh/`、`examples/`、`tests/`、文档、CI、工程 `AGENTS.md`、`pyproject.toml`、`uv.lock` 与 `agentcfg` 入口。
- 运行时仅管理新建的仓库外实例、私人缓存和状态目录；不默认接管现有 DSH/Pi/Codex 配置，不自动初始化业务项目，不读取现存 OAuth 文件。
- 项目名称沿用仓库 `rotom`，CLI 暂定 `agentcfg`。首版平台为 macOS/Linux，WSL 按 Linux 验证，不承诺原生 Windows。
- 本提案不代表任何第三方版本、安装或模型调用已验证；上游调查与锁定是实施的首个验收阶段。不会 push、发布或修改远端配置。
