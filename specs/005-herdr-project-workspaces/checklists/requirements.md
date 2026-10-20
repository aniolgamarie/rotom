# Specification Quality Checklist: Herdr 项目工作区与可验证升级

**Purpose**: 在进入规划前，验证本特性规范的完整性与需求质量。
**Created**: 2026-10-18
**Feature**: [Herdr 项目工作区与可验证升级](../spec.md)

**Note**: 本文件是由 `$speckit-specify` 维护的内置 requirements checklist；后续需求澄清可由 `$speckit-clarify` 更新，不采用独立 `$speckit-checklist` 的自定义清单生命周期。
**Review Ownership**: 审阅者负责需求质量判定；仅在对应标准已经审阅并满足时标记 `[x]`。
**Marker Semantics**: `[x]` 仅表示需求质量标准已满足，不代表实现、原生 smoke、真实客户端或 Agent 验收已经完成。

## Content Quality

- [x] CHK001 No implementation details (languages, frameworks, APIs). 证据：需求限定项目身份、用户命令、配置所有权和结果，不规定语言、框架、模块或接口实现；FR-024 规定公开能力边界。Herdr、Avalon、Pi/DSH/Codex 与 `work enter` / `work open` 是明确的产品范围。
- [x] CHK002 Focused on user value and business needs. 证据：User Stories 1–7 分别说明项目组织、不中断复用、输入连续性、配置恢复、现有工作流、升级证据和可选提示的用户收益及优先级。
- [x] CHK003 Written for non-technical stakeholders. 证据：每个故事以用户目标、收益和 Given/When/Then 描述可观察行为；Key Entities 解释工作副本、工作区、用途实例和基线等概念。
- [x] CHK004 All mandatory sections completed. 证据：规范含完整元数据、7 个 User Stories 及独立检查与接受场景、Edge Cases、34 条 Functional Requirements、Key Entities、10 条 Success Criteria 和 Assumptions。

## Requirement Completeness

- [x] CHK005 No [NEEDS CLARIFICATION] markers remain. 证据：规范未保留待澄清标记；Assumptions 明确首阶段 Git 范围、共享活动项目、冷恢复和预算冻结策略。
- [x] CHK006 Requirements are testable and unambiguous. 证据：FR-001–034 均给出可观察操作、约束或必须保留的证据；下方覆盖表逐组列出场景或验证断言。FR-003/008/009/011 明确不存在、未知、显式新增与错误目标的区别。
- [x] CHK007 Success criteria are measurable. 证据：SC-001–006 给出项目/终端规模、重复次数、零误操作及配置/身份结果；SC-007–010 给出报告完整性、三组对照与至少 600 次暖操作、零未授权迁移及关闭增强后的核心可用性。SC-008 的预算按 Assumptions 在校准后、评价候选前冻结，不虚构机器无关资源数值。
- [x] CHK008 Success criteria are technology-agnostic (no implementation details). 证据：SC-001–010 衡量用户操作结果、连续性、数据保护和证据可信性，未规定实现语言、框架、存储或内部接口。
- [x] CHK009 All acceptance scenarios are defined. 证据：7 个故事均提供前置条件、用户操作与可观察结果，覆盖首建/复用/新增、输入与断连、配置、启动与交接、选版/推广/回退及可选状态；补充约束可按 FR 的明确断言验收。
- [x] CHK010 Edge cases are identified. 证据：Edge Cases 覆盖特殊路径、同名与多工作副本、并发/丢响应、移动/关闭/过期标识、冷恢复未知、旧复用器、写入中断、输入与尺寸冲突及缺失测量条件。
- [x] CHK011 Scope is clearly bounded. 证据：Input 与 Assumptions 只定义一个 Herdr 项目工作区及可验证升级特性；首轮限实际验收的 Linux/客户端组合，非 Git 使用原生临时工作区；任务调度、额外管理服务/清单、自动迁移和未验收平台在范围外。
- [x] CHK012 Dependencies and assumptions identified. 证据：Assumptions 明确受支持且已准备的工具、项目权限、既有部署/启动契约、真实交互环境及授权，并区分历史材料与本规范；FR-018/019/032/034 约束缺少准备或授权时的行为。

## Feature Readiness

- [x] CHK013 All functional requirements have clear acceptance criteria. 证据：下方覆盖表涵盖 FR-001–034；未逐字重复到故事的条款仍有可直接验证的结果或禁止性断言，不依赖推测实现。
- [x] CHK014 User scenarios cover primary flows. 证据：User Stories 1–7 覆盖进入、按用途打开、持续工作、管理配置、启动既有工具、升级和关闭/启用状态增强，各自可独立验收。
- [x] CHK015 Feature meets measurable outcomes defined in Success Criteria. 证据：SC-001–010 分别对应故事的项目归属、无输入复用、客户端输入、任务保留、部署幂等、身份保持、候选报告、对照测量、安全推广回退与增强关闭；此项判定需求足以定义这些结果，未宣称结果已经实测达成。
- [x] CHK016 No implementation details leak into specification. 证据：FR 与 SC 保持用户行为和治理边界；独立 Avalon、既有 Agent 入口与 Codex daemon 策略是指定工作流约束，未规定私有接口或宿主修改方案；既有设计材料仅作为后续规划参考。

## Notes

- 第 1 轮审查（2026-10-18）完成：16/16 项需求质量通过，无需修改规范；未发现需要澄清的质量失败。
- 第 2 轮定向复核（2026-10-18）完成：FR-005 明确非 Git 项目在启动或修改服务前拒绝并退出 2；FR-009 明确冷恢复用途未知时普通打开报冲突并退出 4；FR-012 明确一个客户端切换项目会影响同一主环境的其他客户端。三项澄清加强失败行为与共享焦点的可验证性，16/16 项需求质量通过结论不变；本轮未执行功能验收。
- 审查依据为本规范、`speckit-specify` 内置 16 项标准、解析后的 checklist 模板及宪章 2.2.0；不把现有实现、历史选版或设计文件当作功能通过证据。
- 冷恢复普通打开拒绝未知用途，显式 `--new` 只为对应用途建立新默认，不解除其他未知用途（Story 2；FR-008/009）。
- 选版不是永久 pin：较新稳定版优先、暂留旧版记录原因及重评条件（Story 6；FR-025/026/032）。附加指标缺测单列未验证，不扩大权限、不自动阻塞已有必要证据支持的范围（FR-029）；必需指标缺失或门槛未校准不得通过（FR-028；SC-007/008）。
- 本轮仅完成需求质量审阅。实现、隔离行为测试、原生 smoke、真实客户端、真实 Agent 和性能测量均未在本轮执行，不能据勾选状态记为通过。
- 未满足的需求质量项必须在 `$speckit-clarify` 或 `$speckit-plan` 前修正；本轮没有未勾选项。

| FR 覆盖 | 场景或可验证断言 |
|---|---|
| FR-001–005 | Story 1；SC-001；Edge Cases 的并发、响应丢失与路径异常；确认缺失才创建、非 Git 在服务副作用前拒绝。 |
| FR-006–010 | Story 2；SC-002；用途存在仅聚焦、人工用途不自动执行、显式新增保留默认、冷恢复未知拒绝普通打开且保留旧布局。 |
| FR-011–014 | Story 3；SC-003/004；Edge Cases 的移动、关闭、过期标识和多客户端尺寸；错误目标为零，停止服务不重放任务。 |
| FR-015–017 | Story 4；SC-005；配置仅影响声明目标，五次无变化部署稳定；初始前缀和禁用项可逐项核对有效加载结果。 |
| FR-018–022 | Story 5；SC-006；工具缺少准备明确失败、参数按字面处理、仅选定文件交接、身份保留；独立 Codex 不影响 Pi 或既有 daemon。 |
| FR-023–024 | Story 7；SC-010；关闭增强核心流程仍可用，并发/延迟事件不误关联；官方工具未修改、无额外管理服务或清单、无权限扩张均可核对。 |
| FR-025–026 | Story 6 场景 1/3；SC-007；核对稳定发行、暂留原因与重评条件，分别记录候选及运行身份、有效配置、规则和集成。 |
| FR-027–029 | Story 6 场景 2–4；SC-007/008；可重放负载覆盖声明的规模与状态，同环境冻结评价门槛；无基线不虚构对比，附加缺测单列。 |
| FR-030–031 | Story 6 场景 5；SC-009；新工作试用后显式切未来入口、旧任务保留；程序/配置/持久状态分别验证回退，不能证明时停止。 |
| FR-032–034 | Assumptions 的兼容与授权边界；SC-007/009；兼容不能以补丁号精确匹配替代、验收类别与四种状态分开记录、默认检查无第三方宿主及真实账号/会话/密钥。 |
