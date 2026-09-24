# Pi 迁移初始调查记录

**调查日期**：2026-09-16  
**关联规格**：[spec.md](spec.md)  
**性质**：只读来源盘点、已知断点与规划输入；未安装依赖、执行同步、启动宿主或调用模型。

**范围修订**：初次盘点遗漏了 `starter/skill/model-delegate` 及
`.model-delegate-migration-analysis.md`。以下当前文件/配置观察保留其历史事实，
所有“保留旧执行器”的初始方向被用户确认的完整替换目标覆盖，见末尾补充调查。

## 1. 来源与证据边界

- starter：`/data/1/weixiaoxian.wxx/dev_tool/starter`，HEAD 为
  `c60599df39e6350123f7fb9378cfe63dc5ed814f`。
  调查涉及的 `pi`、`templates/pi`、Pi/sync 实现及 `skill/codex-delegate` 路径没有工作区改动记录。
- 当前机器：`~/.pi/agent`。只读取配置结构、所选包与资源路径、公开包清单和非秘密开关；
  模型配置只统计结构，没有输出服务地址、模型标识和认证字段值；未读取 auth、trust 或会话正文。
- agentcfg：[适配文档](../../docs/adapters.md)、[适配器契约](../../src/agentcfg/adapter.py)、
  [依赖后端](../../src/agentcfg/backends.py)、[启动流程](../../src/agentcfg/runtime.py)、
  [环境构造](../../src/agentcfg/process.py)、[CLI](../../src/agentcfg/cli.py)、
  [实例解析](../../src/agentcfg/workspace.py)。
- 下述“当前选择”仅来自配置，“安装存在”仅来自文件；没有据此断言当前进程实际加载结果。
- starter 的只读试用与 Task Keeper 测试结果均为历史文档自述，本次未复跑，不能当作新组合验收。

| 非秘密配置快照 | SHA-256 |
|---|---|
| 当前 settings.json | `ba47f8606b7d280b23a5daee7d6131c1410af7935b8bb377b93b37e10e433238` |
| 当前 subagents.json | `b3bc64b9c41152ffc7729143dc4fcf4fd8c6b6a270ed5519e9cc5ef8c37cfd47` |
| 当前 .starter-sync-manifest.json | `d733a2a417f336c32ee980dbc9ee26f928bc8366e3b6ceeb96799f57680aec96` |

这些摘要仅用于识别此次观察，不是部署基线或完整秘密检查证明。

## 2. 影响迁移的关键事实

1. PATH 中 Pi 可执行文件解析到全局 `@earendil-works/pi-coding-agent`，包清单版本为 **0.84.4**；
   当前 home 的另一依赖树仍存在 **0.81.1**。本次只解析路径与包清单，没有运行 `pi --version`。
2. 当前设置和 starter 模板选择 **@tintinweb/pi-subagents 0.19.0**；安装目录同时存在它与旧的
   **pi-subagents 0.63.0**。存在两个包不证明已并载，必须另验实际加载来源。
3. Task Keeper 的清单和预检仍要求旧 0.63.0，加载其专用接口、事件与补丁，并核对源码身份。
   当前默认新框架与 Task Keeper 的已验证旧组合不等价。
4. 当前新框架配置关闭默认角色、嵌套、workflows、scheduling 和 worktree isolation，
   fallback 为 none，并发上限为 1；本地角色为 scout/reviewer。这是只读试用能力子集。
5. 当前选择的 6 个本地包仍通过相对路径指向 starter；home 中还有包镜像和旧资源。
   新机器不能通过仅复制 settings 获得同一能力。
6. 当前 skills 还扫描全局/项目 `.claude/skills` 及项目 `./skill`。这些发现路径带来机器与项目差异，
   必须显式界定默认集与可选外部资源，不能作为未声明前提。
7. 当前模型配置包含 14 个 provider、48 个模型条目，14 个 provider 有 apiKey 字段。
   这不证明全部可用，也不说明值是引用还是秘密；迁移不能原样复制该配置进公共来源。

新版身份交叉核对见上游固定提交的
[package.json](https://raw.githubusercontent.com/tintinweb/pi-subagents/e955e29c51b7a6cce37e1108cd2d6c57a77e151c/package.json)。
该文件声明 0.19.0 和相应 Pi peer 依赖；不据此声称是最新发布或当前发布包整体字节一致。
上游 [项目说明](https://github.com/tintinweb/pi-subagents) 使用 Agent、结果获取和 steer 等用户入口，
与旧集成的调用形态不同；本次最终选版与能力认证留给规划。

## 3. 初始资源与处置范围

以下是规格形成时的盘点，不是完整逐文件迁移 manifest。处置方向需要在规划中落实为最终清单、
目标来源、依赖身份和验收；不能把“待评估”直接标成实现完成。

| 类别 | 观察到的来源或内容 | 处置方向与连通性要求 |
|---|---|---|
| settings | starter 模板与当前设置；20 个所选包 | 转换成统一配方与机器绑定，保留禁用语义和来源优先级 |
| models/provider | 模板、Neovim provider 生成体系及本机覆盖 | 统一主模型、角色、第二视角和凭据引用；私有数据保留本地 |
| keybindings、spark | 单独模板及当前文件 | 快捷键纳入盘点；spark 有配置不代表能力已选择，需判定用途 |
| subagents | 独立模板与 subagents.json | 新框架配置与角色联动，区分普通只读和受管任务能力集 |
| AGENTS、APPEND_SYSTEM | starter 模板 | 迁移关联规则，清理过期委托调用说明 |
| 本地 skills | codex-delegate、cpp-database-kernel、neovim-plugin-development、safe-linux-scripting | 完整包及资源迁移，按用途选择，处理共享技能重复来源 |
| Task Keeper 内嵌技能 | kernel-orchestrate | 必须随任务工作流一起适配和发现 |
| 顶层角色 | scout、reviewer | 当前只读用途，不能当作 writer 已完成迁移 |
| Task Keeper 角色 | task-keeper-reader、task-keeper-reviewer、task-keeper-writer | 保留职责，改造后验证实际权限、执行与证据链 |
| Codex 角色 | 见第 6 节的 7 个角色 | 逐项保留/合并/替代，不自动假设新框架发现旧包角色 |
| 顶层扩展模板 | dirty-repo-guard、exit-command、gentle-agent-state、git-checkpoint、handoff、notify | 每项核对触发行为、外部终端依赖及与其他插件冲突 |
| 其他扩展来源 | starter 的 plan-mode 入口；当前 herdr-agent-state.ts | 单独评估来源、完整内容及外部所有权；不默认接管 herdr |
| prompts | starter 的 commit、debug、docs、explain、perf、plan、pr、refactor、review、security、test | 保留有效入口并更新委托说明；当前独有 implement 另行比较 |
| themes | Ayu Dark、Catppuccin Mocha、Dracula、Everforest Dark、Gruvbox Dark、Kanagawa Wave、Nord、One Dark、Rosé Pine、Tokyo Night、poimandres | 显式选择及原生发现；主题历史备份不迁入 |
| MCP | Pi MCP 包与关联服务配置 | 明确服务声明、启动/联网前提和实例外配置归属，不默默继承全局服务 |
| 历史与运行目录 | auth、trust、sessions、missions、recovery、intercom、缓存、日志、旧备份 | 排除公共配置迁移；保留原环境，另列新实例运行数据归属 |
| 其他遗留内容 | 当前 packages/rpiv-todo、extensions/subagent/config.json、权限配置与日志 | 核对实际用途和重复来源；不能因存在目录就当作独立已加载插件 |

### 3.1 当前选择的远程包

版本是当前观察值，不是最终目标锁。

| 包/来源 | 当前身份 | 需要闭合的用途或决定 |
|---|---|---|
| obra/superpowers | `b36e0829c6d0140e93cfef2ca599b1b07d4a7797` | 完整技能资源与显式选择，不迁入旧安装脚本的隐式副作用 |
| pi-mcp-adapter | 2.32.1 | MCP 配置、服务与凭据绑定 |
| @fission-ai/openspec | 1.11.0 | 技能/项目入口及与既有项目集成的一致性 |
| @gotgenes/pi-permission-system | 29.3.0 | 父子权限实际覆盖及与自动确认策略的一致性 |
| pi-web-access | 0.27.0 | 搜索/读取服务、凭据、网络与就绪检查 |
| pi-readseek | 0.9.16 | 读取入口与角色工具集合一致 |
| pi-slopchop | 0.10.1 | 编辑/审查入口与受管写入边界一致 |
| @tintinweb/pi-subagents | 0.19.0 | 新管理者；补齐必需 Task Keeper 集成 |
| @juicesharp/rpiv-todo | 2.9.0 | 普通 Todo 与受管任务身份、统计职责区分 |
| pi-smart-compact | 9.6.0 | 压缩恢复、附加请求与预算控制协同 |
| @rahularya01/pi-cursor | 1.4.29 | 可选账号接入及网络路径，不能复制账号状态 |
| @narumitw/pi-btw | 0.55.3 | 旁路提问与任务上下文/预算归属 |
| @aliou/pi-processes | 0.11.1 | 后台操作、子进程和停止证据 |
| @tigorhutasuhut/pi-rules | 0.6.0 | 项目规则来源、优先级和子任务传递 |

当前 home 的另一 package.json 还声明 pi-observational-memory、pi-spark，
以及不同约束的 rpiv-todo、pi-slopchop。这只是额外声明，不能据此加入默认能力集或断言正在加载。

### 3.2 六个本地包

| 包 | 当前源码版本 | 初始处置方向 |
|---|---|---|
| task-keeper | 0.1.0 | 必需改造，新子代理兼容与完整任务验收是完成门槛 |
| codex-agents | 0.1.0 | 评估角色整合；真实 Codex 执行的独有价值保留为可选能力 |
| colorful-footer | 0.1.0 | 按所选 UI 配方保留，核对状态显示与其他通知的重复 |
| loop-guard | 0.1.0 | 保留所选循环保护语义，明确与重试/恢复的控制责任 |
| openai-proxy | 0.2.0 | 将原机器代理前提改为机器配置，验证与受管请求门控的组合 |
| session-yolo | 0.1.0 | 作为显式权限策略选择，不允许解除受管任务的必需限制 |

openai-proxy 的文档描述默认使用本机 10808、可通过 PI_OPENAI_PROXY 覆盖，代理失败不直连。
这证明存在机器特定网络前提，不证明迁移应在所有机器默认启用同一地址。

## 4. starter 同步行为及目标语义

主要证据位于 starter 的 `local-plugins/ai/lua/ai/pi/`、`local-plugins/ai/lua/ai/sync/`，
以及 `scripts/ai-tools-sync.sh`、`scripts/install-pi-skills.sh`。

| 来源能力 | 观察到的行为 | 迁移要求 |
|---|---|---|
| 配置生成 | config.lua 从模板和 provider 体系生成 settings/models/spark/keybindings/auth 初始结构 | 将非秘密意图纳入 agentcfg 来源，认证状态保持原生所有权 |
| 字段策略 | settings_policy_rules.lua 对已声明字段 replace，packages 按身份替换，skills union，smartCompact 部分叶子生成，未知字段保留 | 与框架数组整体替换、机器覆盖及三方部署逐项映射，不能默默继承旧 union 语义 |
| 单独保守合并 | keybindings/spark 使用 conservative | 明确迁移时采纳哪些用户值以及后续所有权 |
| 资源同步 | resources.lua 枚举规则、技能、角色、提示、主题、本地包与 subagents 配置 | 完整资源与依赖引用可闭合，不迁入 node_modules、备份和运行缓存 |
| plan/validate/apply/sync | target.lua 配合共享同步事务、清单与诊断 | 使用统一命令职责，保留差异、幂等、冲突与恢复 |
| 缺包安装 | 历史同步流程在生成后尝试安装缺失声明包 | 迁移为明确依赖准备动作，不加入配置生成或部署副作用 |
| 迁移助手 | migration_plan / migration_execute | 提供旧新行为比较和切换方案，不运行旧助手接管真实环境 |

旧 README 对包数、角色数和整体合并策略的描述不完全对应当前目录与代码。
规划必须以冻结的来源、当前用户选择和验证证据共同确定基线。

## 5. Task Keeper 与新框架的断点

来源：starter 的 `pi/packages/task-keeper/package.json`、`scripts/prepare-subagents.mjs`、
`src/adapters/subagents.ts`、`src/adapters/capabilities.ts`、`docs/release-notes.md`，
以及 `docs/pi-subagents-trial.md`。

| 领域 | 观察到的旧依赖/限制 | 必须验证的目标结果 |
|---|---|---|
| 执行接口 | 旧包专用 preflight、agents、recovery-owner 接口及 request/response/cancel 事件 | 新管理者下角色发现、任务提交、结果关联及取消真正连通 |
| 身份校验 | 0.63.0 精确门槛、源码摘要和活动监听者身份核对 | 对新实际组合建立有效验证，不能移除校验假装兼容 |
| 请求门控 | required-tools-abort 与 recovery-owner 补丁，防未预算辅助请求 | 父子重试、辅助请求和限流恢复统一受预算及授权约束 |
| 权限/工作区 | 明确 child 工具和受管候选工作区约束 | 新框架执行者实际遵守可读写范围与工具限制 |
| 停止 | 旧集成追踪物理停止与资源状态 | 新 stop/abort 的界面状态与实际操作终止分别验证 |
| 结果/恢复 | 依赖本次运行、候选和证据关联 | GC、过期结果、空结果、resume 与 fresh restart 不误认完成或清空预算 |
| 协议/网络 | 旧发布说明仅验证特定 direct 网络组合 | 所选代理和 provider 路线单独验收，不继承旧 direct 的通过声明 |
| 启用 | 默认关闭，另需模型与项目检查绑定 | 提供完整可复现的启用流程并实际验收，不能以关闭状态交付必需用途 |

旧试用记录明确仅完成 scout/reviewer 子集，Task Keeper 和写角色尚未迁移；记录了父子权限传递、
强制终止、结果回收和恢复预算等限制。记录中的上游问题状态是历史快照，本次未宣称仍 open 或已经修复。
原 Task Keeper 历史测试数量同样不能证明新组合兼容。

## 6. Codex 相关能力的去留依据

现有 7 个角色：codex-context-builder、codex-delegate、codex-oracle、codex-planner、
codex-researcher、codex-reviewer、codex-scout。

- `codex-agents` 提供真实 codex-delegate runner 的只读工具和可选协调角色。
  普通子代理能做类似“审查”不等于调用了 Codex，因此不能按角色名称直接删除真实执行能力。
- 角色注册使用旧包的 pi.subagents 声明，校验器针对旧 subagent/task/chain 调用形态；
  现有 README 所述公开接口兼容性并不证明新框架会发现这些角色或校验它的调用。
- runner 会查找包相对技能路径、旧 starter skill 路径或全局 Pi 技能位置。
  迁移必须闭合完整 runner、脚本、外部可执行程序、凭据接入和实例状态路径。
- `skill/codex-delegate` 与 `pi/skills/codex-delegate` 的 SKILL.md、run-codex.sh 本次比较相同；
  这仅验证两个入口文件，不是整包相同。应选择唯一维护来源并验证全部引用。
- 最终逐角色决策标准：是否提供新框架/Task Keeper 没有的用户用途；能否用更少入口等价保留；
  是否增加额外模型调用、权限或依赖；是否有当前请求的终态与结果凭证。
- 初始方向：整合重复角色；保留有独有价值的真实 Codex 委托为可选集。具体保留名单由规划给出证据，
  不因本次规格创建而删除旧包、启用真实调用或新增独立 Codex 宿主适配器。

## 7. agentcfg 架构适用性初判

**结论：存在可复用的管理基础，尚不能判定无需扩展即可承载完整 Pi 能力。**
下表是代码阅读推断，不是实现设计或运行证明；FR-005 要求规划关闭阻断。

| 领域 | 当前基础 | 规划要回答的问题 |
|---|---|---|
| 配置与资源 | 分层配置、严格 schema、文件/字段所有权、完整 skills | 如何表达 Pi 角色、提示、插件专属配置及其来源一致性 |
| 依赖管理 | 公共 DependencyBackend；DSH 后端独立 | 本地/远程包、传递依赖、原生宿主和外部执行者能否完整重建 |
| 原生生成 | 声明式 Artifact 与可注册字段编码 | Pi 混合原生字段、非受管偏好与初始化内容如何划定 |
| 实例与认证 | 工具/profile 实例、秘密引用、受控 HOME/环境 | Pi、MCP、代理、Codex 等在隔离 HOME 下的资源与登录边界 |
| 启动与活动保护 | 已部署启动契约、依赖预检、活动锁 | 新子代理及外部后台工作是否延续保护，父进程退出后的归属如何证明 |
| 备份恢复 | 三方比较、pending 恢复、上一版备份 | 配置回滚与 Task Keeper 数据/候选/版本不兼容如何区分 |
| 诊断与采纳 | doctor、allowlist capture、来源定位 | 所选能力的配置、发现、登录与实际运行状态能否分别呈现 |
| CLI 与注册 | 公共命令通过 adapter/backend 分发，但注册及部分参数只接受 dsh | Pi 接入时需改变的用户支持集合以及 DSH 回归边界 |
| 跨平台 | 已有 Linux/macOS 目标与证据分层 | Task Keeper 及外部工具实际支持哪些组合；不能把 Linux 旧证据外推 |
| 控制职责 | agentcfg 管配置/依赖/部署；Task Keeper 管任务策略 | 避免把通用管理器变为另一个模型调度者，仍需满足活动与恢复契约 |

## 8. 进入规划前后的边界

本次规格已经确定用户结果与验收要求；以下技术结论属于规划交付，不是要求用户预先设计方案：

1. 固定新子代理、Pi 与 Task Keeper 的目标组合，并给出每个必需旧契约的适配及证据路径。
2. 冻结资源与能力清单，补足实际加载观察，完成每个 Codex 角色及可选包的最终处置。
3. 给出框架适用性决定、需要扩展的边界、单一控制责任与 DSH 兼容方案。
4. 定义支持矩阵、新机器构建、权限/预算/停止负向场景及授权分层验收。
5. 实现与验收前，不改动 starter 或真实 Pi 环境，不把本调查标记为迁移完成。

## 9. model-delegate 补充调查与用户确认

用户确认迁移后放弃codex-delegate，在本次迁移中完善model-delegate并完成全部适配，
七个独立Codex角色退出注册，保留已同意的用途模板整合。新执行入口及替换验收为必需交付。

补查来源为starter的 `skill/model-delegate/` 与 `.model-delegate-migration-analysis.md`。
这些源码此前不在Pi四个顶层技能清单内，不能因此忽略其架构目标。

| 核对项 | 当前源码事实 | 目标处置 |
|---|---|---|
| 多backend | backends/pi.sh、codex.sh真实存在，Codex调用真实CLI | 作为统一执行基础，保留两backend |
| 基本控制 | run-model.sh含start/status/cancel/resume/probe及--observe | 保留并适配实例/监督/精确模型路由 |
| 写入 | codex backend明确supports_write=false | 补齐显式授权与隔离worktree写入；Pi不支持时明确拒绝 |
| 长任务 | 当前主入口没有detach/poll/wait完整协议 | 吸收ready/unknown、cursor观察、等待与取消终止证明 |
| 上下文/反馈 | 有memory注入；历史路线图另列结构化context/feedback迁移 | 统一关联、裁剪及证据状态，不把历史建议当已实现 |
| 批量 | 有独立run-model-fanout.sh，技能又强调上层并行 | 改为上层manager的批次客户端，避免双队列/重试责任 |
| Pi旧插件 | codex-agents仍硬连run-codex.sh与旧凭证 | 替换为model_delegate工具桥、统一receipt-v2及调用方适配 |
| 旧组件 | 两份codex-delegate技能和七角色仍在源环境 | 新发布全部退出，旧机器不删除，历史用途与来源可追溯 |

历史路线图明确提出统一入口、补齐差距和codex-delegate降级；用户此次进一步明确最终交付放弃旧组件。
不采纳旧文档中放宽错误/安全处理的建议作为事实；必要功能以本次严格契约和负向测试为准。
本次未运行backend或测试；测试文件存在和历史通过数量不作为本次替换成功证据。
