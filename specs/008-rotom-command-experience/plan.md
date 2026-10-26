# Implementation Plan: Rotom 命令与会话体验

**2026-10-26 分支复审补验**：Pi 保护失败后的执行阻断已修复，覆盖打印、JSON、RPC 与 TUI；官方运行包分项与受影响隔离回归通过。候选尚未合入 main，合入须人工批准；完整官方 CLI 维护链路等未验证范围仍单独保留。详见[分支复审](branch-review.md)。

**Branch**: `feat/tool-maintenance-workflows-20261026` | **Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/008-rotom-command-experience/spec.md`

**Status**: 候选实现、分组回归及稳定差异审查已完成；基于 main `45953f0`，保留在分支 `feat/tool-maintenance-workflows-20261026`，尚未合入 main。合入须另经人工批准。官方 Pi/OMP TUI/PTY、隔离回归及受影响复验见[验收记录](tool-workflow-validation.md)。

历史任务完成记录 86/117 保留；本轮 T118–T124 已完成，当前 93/125，T125 的 main 人工整合仍待批准。原 pane 与自动继续仍按独立条件能力处理。

Spec Kit 的逻辑功能标签为 `008-rotom-command-experience`，不表示 Git 分支发生切换。
历史设计源码基线 `17bbacd6`；原实施工作树基于 `39a9389` 并完整保留，随后曾从 main `109e2e7` 建立独立承接工作树。已验收范围后来从新主线重放整合；成功人工交接增量基于 main `b55c9b9`，当前只读 status CLI 增量基于 main `18c342f`，各阶段候选与证据见 main-review，不把旧基线当作当前入口。
历史承接记录保留了 `design/rotom-cli-entry` 及原候选，要求实施前核对共享绑定、Pi 启动契约与文件所有权。
当时本地 `main` 为 `109e2e7`，纳入 OMP `18.12.6`，相对该次 fetch 的 `origin/main` `467d5cd`
领先 9 个提交、落后 0；承接工作树为 `.cache/worktrees/rotom-command-experience-main-20261023`，直接继承当时主线锁。
这些值属于历史快照；T001 与后续 main-review 分别记录各轮基线、文件所有权和实际验收，没有重写旧锁或修改上游。
精确源码事实、范围与依赖调整见 [主线核对与规划修订](main-review.md)。

## Summary

本轮采用按工具的阶段编排，替代旧全工具 Domain 许可前提。Pi 公开扩展负责合作 session 租约及切换，OMP 原生竞争首次写入可能分叉；Pi/OMP 使用 HandoffResumeBackend，DSH 原 Host 不变。停止集合不扩大，并发新运行阻挡普通 setup；原操作结果保留，零继续。原 pane/自动继续继续作为独立条件任务。

增加以项目名关联的统一门面，复用 agentcfg、termcfg 和 work 的业务执行路径。
第一阶段交付三工具短启动、显式偏好、所有叶子缺参交互、help、补全及受管 zsh 入口。
第二阶段尽早交付 DSH 的真实 session ID/当前终端官方恢复交接；之后在完整退出证明基础上交付停止维护。
2026-10-24 按用户决定，缺少严格初始加载回执只限制“已恢复”和自动继续，不再阻塞安全的官方交接。
已派发但加载未确认时展示待确认并交给用户操作，不自动重试；原 pane 与自动继续各自准入。
交付仍须真实验证目标、目录、历史和 writer 冲突行为，不能用静态命令或始终拒绝代替；
不修改上游，也不将提交 issue 或等待上游增强纳入当前交付依赖。

历史 main 停止准入仅覆盖完整锁 `e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d` 的 Linux managed DSH 新运行，
使用启动时原 host 句柄及已登记 endpoint。非交互实际请求须匹配当前 plan-id；交互批准在锁外展示完整计划。
先保存人工恢复快照与 fence，再单次投递；默认 30 秒、可选 1–300 秒，整组共用绝对截止点。
未知或到期返回 4，保留 batch，不重发、不强杀、不自动恢复或继续。
status 只读；cancel 只处理未投递项或已确证停止项的收尾对账。
默认普通 runtime 三实例验收中，首轮只停前二且第三项原身份/owner/channel/共享租约保护不变，
独立新 plan 再停第三项，最终三项 exit 0/idle_confirmed/termios 与原租约恢复、0 输入、源码未变。
这份历史证据不单独准入 setup/maintenance execute/restore、Pi/OMP 的停止与恢复、其它平台、旧 run 或 force；
也不替代 T054 已独立准入的当前终端恢复。[原生证据](main-review.md#62-dsh-默认入口的精确停止验收)。

Linux OMP 的现存 setup batch 另有只读 status CLI：须显式 `--profile` 且公开 profile 声明的工具为 `omp`，
沿所选 local/机器路径读取，不扫描历史或其它机器；无显式 profile 保持 DSH 原路由。
对这些旧 Domain 批次只开放 status，不创建新 workflow、完成交接或重发操作；不限制新 workflow 的独立分阶段接口。
JSON 保留原 `operation_result`，查询 `exit_code` 单列；`protected` 仅指本批资源意图，
manual 不表示会话已恢复，continue 为 `not_sent`。成功但未交接仍为 4；completed 且当前目标/资源核验通过为 0，
unknown/pending 为 4，原非零操作码保留；初始未派发即取消且正常观察为 0 仅说明取消，异常观察仍为 4。
CLI 稳定代码回归 336 passed，fixture 拼写纠正后的新 suite 21 passed，重叠不累加；
不冒充 backend 或宿主原生验收。该历史阶段 T077/T078 仅部分推进，任务记录为 86/117。

技术取舍及证据见 [research.md](research.md)。[数据模型](data-model.md) 定义严格持久格式；
[CLI](contracts/cli.md)、[入口部署](contracts/entry-deployment.md)、
[生命周期](contracts/lifecycle.md) 约束用户接口与恢复边界；
[quickstart](quickstart.md) 区分现有回归、未来隔离套件和独立授权的真实验收。

## Technical Context

**Language/Version**: Python 3.11+；仓库自有 DSH 公开插件使用现有 Node.js/ESM 工具链。
最低版本、实际验收环境及锁定运行包身份分别记录，不固定本机补丁版本。
安装入口有不加载业务的 sh/隔离标准库 JSON 定位层，随后 exec 准备 venv；不以系统解释器回退运行项目。

**Primary Dependencies**: argparse/dataclasses/pathlib 等标准库，以及已有 PyYAML、jsonschema、
Jinja2、tomlkit 0.15.2；pytest 为隔离验证。fzf 可选；不新增 TUI 框架、后台服务或未锁依赖。
具体宿主与插件只消费现有完整锁；必要新增独立公开插件同步完整来源/锁，不修改宿主。

**Storage**: 私人 TOML 偏好；termcfg catalog v2、state/journal v3 的受限生成产物；
既有实例 run-owners 扩展 v2 与同 agent state root 内有限的资源意图/批次记录。
所有私人目录/文件为 0700/0600；不建立另一份原生会话正文数据库。

**Testing**: 临时 HOME/XDG、阻断网络、假子进程/事件/时间、文件哨兵和故障注入。
既有隔离验收保留原候选和结果；本轮在可信属主环境运行临时 HOME 与 fake 进程回归，初次沙箱环境拒绝单列记录。真实 Agent、zsh、Herdr、信号及 PTY 需独立授权；
未授权、未实现、环境不足、失败和通过分开记录。2026-10-24 已获用户授权并执行 T039：Linux 下四次入口状态转换、两处目录的十六次入口调用和十二个真实 zsh/PTY Tab 场景全部通过；仅证明该范围，不类推 Agent/Herdr/恢复或日常目录权限。

**Target Platform**: 延续既有各工具与终端的支持矩阵；Linux 为新进程身份/控制原型首目标。
新门面不能把 Linux 证据类推到 macOS；没有稳定身份/释放证明的平台关闭控制能力，
不影响已支持的静态 help、纯配置操作或符合原有支持范围的启动。

**Project Type**: 已有 Python 管理器的 CLI 门面、受管 shell 资源与薄后端适配。

**Performance Goals**: 固定合成环境每场景 30 次冷进程：静态 help p95 ≤ 1 秒，
动态补全 p95 ≤ 1 秒，1,000 条记录的只读列表 p95 ≤ 2 秒。
这是待测目标，不是已通过结果；原生启动、模型、网络、安装耗时分开归因。
停止/ready 默认 30 秒、可选 1–300 秒，整组共享每阶段绝对单调截止时间。

只读实例列表使用独立观察上下文：受保护地读取全部公开 profile 源及同一份机器配置快照，严格验证来源结构、
全部本地 profile 选项覆盖、引用范围和机器路径，再以保存的物理 binding 读取 owner。
查询不解析 provider/model 目录、不物化模型路线、不校验启动就绪或渲染候选；因此无关运行目录的错误
不会阻止观察已有实例。未知字段仍在全部已读来源中拒绝，profile 工具变更仍拒绝跨范围，
损坏/缺失归属仍保留未知，不产生控制资格。启动、部署及维护继续使用原有完整配置解析。

**Constraints**: 未改动的官方 Agent/公开接口；严格未知字段、所有权和秘密边界；
既有 native argv/输出/退出码/路径兼容；原有物理租约为最终门禁。
源 help 无业务读取；安装定位仅最小非秘密绑定；补全不启动程序或写缓存。

**Scale/Scope**: 单个本地所有者，已选机器内的受管资源和明确接受的有限 run 集合。
工程负载包含空配置、32 个机器名/100 个公开配方、1,000 条单机器记录；
不是全机扫描、多用户服务、生产容量上限或跨机器远程控制。

## Constitution Check

本轮以工作树宪章 3.0.0 修订文本评估；其合入与临时同步报告清理仍走独立治理流程。
原始批准日期未知不在本功能编造。下表的 PASS 指设计符合，不能替代行为或原生证据。

| 原则 | Phase 0 前 | Phase 1 后 | 约束及验证位置 |
| --- | --- | --- | --- |
| I 公共核心/原生适配 | PASS | PASS | 门面不复制运行/部署，scope 与后端差异分离；R1/R5 |
| II 秘密/所有权 | PASS | PASS | 最小引用、私人权限、不导出会话正文/环境；数据模型 |
| III 确定部署/恢复 | PASS | PASS | 精确生成字节、v2/v3 兼容、独立停止批准、真实资源门禁；部署/生命周期契约 |
| IV 显式副作用/完整依赖 | PASS | PASS | run 只用部署契约、sync 不改锁、只读查询无隐式执行；R4/R5 |
| V 隔离测试/证据 | PASS | PASS | 默认 fake，真实停止/终端另授权；quickstart |
| VI 不修改上游 | PASS | PASS | 仅公开配置/插件/API/CLI；缺能力拒绝或重新评估；R6–R10 |
| VII 公开隐私/身份 | PASS | PASS | 文档虚构数据/相对链接；本轮不提交；后续提交前核对批准身份 |
| VIII 工作树/稳定差异 | PASS | PASS | 独立分支，保留其它工作；候选/主线/锁摘要写私人任务记录 |
| IX 社区/版本证据 | PASS | PASS | 固定来源证据不冒充原生通过，无模型/版本未知值伪造 |
| X 兼容/升级 | PASS | PASS | 待更新不强制换版，旧 journal 受支持，活动实例不自动停止 |
| XI 终端优先 | PASS | PASS | work 固定绑定与普通终端保留，focus 不输入，OMP type 独立 |
| XII 入口/交互 | PASS | PASS | 注册表双向覆盖、三流门控、递归/秘密输入与批准不遗漏 |
| XIII 身份/会话恢复 | PASS | PASS | writer/退出证明、批次未知、位置与继续分开，能力未证实不开放 |

没有需要豁免的宪章违反项。不能满足 P-SESSION/P-EXIT 等后续能力门槛时，
停止该交付路径并带证据重新决策；不能借本表 PASS 解锁未验证的控制动作。

## Project Structure

### Documentation (this feature)

```text
specs/008-rotom-command-experience/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/requirements.md
└── contracts/
    ├── cli.md
    ├── entry-deployment.md
    └── lifecycle.md
```

`tasks.md` 已生成并随实施维护；当前维护 125 项任务（原 117 项与新增 T118–T125）；仅按实际实现及验收更新勾选，规划变化本身不结项。

### Source Code (repository root)

以下为目标责任范围；文件实际创建与验收状态以 tasks/私人阶段记录为准，不能据此声明全部可用：

```text
rotom
src/rotom/
  cli.py                 # 注册、解析、类型化分发及菜单入口
  context.py             # Scope、输入策略与显式调用上下文
  preferences.py         # 私人偏好与安全保存
  completion.py          # 受限 NUL 候选
  entry.py               # 受管入口协议的静态定位逻辑
src/agentcfg/
  cli.py, commands.py     # 可选上下文及共用业务操作接缝
  runtime.py             # 保留单次运行契约，接入观察/恢复
  run_owners.py           # v1 兼容与 v2 最小登记
  lifecycle.py            # 保留物理租约与准入顺序
  sessions.py             # 新：会话引用/后端恢复契约
  maintenance.py          # 新：有限计划、意图与批次编排
src/termcfg/
  cli.py, work.py, work_ui.py, work_shell.py
  catalog.py, preview.py, transaction.py
schemas/rotom/            # 新：偏好/入口及生命周期的严格格式
schemas/termcfg/          # catalog/state/journal 兼容扩展
terminals/zsh/           # launcher/补全及 fpath 接入资源
agents/dsh/packages/     # 如公开原型通过，新增独立最小观察插件
tests/test_rotom_*.py    # 部分已创建、部分待建；实际状态见 quickstart.md
```

**Structure Decision**: 保持单仓库及现有包/配置路径。门面只负责目标、交互和展示；
agentcfg 仍拥有 Agent 运行/部署，termcfg 仍拥有终端文件事务与 work 绑定。
新 modules 是责任边界，不要求为每个类型拆文件；新增测试文件名采用 quickstart 中的约定。
必要重构只抽取 parser/输入/共用核心操作接缝，不重写原 backend 或复制事务框架。

### 实施顺序与单一写入责任

| 交付包 | 文件责任边界 | 前置与验收门槛 |
| --- | --- | --- |
| A 注册与上下文 | rotom、src/rotom/cli/context，三个旧 CLI 接缝由同一写入者负责 | parser leaf 双向覆盖、native tail、静态 help、旧入口差异 |
| B 偏好与短启动 | preferences/scope 分发和严格 schema | A；三工具、显式覆盖、有效旧部署待更新、失效默认 |
| C 全部输入门控 | agent 输入模块、term/work_ui 与递归调用 | A；每叶子 TTY×缺参/确认/取消/隐藏输入/失败后续；无 fzf |
| D help/补全 | 注册元数据、completion、zsh _rotom | A–C；无配置 help、允许候选来源、NUL 和零副作用 |
| E 受管入口 | term catalog/preview/transaction、schema、shell 资源 | A/D 与 P-ENTRY；恢复前不切换日常绑定；主代理审查日志顺序 |
| F 阶段一收口 | 用户文档、兼容矩阵与稳定差异 | A–E；原生终端验收按授权单列 |
| S 日常恢复/实例 | sessions、runtime、run_owners、DSH 薄插件 | T044/T045 与 US5 保持现有范围；T042 核实安全官方交接，T117 补待确认/零输入契约；加载回执与自动继续分别准入，不要求上游新增接口 |
| M 停止维护 | tool_maintenance、精确 stop、共用 setup 与工具恢复接缝 | T118–T125；三工具 stop_only、先保存清单，同 ID stop 快照，关本次 fence 后普通 setup 最新独立批准/原全门禁，逐项当前终端恢复；OMP 保留 Domain，DSH/Pi 不强套 Domain；未知不重试 |
| P 原位置 | 可选管理容器、work 新版本接缝 | P-PANE；旧实例首次采用、管理代码兼容、单次 run 租约分离 |
| I 可选继续 | 已准入后端输入接缝 | P-INPUT；确切会话与接收结果，不阻塞普通恢复 |

A–D 可先行，E 事务扩展独立验收；S 的原型尽早并行，不能等全部维护完成才调查 session。
P-PANE 可提前比较公开重启与驻留，但未通过时 M 仅使用已接受的新位置或人工路径。
主代理负责事务、锁顺序、日志和恢复的关键判断；共享文件只给一个写入者，
另一任务可只读搜集证据。所有写入结束后才对稳定差异进行最终审阅。

### 验证与交付门槛

- 先执行 quickstart 中实际存在的离线回归，再对新增风险创建有意义的 test_rotom 套件。
  不使用不存在的测试文件或本轮文档检查冒充行为通过。
- E 覆盖 payload/journal/rename/fsync 的每个中断点、旧 v2 恢复、跨 worktree、漂移和源消失。
- S/M 覆盖已派发但加载待确认、迟到失败/失联、零自动输入/重试，以及 emitter 代际/封口、PID 复用、幸存后代、外部新运行、协调锁顺序和部分失败。
- P/I 覆盖终端复用、普通实例采用、管理程序变化、重复/未知请求、错误输入目标及无确认不重发。
- 原生运行、真实信号与 PTY 使用独立明确授权和私人证据；不扩大默认测试权限。
- S 结项要求真实官方恢复交接及状态边界通过；未实现的按钮或静态“不支持”不能替代。
  初始加载机器回执可保持未支持，不得将人工观察写成自动确认；P/I 按各自门槛记录。
- 合并前重新盘点最新 main、候选/锁身份、所有未跟踪文件、作者与历史、实际日常 launcher
  和完整机器配置兼容；准备好干净提交后按授权整合，验证后才考虑工作树清理。

## Complexity Tracking

无宪章例外。新增的有限协调/批次记录只解决本功能的精确停止与恢复，不能扩成任务调度或后台服务。
catalog/state 格式升级源于生成绑定的可恢复要求；保留旧读取路径比复制一个安装器更小。
运行、停止和会话恢复各有一个共享执行契约；不为 TUI、CLI 或维护编排再复制数据库和执行器。

### 历史实施阶段

以下截至旧 DSH/OMP 内部增量的原始阶段记录保留；其中“未准入”“后续接线”等是当时状态，当前公开流程由上方 Summary 与 tool-workflows.md 取代。

以下保留先后顺序和当时的未接线结论；当前精确 DSH stop_only 范围以上文及 main-review 第 62 节为准，不能将旧阶段限制当作当前入口状态。

实施顺序补充（2026-10-23，恢复边界按 2026-10-24 用户决定更新）：T043/T044 的运行归属与完整释放观察不依赖宿主会话 API，
可在 T040/T041 后推进，并使 US5 只读列表独立交付；T045 此时仅提供类型与保存记录的受限视图。
T042 继续核实官方显式恢复、实际配置归属及 writer 防护，T046–T054 按这些独立前提推进；
不以严格初始加载回执缺失阻塞官方交接，也不从启动参数推造实际 session/host。
生产登记仍须验证 argv/stdio/退出码、租约寿命和 unknown 阻塞。

实施状态补充：T043 严格 v1/v2 记录层已完成隔离验收；T044 的通用观察及 DSH/Pi 最小登记已正式通过隔离验收，
T045 提供历史会话视图，US5 接入只读实例列表。Linux 以外的 DSH 保留普通启动租约并明示未登记可靠身份，
Pi 保留原有的可靠身份前置，不能借新路径开放未支持平台。
OMP 同一缓存运行包可由多个实例共享，单实例 owner 检查无法覆盖其他实例的 unknown；
候选已将同域 instance/HOME/runtime 的完整引用接入全新 Linux setup/apply/run 和只读查询。
旧资源首次采用、部分现场、非 Linux 和自动维护不因此准入；T065/T066 的资源协调及普通接线已独立验收，
T062/T063 的完整维护集成仍未完成；已验收的基础范围已合入 main，历史候选与后续内部维护增量分别见 main-review。
该条件独立于已收口的 T044/T045/US5，不把只读查询或新资源候选验收扩成全局历史证明。
保留原有 OMP cache-only sync 和物理/包租约语义，不提前增加全局扫描或凭单个包 EX 声称完整释放。
TUI 精确 commit 已取得；显式非空目标进入严格 resume，但同进程已有 agent 会走独立复用分支。
Core writer 覆盖加载的源码链已取得，真实竞争与已发布运行包仍未验证。公开 scene 的前台元数据、
新 run 私有 IPC 和启动环境准备已有隔离原型，不能证明原初始化提交或实际 native HOME 归属。
`agent/created` 与 `whenIdle()` 不能排除后续初始化失败；自有插件提前 resume 又会改变 TUI 的
preset/route/setup 和 owner。此缺口现在只限制加载自动确认及自动继续：
T042 收口现有官方交接能力与限制，T117 为缺回执时继续交接且零输入增加隔离契约，
T046–T054 实现并验收该边界。[公开启动契约研究](../../docs/rotom-dsh-startup-contract.md)
保留为可选增强，不等待上游支持。独立共享资源协调与停止工作的原有保护不变。

共享资源基础拆分为可独立验收的 T112：先取得经 fd 核实的物理 ResourceKey，并在 OMP 原有包锁内
拒绝命名租约已被替换的情况。它不依赖 T052 的恢复协调器或停止操作测试，解决基础层的反向依赖。
T065/T066 要求可信协调域、首次采纳拒绝和完整引用范围，以及 reservation/intent 的原子状态转换，
才能启用 OMP v2；不将物理身份加固误报为跨实例 unknown 已解决。

该资源协议及普通入口接线已通过独立验收，完成依赖明确限定为基础原语和 T063 中的资源协调竞态子集。
不等待未来停止/setup/恢复编排才验收普通启动；T062/T063 的完整流程仍是 T069 后续控制的前置。
旧资源不补造历史，缺完整引用继续拒绝。ResourceIntent 沿用 Domain 的严格数据/CAS，不新增等价类型。

T113 单独实现新 runtime 的内部协调原型：严格 codec、绑定物理根的域、同一租约 inode 的不可变锚点、
启动前持久引用与意图 CAS。原型没有公开首次采用命令，其初版普通 OMP 入口遇到新锚点一律拒绝，
直到 T066 将登记与维护事务接通；空 ledger 也不是执行许可。已有空租约和既存运行包不能被新域采用，
包 EX 不清 unknown，不提供超时清理、释放、修复或自动对账入口。T065 仍负责实例/原生目录与完整 owner
引用范围。T113 后续修正在发布租约之前保存 cache 内的独立 runtime 声明，并持久化其目录/父目录链；
创建租约前和取得物理锁后检查声明，覆盖单独租约清空、删除重建及整个 leases 目录替换。
T066 现已接通已登记新 runtime 的独立同步；有 scope 时按实例 SH → 包 EX → 短协调事务验证，
无 scope 时只打开现存包租约 EX。确认目标包完整归属及空闲后进入原修复/激活，包 EX 持续到结束。
独立 sync 没有初始化、首次采用或临时许可；无合作上下文的 shared run 仍拒绝新声明。
全新 Linux 普通 setup/apply/run 另经新资源准备、原计划复核和完整合作链接通，不能用同步守卫代替。
旧资源明确拒绝无证据的首次自动采用，不能从空文件推断历史空白。声明与锚点全部被外部清除/回滚、
旧 checkout 不合作及完整历史覆盖不在这项修复的保证范围；自动维护与原生控制仍未准入。


T114 从完整合作准入中抽出可独立验证的同 ID owner 关联。保留已持久化 reservation，再持原有实例、
状态和包 SH；短协调锁内以非阻塞方式进入 owner 元数据锁，不等待物理锁或宿主。关联采用两次
提交：owner_pending 与完整引用先持久化；随后不可覆盖写入 owner，复核后保存 owner_attached。
owner 锁保持到对应协调提交结束；派发前再次核对双向摘要与命名物理对象，再保存 dispatched。
任何中断保留阻塞，没有自动完成、取消或清理接口；普通 register_v2 仍不能自填协调引用。
本阶段每次 owner 关联只选择一个 runtime，不检查同一 manager 跨 reservation 的唯一性，保留 control=null；目录键只是当次物理观察。
T114 本身不证明 instance/native-home 的持久域锚点或完整历史；候选合作入口须另消费后续 scope 和释放协议。


T115 增加当前 manager 的退出记账闭环，复用有限的 ReleaseObservation，不重新设计宿主退出证明。
现有 Linux DescendantScope 以 subreaper 的内核孩子关系覆盖本 manager 派生的后代；要求无既存孩子、
单线程、默认 SIGCHLD 与观察范围有效，不跟踪任意外部服务。观察时 manager 的出生身份须仍匹配。
内部 finish_owner 仅接受同一存活 manager 的完整同 run 观察，以及派发时保存的完整关联；缺一拒绝。
release_pending 先持久化末态摘要和固定观察时间，再写 owner idle 并同步，最后释放本 run 的预留。
中断后 reconcile_owner_release 仍需同 manager 提供完整观察，只接受原 active 或严格匹配的末态 idle。
manager 丢失、任一 unknown 或单边旧 finish 都不通过该入口；新进程不能凭持久收据接管观察能力。
已完成预留保留为 released，既有意图和其它运行不受清除；该释放原语不提供维护许可。

T115 的最终协调 rename 已完成、目录 fsync 失败时，调用报错但 released 可能已可见；owner 和完整
退出事实在此之前已经同步，不能据错误结果反向推断停止未发生。同一存活 manager 可重新完整观察，
对严格匹配的 released/idle 执行同步确认：不重写 owner、时间或收据，不重发动作，只重核并同步两侧
元数据、推进协调 revision。若掉电后协调记录回到 pending，仍按原 pending 门槛处理；manager 丢失后
不能仅凭收据补造新观察。确认过程中发现 owner 回退为 active/unknown 或任何对象不匹配均拒绝。


T116 将新实例的两个资源加入同一协调域，不采用任何已有实例（包括空目录）。内部调用方显式提供
可信 Domain；记录不携带可追踪的域路径。候选入口从已验证机器 state_root/lifecycle 选择域，
不能把每个 profile 的 state_root 当作全局域。登记先在实例父目录的 .rotom-scope-claims 中
不可覆盖保存声明，并同步父目录链；然后创建实例锁、隔离 HOME、owner 和三份一致锚点，最后在
域内登记 instance/native-home 两条物理资源。中断保留声明和已创建内容，不自动重试、采用或清理。
声明缺失时，实例锚点、HOME 锚点或非空实例锁仍阻止旧格式回落；所有证据被外部一起清除不在保证内。

内部 owner 在已声明实例上要求完整集合：恰好一个 runtime，加本实例的 instance/native-home。
attach、dispatch 与退出记账均重新检查声明、锚点、所有权收据、目录/fd 身份与 ready 域记录。
旧未采用实例的 runtime-only 内部测试路径保留，但不因此开放旧资源采用。候选 OMP lifecycle/preflight
对完整 scope 使用现有实例 EX 与元数据门禁，setup 仅登记全新资源；cache-only 不创建实例或状态。
新域登记不证明旧历史、会话 writer 排他或旧 unknown 完整退出；T065/T066 继续承担这些准入条件。

只读查询按物理 SH → 短协调 SH → owner 非阻塞锁读取 scope/双向元数据。全局根/cache 来自同一次
严格机器配置，不从 claim/owner 追踪路径；查询不取包锁或读原生正文，不证明当前包可用或全局空闲。
孤立预留、部分提交、缺记录和活动意图显示 pending/unknown；完整 owner 的 unknown 原样保留。
缺实例但仍有声明不是未准备，旧 OMP 继续显示登记未支持。包已删除仍可展示历史，run 仍拒绝。

DSH 早期只读预览使用独立 StopPlan v2：Registry coordinator 绑定机器/profile、物理根和完整 owner 摘要，
本地资源不附加虚构 Domain/代际；旧 OMP v1 格式保持。正式门面已连接 dry-run 和 setup plan，
按实际 run 归属选择单一实例，当前固定披露未知覆盖、未准入控制及阻断原因。它不创建审阅、批次、
快照或意图，普通停止和维护执行仍未准入。

实施顺序补充（2026-10-24）：T067 的只读 StopPlan 核心与 T068 的严格 Batch codec 提前独立实施，
消费显式、最小、已规范化的快照，只产生数据和摘要；不采集现场资源、不派发、不开 CLI，
不把数据形状校验当现场证明。恢复能力未知时仅保存人工方案或阻断选择，不能伪造可恢复。
T069 及后续接受/持久化/控制仍依赖 T066 与 T062/T063，真实恢复与原生门槛不变。
该顺序调整不减少主交付要求，也不使 T042 或未来恢复测试自动完成。

T069 的恢复清单编码和持久发布接缝也可先按内部元数据事务单独验证：只支持明确 manual 恢复方案，
完整保存所选 v2 RunRecord，并与 StopPlan 的记录/部署摘要、scope、manager/host、资源域相互绑定。
保存的会话和目录仍是历史观察；缺 session 或 session cwd 保留未知，不用启动 cwd 补成会话目录。
当前持久化只接完整的新 OMP 协调元数据：所有资源 generation 使用采集时的全域 revision，
短协调锁内重新核对 revision、资源闭包、全部引用和所选双向 owner 摘要。
在已存在的域根内先不可覆盖写入 `stop-acceptance-<batch_id>.json`、同步并重核命名根/内容，
再原子提交带 `acceptance_digest` 的 ResourceIntent。文件发布后提交失败会留下待核验清单；
回包丢失可能留下完整意图。两者均不自动重放、删除或重建，查询不推进状态。
此接缝返回 None，不持有/重建 host 句柄，不提供停止、维护、恢复许可；真实现场采集和批准接线仍待完成。

实际部署/owner/资源核验可在同一内部边界继续组合：可信调用方先按原顺序持有实例、状态、包 SH，
在协调锁外核对当前部署代际、工作区绑定、运行包标识、native HOME、无待恢复部署，
并复用正常 run 的受保护文件/凭据引用投影；不读取调用者环境或解析凭据。然后进入短协调事务，以非阻塞方式固定所选 Registry，核验当前完整记录及同 scope 的全部关联。
owner 锁必须跨过清单发布与协调表提交，不能核验后先释放再落盘；借入的物理 fd 由调用方保留。
这只解决接受时的现场记录/物理关联一致性，不证明 host 存活、部署内容、独立批准或停止通道，
也不把保存结果升级为可反序列化的控制许可。实际停止派发仍需再次核验且遵守原任务门槛。

停止专属 StopReview 可先独立验收：可信调用方在取锁前展示并批准精确 scope/operation/run 集合与
规范计划，返回精确 True 才创建绑定 plan/batch/创建进程的内存对象；不从摘要或 JSON 推导批准。
reviewed live 入口在所有现场检查后、首次清单写入前以非阻塞内存锁一次消费；发布、提交、
响应或控制中断均不恢复已消费对象。它不证明用户交互已发生、不替代 host/控制现场检查，
也不能作为 setup 的写入批准。旧元数据接受入口和已存 intent 均不能补造此审阅。

人工继续采用 T101 的独立分支：显式根 `--interactive` 提供可跳过的文本预览/确认，正文仅留在本次
必要展示，不传后端或持久化。T096/T102 分开验收人工零发送与输入模型，自动派发未实施/未准入。
停止/ready 阶段的纯单调预算可提前独立验证：一个阶段、整个明确集合共用固定 deadline，不逐实例
重置；预算本身不持锁、写状态或派发动作。内部释放等待循环已接入共享预算和可信观察/记录回调，
先保存同身份完整后代事实，后计入 confirmed；回包丢失不重试，超期保留事实并返回 4。
这不是 manager 的 SH 释放证明，观察来源/时效、有效意图及原物理 EX 门禁仍由调用方核实。
T072 的生产控制/Batch 事实及 ready 等待接线仍依赖 T071。

T070 的启动现场身份观察可独立于停止执行器先行：只在 DSH 候选恢复已有 Popen 分支捕获
单线程 Linux 直接子进程的 pidfd/PPID/出生身份，在 owner 非阻塞锁内绑定本次记录，
control 保持 null；无捕获/登记证据仍运行原 child，不强杀、不重试。本地受管普通 DSH run
与候选恢复共用该生命周期；普通等待异常返回冲突，不继承 subprocess.run 的自动 kill。
SSH、未登记、显式启动 hook 保留原路，OMP 的合作登记需要单独事务，不在此接缝更新。
T073 的 setup 核心等价抽取可在 T008 后独立完成：原 CLI 保留原预览/批准/进度/结果展示，
内部核心按既有顺序执行并返回原 apply 结果与退出码；不外套物理 EX，不引入 Permit 或维护入口。
停止通道的候选实现选择单线程私人文件 inbox：manager 保留原启动句柄，在有界 wait 片段间
处理请求，避免线程破坏现有身份/后代观察前提。请求限定 graceful-stop，绑定精确 run、
manager/host 出生身份、request/batch/plan 和同 boot 单调期限；无 argv/shell/文本/force 字段。
私人根及调用来源、现行批准/意图、期限和 host 仍须接收端核验，codec 不替代这些证明。
逐 run 派发记账可独立实现：发送前不可覆盖 intent，同 run 不因换 request ID 重开，
成功返回后才记录 sent；结果不明保留 unknown。记账对象只在当前 manager 内一次消费，
旧文件不重建对象，目录被替换不能写回。sent 不等于退出或资源释放。
单线程等待循环已独立实现：只有 child.wait 的 TimeoutExpired 后才处理一次 service；
service 普通失败后永久停止该服务，仅同 child 一次普通 wait。wait 错误/控制中断透传，
无 kill/restart；service 必须有界，请求 deadline 由 service 保证，不限制普通 TUI 总时长。
该循环未接默认启动路径。
候选请求处理器另绑定原 SpawnedHost、明确 run 与派发目录；可信 verify 回调负责来源、
停止批准、有效批次/资源现场，不能从 JSON 推导。先核验身份/同 boot 期限，再将本处理器
标为已尝试并持久保存意图，随后重核批准/句柄/期限，最后调用注入通道一次。
回调仅精确 None 表示发送调用成功；结果落盘失败不重试。发送后过期仍保留已发生事实，
外层阶段独立判断超时。过期请求也保留时钟观察，不能用后续倒退时钟重新取得预算。
该处理器本身通过注入通道发送。候选 StopService 已将新私人 inbox、处理器和原 pidfd 单次
SIGTERM 组合，并在共享 DSH 启动函数提供显式可信工厂接缝；默认启动不提供工厂，control
仍为空。只有 host 绑定、启动记账和派发通知全部成功后才创建服务；构造或处理普通失败后
等待同一 child，退出时先撤销服务再关闭句柄。完成/失败均不能再次消费请求，原文件保留。
批准/活动意图/资源核验仍须生产工厂提供；组合测试中的批准与内核均为 fake。

DSH 的正式锁拓扑是实例目录 SH 与状态文件 SH，运行包和 native HOME 都位于实例目录内；
同锁 identity 的不同实例并不共享物理运行包。额外 package SH 仅是扩展接缝的测试注入。
现有 live 接受事务明确仅支持 OMP，不能直接用于 DSH。DSH 后续接线须以同一物理实例的
完整 owner 集合及目录包含关系建立资源闭包：stop_only 保留未选运行，setup 要求所有影响
资源的运行释放；所选目标旧 unknown/缺关联继续拒绝，外部覆盖未知仅保留披露并阻断 setup，
不单独阻断 DSH 精确 stop_only。需覆盖 run、sync、apply
的原物理门禁以及接受后新运行竞争，不能通过放宽 OMP 判断或假 verifier 开放控制。

DSH 当前部署核验单独提供只读接缝：借入上述两把 SH 的 fd，核对实例标记、状态锁、
部署绑定/代际、无 pending、精确基础 argv 与字面量 HOME/DSH_HOME，以及实例内运行包、
native HOME、user HOME 的物理身份。复用既有运行 guards，另核对已保存 launcher 的 FILE
baseline；不比较当前仓库锁/模板，不解析秘密。它证明当前保存部署的包含关系，不证明
运行包完整性、历史实际追加参数、全体外部 writer 或完整合作覆盖。

停止意图可先作为阻断原语验收：在同一 Registry owner 锁内，对完整非空 records 做前后 CAS，
不可覆盖发布兄弟文件并同步祖先、读回。上层须先按原顺序取得实例/状态 SH 并保持至事务结束，
否则不能排除先已进入的 EX 维护。首次发布前的短回调只允许不取得 Domain、Registry/owner 或物理锁的
可信内存消费与独立元数据保存，不做交互、宿主操作或调用另一套 live 事务。
任意存在的意图均阻断新登记及普通维护；已有退出/unknown 记录仍能更新。该文件不提供
停止或维护许可，没有自动删除、超时撤销或重放；正式批次、恢复清单、完整资源覆盖、取消/
对账和控制接线仍由 T069 及后续任务完成，默认运行不创建意图。

人工恢复参考已进一步组合为快照先行的内部事务。DSH 现有记录没有已证明的协调域，
使用小型 run-stop-snapshot 封套复用完整 RunRecord，保存显式所选运行并绑定完整记录摘要；
不伪造 OMP Domain，也不生成已接受 Batch。owner 锁内验证实际完整集合、物理 Registry 和
所选记录后，先不可覆盖写入/同步/读回快照，再发布含 snapshot_digest 的 v2 fence，并重核关联。
同批已有快照在消费回调前拒绝；写入中断留下历史孤儿，不自动删除、重放或生成批准。
独立快照可读但不表示已接受，v2 fence 读取则须快照关联有效；未知 session/cwd 原样保留。
`dsh_stop_scope.save_manual_snapshot` 统一这些内部步骤：先验证借入 fd 并冻结输入，在 owner
锁前及锁内复核所有所选记录的当前部署布局，再执行快照先行发布；原两把 SH 由调用方维持。
该入口不创建生产批准或停止服务，完整覆盖与控制准入仍须后续接线。
当前 manager 可通过只读 `inspect_stop_request` 在同一 owner 锁内核对请求、v2 意图、
所选人工快照和当前目标记录，再复核部署及文件身份。返回历史记录副本，不授予控制；
其它所选项已退出不影响该单项检查，完整覆盖、独立批准、endpoint、期限与原 host 仍另核验。
新增 `save_reviewed_snapshot` 在同一事务中保存嵌入完整 DSH plan 的 v2 快照；原 v1 API 保持。
仅接受 ready 计划与既有 StopReview，核实当前布局和完整 owner 后，在首次快照写入前消费审阅。
首写或后续 fence 发布失败均不恢复审阅，不从历史文件重建它。现场覆盖、host 与工具准入仍独立核验；
默认 CLI 只读预览，不调用该内部保存器。完整资源覆盖、批次状态和生产控制仍未完成。

T070 已有候选服务生命周期组合，生产批准/意图接线与原生准入未完成，整体不结项。T073 的核心抽取及普通 CLI 已独立验收；
T074 同时保留 T072/T073 依赖，后续控制/维护 runner 仍须原门槛。

关键发布的持久化边界包括新目录的祖先项：停止意图、inbox endpoint/request、恢复请求、
协调域初始化与 owner 登记均须在文件发布后同步父目录至根，再复核当前文件和命名根身份，
才能返回可供后续派发的对象。同步异常保留部分事实；OMP owner_pending 不因失败取消或重试。
通用 Tree 的创建/写入语义不扩大为完整持久化承诺，既有资源声明的祖先同步继续保留。

原启动句柄内提供显式单次 SIGTERM 候选：先消费、复核原 snapshot，固定调用原 pidfd；
不按 PID 重开，不降级或升级。复制不复制发送资格，控制中断/未知不恢复资格。该原语
不提供批准或意图，默认启动只观察，不自动调用；需生产工厂、工具原生语义和完整释放验收。
