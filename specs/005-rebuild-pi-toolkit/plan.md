# Implementation Plan: 公共治理对齐与 Pi Base/Pro 重建

**Branch**: `design/pi-toolkit-reboot` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

**Input**: `specs/005-rebuild-pi-toolkit/spec.md`

**Status**: 公共治理、旧Pi退役、Base及状态信息交付门已实现并取得限定Linux验收；本轮四模块组合/性能门已完成。Pro依用户决定等待社区上游，Brave/Cursor真实账号验收延后，完整feature未完成。当前证据见[本轮交付验收](current-delivery-acceptance.md)，下述Phase 0/1步骤保留为原实施方案。
`setup-plan.sh` 返回的 BRANCH 为 feature ID `005-rebuild-pi-toolkit`，实际 Git 分支保持上述值。

## Summary

先对齐 DSH/OMP/Pi 的公共配置、完整依赖治理、部署所有权、配置恢复与实例维护准入，
通过现有公共模块及必要中性原语共用；工具原生目录、锁格式与包管理由薄适配保留。
再以未修改的官方 Pi Node CLI 重建 Base/Pro，并按消费者清单退役整套旧 Pi 专属执行平台。

Base 以 Pi 1.3.0、Node ≥22.19.0、原生 UI、静态 Catppuccin、精简规则/资源和既有 SpecKit 为起点。
Pro 候选目前不能满足强制“每主会话至多两个只读调查且禁递归”，保持协作 not_ready；
Powerline 0.20.2 仍暂停准入；公开API替代pi-footer0.5.1已完成状态信息门，用户明确接受
权限详情说明、分支输出均速和窄屏详情三处差异。US6本轮所选组合/禁用恢复与条件一致的性能对照已通过；
Pro与完整feature门仍开放，不因已有计划或Base通过而豁免。

研究与备选见 [research.md](research.md)。原计划生成阶段止于设计，没有执行安装、宿主或
部署；后续实施和真实验收以[实施记录](implementation-status.md)及[本轮交付](current-delivery-acceptance.md)为准。

## Technical Context

**Language/Version**: 管理器 Python 3.11+；官方 Pi 1.3.0 使用 Node ≥22.19.0。
公开扩展按其上游语言和接口接入，不将插件改写为 Python，不构建修改过的宿主。

**Primary Dependencies**: 现有 uv.lock 的 PyYAML/jsonschema/Jinja2/pytest；
新 Pi 完整 npm 闭包以 `@earendil-works/pi-coding-agent@1.3.0` 与静态
`catppuccin-pi-theme@0.1.6` 为直接来源，实际完整锁在实施阶段显式生成并审阅。
默认无第三方进程内扩展或外部 MCP；可选候选与 held 原因在研究文档固定。

**Storage**: 现有 TOML 公共来源/机器覆盖、JSON 原生投影、完整依赖锁、部署 journal/上一版配置、
私人实例身份与活动记录。原生 auth/trust/session/log 和模块缓存由各实例拥有。
不新建任务数据库、逐工具租约、重试队列或跨崩溃执行恢复账本。

**Testing**: pytest 默认临时 HOME/XDG、网络阻断与假进程；公共变更覆盖受影响 DSH/OMP。
原生宿主、终端与平台、真实账号/模型分别独立授权验收。本轮仅静态文档检查，不跑宿主或 pytest。

**Target Platform**: 首个实施验收目标 Linux x86_64；macOS 为后续原生候选；其他 OS/架构未纳入当前
通过承诺。每个以后声明已通过重建的平台至少两个不同用户目录/仓库位置；本轮不宣称任何平台已通过。

**Project Type**: 既有多宿主配置/部署 CLI，新增 Pi 薄适配与两档资源配方；不新增 agent 服务。

**Performance Goals**: 未选模块的扩展加载、服务连接、后台工作数为 0；Base 不新增强制计划/协作步骤。
对 US6 选中交付的按需模块，记录同任务同模型/缓存条件的冷/热启动、额外进程、初始上下文、用量和资源占用；
缺所需授权或测量条件时保持未执行。若没有选中模块，模块性能比较记录为阶段不适用并注明理由，
不要求为此单独运行原生基线；未选模块零加载/连接/后台的隔离验证仍须完成。
没有测量不承诺更快或节省百分比。状态栏以 60/90/130 列中文与 resize 验收可用性。

**Constraints**: 不修改上游；输入未知字段失败；秘密不入普通配置/摘要/日志/备份；
离线操作不安装或启动宿主；run 不补依赖；活动/未知 owner 阻止不安全维护。
官方公开接口不满足时禁用相关能力，不修补宿主、不通过新执行平台弥补。
同一 Pi 配方支持多个独立主会话；运行登记、退出与排他维护共用受保护准入边界，
所有相关主会话及后代确认空闲后才允许维护共享资源。

**Scale/Scope**: 3 种工具的受影响公共契约、2 个新 Pi 配方、10 类状态栏信息、首轮每主会话至多 2 个
只读调查；同配方多主会话独立计数，两个主会话可各有两个调查；按需模块逐项准入。
旧 Pi 4 配方、执行平台、插件、锁、测试与引用逐项退役，
保留用户原生状态及历史证据，不顺带更改其他工具功能或终端/代理配置。

## Constitution Check

*GATE: Phase 0 前评估；Phase 1 写入结束后重新核对。此处通过仅指设计符合，不代表迁移完成。*

| 原则 | 研究前门禁 | Phase 1 后设计结论与证据 |
| --- | --- | --- |
| I 公共核心与真实适配 | PASS：先核对 DSH/OMP 实际差异，不把旧 Pi 平台当公共层 | PASS：公共管线/backend/hook 共用，原生格式薄适配；common-management、research §2 |
| II 秘密与所有权 | PASS：不读取真实密钥或会话，不默认接管全局 home | PASS：稳定独立实例、非秘密覆盖与 SecretRef；data-model §2–4、runtime 契约 |
| III 确定部署与恢复 | PASS：三方、pending、备份规则不弱化 | PASS：配置恢复、维护准入、任务结果分层，unknown 保守阻塞；公共契约 §3/5 |
| IV 副作用与完整依赖 | PASS：只写计划材料，不安装或运行 | PASS：lock/sync/apply/run 分离，完整 npm 闭包与发布物校验；两份运行契约 |
| V 隔离与证据 | PASS：默认不运行宿主 | PASS：既有回归、新隔离、原生与账号分层；quickstart、退役契约 §4 |
| VI 上游不可修改 | PASS：旧偏离只作待退役历史，不运行或继续构建 | PASS：Pro/Powerline held，不以私有接口或补丁解决；research §5–6 |
| VII 公开隐私与身份 | PASS：文档仅相对路径/虚构数据，不提交 | PASS：来源与证据脱敏，提交身份门禁保留；退役契约 §6 |
| VIII 工作树与历史 | PASS：保留当前分支与已有编辑，不合并或清理引用 | PASS：稳定最终审查、目标变化重评、临时材料退出；退役契约 §5–6 |
| IX 社区与版本证据 | PASS：热门候选不冒充兼容证据 | PASS：固定版本与一手来源、精确发布物/真实键核对，区分静态与运行；research |

**门禁结论**：无需要豁免的设计违规，无未解决的人类澄清。
现有旧宿主补丁及执行平台仍在仓库，状态为待退役；本计划没有新增或继续构建发布它们。
Pro 协作和状态栏完整对齐存在已知准入阻断，必须生成后续明确任务并保持未完成，
不能将设计门禁通过或 Base 阶段验收当作整个功能完成。

## Project Structure

### Documentation (this feature)

```text
specs/005-rebuild-pi-toolkit/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/requirements.md
└── contracts/
    ├── common-management.md
    ├── pi-runtime-and-modules.md
    ├── collaboration-and-status.md
    └── retirement-and-evidence.md
```

`tasks.md` 由后续 `$speckit-tasks` 产生，不在本命令生成。

### Source Code (repository root)

以下是未来实施的归属边界，不表示本轮已写入这些位置。

```text
src/agentcfg/
  workspace.py config.py merge.py render.py adapter.py
  commands.py runtime.py backends.py
  deployment.py native_projection.py storage.py
  lifecycle.py omp_identity.py
  pi.py pi_dependencies.py pi_lifecycle.py
  model_delegate*.py activity.py workspace_leases.py pi_recovery.py ...
agents/pi/
  agent.toml bindings.toml content.toml dependencies.json plugins.toml
  schemas/ build/ runtime/ templates/ prompts/ themes/ extensions/ roles/ packages/
profiles/
  pi-base.toml pi-pro.toml（待新增）；旧 pi-*.toml（待退役）
locks/pi/
  两档完整依赖与身份资料（待重建）
shared/
  rules/skills 等同源公共内容
schemas/ examples/ tests/ docs/
  最小必要变更、虚构绑定、受影响回归、正式指南与支持矩阵
```

**Structure Decision**：保持现有 Python 包与公开 CLI。配置/部署继续走公共模块；
依赖继续通过 `DependencyBackend`；运行继续通过 adapter lifecycle hook 与通用 runtime。
在现有 lifecycle/storage 范围提取中性原语，避免另造 Pi 框架或强制迁移 DSH/OMP 标记。
Pi 适配重建与旧文件删除按引用分批处理，不能依据上面的省略项或文件名前缀直接删除。

### Phase 0 决议与 Phase 1 产物

[research](research.md) 已就公共接缝、锁格式、发行方式、配置/发现、主题、Pro、状态栏、
模块及后代维护作出选择，含理由与备选；没有以“以后再决定”保留基础架构空白。
其中运行准入失败明确归于 held/not_ready，后续需要技术条件改变与验收，而非用户现在补充描述。

[data-model](data-model.md) 定义配置/资源、依赖身份、实例/部署/活动、模块准入、
调查观察、状态栏与退役/证据关系；没有把概念实体全部变成新文件或数据库。
四份契约固定 CLI、副作用、配置恢复、依赖激活、发现范围、协作/状态及退役证据。
[quickstart](quickstart.md) 区分当前可做检查、未来实现后的重建及单独授权原生步骤。

### 实施顺序与阶段退出

| 阶段 | 单一写入职责与交付 | 进入下一阶段的条件 |
| --- | --- | --- |
| P1 清单与共同基线 | 文件/动态入口/消费者清单；DSH/OMP/Pi 差异矩阵；现有保护测试 | 每个删除候选有归属；公共改变可定位到场景 |
| P2 公共中性接缝 | 公共配置/依赖检查/生命周期原语；保留薄适配；同配方多主会话归属 | 受影响 DSH/OMP 隔离回归，冲突/失败/unknown 无弱化；运行登记/退出与排他维护竞争验证 |
| P3 官方 Pi 与 Base | 先退出四旧 profile 及默认/绑定引用，同批建立最小有效 Pi catalog，再收紧 schema、增加新两档和完整资源；官方 npm 后端、完整锁、稳定实例及 CLI | 全 catalog 加载与旧 ID 拒绝通过，DSH/OMP 不受影响；隔离契约通过；原生授权后单独证明 Base 能力；两个路径干净重建 |
| P4 旧集成退役 | 清除旧 SDK 主路径、任务/委托/监督链、剩余插件/锁/测试及引用，复核 P3 已完成的旧 profile 退出 | 新组合不依赖旧链；公共消费者无未决；退役后新锁有效；用户状态保留 |
| P5 Pro 与状态栏 | 候选公开接口复核、强制边界与十类信息场景 | 未达条件不加载、不标完成；可与 Base 阶段交付并行推进 |
| P6 按需模块与正式收口 | 逐类准入、组合/平台证据、正式文档、临时资料退出 | 选中能力完整证据；范围内已知失败修复或明确接受；最终发布门禁 |

P1 的完整清单先于删除。公共加载器会校验全部 profile，不能等 P4 才退出含旧字段的配方：
T025 先处理四旧 profile、`agents/pi/agent.toml` 的旧默认和 `bindings.toml` 的旧 owner，
将 Pi registry 同步切到无旧执行引用的最小有效集合；T026 再新增两档，T027 完整承接资源。
此处只改变仓库有效来源，不触碰旧实例、活动归属或用户 home；DSH/OMP 和公共模型来源保留并重验。
新 `recipe_digest` 只绑定实际依赖输入，具体集合见 data-model §3；不相关旧链删除不得作废新锁。
P4 清理后显式核验锁身份及旧链缺席重建；实际依赖输入变化时先重锁、重审、重验再完成阶段。
P4 可以随消费者解除分批推进，不必先复刻旧功能。
P5 当前的委派与 Powerline 无合格默认候选：后续任务必须包含准入检查与清晰停止条件，
不得自行改成编写新调度器、通用沙箱或完整 footer 平台。
Base 可阶段性交付，但 Pro、信息对齐或其他必达项未闭合时，整个 feature 不得完成/归档。

每批修改由单一责任者写共享文件，事务/锁/恢复/失败顺序的改变升级主代理决策，
子代理只能执行已决定的有界任务；最终审查在稳定写入结束后进行。

### 需求与设计映射

| 需求 | 主设计产物 | 验收出口 |
| --- | --- | --- |
| FR-001、FR-017–018 | retirement-and-evidence | 清单全覆盖、新链无旧依赖、状态不丢失；SC-001/008 |
| FR-002–003、FR-008–016 | common-management、data-model | 三种工具共同七类场景、双路径重建；SC-002/003/008 |
| FR-004–007 | pi-runtime-and-modules | Base 独立、共用来源、简单任务无额外流程；SC-003/004 |
| FR-019–022 | collaboration-and-status §4–5 | 十类口径、三种宽度、未知及差异接受；SC-005 |
| FR-023–026 | collaboration-and-status §1–3 | 六类协作及边界场景，含多主会话独立计数；未满足则 held；SC-006/009 |
| FR-027–031 | pi-runtime-and-modules、research | 逐个模块六类场景；长命令不冒充恢复；SC-007/009 |
| FR-032–034 | retirement-and-evidence、quickstart | 证据分层、平台范围、临时资料清理；SC-009/010 |

### 本轮验证记录

本轮只验证文档结构、链接、模板替换、来源记录及稳定文件范围，不验证运行功能。
检查命令为已准备仓库 Python 的 stdin 静态脚本、`bash -n`（仅语法）及 `git diff --check`。

| 检查 | 结果与限制 |
| --- | --- |
| 8 份新计划材料的章节、行尾、围栏、占位符与公开内容 | 通过；直接检查未跟踪文件，不只依赖 git diff |
| 本地相对链接 | 25 处可定位；不是远端链接持续可达证明 |
| quickstart shell 块 | 8 块 bash -n 通过；未执行其中命令 |
| 既有内容保护 | 宪章、spec、检查表和 8 份临时材料共 11 文件哈希未变 |
| 独立审查 | 两路 scout 审阅公共契约与上游接缝，无阻断；项目上下文边界与未跟踪文件检查说明已澄清 |
| 宿主、插件、pytest、账号、安装与部署 | 全部未执行，不能作为通过证据 |
以上为计划生成阶段的检查记录；随后 2026-10-18 两项澄清均选择 A，spec、活动模型、公共/协作契约和
本计划/研究/验证指南已同步为同配方多主会话、每主会话两调查规则，不能沿用先前静态结果代替本次受影响检查。

- 已完成：研究与 Phase 1 设计产物。
- 进行中：无实现任务；下一阶段待用户调用任务命令。
- 失败待决策：无需要人类决定的治理冲突；Pro/Powerline 已知准入失败保留在交付条件。
- 环境不足未验证：未检查出本轮文档阻断；宿主/账号/平台检查因本轮范围未执行，不记为通过或环境确实缺失。

## Complexity Tracking

没有宪章违规需要豁免，不填写例外表。共用契约不强制同锁格式或目录；
当前平台与候选的不可用状态不通过新执行平台、宿主补丁或隐式副作用解决。
