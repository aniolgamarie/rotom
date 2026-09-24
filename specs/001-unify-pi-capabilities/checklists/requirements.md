# Specification Quality Checklist: Pi 能力梳理、统一与跨机器迁移

**Purpose**: 验证规格完整性与质量，确认可以进入实现规划。  
**Created**: 2026-09-16  
**Feature**: [spec.md](../spec.md)

**Review Ownership**: 本文件由 speckit-specify 执行规格质量审查并维护。  
**Marker Semantics**: `[x]` 仅表示需求质量已审查通过，不表示实现、迁移或原生验收完成。

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No unresolved clarification markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- 2026-09-24 用户明确缩小当前 spec 验收范围：软件实现要求保留，Linux x86_64 四配方 mock/native 与双路径冷重建为当前完成门槛，其他平台和 live 转出。规格、计划、任务、验证矩阵及证据契约已同步；新 scope 的 81 项全部匹配通过，见 [关闭报告](../../../docs/acceptance/pi-spec-closure-20260924/README.md)。历史 364 项报告仍保留 283 项 not-run，不扩大支持声明。

- 2026-09-16 初始规格审查及用户确认替换目标后复审：16/16项需求质量通过；随后跨文档分析发现U1/U2/U3/I1设计缺口，本次授权修订及自动复核继续修正I2/U4，已给出明确契约与任务覆盖，无遗留需求澄清标记。
- 规格中的 Pi、Task Keeper、Codex 与 agentcfg 是用户要求管理的产品和能力名称，
  当前包身份用于界定调查范围；未指定实现语言、接口签名、类结构或设计方案。
  代码事实与技术适用性初判单独位于 [source-inventory.md](../source-inventory.md)。
- “任意机器”明确限定为公开前提及已验证的平台组合；完整性以能力基线和所选可选项衡量。
  SC-002 要求不同 HOME/仓库路径的干净环境，SC-003 不允许用已安装或试用代替连通验收。
- Task Keeper 必须适配新子代理并验证受管任务，不能以默认禁用作为交付完成。
  用户已明确model-delegate完整替换codex-delegate，七角色转用途模板；不再把是否长期保留旧执行器当作未决项。
  FR-043—FR-046与SC-011—SC-012覆盖补齐能力、调用方适配和旧组件完全缺席验收。
- 所有运行、权限、停止、账号和平台通过条件均描述为后续验收要求；
  当前只读调查、历史测试和本次文档检查没有被宣称为功能通过。
- 规格所遵循的宪章为 1.0.0；其原始批准日期 TODO 是既存治理记录待确认，
  不改变本规格采用的原则，也不是本特性的需求歧义。

### 验收覆盖核对

| 功能要求 | 用户场景 | 可衡量结果 |
|---|---|---|
| FR-001—FR-006 | US1：盘点、差异、连通性及架构适用性 | SC-001、SC-003、SC-010 |
| FR-007—FR-010 | US2：新机器构建、前提及副作用 | SC-002、SC-003、SC-010 |
| FR-011—FR-016 | US2、US5：完整资源、来源优先级与统一入口 | SC-001、SC-002、SC-003、SC-008 |
| FR-017—FR-021 | US4：隔离、预览、冲突及恢复 | SC-006、SC-007 |
| FR-022 | US3、US4：子任务终止与活动保护 | SC-005、SC-006 |
| FR-023—FR-025 | US3：新框架适配及候选验收 | SC-003、SC-004 |
| FR-026—FR-029 | US3：用量、预算、恢复与权限 | SC-004、SC-005 |
| FR-030—FR-031 | US3：一次性定时、启用与绑定 | SC-003、SC-004 |
| FR-032—FR-034 | US5：统一model-delegate入口、真实凭证及控制冲突 | SC-005、SC-008、SC-011 |
| FR-043—FR-046 | US5：完整替换、长任务控制、全部调用方适配与旧组件退出 | SC-011—SC-012 |
| FR-035—FR-037 | US4、US6：状态、诊断与维护来源 | SC-003、SC-010 |
| FR-038 | US4、US6：DSH 兼容 | SC-006、SC-009 |
| FR-039—FR-041 | US2、US6：支持矩阵与分层验收 | SC-002、SC-003、SC-006 |
| FR-042 | US6：升级影响与证据失效 | SC-003、SC-004、SC-010 |

### Constitution Check

| 原则 | 规格覆盖 | 审查结论 |
|---|---|---|
| I. 公共核心与真实原生适配 | FR-005、FR-010—FR-016、FR-023—FR-024 | 要求真实适配与入口连通，未宣称 Pi 已支持 |
| II. 秘密隔离与明确所有权 | FR-017—FR-019、FR-029、FR-036 | 保护原环境、身份与非受管数据 |
| III. 确定性部署与可恢复状态 | FR-020—FR-022 | 保持三方比较、上一版备份与活动保护 |
| IV. 显式副作用与可复现依赖 | FR-007—FR-010、FR-034、FR-042 | 固定完整来源，分开配置、安装和启动 |
| V. 默认隔离测试与可核实证据 | FR-035、FR-038—FR-041 | 真实验收独立授权，未执行不计通过 |

没有提出宪章例外。恢复控制、跨实例写入互斥、权限字段/匹配与条件验收已在contracts中固定，并同步任务和验证场景。
设计通过不表示运行证据已通过；架构覆盖与迁移技术问题需按修订后的计划闭合，
之后才能生成并执行实现任务。原生部署和账号验证保留各自的显式授权边界。
