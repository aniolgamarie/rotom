# 能力基线、处置与冲突矩阵

**Decision date**: 2026-09-16。以下是最终规划处置；实施还必须生成逐文件 manifest 和实际加载证据。
源版本来自 [调查记录](../source-inventory.md)，新派生包必须保留原始身份、许可和变更说明。

## 1. 配方

| 配方 | 引擎 | 固定用途与默认能力 |
|---|---|---|
| pi-default | Node 24.14.0 | ordinary 主会话、唯一新管理者、scout/reviewer、model-delegate的Pi后端、权限、Todo、规则、循环保护、普通 UI；Task Keeper 不启用 |
| pi-managed | Node 24.14.0 | 必需 Task Keeper 与桥接、三个受管角色、kernel-orchestrate、受控工具、候选/检查/审查/第二视角/预算/恢复/一次定时 |
| pi-codex | Node 24.14.0 | 普通核心的model-delegate另启用Codex backend；不加入 Task Keeper 自动恢复/第二视角 |
| pi-cursor | Bun 1.4.0 | 普通核心加 Cursor 账号；不选择 Task Keeper，单独证明普通加载与账号能力 |

各配方是完整 TOML，不新增隐式 profile 继承语义。外部能力通过完整 plugins/resources 选择数组启用。
普通核心在 Bun 下仍须独立验收；不能复用 Node passed 直接认证 Cursor 配方。
完整交付同时要求 pi-default 与已绑定 pi-managed；只读/Bun 子集不抵扣受管任务要求。

## 2. 本地六包

| 源包 | 处置 | 目标与加载边界 |
|---|---|---|
| task-keeper 0.1.0 | adapt → 0.2.0-agentcfg.1 | agents/pi/packages/task-keeper；managed 必需，移除旧框架、全量迁移角色/技能/依赖和测试来源 |
| codex-agents 0.1.0 | replace | agents/pi/packages/model-delegate新工具桥；吸收请求/凭证校验，旧包和七角色不发布 |
| colorful-footer 0.1.0 | keep/adapt | 同名包；展示实际统一状态，不作为授权或终止证明 |
| loop-guard 0.1.0 | keep/adapt | ordinary 父会话保留确定性重复动作熔断；managed 由 Task Keeper 消费熔断事件，不形成另一恢复者 |
| openai-proxy 0.2.0 | optional/adapt | 同名包；显式 network route，无固定10808默认；managed 只使用 transport 内组合 |
| session-yolo 0.1.0 | optional/adapt | 同名包；连接实际权限服务，缺失或无效策略拒绝，不能显示已启用却只改 Symbol |

修改后的派生包以自身变更版本与内容摘要入锁。完整 skills/scripts/resources/notices 必须可从仓库重建。

## 3. 十四个远程来源

O=普通父会话；M=受管配方；“M 关闭”表示不直接加载至工作进程，不等于删除原用途。

| 来源基线 | 处置 | 闭合条件 |
|---|---|---|
| obra/superpowers @ b36e0829c6d0140e93cfef2ca599b1b07d4a7797 | optional 技能集 | 完整归档与引用；显式选择，适配过期工具名，不隐式注册调度者 |
| pi-mcp-adapter 2.32.1 | optional O | 包内技能+显式服务/凭据/外部工作登记；M 工作进程不暴露 MCP |
| @fission-ai/openspec 1.11.0 | optional | 锁定 CLI 与资料投影，显式 project init；没有 pi manifest 不能仅靠 packages 声明验收 |
| @gotgenes/pi-permission-system 29.3.0 | O 核心，适配桥 | 明确父策略服务，接入 tintinweb；M 使用规范化策略与受控工具，不能假设原包自动支持新框架 |
| pi-web-access 0.27.0 | optional O | 外部服务、凭据、网络就绪明确；M 原生工具关闭 |
| pi-readseek 0.9.16 | O 保留 | 默认 overrideTools=[]；它含 edit/write/rename，不能当只读插件；锁平台原生包；M 使用 tk 工具 |
| pi-slopchop 0.10.1 | O 保留 | /slopchop /diff 的人工可视审阅；外部编辑必须受活动范围保护，M 执行期间禁止 |
| @tintinweb/pi-subagents 0.19.0 | adapt → 0.19.0-agentcfg.1 | 唯一管理者，受管 executor 补丁与完整源码身份 |
| @juicesharp/rpiv-todo 2.9.0 | O 保留 | Todo 独立统计；M 不以 Todo 代替受管任务/预算 |
| pi-smart-compact 9.6.0 | O 保留、单一压缩者 | O 关闭重叠原生自动压缩；M 使用 Task Keeper 受准入的压缩路径，不加载此独立调度扩展 |
| @rahularya01/pi-cursor 1.4.29 | optional pi-cursor | Bun-only，独立账号与引擎；Node managed 选择时配置错误2 |
| @narumitw/pi-btw 0.55.3 | optional O | M 活动时禁止独立旁路请求；同任务问答必须走 Task Keeper gate |
| @aliou/pi-processes 0.11.1 | optional O、适配 supervisor | 三扩展+技能完整；所有启动登记，M writer 不可调用自由进程工具 |
| @tigorhutasuhut/pi-rules 0.6.0 | O 显式项目规则 | 指定来源根与优先级；M 从固定规则投影加载，不能自动扩大权限 |

可选插件一经选择就要验收完整调用链。修改原包适配接口时生成派生 archive，不在安装后的全局包目录打补丁。

## 4. 七个 Codex 角色收敛

| 旧角色 | 唯一入口的模式/preset | 保留用途 |
|---|---|---|
| codex-context-builder | investigate/context | 背景、需求、开放问题 |
| codex-delegate | investigate/general 或 review/general | 显式真实执行与凭证 |
| codex-oracle | review/challenge | 挑战假设及交叉验证 |
| codex-planner | investigate/plan | 分解、依赖、风险与回退 |
| codex-researcher | investigate/research | 有来源的调查；联网前提另验 |
| codex-reviewer | review/review | 当前 diff、文件位置、严重级别 |
| codex-scout | investigate/scout | 简短文件、模式与陷阱 |

不再注册七个同质Pi协调子代理；表内用途均使用 `model_delegate(backend=codex, mode, preset)`，
通用只读Pi委托使用同一工具的Pi backend。model-delegate完整技能补齐显式write/resume/observe/control，
写入仅限独立授权的工作区。迁移后无codex_delegate别名、旧skill或run-codex.sh回退。
代码使用部署manifest唯一的run-model.sh引用，不猜测starter或全局HOME。

model-delegate的run-model.sh、backend/lib、schemas、references/examples及测试完整迁移；
旧执行器需要保留的校验、进度、上下文/反馈语义吸收到新协议及backend，保留来源说明，
不把旧可执行包整体带入发布。进程启动/停止接入统一supervisor，Bash/jq/Git明确为工具前提。
可选 Codex 发行包由 sync 准备，CODEX_HOME 是实例私人目录；原代理地址改为机器 network route。
登录通过该实例的显式 Codex 登录入口，不能借用现有用户账号。
receipt 必须匹配本次 request/cwd/model/终态/非空 final/进程停止；requested_model 与 observed_model 分开。

## 5. 资源与遗留内容

| 资源 | 处置 |
|---|---|
| cpp-database-kernel、neovim-plugin-development、safe-linux-scripting | 完整保留于 shared/skills，显式按领域选择，不把 Neovim 当 Pi 运行前提 |
| model-delegate skill（补查来源） | 必需完善并迁入shared/skills/model-delegate；Pi/Codex backend与完整控制协议 |
| codex-delegate skill（两个旧副本） | 被model-delegate替换，退出新发布与发现；旧机器内容不删除 |
| kernel-orchestrate | Task Keeper 包随附，更新新契约并验发现 |
| scout/reviewer + 三个 task-keeper 角色 | 生成独立资源，普通与受管权限不得互换 |
| 11 个 starter prompts + 当前 implement | 全部保留；implement 普通父实施→父检查→fresh reviewer，managed 路由 kernel_task |
| 11 个主题 | 全部收录，默认 Everforest Dark；备份不迁入 |
| AGENTS/APPEND_SYSTEM/keybindings/subagents | 转换为配方资源，全部委托引用同步新入口 |
| dirty-repo-guard、exit-command | Git 状态经显式只读绑定、同一 manager/supervisor 和 worktree 租约；失败/截断/终止未知取消切换，非 Git 与干净分开；exit 不绕开任务活动监督 |
| gentle-agent-state、notify | 可选终端能力，明确 agent-report.sh 外部依赖或完整受管脚本；只父会话通知 |
| git-checkpoint | 普通显式可选；不是配置备份，M 工作区活动期间禁用 stash/restore |
| handoff | O 保留；M 活动期间拒绝自由换会话与辅助摘要，任务交接走受管状态/预算 |
| plan-mode | 排除默认 legacy；原同步测试本就不复制，规划用途由 /plan 保留 |
| spark / pi-observational-memory | 非现用选择，不进入活动默认，保留迁移记录；不丢弃旧 home |
| herdr-agent-state | 外部所有权，不接管；只允许显式登记外部集成 |
| 旧 0.63、重复 rpiv、旧 subagent config、备份/缓存/账号 | 排除新加载和公共迁移，旧环境保留 |

## 6. 单一控制矩阵

| 控制领域 | ordinary 权威 | managed 权威 |
|---|---|---|
| 子执行队列与生命周期 | 新AgentManager；model-delegate经其external executor提交单run | 同一新AgentManager的managed executor；未经认证的外部委托拒绝 |
| 任务计划、恢复、一次调度 | 主会话；框架 workflows/scheduling 默认关 | Task Keeper |
| 请求预算与模型切换 | 明确用户/所选插件策略，不承诺 TK 硬预算 | Task Keeper transport gate，所有尝试入同账本 |
| 权限 | 权限服务+显式 session override | 编译策略交集+受控工具；YOLO 不得放宽 |
| 压缩 | 所选 smart-compact；其他自动压缩关 | Task Keeper 可计量路径 |
| 循环保护 | loop-guard | Task Keeper 接收 latch，保留原预算 |
| 网络 | 显式 route 与代理插件 | 受控 transport 内 route；禁止事后覆盖 |
| 工作区备份/检查 | 显式 checkpoint、人工 diff | Task Keeper 候选与 supervisor checks |
| 运行资源/部署锁 | agentcfg supervisor | 同一 supervisor |

选择互斥组合返回配置错误2；缺乏契约实现的已选组合返回依赖/能力错误5，不能静默禁用一半后声称成功。

### git-checkpoint 实施处置

使用实例私有、按会话与权限范围绑定的代码快照替换内存stash引用；增加/checkpoint与/checkpoint-restore。
捕获与恢复接同一manager/supervisor/worktree租约，恢复前预览、原状态备份、逐文件CAS和权限检查。
不运行Git filter，不改Git分支/索引，不宣称Git stash格式/合并兼容。包含授权范围内的普通未跟踪文件；秘密排除、大小与数量限制明确，超限失败不截断。
该变化解决agent_end清空恢复点的问题；UI分叉事件的实际原生时序仍须验收。
详情见[代码恢复点指南](../../../docs/pi-checkpoints.md)。
