# Rotom 会话能力与证据

状态：实施中的能力核验。公开接口证据、隔离机制验证和真实宿主验收分别记录；静态帮助或拒绝分支不代表恢复已实现。

## 当前决策：官方恢复交接与加载确认分开

2026-10-24 按用户确定的范围，首版真实派发官方显式 session 恢复到用户选择的终端，沿用已部署 runtime、native HOME/scope、原目录和租约。缺严格初始加载回执本身不再禁止启动，也不以新上游接口作为主交付前置；Linux 固定组合的 T053 原生交接验收和 T054 日常入口准入已完成；最新 main 整合候选的复验范围见[整合记录](../specs/008-rotom-command-experience/main-review.md#65-最新-main-的整合候选)。

分别保存并展示请求目标、启动派发、实际加载确认、继续是否发送。可证明已启动但缺可信加载结果时显示：“已发起恢复，加载待确认；请在 TUI 检查；未发送继续”。不能写 `restored`，未知不伪装 `failed`，不自动重试或超时强杀。范围、归属、cwd 或原生 writer 冲突防护不足时仍拒绝 Rotom 自动派发，提供人工操作说明；缺加载确认不放宽这些安全条件。

用户直接在官方 TUI 操作属于人工交接，人工观察与机器确认分别记录；口头确认不升级为可信加载回执或自动输入许可。自动继续默认关闭，仅在完整目标、加载、ready、writer 和接收能力另行证明后开放。查询、恢复派发、加载确认、停止、原位置与输入分别准入。

T042 调查并原型验证现有官方恢复入口、实际 HOME/scope、writer 与状态边界。T053 已完成固定 Linux 组合的真实交接、合成历史、缺失目标、活动 TUI 和外部 writer 拒绝验收，机器状态保持待确认；额外请求已通过公开 hook 定位为 TUI 自动回顾。T054 已完成精确组合接线、稳定差异审阅和普通 CLI 的独立原生复验。Core 两个内存 case 只证明缓存包初始化发布窗口，不是恢复验收。严格回执提案保留为可选历史研究，未发送、当前不计划提交，不属于交付依赖。

以下保留历史实施与研究记录；其中以严格公开回执作为整个恢复前置的表述依据旧范围，应以上述当前决策为准。

## 当前候选边界

既有当前终端维护候选的实现与分组验收保留原范围：基于 main `45953f0`，分支 `feat/tool-maintenance-workflows-20261026`；保留在任务分支，尚未合入 main；合入须另经人工批准。2026-10-27 已补齐三工具贯穿公开 CLI 的真实维护链路，并单独核验新 Pi 锁 Base/Pro，见[最新验收记录](../specs/008-rotom-command-experience/tool-workflow-validation.md)。

| 工具与版本 | 当前终端交接 | writer 与加载限制 |
| --- | --- | --- |
| DSH core 0.2.1-rc.2、TUI 0.16.1 | 原 Host 后端，固定锁公开 CLI 维护与恢复已补验 | 加载待确认、零继续；恢复可产生宿主自身辅助模型请求，详见最新记录。 |
| Pi 1.3.0 | 候选 `HandoffResumeBackend` 精确文件/原 cwd 交接 | 公开扩展 guard 只保护 Rotom 合作进程；旧 unguarded active/unknown 阻挡 claim，原生缺失文件可能产生新 ID。 |
| OMP 18.12.6 | 候选 `HandoffResumeBackend` 精确路径/原 cwd 交接 | 只读 open 不取得 writer 锁；竞争首次写入会分叉新 ID，不能承诺提前拒绝外部 writer。 |

详见[维护流程与分项证据](tool-maintenance-workflows.md)。Pi 原生 `--resume` 是 picker；明确恢复用 Rotom `resume pi --session` 完整 ID，普通 `--session` 完整 ID 转为精确路径并持租约。恢复前严格重核存在性；外部事后变化仍可使结果 unknown。OMP 固定源码 `session-manager.ts:1103–1128` 的 sibling 分叉语义已用无网络合成会话原生验证：第二次同 ID 打开成功，首次写入后新 ID，原 ID 不变；原 writer 释放后可恢复原 ID 写入。

当前恢复都区分请求、派发、实际加载与继续；请在官方 TUI 核对 ID。严格加载确认和自动继续未因此开放；原 pane/新 tab 候选已实现，但已通过最终十二组无 trace 原生验收，现仅开放六个精确 Linux managed 组合的两种位置。普通 --session 的位置恢复保持未开放。DSH 历史完整锁为 `e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d`，运行包变化不自动继承准入。

Pi 的公开 guard/helper/扩展由 `locks/pi/session-control.json` 对三个自有来源校验。辅助观察仅作 historical，不读正文；合法旧 hash 与已不存在 cwd 可保留历史线索，实际恢复仍重新检查。损坏/跨 run/host/目录/权限记录拒绝采用，观察失败不丢掉进程列表。


当前 `sessions.py` 静态交接表仅准入以下精确组合，全部为 Linux / managed / here；任一运行锁、观察来源、平台或位置变化都拒绝并需重审。条目只准入交接，`load_confirmation` 与 `automatic_continue` 均为 false。

| 工具 | 完整 runtime identity | observer identity |
| --- | --- | --- |
| DSH | `e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d` | `none` |
| Pi | `62ac8348c34339599d280df5769ab0f8383a2f48c0885d84fa16c22a40a6b558` | `e286d053f59613d94c8be14d89f3def12dafdc67ef54a9746d7d2229ce362d9a`（三来源控制锁） |
| Pi（新锁，Base/Pro 分别核验） | `a68d9dcf3346c0c6ab9bff231f85510dea2d9d25794664cd835cd476c3460587` | 同上；Base 的 footer/Cursor 顺序及 provider 选择须与锁一致，不自动改变公共默认。 |
| OMP | `490e6c90d0ef4d890bb2ab14e006dcd3a3f4d79b5e6ad0ca9fbf3e8f4ab610ab` | `none` |

## 运行归属实现进度

RunRecord 的严格 v1/v2 reader 与 v2 schema 已完成隔离验证；旧 v1 记录不自动升级，
旧 reader 遇 v2 会拒绝。旧协议的额外进程身份字段继续完整保存和比较。
同一 scope 出现 v2 后，应继续使用兼容 v1/v2 的 checkout 查询和核实；配置 rollback
不降级运行归属记录，不能删除 active/unknown 来让旧 checkout 继续操作。
`active`、`unknown`、`idle_confirmed` 与进程观察保持自洽；带最终会话确认的结构只能搭配完整释放状态，
这项结构校验本身不提供原生最终封口证据。

DSH/Pi 的基础登记已通过 T044 正式隔离验收。Linux 路径记录管理进程及出生身份、保存部署/运行包的身份、
受管存储与启动目录，不从原生 argv、profile 或 HOME 猜测 session。宿主进程、会话目录、确切会话、
终端位置与控制能力在没有证据时保持未知。工作目录的记录观察解析真实 symlink/..，不更改原生启动参数。
其他平台的 DSH 保留普通启动租约，并提示可靠进程身份尚未登记；不能把缺记录当成没有活动实例。
Pi 保留原有的可靠进程身份准入限制，不能借新登记路径绕过尚未支持的平台。

DSH 的普通部署、排他认证及 sync 在物理 EX 后检查持久 owner；sync 的检查先于运行包修复。
Pi 保留既有维护检查。`unknown` 不能靠 PID 消失、时间推移或重试清除，完整释放证明仍走显式物理 EX 核实路径。

OMP 的同一缓存运行包可以被多个独立实例共享。单个实例的 RunRecord 视图无法看见其他实例留下的 unknown，
候选 checkout 已为 Linux 下全新资源接通普通 setup/apply/run 的合作登记：唯一可信域关联
instance、native HOME 和共享运行包，先保存预留再启动，完整退出才释放本 run 的引用。
同步检查共享包的全部非终态预留和意图；可取得包 EX 仍不能清除其它实例的 unknown。
旧实例、旧运行包不自动采用，非 Linux 不新增合作登记，部分声明或归属不明时拒绝降级。
首次跨资源登记不是全有或全无，失败后保留现场与保护；没有自动清理或修复入口。
T065/T066 的资源协调与普通启动隔离验收已完成，当前整合状态见实施记录；这不代表真实 OMP 宿主或自动维护准入。
只读 `agent instances list` 已接通；查询本身不授予会话恢复、停止或维护权限。使用方式和证据解释见下节。

## 只读实例查询

在准备好的功能 checkout 中执行；以下机器名仅为示例。尚未部署日常入口时使用 `./rotom`：

```sh
./rotom agent --machine workstation instances list
./rotom agent --machine workstation instances list --agent dsh --format human
./rotom agent --machine workstation --profile pi-base instances list --format json
```

不指定 profile 时查询所选机器的全部相关配方，管理默认配方不会成为隐藏过滤器。
显式工具和配方必须匹配。一次查询读取同一机器配置快照；每条进程观察有自己的来源与时间，
整个列表不是全机同一时刻的原子快照。JSON 包含 `instances`、逐配方 `coverage`、`incomplete` 和同范围的刷新命令；提示进入 stderr。

- `active` 只在 Linux 下核对已登记 manager 的 PID 与出生身份相符时展示，覆盖范围明确为 `manager-only`。
  宿主 PID 没有独立证据时仍未知；manager 存在不证明宿主、后代或当前会话仍有效。
- `stopped` 只来自已保存的完整释放证明；找不到 PID、PID 被复用或观察不完整均为 `unknown`，不会修改 owner。
- 启动目录与会话目录分别展示。保存的会话引用一律按历史信息展示，不读取原生正文，也不冒充当前确认或开放恢复。
- 终端位置与原位恢复保持未知。旧 v1 只有不完整身份信息时不会推造 SessionRef 或目录。
- 新合作 OMP 的 scope/双向 owner 元数据通过核验后显示 `registration=cooperative-v2`；有预留却缺 owner、
  部分提交或活动意图时保留已知行，并增加待核实项、设置 `incomplete`。缺实例但仍有声明不能当作未准备。
- 旧 OMP 实例继续显示 `registration=unsupported` 和未登记/未知行。新查询只观察元数据及 manager，
  不取运行包锁、不验证当前包可用性；包已删除时仍可展示历史，实际启动仍须通过运行包门禁。
  物理租约可取得不证明其它实例或共享包空闲，查询不会授予 stop/resume 或清理权限。
- 损坏记录、所有权不符或无法安全读取时保留未知项、设置 `incomplete` 并返回 4；普通未知字段不被静默当作空列表。

查询只打开已有实例和元数据、短暂观察现有租约，不创建目录/锁文件、不清理记录、不发信号、不启动宿主。
未准备的配方通过 `coverage=not-prepared` 说明；查询不扫描系统全部进程参数、认证目录或会话正文。
查询严格检查全部公开配方及同一份机器配置快照中的字段、配方选项覆盖和归属路径，
但不要求当前 provider/model 目录或启动路线已经就绪；修改模型配置时仍可观察已有实例。
公开配方发现和读取均拒绝链接及不安全来源，损坏字段与运行归属继续明确报错或保留未知。
候选已扩展三工具精确停止和逐项当前终端恢复，但列表本身不授予停止或维护许可；实际动作仍需当前计划、原通道与全部原门禁，详见[维护流程](tool-maintenance-workflows.md)。

## 历史阶段：主线与精确源码核对

本地 `main` 已推进到 `109e2e7`；相对上轮 fetch 的 `origin/main` `467d5cd` 领先 9、落后 0。
原 `39a9389` 工作树保留；本轮从 `109e2e7` 建立承接工作树并继承 OMP `18.12.6` 锁，重新执行受影响隔离回归。
升级未改变共享 cache 的 owner 可见性；迁移和 fake 验收不代表恢复或原生组合已准入。
通过官方 Git 取得 TUI `v0.16.1` 的 commit `73ff99fbed56563bf154d719effd09f9f9725349`，
与 DSH manifest 一致；本次不再以源码下载失败作为全部阻点。npm 归档本次仍因 TLS 未取得，
不新增运行包 integrity 或原生通过结论。完整事实与任务解耦见 [规划修订](../specs/008-rotom-command-experience/main-review.md)。

## DSH 公开来源

以下来源都固定到依赖锁中的版本，不修改上游代码，也不以源码可读为由导入私有路径。

- [Core 会话接口](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/session/README.md) 提供 `ctx.sessions` 和 `session/event`，`flush(session)` 是持久化屏障。事件正文只留在宿主；Rotom 仅观察必要的身份、目录、代际和序号。已弃用的 `eventAt`、`snapshotEvents`、`ownEvents` 不用于新实现。
- [持久化公开接口](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/session/session-persistence/src/index.ts) 的 `stat` 只给元数据，不存在时返回空；写入式 `open` 在目标不存在时失败。[JSONL 后端](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/session/session-persistence-jsonl/README.md) 声明跨进程单会话 writer 锁。其平台和文件系统限制必须保留，Rotom 自有文件锁不能替代它。
- [Core agent 接口](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent/src/index.ts) 的 `roots()` 表示没有 runtime owner 的根 agent；它不指定 TUI 当前前台会话，不能按首项、末项或唯一根节点猜测。
- [AgentLoop 实现](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent-loop/src/index.ts) 区分严格 `resumeSessionId` 与允许在不存在时新建的稳定 `sessionId` 路径。不能把其中一条路径的行为直接当作 TUI 的启动保证。
- [TUI 公开扩展契约](https://github.com/ccch1mneyyy/dsh-TUI/blob/v0.16.1/tui-profile/docs/plugin-admission-and-development.md) 给出 `tui/session-switch` 与 `tui/session-switched`。前者是决策通知，后者报告 `/new`、`/resume` 和 rewind 完成的目标；切换完成才能更新已确认会话。公开入口由 [package exports](https://github.com/ccch1mneyyy/dsh-TUI/blob/v0.16.1/package.json) 限定。
- [TUI 配置](https://github.com/ccch1mneyyy/dsh-TUI/blob/v0.16.1/docs/configuration.md) 与 [profile patch](https://github.com/ccch1mneyyy/dsh-TUI/blob/v0.16.1/cordis.patch.yml) 声明 `DSH_TUI_RESUME_SESSION` 到 `sessionId` 的配置通道。Rotom 当前使用公开 profile boot，不能因此假设上层 launcher 的 argv 已经过解析。
- [DSH 启动实现](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/plugin.ts#L2815) 的显式目标进入 `ctx.agents.resume({ resumeSessionId })`；失败不创建替代会话。同进程已存在的 agent 则直接复用，须另行确认其来源。[其它 backend 的启动实现](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/backends.ts#L98) 不能单独证明 DSH 的接线。以上源码仅作行为调查，不成为允许导入的私有路径。
- 此前审核的 [api](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/api.ts)、[extensions](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/extensions.ts) 与 [plugin-host](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/plugin-host.ts) 没有独立的初始加载事件。本轮补查公开 [scenes](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/scenes.ts)，发现 `TuiSceneProps.channel` 可以提供实际前台元数据；不能再将先前调查概括为“整个公开 API 没有初始观察接缝”。它与内部 `AgentSession.ready` 是不同接口，后者仍禁止导入。

## P-SESSION 当前核验范围

本节保留 T042 调查和早期未注册候选的阶段记录；其中“未开放”“未注册”和原型限制指当时状态。当前三工具的交接、停止及自动输入边界以上方候选能力表与维护指南为准。

T042 的源码调查与 fake 恢复原型已推进到下面的边界；生产适配、CLI 接线及原生验收仍单独记录。缺严格回执不阻止安全交接实现，若派发安全条件不足则拒绝自动派发并转人工说明。

### 官方恢复参数、配置范围和 writer

锁定 TUI 的 `src/sessionHistory.ts:73–108` 接受显式 `--resume ID` 和 `--resume=ID`；
`src/dsh-adapter/plugin.ts:579–589` 从公开 cmdline 服务读取参数，但配置 `sessionId` 的优先级高于 argv。
Rotom launcher 将原生尾参数传给公开 `runProfile`，profile boot 再将它们写入 cmdline 服务。
受管恢复必须带确切 ID，不能使用可能选择 resume.txt 或最近会话的裸 `--resume`。
launcher 的 fake 测试只证明参数转交；TUI 参数解析结论来自上述固定源码。

DSH 的实际配置层顺序为 bundle、profile 用户 patch、HOME patch、显式 patch。
Rotom 的最后一层是 `dsh-home/agentcfg.patch.yml`。固定 TUI 的 JSONL 配置默认使用
`DSH_TUI_SESSION_ROOT` 或 `DSH_HOME/sessions`，后续配置层仍可覆盖 `config.root`。
现有普通启动只保护部分受管资源，不能据此证明 sessionId/backend/root 未改变。
恢复适配必须额外检查这些公开配置层与部署的 launcher；未核验的配置覆盖应拒绝自动派发，
不能仅凭请求的 HOME、argv 或环境变量宣称实际范围正确。核验不修改用户原生偏好，也不读取会话正文。

恢复启动 cwd 来自目标的已知原目录；launcher 将真实进程 cwd 传入公开 workspace 配置。
实际 session header cwd 和加载成功仍需独立观察，请求目录不会填入实际观察字段。
DSH 的显式恢复路径先建立 mount reservation，再调用 `ctx.agents.resume({ resumeSessionId })`；
目标缺失或冲突会拒绝该请求，不回落创建替代会话。JSONL write-open 在宿主内部取得原生 writer，
覆盖权威目标打开、加载和后续使用，直到宿主 close；父进程不能预抢同一把锁。
该结论只覆盖遵守同一 JSONL 后端锁的原生 writer，平台和文件系统竞争仍由 T053 验证。

Core/profile-boot 的此前源码调查来自已缓存的 `0.2.1-rc.2` 包；TUI 来自固定 Git commit。
该调查没有重新验证官方归档字节身份，也没有启动官方宿主，不能将静态调用链当成原生验收。

内部协调器现已区分 `LaunchReceipt` 与 `LoadReceipt`。前者只记录新 run 和派发结果，
退出码 0、请求字段回显、ready 或人工确认都不提升为 `restored`。
宿主内部 writer 接缝与父进程持锁的合成后端分别测试；同一已接受请求只派发一次，
失联、超时及错误回执保持未知且不发送输入。此防重保证目前限同一协调器对象，
不声称已实现跨进程重启的持久事务。公开 CLI 的能力门禁保持未开放。

`src/agentcfg/dsh_sessions.py` 已增加未注册的受管候选：要求同 machine/local、profile、native HOME、
确切 session 与原目录，复用 `runtime.run` 的部署、环境、租约和新 run 登记。
profile 仅接受部署声明内的唯一行及字段，持续受管字段须等于基线；原生 UI 初始化偏好允许普通数据变化，
未知表达式、insert、重复 ID、目标/backend/root 覆盖均拒绝；循环、过深或过量的 YAML 别名展开也拒绝。
HOME patch 只接受缺失或空，
最终 patch 与 launcher 按保存的完整基线核对。检查不建立新的原生会话目录，不修复用户配置，
也不声称能抵御同一用户绕过合作租约任意篡改文件。候选保留官方终端输入输出和退出码，只返回派发回执。

本轮稳定隔离验收：恢复与事件 **122 项**、受管启动接缝 **19 项**、DSH 候选 **34 项**，
CLI 与已知会话/运行记录回归 **271 项**通过；launcher 另有 **3 项**假模块检查通过。
原来 22 项未实现的事件契约已实现，并补充乱序、身份矛盾、精确完整 manager 身份及有界缓存测试。
合成事件跟踪器没有接入官方事件源，不把它当成可用的加载确认或最终封口。

T042/T117/T046 的源码、原型与内部机制以及 T047/T048 的最小候选接线已完成；CLI、能力矩阵和原生准入见本页末尾当前进度。
首次已知缓存的运行包收据不足、顶层依赖指向旧 TUI，且官方归档的有界 TLS 下载未取得字节。
2026-10-26 已从标准登记部署取得匹配当前锁的官方安装包，经受管收据、原包索引与完整复制摘要核验，
在用户授权的私人 scope 实际执行启动、精确停止和合成历史恢复，材料不足不再是当前阻塞。
元数据查询已核实原 ID/cwd，缺失 ID 拒绝且不改变合成会话。首次公开 `--resume` 显示原历史、
不新建 session、stdin 为零；额外本地模型请求已由公开 hook 确认为 TUI 自动回顾，非 AgentLoop。旧零请求断言失败保留；修正后真实候选正例已返回 0。
后续已实际经过 T049 受控入口，独立原生 writer 持有时明确拒绝且不新建/修改会话，
释放后再次 write-open 成功；活动 TUI 的更早 occupied-mount 拒绝、原实例保持不变以及退出后恢复已通过最终复验，T053 收口，T054 亦已完成当前终端的精确组合准入；
详细有限事实见 [实施审查](../specs/008-rotom-command-experience/main-review.md)。

### 历史可选：严格加载确认协议

本节的公开回执条件只用于可信加载确认与自动继续，不是 T042 交接主线的全部前置。源码已经确认显式目标的严格恢复及 Core writer 覆盖加载的路径，公开切换事件仍仅证明后续切换。
公开 scene 是初始前台观察的可行候选；现有隔离探针仅验证元数据观察机制，不能直接输出加载成功。
测试原型现已增加 scene 注册和新 run 私有回执接线；同进程复用分支仍缺初始化成功证明。
严格确认缺口与可选历史研究见 [启动结果契约提案](rotom-dsh-startup-contract.md)；不要求提交上游或先解决该缺口才能实施官方恢复交接。
可选研究可继续核实满足严格确认契约的公开组合，不要求升级或先完成该组合才能推进官方交接。
受管 runProfile 的配置/环境接线、实际缺失目标失败和加载结果仍须独立验证，不能把源码结论冒充原生通过。

要报告可信加载成功，候选必须将请求与本次新运行绑定，保持原生 writer 排他覆盖检查到实际加载，并从宿主公开接口确认实际会话和持久化 cwd。只比较请求参数、历史索引或根 agent 列表均不足。原生最终事件封口另行验证；缺封口限制“恢复刚才确切实例”的自动化，不否定已经证明的普通退出事实。

以下条件用于评估可信加载确认及后续自动继续，不作为允许官方恢复交接派发的统一前置；它们不是上游已经提供的完整回执 API：

1. 公开的初次加载结果或只读当前状态，能区分“已创建进程”“已打开存储”“历史已加载”，返回实际会话身份和原生目录；不能仅回显请求。
2. 状态查询与事件订阅有可核验的代际/顺序关系，避免插件稍晚加载就永久漏掉初次确认。
3. 官方恢复入口负责严格打开指定目标，并证明原生 writer 排他覆盖实际加载；外部 writer 冲突可靠传播，目标缺失不创建替代会话。
4. 证据可以绑定本次 Rotom 新 run，退出封口和可输入状态分别说明，不要求读取正文或私有 getter。

锁定 TUI `0.16.1` 尚未获得严格机器加载确认准入；历史观察候选使用现有公开 scene，不能因此宣称交接恢复已通过或必须等待替代版本。
先完成现有官方恢复入口的受管交接与安全边界，再执行独立原生验收；严格启动完成的公开证据缺口只限制可信加载确认和自动继续。

### 历史可选：最小加载回执验证路线

以下是旧范围的严格确认待验证契约，不是上游已经提供的字段或 Rotom 已开放的协议。
恢复事务可以由官方宿主内部取得原生 writer 并持有到历史加载完成及会话使用期间；
Rotom 不需要在父进程预抢同一把锁，也不能用本地锁或一次无 writer 观察替代它。
初步元数据检查不成为执行凭证；权威目标核验与加载必须落在已证明的原生排他覆盖内。

DSH 内核的启动路径和其它 backend 的启动路径须分别取证。
锁定版本的 [DSH resolveAgent](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/plugin.ts#L2823)
先建立 mount reservation，再通过 `ctx.agents.resume({ resumeSessionId })` 恢复；失败拒绝启动并释放预留。
这不等于公开的初始前台加载回执，也不能仅凭 mount reservation 宣称覆盖了所有外部原生 writer。
`prepareBackendStartup` 的 `backend.open/history` 证据属于其它 backend 路径，不能单独证明 DSH 内核接线。

| 需要的事实 | 接受条件 | 不能替代它的观察 |
| --- | --- | --- |
| 实际前台会话和目录 | 从宿主公开结果取得实际 SessionRef、原生 cwd 和历史加载完成事实 | 请求 ID、启动 cwd、历史索引或唯一根 agent |
| 初始状态与后续切换 | snapshot 与订阅有可核验的 epoch/sequence 水位或等价无遗漏切面；缺口可补齐或明确降为未知 | 仅订阅后续 `tui/session-switched` |
| 本次新运行关联 | 自有插件/受保护观察通道将宿主事实绑定新 run 与观察代际；不要求上游认识 Rotom 的 run ID | 用户注入的 JSON、旧回执或环境参数回显 |
| 原生 writer 覆盖 | 官方严格恢复路径取得并持有 writer，外部竞争和缺失目标可靠失败，排他覆盖权威核验与实际加载 | 包 EX、本地合作锁或保存的 no-writer 布尔值 |
| 独立能力 | history-loaded、input-ready、最终封口分别取证 | input-ready 代替加载，或进程退出代替最终会话封口 |

现有合成恢复测试的 `acquire → verify → launch → release` 表达了一条证据生命周期，
不应成为生产适配器必须由父进程预抢锁的接口要求。本轮补充宿主内部恢复事务的合成模型，
以相同安全性质验收：错误目标/目录、旧 run 回执、writer 冲突、缺失目标、历史加载失败均不得 restored，
目标缺失不得创建替代会话。另验收 snapshot/订阅间切换及 epoch 变化；这些仍只是 fake 机制证据。
明确历史会话的正常恢复不要求停止最终封口，且普通恢复不发送继续文本。
这一历史原型没有完成生产恢复；当前源码与隔离机制进度以上述本轮验收为准，真实交接仍须独立通过。

### 公开 scene 候选与 writer 调用链

#### 历史可选：scene 观察原型

以下记录原型当时的选择与证据，scene 接线不是当前官方交接主线的强制依赖。原型采用最小候选：官方 TUI 执行原有严格恢复，自有插件通过公开 `ctx.tuiScenes` 注册临时
“恢复校验”场景，再观察宿主传入的 `TuiSceneProps.channel`。场景退出后解除观察；不能假定它
仍能跟踪所有前台切换或为停止提供最终封口。也不在插件 `apply` 中抢先恢复或长时间等待
Core，以免改变 preset、句柄归属和 Loader 依赖顺序。`agent/created` 可能早于其它监听器失败，
只作辅助关联，不能独立作为恢复成功回执。

| 环节 | 本轮证据 | 剩余边界 |
| --- | --- | --- |
| 实际前台身份 | 公开 scene props 提供 `sessionRef`、`sessionId`、`cwd`、绑定 generation、`version`、`ready` 和订阅 | 不包含 native HOME/scope，必须与受管启动的可信归属绑定 |
| 回滚与失效 | 宿主将带 lease 检查的 ChannelUi 传给 scene；owner 撤销后，每次属性读取都会拒绝 | 回调不能在同步 adoption tail 内立即发送成功；延后采样并重新读版本，失效即未知 |
| 历史加载 | Core `resumeWith` 先 write-open，再读取全历史、重建 Session，完成发布后返回 handle | scene 的 `ready` 本身只承诺绑定 live session，组合的加载结论须限定精确启动路径并验证 |
| 外部 writer | JSONL 对已有目标取得原生 lease 后解码与校验，write handle 持有到 close 排空写入后释放 | 仅覆盖遵守同一后端锁的写者；不扩展为任意程序、任意平台/文件系统均可靠 |
| 受管 launcher | 隔离假模块可观察到原样的恢复环境、profile、patch 和 argv；没有继续输入 | 不执行官方配置求值，也不证明 TUI 挂载、实际加载或观察插件已就绪 |

[公开 props](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/scenes.ts#L32)
的 channel 由 [宿主挂载](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/channel-ui.ts#L23)
提供生命周期保护，最终每次读取走 [公开视图的 lease 检查](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/adapter/channel/ui.ts#L65)。
scene 插件只消费公开 props，不导入这些实现文件。订阅后延迟读取，前后核对版本和绑定代际，
只给一个当前观察切面；合并通知可能跳过中间切换，不能把本地 sequence 当宿主事件完整水位。
scene 服务缺失、插件 activation 无效、open 失败或未渲染都必须保留未知。

[Core 恢复实现](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent-loop/src/index.ts#L806)
与 [JSONL open](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/session/session-persistence-jsonl/src/index.ts)
共同建立源码中的 writer → 历史读取 → Session 重建 → 发布顺序；
[handle close](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/session/session-persistence-jsonl/src/storage.ts)
在排空后释放。TUI 的 mount ledger 只是额外协调，提前读取的 preset/route 不成为权威加载证明。
TUI startup 的 `history: []` 也不是“Core 没加载历史”的反证：DSH 的绑定扩展管理自己的历史投影。
源代码阅读没有验证已发布归档和真实运行包的执行结果。

[JSONL 公开限制](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/session/session-persistence-jsonl/README.md)
包括 POSIX advisory flock 在部分 NFSv3 上不可靠、Windows semaphore 以登录 session 为范围。
本轮未逐行取得锁定 tag 的 `lease.ts`，不拿其它 commit 代替精确证据；原生竞争测试仍未执行。
普通缺失目标不会创建 session；查找后文件被并发删除仍须作为失败验证，不能将“不新建会话”扩大成“绝无目录副作用”。

候选恢复入口还须控制 `DSH_TUI_RESUME_BACKEND` / `DSH_TUI_RESUME_RETRY` 等启动状态：
官方 safe-mode retry 允许撤销跨 backend 的恢复目标后冷启动。恢复请求不得走这条退路，
且必须拒绝空目标、错误 backend 和未知原目录。现有通用 launcher 的环境透传不完成这些准入检查。

隔离元数据探针位于 `tests/fixtures/dsh-session-observer-probe/index.mjs`，只输出前台元数据或未知状态；
它不装入运行包、不读正文，也不宣称 loaded/input-ready/final-seal。新增 `scene.mjs` 负责公开场景
注册与撤销，`attempt.mjs` 负责父子消息关联；这些都是测试原型，不是已经安装的生产插件。
Node 用例验证观察竞态、失效、元数据脱离原对象和 fake 宿主持锁生命周期，包括排空期间继续持锁、排空失败向调用者报错；
`tests/node/dsh_resume_launch.test.mjs` 单独验证受管 launcher 的假模块接线。
当时的严格候选要求确切运行包、原生 HOME、严格恢复完成和外部 writer 证据，未据此开放能力。
当前交接须核实现有官方入口/HOME/scope/cwd/writer；缺严格加载确认只保留待确认，不成为 T047 接线的硬前置。真实官方交接、加载人工观察及竞争由 T053 验收，
不以依赖 T042 的后续任务反向阻塞原型。原阶段隔离结果为探针/内存事务 36 passed、launcher 3 passed；
未来恢复/事件契约仍保留最近的 5 passed / 44 failed，本轮未重跑，也不将新增测试计为这些失败已修复。

### 历史可选：scene 接线、新 run 关联与初始化结果缺口

`scene.mjs` 仅调用公开 `ctx.tuiScenes` 注册、打开、订阅和清理场景，通过 props 的 React effect
安装元数据观察器。Cordis `ctx.effect` 接受立即执行的工厂，因此清理注册必须是
`ctx.effect(() => control.dispose)`；不能把 disposer 本身当工厂。隔离 fake 同样执行该工厂，
不以错误的宿主模型掩盖立即撤销问题。重复安装、失效、换场景、换 channel、回调和清理异常均降为未知。

`attempt.mjs` 生成新的 run ID/nonce，通过父进程持有的 child IPC 绑定消息；不从 stdout/stderr
提取 JSON 回执。接收器核对目标 session/cwd、emitter 与观察代际、连续序号，重复原消息幂等，
冲突、跳号、旧 run、额外成功字段及通道丢失均拒绝。场景观察最高产生 `foreground-matched`，
不产生 loaded/restored。请求里的 native HOME、scope、profile、runtime 只是父进程请求上下文，
尚未证明官方配置实际采用它们，因此明确保存 `launch_binding: unproven`，不能将其作为可信 SessionRef 入库。
IPC 能区分该子进程和终端文本，不能防范同一宿主内部恶意插件，也不是通用认证服务。

启动准备清除继承的 retry/handoff/host-entry-path，固定 DSH backend、精确目标和 profile-boot 路径，
拒绝额外原生 argv。它只验证本原型的准备动作；实际官方配置求值、插件装载及 HOME 归属仍待验证。
fake-host 中出现 idle、ready 且 session/cwd 匹配后异步失败的场景，仍不能升级为初始化成功。

本轮明确排除了两个不足的补证办法：`agent/created` 可以先于后续监听器失败；`whenIdle()`
在初始化成功或失败后都会结束等待，追加空 maintenance 也不返回原初始化结果。
TUI 会直接复用 registry 中的目标，外部 scene 没有获得该初始化的成功 promise。
当前调查未找到在这个精确复用点拒绝既有 agent 的公开策略；固定版本范围内的来源和替代能力要求
见 [具体契约提案](rotom-dsh-startup-contract.md)。严格确认研究的缺口已从“无法取得源码”收敛为
“当前候选缺少可关联的严格启动提交结果”；继续堆叠等待、ID 比较或 nonce 无法消除它，但不阻塞当前有界官方交接路线。

合成场景见 `tests/fixtures/rotom/session-capabilities.json`；它们只是后续隔离测试的输入，不是原生通过记录。真实宿主、账号、信号、PTY、Herdr 与输入测试按各自范围另行授权，证据保存在私人位置。

## 运行中的请求与派发观察

当前候选在配置核验、新 run 登记之后，把请求 SessionRef/cwd 与派发意图保存到独立私人记录。
官方子进程创建成功后立即保存并发布 `launch_dispatched`，此时原生 TUI 仍在运行；不再等到
退出才让调用者知道已经交接。原生输出和输入继承当前终端，恢复代码本身不写入 stdin。

`rotom agent instances list` 把请求目标与当前会话分列，并显示派发状态和已知原生退出码。
没有实际会话观察时，`session` 与 `session_cwd` 继续为 unknown。启动意图没有派发确认时显示
unknown，非零原生退出明确失败，零退出仍保持加载待确认。请求记录损坏不抹除独立的进程事实。

启动前落盘失败不派发。启动后的记账或展示失败会继续等待同一个子进程，不终止、不重启；
不能保存退出事实时保留旧记录并保留原生退出码。候选没有确认超时，也不发送探测或继续文本。
此接线仍属于未注册候选；公开 resume 尚未通过真实交接准入。

## 显式 session 元数据的可行公开路线

固定 Core `0.2.1-rc.2` 的公开 `ctx.sessionPersistence.stat(SessionId(id))` 返回 header、revision
等元数据；header 含 ID 和可选原 cwd。接口声明不读取事件日志、不取得所有权；JSONL 实现只读取
所选 generation 的 header 与文件 metadata，不迁移正文。初始化 JSONL provider 只核查已存在 root，
不存在的 root 到首次写入才创建。此结论来自缓存包类型、README 和实现；归档字节尚未重新核验，
也未执行该独立组合的真实验收。

可用最小路线是短命 Cordis context，仅加载公开 JSONL provider，以已验证的受管 sessions root
调用 stat，随后 dispose。ID 在多个项目目录重复时官方查找报错，不任选；没有 snapshot 可能是
缺失或 malformed header，统一拒绝/保留未知，不解释为确定从未存在。只接受精确 ID 和有效 cwd，
仍由实际官方 resume 在执行时严格取得 writer。该查询不证明加载成功或无外部 writer。

`lookup_metadata` 与仓库自有 `session-metadata.mjs` 已接到可信 Python 候选工厂。查询先取得已有
物理共享租约与状态共享租约，核对部署绑定、完整锁、配置与包收据；不存在的锁不创建。
DSH 包位于物理实例内，受同一物理租约保护；测试注入的第三层包锁不是 DSH 生产实现的声明。
helper 只继承必要路径环境，stdin 为 DEVNULL，不解析凭据，不登记 run、不启动 Agent。
其 10 秒预算只约束独立只读 helper；恢复 Agent 本身没有确认超时或自动终止。
缺失、重复、损坏、超时或不可解析输出统一保留不可核实，不新建替代会话。
当前候选 ID 限定为 1–128 字符的安全 ASCII 标识；其它官方 ID 格式尚未覆盖，不能据此认为它不存在。

候选停止服务的共享启动接缝也已分别验证正式两锁路径和可选第三锁传递。服务只在本次 host
绑定及启动记账成功后构造；构造/处理失败继续等待原宿主，恢复记录仍是加载未知、继续未发送。
该验证使用临时部署和记录，内核、宿主、批准及后代观察均为 fake；不构成原生停止准入。

元数据来源没有旧 Rotom run 时保留 null；请求意图、派发和实际会话仍分开保存。
新会话和后续切换的公开 scene 观察尚未接入生产；需先订阅再采样，结合切换通知重读 channel。
切换通知没有初始通知或完整水位，ready 也不是历史加载完成；查询实现不证明已登记真实前台 session。

## 历史阶段：DSH 默认 CLI 恢复入口

`rotom resume` 在选中恢复命令并核验参数后，惰性构造已有 DSH 后端工厂；可信 Python 注入接缝仍供测试使用，
没有用户 flag、环境变量或配置开关绕过精确组合准入。静态 help 和补全不构造后端、不查询原生会话。
入口按所选 machine/local 查询历史归属；显式 ID 唯一时推断工具，歧义通过三流 TTY 菜单选择，
`--no-input` 缺参或歧义返回 2，取消返回 130。未知 ID 只查明确工具和 profile；多个 profile 需选择，
不使用 `run_profiles` 或管理默认配方。每次加载 workspace 重新核对实际工具、profile 与 scope。

当前只支持精确 Linux DSH 组合的 `--here`；其它位置返回 5，并展示范围完整、可复制的当前终端命令和人工说明。
派发通知在原生等待期间只显示一次，未取得加载回执时保持待确认；退出码和原生失败如实保留，
展示失败不覆盖退出结果。没有候选且不能推断工具时，按公开配方提供工具选项，再补齐 ID 和必要配方；
Pi/OMP 明示尚未准入，选择后不查询其原生元数据或启动宿主。精确完整锁、平台、部署与配置在实际查询/派发前逐次核验。
普通入口已实际核对原 session/cwd/历史、新 run、unknown/not_sent、零输入和原生退出；未启用 Pi/OMP 恢复、自动继续或原位置控制。

接口来源：Core 包 `@deepseek-ai/dsh-session-persistence` 的 `lib/types/index.d.ts`，
`@deepseek-ai/dsh-session` 的 `lib/types/types.d.ts`；JSONL 包 `README.md` 的程序化挂载与只读查询说明，
`lib/index.js` 的 stat/header、ID 查找、root 核查实现（固定缓存位置分别为 2570、3140、3444、3458 行）。
公共源码路径为 `packages/session/session-persistence-jsonl`，TUI 公开 scene 证据见上文固定提交链接。

## 当前后续工作

严格初始化回执缺口只限制 `restored` 与自动继续。T042 已完成现有官方入口、实际部署/native HOME/scope、归属/cwd、原生 writer 和状态边界的源码及假进程核验；不等待上游新增接口。T053 已完成固定 Linux 组合的真实交接、原历史观察及缺失目标、活动 TUI/外部 writer 拒绝验证，T054 已完成默认入口准入及原生复验。本轮三工具分阶段维护已接线，官方 Pi/OMP TUI/PTY 与本轮分组回归已验证，main 整合仍需人工批准，见维护指南。用户在 TUI 人工操作不生成机器可信回执，缺加载确认保留待确认和零自动继续。
