# Implementation Plan: Pi 能力统一与跨机器迁移

**Branch**: `main`（实际 Git 分支；Spec Kit 返回的特性标识为 `001-unify-pi-capabilities`） | **Date**: 2026-09-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-unify-pi-capabilities/spec.md`

## Summary

通过 PiAdapter 和独立 PiBackend 接入现有 agentcfg 配置、锁、部署及运行流程。
将当前机器与 starter 的资源归一为完整、可追溯的能力基线，提供 pi-default、pi-managed，
以及可选 pi-codex/pi-cursor 配方。旧 home 与账号保留，迁移采用新隔离实例。

Task Keeper 改造为使用唯一新版 AgentManager 的受管进程执行接口，固定 Pi 0.84.4 与
带审阅补丁的新子代理 0.19.0 来源；预算在实际请求发送前约束，权限、候选、结果与终止均可核验。
完善 model-delegate 作为 Pi/Codex 统一委托入口，吸收必要写入、进度、控制和上下文/反馈能力；
Codex 七个协调角色合并为用途模板，迁移后彻底退出 codex-delegate 运行依赖。Cursor 独立使用 Bun 普通配方。
2026-09-24 用户修订本 spec 的交付范围：完成全部软件迁移、Linux x86_64 四配方 mock/native 与各双路径冷重建；其他三平台实机和真实服务 live 转出，未来另行验证。原平台实现保留，未验证组合不声明通过。见 [范围修订](scope-change-20260924.md)。

2026-09-16 的规划阶段完成了 Phase 0 研究和 Phase 1 设计，当时未执行安装或账号调用。
当前 spec 已按上述修订范围完成；实际完成项、候选身份和运行证据见 [tasks.md](tasks.md)、
[实施记录](implementation-progress.md)及[关闭报告](../../docs/acceptance/pi-spec-closure-20260924/README.md)。本计划的历史设计检查不代表其他平台或账号验收通过。

## Technical Context

**Language/Version**: Python 3.11+ 管理器；TypeScript Pi 插件；Node 24.14.0 / npm 11.19.1；
可选 Cursor 引擎 Bun 1.4.0；macOS 进程身份 helper 使用小型 C 程序与系统 SDK 构建。

**Primary Dependencies**: 保留 PyYAML/jsonschema/Jinja2/pytest；Pi 0.84.4；
@tintinweb/pi-subagents 0.19.0 来源生成 0.19.0-agentcfg.1 vendor；
Task Keeper 0.2.0-agentcfg.1；model-delegate 完整技能与 Pi 工具桥；可选 Codex CLI 0.154.0。
14 个远程包、6 个本地包的保留/改造/可选身份详见 [能力契约](contracts/capability-matrix.md)。

**Storage**: TOML 公共/机器来源；JSON/Markdown 原生产物；既有部署 current/previous/pending；
独立 Pi 锁和分配方运行收据；私人持久 lease/evidence；Task Keeper 原生任务库独立于配置回滚。

**Testing**: 默认 pytest + 隔离 Node 单元测试，宿主/模型/子进程替身；
真实 Pi/Codex 原生加载和账号调用分别独立授权。新增故障注入、请求门控、权限及跨进程终止用例；
完整 DSH 回归。旧 Task Keeper 含真实 Pi 的测试入口拆分后才能接入默认测试。

**Target Platform**: Linux x86_64 为本 spec 验收目标；Linux arm64、macOS arm64/x86_64 保留设计与实现，实机验收已转出本 spec；
Linux bwrap/namespace、macOS libproc helper/sandbox-exec 分别认证。
平台、引擎、插件、协议的通过级别单独发布，未验证组合不声明支持；原生 Windows 不纳入。

**Project Type**: 仓库内 Python CLI、声明式配置、Pi 原生插件与受管执行监督。

**Performance Goals**: 重复部署零实际变更/零备份轮换；相同幂等键零重复派发；
超过配置额度的模型请求零次；每个支持平台至少两种 HOME/仓库路径冷构建。
执行 deadline/请求/轮次由用户绑定，不额外引入无依据的响应时间指标。

**Constraints**: 严格未知字段、无秘密投影、运行不下载、不执行未声明扩展、无双管理者；
子执行未确认终止持续阻止变更；默认测试不运行第三方宿主；不改变 DSH 现有语义与工具链范围。

**Scale/Scope**: 46 条 FR、12 条 SC；4 配方、20 个初始包来源、原4顶层技能加补查的model-delegate来源，
替换后交付4个顶层技能（model-delegate及3个领域技能）、
3 个 Task Keeper 角色+内嵌技能、2 个普通角色、12 提示和11主题。
受管初始并发上限为2，每任务writer上限1、并行reader上限1，禁止嵌套；Task Keeper 一次性调度。

## Constitution Check

*GATE: Phase 0 初检和 Phase 1 设计后复检；以下通过仅代表设计遵循规则。*

| 原则/约束 | 初检 | 设计后复检与证据 |
|---|---|---|
| I. 公共核心与真实适配 | 通过 | Pi 独立 schema/backend；公共 roles 语义不变；桥接是实际待实现接口，不以空实现冒充支持 |
| II. 秘密与所有权 | 通过 | 原生叶子投影前 guard；实例 HOME；RUNTIME 不备份；旧 home 不接管；见 CLI/数据模型 |
| III. 可恢复部署 | 通过 | 复用三方/current/previous/pending；supervisor+持久 lease 补齐子活动；未知终止不放行 |
| IV. 显式副作用/完整锁 | 通过 | PiLock/切片/归档/构建规则；run loader 禁下载；生成、安装、部署和登录分离 |
| V. 隔离测试/真实证据 | 通过 | 默认假宿主；native/live 显式授权；平台与能力逐项证据，不继承旧通过 |
| 技术栈与退出码 | 通过 | Python公共管理保留，Pi插件不强制改写；新增C仅为macOS系统身份适配；0/2/3/4/5/6保持 |
| 完整迁移/DSH兼容 | 通过 | 必需managed闭环；旧Codex用途映射；DSH全量回归；SC全部映射到验证入口 |

无宪章例外。未实现/未认证是实施门槛，不视为设计已通过运行验证。
分析U1/U2/U3/I1已由控制恢复、跨实例工作区租约、固定权限语言及条件验收契约修订；
这只代表文档问题有明确处理方案，新增实现与场景仍须实际验证。
宪章的 RATIFICATION_DATE 是既存维护者记录待确认，不属于本特性技术未决项。

## Project Structure

### Documentation (this feature)

```text
specs/001-unify-pi-capabilities/
├── spec.md
├── source-inventory.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── validation-matrix.md
├── contracts/
│   ├── cli-and-configuration.md
│   ├── runtime-and-dependencies.md
│   ├── managed-execution.md
│   ├── capability-matrix.md
│   ├── model-delegation.md
│   ├── recovery-and-workspaces.md
│   ├── permission-policy.md
│   └── evidence-and-release.md
└── checklists/requirements.md
```

`tasks.md` 已由 `$speckit-tasks` 生成并随实施维护；当前有效任务和转出记录以该文件为准。

### Source Code (repository root)

以下是规划时确定并已用于实施的主要目录位置；具体实现与拆分见仓库和任务清单：

```text
src/agentcfg/
├── pi.py                       # PiAdapter，与dsh.py对等
├── pi_dependencies.py          # PiBackend、独立锁/运行收据
├── pi_inventory.py             # 只读迁移盘点和提案
├── activity.py                 # 公共活动记录与平台监督协调
├── workspace_leases.py         # worktree身份锚定的跨实例写入仲裁
├── native_projection.py        # 声明式原生投影保护
└── existing modules            # schema/config/cli/runtime/deployment最小兼容扩展
agents/pi/
├── agent.toml                  # 默认与Pi资源目录
├── bindings.toml
├── plugins.toml
├── content.toml                # 仅已有公共规则/技能种类
├── schemas/
├── templates/
├── roles/
├── prompts/
├── themes/
├── extensions/
├── runtime/                    # launcher、封闭loader、supervisor客户端、平台helper源码
└── packages/                   # task-keeper、model-delegate桥等本地源码与新管理者补丁输入
shared/skills/                  # model-delegate和3个领域技能；不交付codex-delegate
profiles/                       # pi-default/pi-managed/pi-codex/pi-cursor.toml
locks/pi/                       # 独立manifest、每配方完整npm锁、vendor、平台/配方切片
schemas/pi-lock.schema.json
examples/                       # Pi机器覆盖、受管绑定和服务虚构示例
scripts/verify-pi.py             # mock/native/live显式分层验证入口
scripts/build-pi-vendor.py       # 可重建vendor与许可/输入摘要
scripts/pi-supervisor.py        # 实例生命周期与Linux/macOS执行后端
scripts/pi-supervisor-macos.c   # macOS身份helper，独立输入与构建收据
scripts/pi-project-check        # 沙箱内执行已声明foreground检查的薄入口
tests/test_pi_*.py              # 隔离回归与契约验证
docs/pi.md                     # 安装/维护/验收边界
```

**Structure Decision**: 保持单仓库公共管理器。新原生细节属于 agents/pi 与 PiAdapter；
通用 activity/projection 扩展只携带中性声明和状态。Task Keeper 内部继续管理任务账本，
不把模型调度逻辑引入公共 CLI。插件原有内部风格可保留，新增 Python 遵循双引号/2空格/中文注释。

## Complexity Tracking

无宪章违规项。必要复杂性来自三处有证据的缺口：DSH 专属依赖策略不能直接复用；
进程内子会话不能提供受管终止证据；原生凭据字符串不能进入普通文件投影。
选择独立Pi后端、受管executor补丁、投影guard分别解决；不新增第二个通用管理器或模型调度服务。

交叉审查已补齐：只对选中profile检查必需机器绑定；每切片独立npm完整锁；
保存历史runtime组合身份；凭据引用按各版本allowlist验证；补全外部资源/策略/工具catalog；
Task Keeper预分配attempt与明确owner。以上均纳入后续契约回归。

## Phase 0 — Research Decisions

[research.md](research.md) 的 R1—R14 已完成选择和替代方案比较，覆盖框架、版本、桥接、
预算/权限、平台监督、配置投影、完整依赖、能力整合、迁移诊断、测试与可选运行时。
研究问题均已作出设计选择；源码构建和运行证明由实施阶段完成。

## Phase 1 — Design & Contracts

- [data-model.md](data-model.md)：资源/能力、角色/机器、锁/收据、lease、task/attempt/budget、证据与一次调度。
- [CLI与配置](contracts/cli-and-configuration.md)：新增只读迁移参数与Pi选择，严格schema和原生所有权。
- [运行与依赖](contracts/runtime-and-dependencies.md)：锁切片、构建、封闭发现、监督和平台接口。
- [受管执行](contracts/managed-execution.md)：新管理者桥接、请求准入、结果接受和停止/恢复。
- [能力矩阵](contracts/capability-matrix.md)、[统一模型委托](contracts/model-delegation.md)：逐项最终处置和独有用途。
- [控制恢复与工作区](contracts/recovery-and-workspaces.md)：显式停止恢复与跨profile写入互斥。
- [权限规则](contracts/permission-policy.md)：closed字段、匹配、父规则转换及负向样例。
- [证据与交付](contracts/evidence-and-release.md)：持续报告、固定范围和条件批准。
- [quickstart.md](quickstart.md)、[validation-matrix.md](validation-matrix.md)：可执行验证步骤、授权层级与FR/SC覆盖。

## Implementation Ordering Input

实施依赖顺序如下，第8步按2026-09-24范围修订更新：

1. 冻结来源/资源manifest和派生包输入，加入严格schema及契约替身。
2. 实现投影保护、PiAdapter与只读盘点；复用部署并补CLI支持集合。
3. 实现PiBackend、完整锁/构建/封闭loader；在干净环境证明无隐式依赖。
4. 实现实例supervisor和两平台后端，先证明活动/未知状态与安全停止。
5. 实现唯一新管理者的managed桥接，再迁移Task Keeper请求门控、角色、证据与恢复。
6. 完善model-delegate只读/显式写入、后台/增量控制、上下文/反馈与两backend；
   将Pi工具桥、七角色用途、所有调用方及锁/技能发现切到新入口，完成旧组件完全缺席验收。
7. 闭合普通资源、权限/通知/压缩控制及可选Codex/Cursor服务配方。
8. 生成验收scope与支持矩阵，冻结锁并执行默认回归和Linux x86_64四配方原生/双路径冷构建；
   最终以当前软件scope全部81项匹配通过完成T112。其他三平台及live已移至[独立后续清单](../../docs/follow-ups/pi-platform-and-live-validation.md)，不阻塞本spec完成。

原计划曾要求四平台和已选live共同闭合；该完成门槛已被用户明确修订。未来live执行仍需对应native证据与独立授权，未验证状态不因转出而改变。

每一步以契约与负向验证作为依赖门槛，不允许绕过Task Keeper必需能力完成标记。

## Analysis Remediation Record

| Finding | 设计修订 | 实施/验证任务 |
|---|---|---|
| U1 | reconcile仍只读；显式recover_stop绑定短期计划、旧控制者死亡证明与仅停止授权 | T036、T039—T043、T054、T057 |
| U2 | workspace_key锚定worktree专属git-dir身份；共享持久写租约，不依赖实例HOME | T036、T039—T043、T049、T063、T068、T072、T075、T086 |
| U3 | Permission Policy v1 closed字段、exact/subtree、deny优先、父规则转换和样例 | T007、T038、T049、T084 |
| I1 | 固定scope，持续report-only与独立check-release；可选账号按选择判适用 | T004、T089—T092、T098、T101—T102、T110—T112 |

本次修订不改变46条FR、12项SC和112项任务总数；末阶段任务重新编号，使持续报告先于构建/验收，
所有引用同步更新。这段记录描述当时的设计修订；当前执行状态以实施记录为准，不能以文档修订代替验收通过。

### 自动复核追加修订

- I2：Permission Policy按ordinary/managed/delegate-readonly/delegate-write区分根与授权；
  普通父会话可编辑明确授权的业务worktree，不套用候选专属源checkout禁写。覆盖T007/T038/T049/T084。
- U4：ExecutionLease先持久化allocating及完整目标，再写共享预留，提交starting后才可spawn；
  abort_allocation恢复有完整未启动证明的预留，日志缺失或提交后未知仍阻塞。覆盖T036/T039/T040/T054/T072。

这些修订不削弱权限或未知终止保护；原生实现与验收的当前结果单独记录。

### Codex 工具执行接法（按重新评估继续实施，2026-09-17）

用户要求继续后，采用[评估结论](codex-execution-reassessment.md)：普通Codex委托使用官方CLI和原生工具，
agentcfg管理冻结运行授权、原生沙箱范围、写租约与物理生命周期；Pi受控工具/Task Keeper仍逐动作复核。
请求/收据新增execution_boundary和execution_policy_digest；Codex配置显式native_execution.allow_shell与tool_network=none。
原生结果验证冻结授权与候选最终快照，不强制MCP变更日志。MCP原型退出默认控制入口与运行包必需闭包。
取消到物理终止的窗口保持写锁；不可表达父侧限制仍失败。系统/企业配置与原生沙箱平台证明继续作为未完成项，不能因路线调整删减验收。

2026-09-18 用户选择保留官方 CLI：系统配置或企业账号无法核验时拒绝执行，接受这些环境的兼容性缺口。采用 `official-cli-restricted-v1` 准入并纳入执行策略身份；实现与限制见 [配置准入决定](codex-config-admission.md)。不维护 Codex 分支，不恢复 MCP 默认工具桥。稳定受信机器和账号是运行前提，不声称独立预检提供原子保证。平台与全部已选服务的验收范围不删除。


### Linux Codex 生命周期实现补充（2026-09-20）

官方 CLI 保持原生工具入口。Linux 整次委托使用固定 bwrap 的独立 PID 命名空间，
先验证 PID 1 和包装进程的出生身份，再通过第一方门控入口放行；内核范围覆盖独立组和重新托管的后代。
旧进程组记录的 unknown/escaped 不重解释。详细协议见 [运行与依赖契约](contracts/runtime-and-dependencies.md)。
原生通过仍按具体候选、平台和场景记录，不能由该实现选择推定其他平台已验证。
