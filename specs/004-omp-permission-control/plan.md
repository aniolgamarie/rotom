# Implementation Plan: OMP 权限管控

**Branch**: `main`（实际 Git 分支；未新建功能分支） | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

**Feature**: `004-omp-permission-control`。setup-plan 的 `BRANCH` 是 feature pointer 推导的标识，不代表已切换 Git 分支。

**Status**: 仓库实现、限定验收与本机迁移完成；参见 [独立插件迁移计划](standalone-plugin.md#计划与验证)。T001—T087/Phase 11 是历史补丁交付，不能继续构建发布；本文件下文保留历史设计与验收身份。

## Summary

**当前架构**：官方未改动 OMP + 独立 `permission_bash` 工具 + 受管 `permission-control.json`。模型和人工审批位于工具执行函数内，仅通过公开 API 发起命令。原生 Bash 保持 prompt；不再使用宿主 bridge、私有执行计划或 patched standalone。宪章第 VI 项适用，旧计划的补丁许可失效。当前接口、能力取舍和验证步骤以[独立插件修订](standalone-plugin.md)为准。

**以下为历史方案**：

实现仓库内 TypeScript 扩展 `omp-permission-control`，供 `omp-kernel` 选择；支持 `/permission-control smart|manual|status|explain`。确定性规则先处理安全/禁止边界，独立模型审查完整 Bash 操作；主审可指定现有低成本模型，省略使用会话主模型。显式 reviewer_model 优先，省略时才会话默认；可选 remote_fallback_model 在主审运行时故障/不支持时接替同等级审查，tiny 最后仅辅助 ask/deny。

锁定 OMP v18.3.0 的公开接口无法同时消除重复 prompt、保留有效原生规则和绑定最终执行，故采用薄宿主补丁 `permission-control/v1`。宿主掌握原生保护、人工 UI 与一次性许可；扩展不覆盖 Bash，不使用 YOLO。补丁以独立锁的本地 standalone variant 交付，其它 OMP profile 继续官方包。取舍见 [research.md](research.md)。

## Technical Context

**Language/Version**: Python 3.11+；扩展/补丁为锁定 OMP 兼容的 TypeScript/Bun。运行用 standalone 内嵌 Bun；构建工具链精确版本和摘要先锁入独立 `agents/omp/patches/permission-control/build-inputs.lock.json`，由 `schemas/omp-permission-build-inputs.schema.json` 校验；基础测试以该输入清单核验 Bun，构建后再与正式 receipt 交叉核验，日常使用不要求系统 Bun。

**Primary Dependencies**: 现有 PyYAML/jsonschema/Jinja2/pytest；OMP commit `62bc57be1b03ef0802a33cf7f5f530e534527531` 与完整 bun.lock；ModelRegistry、pi-ai、原生 UI/session、installed-only tiny。保守 Bash 分析器不执行输入、不增加第三方运行依赖。

**Storage**: TOML 配方/机器覆盖，`config.yml` 受管 `/permissionControl`，独立补丁锁/receipt；状态/许可只驻内存，脱敏审计写原生会话扩展记录。无新数据库、凭据库或批准缓存。

**Testing**: pytest管理器契约；Bun纯逻辑与实际补丁集成（fake transport/UI/execute、网络阻断）；预冻结240条标签样本。T081/T082最终三组材料化加kernel渲染单项152 passed/71.68s，bridge37 passed/287 assertions，完整coding-agent strict与相关format check退出0。新runtime真实隔离宿主通过单次pwd许可、new/resume、missing-plugin和rollback，外部模型0。T080冻结质量评测safe99/100、risk危险allow0/100、fault allow0/40是保留原身份的历史模型证据，本轮没有重测，不代表全部SC或其它平台普遍保证。

**Target Platform**: 首版 Linux glibc x64 主会话 Bash。Linux arm64/WSL/macOS/Windows 分别登记；缺平台补丁资产启动报错，已运行但超出智能范围采用人工/原生保护。

**Project Type**: 本地扩展、最小宿主补丁、现有 Python 管理器的 OMP 适配扩展。

**Performance Goals**: 无 remote 时主审最多25秒，配置 remote 时主审最多12.5秒、remote 使用剩余审查时间；已配置 tiny 保留最多5秒，包含预处理的自动流程合计30秒；取消 1 秒内撤销执行资格。每操作最多 1 主审 + 1 合条件远程 fallback + 1 合条件 tiny；输入上限 24/8 KiB、输出 512/128 tokens，另限制输出字节数。

**Constraints**: 严格 schema；native deny/命令 prompt/critical 优先；最终参数冻结；许可不跨请求/会话；秘密不进入审查器或日志；无隐式安装/下载；不动本机 OMP。非 OS 沙箱，不覆盖 eval/MCP/子代理统一智能审查。

**Scale/Scope**: 单人自用、一个审查器、四命令、两模式；会话内串行处理 Bash 审查至执行发起。首批支持 kernel 所用两类 provider API，其它 transport 未证明有界则转人工并显示限制。

## Constitution Check

| 原则 | Phase 0 前 | Phase 1 后与落实 |
|---|---|---|
| I 公共核心/原生适配 | 通过：限定 OMP | 通过：专属闭合 schema/bridge/variant；无 raw_native；不伪造支持 |
| II 秘密/所有权 | 通过：无本机账号变更 | 通过：认证留宿主、最小模型输入/审计；沿用字段所有权及路径保护 |
| III 确定性/恢复 | 通过：不部署 | 通过：确定性渲染、三方比较、stage/receipt/租约/pending；rollback 不降级软件 |
| IV 显式副作用/锁 | 通过：只读研究 | 通过：可追溯补丁、显式构建、独立 lock、sync 消费、apply 部署、run 使用 |
| V 隔离验证/证据 | 通过：仅文档检查 | 通过：fake tests 不启动宿主；真实模型/二进制/platform 另行授权，证据不互替 |
| 技术/退出码 | 通过：现有入口和 Python | 通过：插件用原生 TypeScript；保持 0/2/3/4/5/6 |

宪章 1.0.0 中“已实现 DSH、Pi 为下一目标”及 Pi 来源迁移段是旧阶段事实；当前 [AGENTS.md](../../AGENTS.md) 和代码已包含 OMP。本特性不是 Pi 迁移，不重新迁移 starter；继续遵守相同隔离/依赖/证据原则。本轮不修宪章，也不把旧阶段描述当作 OMP 禁令。无需豁免的原则冲突。

## Project Structure

### Documentation (this feature)

```text
specs/004-omp-permission-control/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── configuration.md
│   ├── host-bridge.md
│   ├── review-decision.md
│   └── session-commands.md
└── checklists/requirements.md
```

任务清单已由 `$speckit-tasks` 生成，见 [tasks.md](tasks.md)；当前执行进度由任务 checkbox 与验收记录维护。

### Source Code (planned, repository root)

```text
agents/omp/
├── packages/omp-permission-control/
│   ├── index.ts                # 注册、四命令
│   ├── controller.ts           # 模式、generation、编排
│   ├── shell-analysis.ts       # 完整保守解析、效果/目标依赖
│   ├── policy.ts               # 固定决策策略
│   ├── reviewer.ts             # 输入/输出、单次预算
│   ├── audit.ts                # 理由码、脱敏、会话记录
│   └── tests/
├── patches/permission-control/ # 有序补丁、来源、补丁集成测试
├── build-permission-control.py # 显式离线构建
└── plugins.toml
locks/omp/permission-control/   # manifest、build receipt、构建材料
schemas/omp-permission-runtime.schema.json
schemas/omp-permission-build-inputs.schema.json
src/agentcfg/
├── cli.py                     # 补丁lock维护参数；不改变日常run语义
├── omp.py                     # 引用、渲染、能力、启动核对
├── omp_settings.py            # 闭合配置与 eval 原生 prompt 字段
├── omp_dependencies.py        # variant 选择、stage复用
└── omp_permission_runtime.py  # 补丁锁/asset/receipt校验
profiles/omp-kernel.toml
tests/
├── test_omp_permission_control.py
├── test_omp_permission_runtime.py
└── fixtures/omp/permission-control/
```

现有 OMP adapter/dependencies/kernel/runtime 测试和 DSH/Pi 边界按影响回归。同步原生 schema/发现清单、锁、示例、OMP 文档及平台矩阵。上表保留规划时的目录设计；当前文件与实施状态以 tasks 和验收记录为准。

**Structure Decision**: 本地扩展沿用 packages，宿主差异保留 patch，管理器变更限定 OMP 模块。独立运行包锁不冒充官方资产，不引入第二套事务。详见 [配置](contracts/configuration.md)、[宿主](contracts/host-bridge.md)、[模型](contracts/review-decision.md)、[会话命令](contracts/session-commands.md)。

## 实施顺序与验收门槛

1. **执行边界**：bridge、原生来源、无副作用 prepare/审批后资源 stage/单次 commit、许可、installed-only tiny；用真实 wrapper/prepare/commit 函数配假依赖验证时序/取消/无 UI。覆盖前台 native backend 及其原生自动后台管理；interceptor 未命中、可核实的已初始化环境不因开关本身转人工。冷启动、实际动态 direnv/prefix/service/pty/不可核实状态等保留人工。证明补丁可干净应用、产物可构建，不以 fake bridge 代替宿主交付。
2. **规则与模型**：先冻结实际 240+ 样本内容、标签和 tree digest，再实现 Bash 子集、效果、授权、脱敏、规则、provider single-attempt 和 tiny 限权。受限只读操作可免逐次授权，但不能越过用户限制；其余主审 allow 必须有完整上下文及逐 effect 引文/绑定。主审承担自然语言授权语义判断，宿主核验来源、字节区间、effect scopeDigest、失效条件与固定风险下限；未解释的用户限制不走确定性直通，语义正确性单独实测，不宣称代码可独立证明任意自然语言授权。宿主独立强制预算与失效。
3. **会话体验**：四命令、模式失效、status/explain、审计；新建/恢复读默认，加载失败/覆盖范围如实显示。
4. **受管交付**：schema、引用、kernel 选择、artifact/锁/receipt、sync/apply/run/rollback。保留 Bash 原生 prompt，为 task/eval 设原生人工门槛；其它 profile 官方路径不变。
5. **分层验收**：最终完整 patch series 必须重新干净应用并通过真实 bridge/prepare/commit 与 installed-only 集成组，不沿用早期 patch 证据。[quickstart](quickstart.md) 隔离验证与秘密哨兵；真实宿主与真实模型分别授权、登记。T072 用真实 standalone 与固定响应 provider 验证宿主链，固定响应和有限主模型请求都不替代 T073 reviewer 评测。

### 需求追踪

| 需求 | 设计/验收 |
|---|---|
| FR-001—003 | session-commands、configuration、模式测试 |
| FR-004—009 | host-bridge、review-decision、shell-analysis、compound样本 |
| FR-010—013、034 | host-bridge、data-model、并发/失效/无UI/执行哨兵 |
| FR-014—020 | configuration、review-decision、provider/tiny故障矩阵 |
| FR-021—026 | session-commands、data-model、预算/脱敏/审计 |
| FR-027—031 | host-bridge、锁/所有权/rollback/平台矩阵 |
| FR-032—033 | quickstart、隔离与独立证据记录 |
| FR-038—039、SC-013 | configuration/review-decision、Cursor模型与资源来源隔离、remote-fallback core/实际runner与新资产fixture |
| SC-001—011 | quickstart固定样本、性能/秘密/交付门槛 |

## 风险与完成标准

- 上游升级需要重新核对 wrapper/Settings/tiny、干净应用补丁、独立构建，不能只改版本号。
- 保守语法和有界 transport 会使部分请求仍需人工；固定样本达到 99/100 safe 免问且 risk 0/100 危险 allow。该结果不外推到冻结集之外，不得为了指标放宽 unknown/硬规则。
- 许可绑定防陈旧批准复用，不能代替 OS 隔离或保证外部文件竞争绝对原子性。
- tiny 资源未完整安装时显示 unavailable；这是合法状态，不是自动安装理由。
- Phase 9 交付已按 T081/T082 修复后的字节重建资产与receipt，combined runtime为 `36c0e8a46da3999b4eee73edc0121117fd284f2880bc7784ba36189946854e0f`，同一资产的Linux x64隔离宿主复验通过。任何后续受锁字节变化仍须从recipe identity起重建。T072历史runtime `bf6f18b45fc80c177f6644e96366b978bb3d524b0d476664d228e4a7de48bc08` 与T080历史runtime `b1566c3e211f0dbd71d1849509a7f3b10bb27651602f1ca6fc5b51bd1f7ccbe4` 的host/model记录保留各自身份；本轮模型请求0，102/102历史账本不变。真实tiny、其它平台和冻结集外质量未验证，日常本机配置未修改。

## 规划阶段任务记录（历史）

| 状态 | 记录 |
|---|---|
| 完成 | 研究、技术取舍、数据/接口/验证设计、宪章前后检查；文档检查见本轮报告 |
| 进行中 | 无；实现与 tasks 尚未开始 |
| 失败待决策 | 无；纯扩展无法满足约束，已决定使用 bridge |
| 环境不足未验证 | 本轮未尝试构建/运行，不能判定环境不足；宿主/模型/platform 记为尚未执行 |

2026-09-29 文档验收：使用仓库 `.venv/bin/python` 检查本轮 8 份设计文档，26 个相对链接全部存在，6 个 JSON/YAML/TOML 示例可解析，模板占位与尾随空白均为 0；命令集合恰为四个约定子命令。`git diff --check -- specs/004-omp-permission-control` 无错误。前后检查均未发现 `.specify/extensions.yml`，无待执行 hook；未生成 tasks.md。源码研究由 scout 分工完成，四份数据/契约文档由 `gpt-5.6-sol / medium` executor 编写并修订，主代理完成架构取舍和交叉验收。未执行功能测试、构建或真实调用。

## Complexity Tracking

无宪章违规豁免。补丁和运行包复杂度是满足 FR-005/010/028/034 的明确代价，替代方案见 research R1/R6。

## Phase 9 历史交付身份（2026-09-30）

| 身份 | 本轮实际值 |
|---|---|
| 0001 patch | `f5478d8c128a92e19fc5ff46269a6cf6743dc8fc7c20389211c676afe605ce94` |
| standalone SHA-256 | `ada205aeec0cd2aefbb4c2d0b00d924ba2d9360395159fdd76f2c6a56a128f41` |
| standalone size | 367281352 bytes |
| patched manifest | `f3a274d2c593851d17101d57a8aca6c5705994655f6b93755f356d258918af2f` |
| build receipt | `f5ab42e0d4ef6997d0f13bed74d97945190e0a6dbb149ce6d94808bf85269da3` |
| combined runtime | `36c0e8a46da3999b4eee73edc0121117fd284f2880bc7784ba36189946854e0f` |


T080 runtime `b1566c3e211f0dbd71d1849509a7f3b10bb27651602f1ca6fc5b51bd1f7ccbe4` 的构建、宿主和模型结果保留为历史。该阶段source patch已改变，对应宿主证据单独登记在host JSON的convergenceDelivery20260930，不将历史host通过冒充新资产通过。

## Phase 11 模型选择与可用性决策

- execution model 与审查链独立。主审显式reviewer_model优先，省略才用session；错误引用配置失败。remote_fallback_model只作运行时故障接替，不覆盖主动主审、不复审有效决定，重复实际provider/model跳过。kernel默认remote选择已声明GLM5.3Flash，tiny保留installed-only。
- 新增disabledModelProviders：未配置回退原disabledProviders；仅patched profile生成独立模型列表，ModelRegistry及model hub统一使用。capability仍使用原资源denylist，不能仅靠enabledProviders=[]关闭项目Cursor来源，official profile不变。
- remote完整使用同一24KiB上下文/逐effect授权/512tokens/4KiB严格协议及固定风险下限；来源remote-fallback，不与tiny的fallback来源合并。tiny仅ask/deny。各层调用、配置主审与实际模型均分别可审计，历史决定不被后续状态变化改写。
- 总自动deadline仍30秒；无remote沿用primary最多25秒/tiny5秒；有remote时primary最多12.5秒，remote最多剩余时间并为已配置tiny保留最多5秒。unsupported主审零请求，可把剩余最多25秒用于remote。取消、generation和目标绑定检查覆盖每层，不等待串行队列。无remote保留原tiny故障触发集合；有remote时unsupported/unavailable也可进入该显式链。
- 使用新增SC-013隔离组，保留240冻结fixture与102/102历史账本。固定本地provider验证新runtime宿主审查链；真实Cursor目录、GLM远程fallback质量和其它平台单独登记，不以fake结果替代。

## Phase 11 最终交付身份与验收

| 身份 | 本轮实际值 |
|---|---|
| official recipe | `60d399dd4b0a2f2265d117d17b9e566669b64ca1413d4dc0fac66487165b9521` |
| plugin tree | `4511e7cdb9efb312029acfff93f0f6fe73cc5c3c018325c25756f9fd7eea040d` |
| 0001 patch | `45a0fcbdd4092161cbc3c14ac8b40a323928cd4dc915538e2cbee7f6ead8e51f` |
| 0002 patch | `c34d02d19941e09ca507e67164f5b8d37a67e991b6ed96ab51dca2b67ece33da` |
| standalone SHA-256 | `0fe58d4af126d162979efe3188b0a11d3f35b4a52f01049d7c4ac8871b63fa86` |
| standalone size | 367318216 bytes |
| patched manifest | `dce490890453ccff4165ece76a460fb9cbf23756cdb553c3fd7fe8d72bbb815e` |
| build receipt | `f0716c84316192f349253d68247ba4bcfc455f41218816efe79675952df4a0ac` |
| combined runtime | `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2` |

Phase 11 新资产已完成正式离线构建、锁/receipt核验和266项材料化及相关OMP回归（96.59s，无跳过）；core 291 pass / 1085 assertions，宿主检查见本轮记录。Linux glibc x64临时HOME真实standalone通过主审503一次→远程Anthropic完整审批一次→pwd成功结果一次，primary1/remote1/tiny0/human0，permit pending→consumed；new/resume、missing-plugin pre-spawn exit5及rollback通过。固定服务main2/primary-failure1/remote-review1，外部模型0，服务已停止。 详细命令与结果见[验收记录](../../docs/acceptance/omp-permission-control.md)和host JSON的remoteFallbackDelivery20260930。
