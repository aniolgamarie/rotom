# 技术研究与决策

## 当前范围决策（2026-10-24）

首版真实派发现有官方显式 session 恢复到用户选择的终端，沿用已部署 runtime、native HOME/scope、原目录与租约。请求目标、启动派发、实际加载确认、继续是否发送分别记录。可证明已启动但缺可信加载回执时报告“已发起恢复，加载待确认；请在 TUI 检查；未发送继续”，不标 `restored`，未知不伪装 `failed`，不自动重试或超时强杀。

缺严格回执不再禁止启动；范围、归属、cwd 或原生 writer 冲突防护不足仍拒绝 Rotom 自动派发，转人工说明。用户直接在官方 TUI 操作及人工观察独立记载，口头确认不是可信加载回执或自动输入许可。自动继续默认关闭，完整目标、加载、ready、writer 与接收能力另行准入。

T042 负责现有官方入口、实际 HOME/scope、writer 与状态边界调查及原型；T053 负责真实官方交接、加载人工观察、缺失目标和外部 writer 验证，机器态可以保留待确认。上游提案未发送、当前不计划提交，仅为可选历史研究，不属于交付依赖。缓存 Core 两个内存 case 不证明恢复。以下历史证据保留，R6/R7/P-SESSION 的当前决策按本范围解释。

日期：2026-10-23。范围：实现规划所需的源码调查、固定版本公开接口核对与取舍。
本轮不启动宿主、不发信号、不读取真实账号或会话，也不安装依赖。
设计源码基线为 `17bbacd6`；原 `39a9389` 实施工作树保留，本轮已从最新主线 `109e2e7` 建立独立承接工作树。
上轮 fetch 的 `origin/main` 为 `467d5cd`，现落后本地 9 个提交；OMP `18.12.6` 升级已进入主线。
承接工作树继承主线 OMP `18.12.6` 锁并重新运行受影响隔离检查；不把旧候选证据直接计到新组合。
最新固定源码事实与修订后的任务边界见 [主线核对](main-review.md)。

## R1. 统一入口与既有业务分发

**Decision**：增加仓库 `rotom` 和小型 `src/rotom/` 门面，直接复用既有 parser/业务处理器。
命令注册补充 scope、缺参类型、批准方式和输出元数据，不复制完整 parser 或执行平台。
给旧入口增加可选的显式调用上下文与输入网关；省略时使用原有行为。

**Rationale**：[agentcfg cli](../../src/agentcfg/cli.py) 与
[termcfg cli](../../src/termcfg/cli.py) 已暴露 parser；work 的 parser 与递归分发需要抽出薄接缝。
菜单、help、补全与完整命令最终到达相同处理器；原生尾部在交给门面前固定边界。

**Alternatives considered**：shell 拼接会破坏 argv/批准边界；完整重写三个 CLI 增加兼容风险；
全局替换 input/isatty 不能可靠约束递归和隐藏输入，因此均不采用。

## R2. 输入网关与所有叶子覆盖

**Decision**：`InvocationContext` 显式携带前缀、显式字段、scope、输出形式和输入策略。
每个可能读取输入的业务接缝接受同一网关；先完成元数据/未知字段校验，再补真正缺项。
无输入模式不是批准。fzf 是可选前端，编号前端使用相同不透明候选键。

**Rationale**：[work_ui](../../src/termcfg/work_ui.py)、termcfg 确认、模型隐藏输入各有入口，
且 work 有递归 `main`。只限制顶层菜单不能覆盖所有输入。验收以 parser 叶子集合和注册表
双向比较为准，再逐叶检查缺参、批准、取消、失败后续和结构化输出。

**Alternatives considered**：只给几个常见命令写向导会遗漏叶子；把所有参数错误转菜单会掩盖错误；
强制安装新 TUI 依赖增加启动成本，均不采用。

## R3. 偏好与目标解析

**Decision**：私人 TOML 只保存三管理面的默认机器和三工具启动配方，使用已有安全路径和
tomlkit；schema 关闭未知字段。显式参数优先，work 固定 binding 与已知 session 归属不被偏好覆盖。
help/公开目录先返回，不能为帮助加载偏好或机器。精确规则见 [CLI 契约](contracts/cli.md)。

**Rationale**：一个 `machine.default_profile` 无法同时提供三工具短启动，但它仍属于原管理命令。
保留既有默认语义，比将新偏好注入全部命令更可预测。

**Alternatives considered**：自动记住上次使用、迁移旧 HOME、用全局 shell alias 注入配方均被排除。

## R4. 受管生成产物与版本兼容

**Decision**：catalog 新增版本 2 的受限 `rotom-entry-binding` 类型，不提供任意模板/执行器。
新读取器接受旧 catalog v1；带生成目标的状态和 journal 使用 v3，并继续读取/恢复 v2。
纯静态且未携带生成目标的事务保留 v2；不将 v3 自动降为 v2，也不默改未知版本。
生成内容先确定精确字节并持久化，再修改目标；checkout 绑定最后激活。

固定 launcher 使用极薄的 sh 定位层，以 `python3 -I -S -B` 运行内嵌标准库 JSON 解析，
只读 entry.json 并 exec 已验证 checkout 的入口；不导入项目模块或使用 stdin 读取程序。
所有项目业务代码仍由该 checkout 已准备的 Python 3.11+ venv 执行，不以系统 Python 回退运行。
定位层只需支持其标准库语法的 Python 3，不额外要求系统解释器等于项目/验收补丁版本；
缺失或无法定位时给静态修复诊断。普通 shell/Python 定位层不承载 Agent 启动业务或安装逻辑。
新入口在导入前禁写 bytecode，venv 交接保持这一策略；无副作用查询不靠继承环境避免 pycache。

**Rationale**：当前 [catalog](../../src/termcfg/catalog.py) 仅允许静态来源与摘要；
[preview](../../src/termcfg/preview.py) 和 [transaction](../../src/termcfg/transaction.py)
已提供计划重算、写前/写后身份及逆序恢复。最小扩展是将生成内容纳入同一机制，
而不是写一个独立安装脚本。详细中断语义见 [部署契约](contracts/entry-deployment.md)。

**Alternatives considered**：运行时搜索 checkout、每次 apply 默认换绑、恢复时重新渲染，以及
把新字段写入旧 schema 版本均不采用。旧工具不支持新状态时拒绝写入，比丢字段继续操作安全。

## R5. 继续复用已部署运行契约

**Decision**：根 run 解析工具/profile 后仍调用现有 `runtime.run`；不因新锁有更新阻止有效旧部署。
未部署、启动绑定不兼容、已部署包不可用分别诊断，待部署更新仅提示显式 plan/apply。

**Rationale**：[runtime](../../src/agentcfg/runtime.py) 使用保存的运行身份和启动绑定，
主线 `567c917`、`ae010a8` 改进 Pi 配方及 readiness 提示，没有把所有更新都变成启动失败。
不复制运行前检查、环境过滤、秘密解析、原生参数限制或三层租约。

**Alternatives considered**：启动时重建部署、按新锁改包或将 readiness 的每个提示都升级为拒绝，均不采用。

## R6. DSH 的最小会话恢复路径

**Decision**：DSH 是首个实际恢复目标；在当前受管 `runProfile` 路径中，通过经过验证的
本段为早期研究状态：当时 ResumeRequest 接入官方会话恢复入口仍待实现/验证，不表示当时参数通道已打通；已有公开观察仅作为可选证据，不能为缺失的加载事实背书。
不执行上游全局启动器的安装/修复路径，不读取或复制会话正文，不靠原生 argv 猜测恢复。

**Rationale**：当前 [launch.mjs](../../agents/dsh/templates/launch.mjs) 直接调用公开 profile-boot，
不会经过上游全局启动器的参数处理。锁定 TUI 0.16.1 的
[profile 配置](https://github.com/ccch1mneyyy/dsh-TUI/blob/v0.16.1/cordis.patch.yml)
声明 `DSH_TUI_RESUME_SESSION` 恢复通道；launcher 隔离测试只验证传给假 profile boot 的参数和环境，
不证明官方配置求值、实际加载或最终事件封口。裸 `--resume` argv 的假模块透传只证明参数被转交，不证明公开 profile-boot 会解析该选项；该路径尚未验证，不能报告官方参数已经打通。
公开导出以 [package.json](https://raw.githubusercontent.com/ccch1mneyyy/dsh-TUI/v0.16.1/package.json)
为界，不能因源码可读而导入私有文件。

**Alternatives considered**：裸 `--resume` 透传、读取“最近会话”、抓终端文字和修改宿主均不采用。
事件名、会话归属与封口证明须由 P-SESSION 原型核实，不能在实现中编造。

**本次源码核验**：已取得与 manifest 一致的 TUI commit
`73ff99fbed56563bf154d719effd09f9f9725349`。DSH 的 `resolveAgent` 走
`ctx.agents.resume({ resumeSessionId })`，缺失或失败不转 create；同进程已存在 agent 会复用，
需要单独确认其创建来源。`prepareBackendStartup` 只证明其它 backend，不能替代该 DSH 路径。
公开 `tui/session-switched` 用于后续显式切换。

此前只审核 `./api`、`./extensions`、`./plugin-host`，本轮补查公开 `./scenes`：
`TuiSceneProps.channel` 提供实际前台 SessionRef/cwd、绑定代际、版本、ready 与订阅，
并由宿主每次读取的 lease 检查阻止 owner 失效后的继续使用。这是新的公开候选，
不是允许导入内部 `AgentSession.ready`。观察回调须延后到同步 adoption tail 结束，
重新核对版本和代际；ready 单独只证明 live session 绑定，不直接声明历史加载。
Core 恢复在 writer 内读取历史后才发布，TUI 的 `history: []` 不否定 Core 已水合。
候选选择原 TUI 恢复加临时 scene；不在插件 apply 中抢先 resume 并改变 Loader/preset/handle 归属。
`agent/created` 可早于其它监听器失败，只能辅助关联。

隔离原型现包括公开 scene 生命周期、新 run/nonce 的私有 IPC 关联和 retry/handoff 清理，
最高只得到前台元数据匹配，不声称生产插件已安装或原生 HOME 已被实际采用。
同进程已有 agent 可能在初始化提交前进入 registry；TUI 复用分支不等待原初始化结果。
`agent/created`、`whenIdle()` 与空 maintenance 都不能证明原初始化成功，延时和反复比对 ID 也不补足它。
固定版本中尚未找到公开拒绝复用策略或 TUI 启动提交结果，已形成
[最小上游契约提案](../../docs/rotom-dsh-startup-contract.md)，尚未对外发送。
下一步推进现有官方入口的受管交接与独立原生验收，不等待新的上游契约；严格回执缺口只限制可信加载确认和自动继续，scene.ready 不能升格为 loaded。
npm 归档本轮仍未验证，不新增 integrity 或真实运行证明。T042 保持未完成，具体来源和分层证据见
[会话能力记录](../../docs/rotom-session-capabilities.md#公开-scene-候选与-writer-调用链)。

## R7. writer 排他是开放恢复的条件

**Decision**：自动派发必须确认 scope/归属/cwd，并沿官方恢复路径保留原生 writer 冲突防护；加载后的实际 ID/cwd 确认独立记录，缺严格机器回执时可以交接用户并保持加载待确认。
Rotom 本地锁只排除合作入口，不能证明宿主或外部 CLI 不会同时写入。
原型必须核实官方 writer 保护与冲突传播；该安全边界不足时拒绝 Rotom 自动派发并给人工说明，不能与仅缺加载回执混为一谈。
官方宿主可内部持锁；源码已确认 Core write-open → 全历史读取 → Session 重建 → 发布，
JSONL handle 持锁到 close 排空后释放。父进程不预抢同一把锁；原测试的 acquire/verify/launch
只是合成模型，后续协调器接口须允许官方宿主持有的事务，不在回执发出时释放 writer。
TUI mount ledger 与不加 writer 的 preset/route 预读不替代这条权威链。
该源码证据仅覆盖相同后端协议；平台/文件系统限制及真实竞争仍须独立验证。

**Rationale**：会话存在、历史 ID 和无 writer 的两次读取均不能排除竞争。
阶段二要求真实执行官方恢复交接及原生负例验证，持续拒绝不算完成；加载人工观察与机器确认分别记录，不要求新增上游接口。

**Alternatives considered**：用本地锁宣称排除所有外部写入、复制会话数据库、冷启动替代均不采用。
若原型证明主交付无法满足，则带证据重新调整设计或范围，不能把要求改成“总是拒绝”后勾选交付。

## R8. 进程观察、停止与 Linux 边界

**Decision**：扩展现有 [run owners](../../src/agentcfg/run_owners.py) 的最小元数据，
保留 `active/unknown/idle_confirmed` 含义；不从 PID 死亡或 manager 返回推定完整退出。
Linux 稳定句柄可使用 pidfd 候选，且保持 manager 观察者运行；其它平台没有对应证明时关闭控制能力。

**Rationale**：Python 的 [pidfd_open](https://docs.python.org/3.11/library/os.html#os.pidfd_open)
和 [pidfd_send_signal](https://docs.python.org/3.11/library/signal.html#signal.pidfd_send_signal)
提供 Linux 进程句柄接口，但句柄仍不是后代、资源或会话释放证明。
现有 Registry 明确需要完整 ReleaseObservation；主线已有 Linux DescendantScope 及 Pi
有限原生完整释放证据。复用该机制，只有本次已武装且完整同身份观察才可释放当前 owner；
缺覆盖、幸存后代、manager 丢失和旧 unknown 仍保持阻塞。不把历史 Linux 退出验收等同于新停止通道、
最终 session 封口或其它平台已经通过。

**Alternatives considered**：裸 PID kill、killpg 当作归属证明、按名字批杀、超时清 owner 均不采用。
优雅与强制操作独立批准；没有稳定控制句柄或退出覆盖时保持不可用/未知。

## R9. 最小维护协调，不建通用平台

**Decision**：在既有 agent 状态根下增加有限的批次/资源意图元数据；普通 stop 与维护共用停止执行器，
日常 resume 与 restore 共用会话执行器。合作入口在启动前登记资源 reservation，
维护原子登记精确资源意图；物理租约仍是最终门禁。

**Rationale**：已有 owner 元数据遵守物理锁先于 owner 锁。新增短协调锁不得持有着等待宿主、
物理锁、用户或网络。恢复许可绑定精确后继 run/op，不是绕过所有维护的白名单。
完整顺序及非合作入口边界见 [生命周期契约](contracts/lifecycle.md)。

**共享资源修订**：OMP 的 cache/runtime 可跨 instance/state 共享；已进入主线的 `18.12.6` 升级未改变此关系。
T044 只完成基础观察和 DSH/Pi 登记，OMP 缺记录保持未登记/未知；其生产合作登记移到 T065/T066
完整资源归属建立后。共享物理资源须有唯一可信协调域锚点与完整 owner/reservation 引用，
否则拒绝相应自动维护。普通 OMP sync 的修复/激活也要纳入已证明的资源门禁，同时保持 cache-only 契约，
不能用本实例空 Registry 或包 EX 作替代，不隐式扫描所有机器来建立归属。

**Alternatives considered**：后台调度服务、长期持全局锁、每工具另一套数据库及自动重试 unknown 均不采用。

## R10. 原位置与继续分别准入

**历史 Decision**：优先扩展现有管理层的可选驻留，普通单次 run 保持原行为。
驻留等待在单次运行租约之外；管理代码/协议变化时首版拒绝旧进程原位恢复，允许明确选择新位置。
Herdr 公开重启作为比较路线，不凭现有 Rotom allowlist 断言上游不存在能力。

**本次候选实现（2026-10-27）**：薄驻留启动器和 Herdr 新标签页 transport 已实现，最终十二组无 trace 原生验收全部通过，现按六个精确 Linux managed 组合开放两种位置。
原 pane 仅面向通过 Rotom Herdr 入口新建、由驻留启动器托管且该工具已验收的实例；
仅停止 Agent 并保留 launcher/pane 才能等待原位恢复。普通 shell 启动退出后返回 shell，旧普通实例不升级，
仅在 Herdr 内或刚新启动不构成资格。launcher/pane 丢失、被复用或身份不明时使用明确接受的新位置。
候选只接受已停止且已完成 setup/update 的完整 workflow；普通 --session 不取得位置能力。P-PANE 约束精确 Linux managed 组合正式开放，不能由核心探针、help 或隔离回归代替。
统一严格加载回执、原生 TUI 自动继续及 Pi Pro 委派不在本轮承诺内；恢复仍可保持加载待确认、零自动输入，
`pi-pro` 普通 profile 的停止、更新与恢复兼容性保留。最新边界见[原位置能力指南](../../docs/rotom-pane-capabilities.md)。

**Rationale**：已审核的 Herdr 0.9.5
[方法 schema](https://raw.githubusercontent.com/herdrdev/herdr/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema.rs)
及 [pane schema](https://raw.githubusercontent.com/herdrdev/herdr/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/panes.rs)
不能单独证明原位恢复满足身份、cwd、单次请求和无键盘注入要求。
现有 [原生 API 契约](../006-configurable-workspaces/contracts/native-api.md) 未准入该控制路径。
历史自动继续研究还需新运行/确切会话/ready/接收确认；当前不承诺该能力，默认不发送。

**Implementation**：agentcfg.pane_records 保存容器身份；restore_locations 保存目录身份锚定的不可变请求与 CAS receipt；tool_maintenance 先 reserve 原恢复意图。rotom.resident/pane_dispatch/restore_child 与 termcfg.restore_tabs 只用固定公开 API、socket 请求引用和固定子命令。新 tab 创建不重发；批量 --all 先核验整批、逐项独立交接，失败后保留部分结果。源码身份变化拒绝旧容器；parked 释放 Agent 单次租约与凭据环境。普通 rotom run 不驻留，Herdr V1/V2 新 DSH/Pi 与符合组合的新 tab 恢复才参与驻留准入。

**Alternatives considered**：给 shell 键入命令、从标题猜位置、复用旧 work receipt、自动导入新模块或重发未知输入均不采用。

### 当前实现的锁与驻留选择

薄 parent 在 child 活动时仅等待退出，不轮询 Registry/Domain。child 退出后核对唯一出生身份和完整 release 才保存真实 run_id 并 parked；active 位置按需关联只是候选，不能绕过原位 saved run、parked 与一次请求消费。

Domain 首次写锁默认等待 2 秒；显式 deadline 保留原预算，body/commit/unlock 不重放。默认外部读仍 NB，合作启动只为 package_guard/check_omp_launch 两处只读首锁给 2 秒。资源/anchor 选择与预留现在同一写事务完成，替代早期 snapshot→reserve 拆分后依靠全域 revision 竞争拒绝的设计；通用 reserve 的严格 CAS 不变。停止最终 status 沿原 deadline 观察，过期无竞争可读，有竞争保留未知，不重 close/信号。

V1 accepted 前保存最后核验的 caller，accepted 后 pending 正常清除不使驻留包装误退 shell。机制本身不能证明原生可用；当前六组合、两位置的准入另由最终十二组无 trace 原生验收确立，DSH/Pi 的 V1/V2 work Agent 入口四项亦通过。

## R11. 性能与规模的初始验收口径

**Decision**：使用固定合成负载与同一准备环境，每场景 30 次独立冷进程，报告 p50/p95/max：
静态 help 目标 p95 ≤ 1 秒；允许范围的动态补全 ≤ 1 秒；只读实例列表 ≤ 2 秒。
负载分为空配置、32 个机器名/100 个公开配方、单机器 1,000 条运行记录。
这些是初始工程验收预算，不是当前实测或生产容量上限。

不测原生宿主、模型、网络或安装耗时来归因门面性能；首次实现先记录真实基线，
正确性与隐私失败不能靠性能结果豁免。指标超限必须修复或明确重新审阅预算，不能静默标通过。
停止等待默认30秒、可选1–300秒，使用单调绝对截止时间，整个停止集合共享阶段预算。新增位置交接按每个有界请求核验，不把批量逐项执行描述为一笔跨终端事务。

**Rationale**：这是本地个人 CLI，不需要服务器吞吐或 uptime SLA；重点是发现入口和拒绝等待的响应。
驻留 CPU/内存与 PTY 成本随 P-PANE 单独建立实际基线，未测量不宣称性能通过。

**Alternatives considered**：虚构现有性能基线、给每个 run 重启完整等待预算、无上限轮询均不采用。

## R12. 能力原型与研究完成边界

技术选型、数据归属、版本方向和失败策略已确定；没有留给用户的技术栈或范围问题。
以下表格保留原型规划；实际完成范围以任务及验收记录为准，不能将规划当作已通过的研究实验。
本轮六个精确 Linux managed 组合已完成 P-PANE，最终十二组无 trace 原生验收全部通过；其它组合仍须逐项满足原生验收门槛。P-PANE 不是开始开发的前置；P-INPUT 是独立历史研究，不是本轮交付依赖。

| 编号 | 输出证据 | 通过后解锁 | 失败时处理 |
| --- | --- | --- | --- |
| P-ENTRY | v2 catalog/v3 journal 的精确生成、逐写入中断及旧状态恢复 | 阶段一受管入口 | 调整事务设计，不能切换日常入口 |
| P-SESSION | 现有官方恢复入口、实际 HOME/scope/归属/cwd、writer 冲突防护及四层状态原型；严格机器加载确认与停止封口独立 | 阶段二真实官方交接和 T053 原生验收；允许加载待确认，不发送继续 | 安全边界不足拒绝自动派发并转人工；仅缺严格回执时保留待确认，不等待上游变更 |
| P-EXIT | 稳定句柄、manager 保留、后代/资源完整释放、Pi unknown 不被抹除 | 阶段三停止维护 | 仅显示/人工，不承诺可恢复维护 |
| P-PANE | 已选驻留路线的逐工具 PTY/信号、完整退出/释放、首次采用、代际、代码兼容和真实 Herdr 绑定；公开重启保留比较证据，新标签页另验公开 API 与未知请求对账 | 正式开放已验收托管新实例原 pane；新标签页须完成自身验收 | 保持未开放，使用事先接受的当前终端、新位置或人工方案 |
| P-INPUT | 新 run/session-ready、排他覆盖、准确批准与接收结果 | 独立自动继续能力，非本轮承诺 | 保留人工指引，不自动输入或聚焦 |

默认原型先用假进程、假事件和合成状态；真实进程、zsh、Agent、Herdr、信号及 PTY
需独立授权后验证。本轮的源码/公开资料调查不代替这些结果。
