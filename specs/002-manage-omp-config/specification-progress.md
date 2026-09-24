# OMP 规格任务记录

## 已完成

- 检查 before_specify / after_specify hooks：仓库无 `.specify/extensions.yml`，按技能规则跳过。
- 读取项目宪章，通过模板解析脚本获取 spec-template，创建 `002-manage-omp-config` 并记录 `.specify/feature.json`。
- 盘点仓库遗留问题：AGENTCFG-F01 为本次 OMP 直接交付范围，其余作为约束或排除。
- 查阅 OMP 官方配置/profile、环境变量、目录实现、用量入口和 provider 文档，记录可变来源及核实日期。
- 完成 5 个用户故事、28 条需求、7 项成功标准；只读复核后补充原生模式状态哨兵、冲突退出码和继承归属。
- 需求质量检查：16/16 通过。检查章节、编号、占位、相对链接及当前功能定位。
- 未创建 Git 分支；当前实际分支为 main，功能目录独立。前置脚本输出的 BRANCH 是功能上下文值，不代表创建了同名 Git 分支。

## 进行中

- 无。speckit-plan Phase 0/1 与 speckit-tasks 已完成；产品实施尚未开始，tasks.md 全部保持未勾选。

## 失败待决策

- 无需要人类决策的规格阻塞项。

## 环境不足未验证

- 智谱专用用量插件网页及其 Markdown 入口获取失败；官方助手提及插件仅能证明存在该能力说明，不能证明公开接口或 OMP 已支持。已把固定版本复核写入 FR-023。
- 未运行 OMP、读取真实认证或调用订阅服务；原生 profile/用量行为只有文档与源码证据，无本机执行证据。
- 未运行产品测试；本轮只修改规格文档，隔离测试与真实 smoke 均不能记成通过。

## 执行分工与验证

- 主代理负责上游事实核实、需求取舍、文件编写及最终验收。
- specify/clarify 阶段实际调用的 scout 角色使用 gpt-5.6-luna / medium，负责仓库只读证据与规格复核；这些阶段没有 executor 实现任务。plan 阶段分工见下方记录。
- `python3` 文档检查：必需章节、5 个故事、28 个连续 FR、7 个连续 SC、无模板占位、相对链接、功能定位记录均通过。
- `.specify/scripts/bash/check-prerequisites.sh --json --paths-only`：定位至本功能目录。
- `git diff --check`：通过；新增未跟踪文件另做空白与链接检查。
- 保留会话开始时已有的未跟踪文件，不修改或关闭既有遗留问题记录。

## 2026-09-24 澄清完成记录

- Q1：仅新建独立 OMP 环境，允许重新登录；只导入非秘密配置和资源，旧环境的登录和历史会话保留原位，不做原地纳管。
- Q2：首版完整纳管八类配置，每类至少一个可用验收样例；主题与快捷键分别验证，不能以整类不支持或延期替代交付。
- 更新章节：Clarifications、User Scenarios & Testing、Functional Requirements、Measurable Outcomes、Assumptions 与 Scope Boundaries。
- 清单过程：会话起始 16/16；发现最低范围歧义后 CHK006 暂时取消勾选，15/16；Q2 回答后恢复 CHK006，16/16。最终无退化、无未勾选项，清单仅修改该标记，其他文字未改。
- 最终验证：2 条问答无重复、迁入范围一致、必交能力及成功样例一致、28 FR / 7 SC 编号保持、文档相对链接与空白检查通过。
- before_clarify / after_clarify hooks：无 `.specify/extensions.yml`，均跳过。
- 功能范围、身份与数据关系、交互流程、完成标准：Resolved；非功能质量、异常处理、约束取舍、术语、占位项：Clear。
- 外部集成：Deferred 至 plan 固定 OMP 版本、平台矩阵、字段/资源映射及上游用量支持证据；不影响已确定的需求范围。无其他待用户回答事项。
- 主代理完成答案整合及最终验收；scout（gpt-5.6-luna / medium）已独立识别最低交付范围歧义。未执行产品测试、真实宿主或账号调用。

## 2026-09-24 Plan 完成记录

- 已完成：setup-plan 解析模板；固定 OMP v18.3.0 / 62bc57be1b03ef0802a33cf7f5f530e534527531；只读取得源码和官方发布校验声明，未下载运行二进制。
- 已完成：research.md 的 R01–R09 决策；plan.md、data-model.md、三个 contracts、quickstart.md、validation-matrix.md；Phase 0/1 宪章检查无设计偏离。
- 已完成：两层 profile 算法、独立 HOME/XDG、不可接管旧身份、来源 preflight、bare-env 守卫、八类九行样例、原生/受管 usage、只读 inventory 和完整依赖契约。
- 已完成：复核修正模型容量为管理器政策、MCP 缺 env 由管理器报3、固定 discovery ID 清单及命名冲突；确认 pending 由 apply/rollback 沿公共部署器恢复，不移植 recover pi 的执行租约语义。
- 已完成：before_plan/after_plan hooks 检查；仓库无 `.specify/extensions.yml`，按技能规则跳过。
- 执行分工：主代理完成设计取舍、上游调查、契约编写与验收；scout（gpt-5.6-luna / medium）提供仓库/上游证据与关键事实复核；executor（gpt-5.6-sol / medium）仅编写 quickstart/validation-matrix 并交叉核对。无产品代码实现，无下级委派。
- 静态验证范围：11 份 Markdown、相对链接、围栏、尾随空白、2 个 TOML 示例语法、28 FR/7 SC/24 场景覆盖、功能定位和实际 main 分支；当前检查结果与主计划交付一并报告。
- 检查工具修正：系统 python3 缺 tomllib，已切换仓库 `.venv/bin/python`；清单中“无 NEEDS CLARIFICATION”是勾选说明而非未决占位，检查按正文/清单区分。
- 失败待决策：无。未关闭 AGENTCFG-F01 或其他缺陷，因为计划完成不等于功能验收完成。
- 环境不足未验证：真实宿主/账号/用量/模型/macOS、各平台发布二进制实际 SHA 和运行效果均未执行；国内智谱专用插件页仍不可复核。源码证据不替代这些验证。
- 后续：进入 `$speckit-tasks` 生成实施任务；本轮未生成 tasks.md、未改产品代码、未创建 Git 分支或提交。

## 2026-09-24 Tasks 生成记录

- 已完成：按 speckit-tasks 读取模板、spec/plan/data-model/contracts/research/quickstart/validation-matrix 与宪章，生成 tasks.md；八阶段、66项任务全部未执行。
- 任务分布：Setup 3、Foundational 13、US1 14、US2 7、US3 7、US4 7、US5 6、共同收尾9；23项具有有条件的并行标记，最多两个执行槽，共享文件单写入者。
- 已完成：身份/owner/来源检查、秘密守卫与lock/sync/runtime公共能力前置，避免US1依赖后排US2/US5；增加最小bootstrap声明，避免adapter注册依赖后排资源任务。
- 已完成：FR-001–028、SC-001–007映射到执行任务与既有验收场景；八类九行、两条pending恢复路径、原生/受管usage及分操作真实验证均保留。
- 执行分工：主代理单写tasks及进度记录并验收；scout（gpt-5.6-luna / medium）只读识别易漏约束及基础前置；executor（gpt-5.6-sol / medium）只读复核任务与契约的一致性。未执行产品实现或测试。
- 静态验收：检查全部任务复选框/连续ID/故事标签/精确路径、并行批次文件不重叠、任务引用存在、FR/SC覆盖、链接和空白；脚本确认当前功能可被后续工作流定位。
- 独立复核收敛：明确部署前candidate与已部署binding的区别、lock后端和CLI分发各自文件归属；补PluginPackage及四类生成原生文档schema、run/help/version/doctor先行测试；迁入与usage结果测试移到对应实现前。未发现依赖环或已标记批次文件竞争。
- before_tasks/after_tasks：仓库无 `.specify/extensions.yml`，按技能规则跳过。
- 失败待决策：无新增需要用户决策项；真实宿主、账号和平台验证保持未执行，不因任务已生成而记为通过。
- 后续：建议先执行 `$speckit-analyze` 检查spec/plan/tasks一致性，再进入 `$speckit-implement`。实际Git分支仍main，未创建分支或提交，保留原有未跟踪文件。

## 2026-09-24 Analyze 后授权修订

- 用户已明确授权修订I1、I2、U1并在完成后重新执行speckit-analyze；修订阶段仅修改tasks.md、quickstart.md与本记录。
- 已完成I1：T005前置argv负向测试，T014实现共享token-aware参数门禁，T015再注册run；T034只复用门禁并补多profile回归。
- 已完成I2：明确omp-default为bootstrap，omp-validation为临时仓库内已登记的九行验收配方；指南提供源文件/fixture registry/profile/技能复制、现有.venv复用、假值SecretRef与正式锁/真实二进制验证步骤。测试替身不进入真实smoke证据。
- 已完成U1：T026生成首轮manifest、upstream/bun.lock、provenance.json、NOTICE.md完整文件组；T054仅做最终重新解析与审阅，独立synthetic锁仅在隔离测试仓库使用。
- 同步修订：指南第4节使用明确选择的OMP_CASE_PROFILE；真实登录前必须部署同一个bootstrap身份；资源变化后显式更新锁并sync。任务数量、编号、需求范围和真实执行授权边界保持不变。
- 分工：executor（gpt-5.6-sol / medium）负责tasks.md修订与自检；主代理负责quickstart、本记录及最终验收。重新分析阶段只读，分析结果在对话中报告，不在该阶段回写文件。
- 文档验证：quickstart的15个shell代码块仅执行sh -n语法检查，TOML及公开假值片段可解析；未执行示例命令、产品测试、OMP、登录、usage或模型调用。
- 失败待决策：修订阶段无。环境不足未验证：所有既有真实宿主/账号/平台验证仍未执行；66项实施任务保持未勾选。

## 2026-09-24 用户授权验收范围修订

- 用户明确将 Linux arm64/macOS 实机、真实登录、真实 usage、指定模型调用转为遗留，本机没有对应环境，不在 spec 002 范围。
- 当前 62/62 项完成（T001–T061、T066），原 T062–T065 与 T061 未覆盖架构转入 OMP-F01–F05，均保留未验证，不伪造通过。
- spec、plan、tasks、contracts、验证矩阵、实施记录和支持文档同步；历史研究/阶段测试记录仍保留原结论与时间。
- 详见[范围修订](scope-change-20260924.md)和[遗留清单](../../docs/follow-ups/omp-platform-and-live-validation.md)。本次只修改文档，未执行宿主、账号操作或重跑产品测试。
