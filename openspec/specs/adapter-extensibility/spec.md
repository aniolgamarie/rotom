# adapter-extensibility Specification

## Purpose
TBD - created by archiving change build-agent-config-framework. Update Purpose after archive.

## Requirements

### Requirement: EXT-01 Common core owns portable management behavior

公共核心 SHALL 负责 schema 合并、来源、秘密隔离、路径保护、文件事务、备份和进程锁；adapter SHALL 通过 validate/render/dependency_plan/managed_targets/launch_spec/capture/doctor 及必要锁/序列化钩子表达工具行为，不直接绕过公共保护修改目标。

#### Scenario: A test adapter reuses deployment and rollback unchanged
- **WHEN** 测试中注册一个不同原生格式的最小适配器并执行 render/plan/apply/rollback
- **THEN** 复用公共合并、上一版备份和冲突逻辑，无需在核心增加 DSH 专用分支，测试适配器不作为生产支持发布

### Requirement: EXT-02 Capabilities and native bindings remain explicit

每个工具 SHALL 有版本化声明和能力边界，原生路由/字段/认证拥有者留在 adapter，公共层仅抽象实际共有语义。不支持的选择 MUST 明确失败，不静默丢失字段，不因同名模型推断相同能力。

#### Scenario: Unsupported tool options are rejected at the right boundary
- **WHEN** profile 选择 adapter 不支持的模型参数/MCP transport，或把 DSH 原生字段用于另一工具
- **THEN** 校验指出不支持的映射和工具，不自动降级，不污染通用 registry

### Requirement: EXT-03 Only implemented adapters are exposed as supported

首版 SHALL 只注册真实 DSH adapter，不创建空 Pi/Codex 产品目录或成功占位实现。文档 SHALL 给出新增第二工具的接口、所有权、凭据、依赖和验收步骤，明确未来支持状态。

#### Scenario: Requesting an unimplemented tool does not pretend to sync it
- **WHEN** 首版请求 Pi/Codex 适配操作
- **THEN** 明确返回未支持，文档说明接入步骤，不生成假配置、不宣称已安装

### Requirement: EXT-04 Multi-tool state and local overrides are independently scoped

工具/profile SHALL 独立管理实例、运行数据、上一版备份与锁；同一本地文件的 profile overrides SHALL 按所声明工具的 schema 分别校验，不自动批量部署全部工具。共享技能包 SHALL 保持一份来源，可按不同 profile 分发。

#### Scenario: Updating one profile preserves other tools and their backups
- **WHEN** 通过测试适配器组合模拟 DSH、Pi 两套配置，只 apply DSH
- **THEN** Pi 的文件、状态、备份和未选择覆盖不变；共享源变更只在各自显式部署后生效
