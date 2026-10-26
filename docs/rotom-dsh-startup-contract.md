# DSH 严格启动结果的公开契约需求

这是 T042 调查形成的可选历史研究，尚未发送给上游，当前不计划提交，也不是已经存在的 API。

## 当前交付决策

2026-10-24：首版使用现有官方显式 session 恢复入口，真实派发到用户选择的终端，沿用已部署 runtime、native HOME/scope、原目录与租约。严格初始加载公开回执不是整个 resume 主交付的硬前置，不请求上游变更。

分别记录请求目标、启动派发、实际加载确认和继续发送。已启动但缺可信回执时报告“已发起恢复，加载待确认；请在 TUI 检查；未发送继续”，不能标为 `restored`；未知不伪装失败，不自动重试或超时强杀。范围、归属、cwd 或原生 writer 冲突防护不足仍拒绝自动派发并给出人工说明。用户在官方 TUI 的直接操作属于人工交接，其口头确认不是机器可信回执或自动输入许可。

自动继续默认关闭；完整目标、加载、ready、writer 与接收能力须另行证明。T042 转为现有官方恢复入口、实际 HOME/scope、writer 与状态边界调查及原型；T053 仍需真实交接、加载人工观察、缺失目标和外部 writer 验证，机器状态可以保留待确认。缓存 Core 两 case 仅为内存初始化行为证据，不能称为恢复验证。

以下严格回执方案与验收矩阵按旧范围保留，只研究 `restored` 与自动继续所需的额外证据，不再阻塞普通官方恢复交接。
适用调查范围为 TUI `0.16.1` / commit `73ff99fbed56563bf154d719effd09f9f9725349`，
Core `0.2.1-rc.2`。没有据此判断其它版本的能力。

## 严格加载确认的历史缺口

公开 scene 的 `channel` 能提供实际前台 session、cwd、版本和绑定代际；它没有声明初始化事务成功。
为观察消息绑定新 run、nonce 和私有 IPC，可以拒绝旧回执和错误目标，但不会增加消息本身包含的事实。
本轮原型最高输出 `foreground-matched`，`native_load` 与 `launch_binding` 均保持 `unproven`。

锁定版本存在如下路径：

1. Core 在完成全部 `agent/created` 监听器前，先把 agent 放入 registry。
2. TUI 的 `resolveAgent` 查到同进程已有的目标 agent 就直接复用，不等待该次初始化的结果。
3. 后面的 `agent/created` 监听器仍可能失败；早先观察到的创建通知、相符的 ID/cwd 和 idle 状态均不能排除它。
4. `whenIdle()` 等待活动结束，`runMaintenance()` 的 finally 在成功或失败时都释放等待者。
   在它后面追加一次空 maintenance 只能确认当前空闲，不能追溯原初始化是否成功。

依据：[TUI 复用分支](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/plugin.ts#L2834)、
[Core 发布与初始化回滚](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent-loop/src/index.ts)、
[活动等待实现](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent-loop/src/agent.ts)、
[公开运行时契约](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent/src/runtime-types.ts)。
延迟固定毫秒数、等待若干微任务、轮询 registry 或重复读取 scene 都不能充当事务成功结果。

直接调用者 `await ctx.agents.resume(...)` 可以得到初始化成功后的 handle；现有 TUI 启动内部消费这个结果，
此次未找到把该完成结果转交给外部插件的公开启动接缝，也未找到可在精确复用分支前拒绝的公开策略。
在插件 apply 中抢先恢复会改变 preset/route、Loader 顺序和 handle 归属，不能当作等价替换。
调用者成功契约见 [Core agent API](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent/src/index.ts#L383)。
具体而言，TUI 在调用 resume 前组合持久 preset、route 和 setup，并建立 mount reservation；
这些运行时 helper 没有作为公开子路径导出。公开 `./preset-patch` 是配置补丁入口，不是对应的运行时解析 API。
另一个插件自行 resume 后，TUI 复用分支不会重新应用这些步骤，生命周期 owner 也属于原调用插件。
来源见 [TUI 恢复准备](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/plugin.ts#L2854)
和 [公开 exports](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/package.json)。

## 进一步缩小的上游接缝

固定 TUI commit 内部已经有启动 Promise：
[创建结果](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/plugin.ts#L735)
及 [打开 profile row 后的完成处理](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/plugin.ts#L2747)。
这缩小了可向上游提出的改动位置，但它不是公开插件 API，Rotom 不导入或改写这些内部实现。
即使上游公开该结果，仍须同时处理既有 agent 的初始化结果；单独暴露当前 Promise 不能排除复用分支的未提交初始化。

2026-10-24 补查的官方 [最新发布入口](https://github.com/ccch1mneyyy/dsh-TUI/releases/latest)
仍指向 `v0.16.1`。可读取的 main package/startup 快照仍有直接复用分支；未能固定当前默认分支
HEAD，部分公开 API 文件也未取得，因此这次检查不是对当前 main 的完整定版审计，不据此断言所有后续版本均无能力。
锁、运行包和生产准入均未因本次只读取证改变。

## 推荐解法：首版严格恢复拒绝复用

首选向上游提出两个有界能力：在严格恢复的实际复用分支拒绝已有 Agent，以及公开与前台绑定
关联的初始化成功结果。首版不等待 Core 建立面向所有 Agent 的初始化查询服务，也不要求支持
同进程复用。这里拒绝的是新宿主进程内部已有的 Agent；外部进程的占用仍由官方 writer 排他处理。

建议的执行顺序如下，均为待上游实现和验证的契约：

1. 启动前固定确切目标及严格恢复策略；目标缺失、writer 冲突、加载失败均不回落新会话。
2. 在 `resolveAgent` 的 `existing !== undefined` 分支立即拒绝，包括已成功和仍在初始化的
   Agent。启动前只检查一次 registry 为空不能替代此策略；检查后发生的竞争仍交由官方
   resume 的 writer/身份准入拒绝，不捕获冲突再转入复用。
3. 继续使用 TUI 原有的 mount reservation、持久 preset/route 和 setup，等待官方
   `ctx.agents.resume(...)` 成功返回。Rotom 不接管这些内部 helper 或 handle 所有权。
4. 待对应会话被 channel 实际采用，才公开该次初始化结果及实际 session/cwd、绑定代际。
   现有内部启动 Promise 是接缝线索；仅将它原样 export，既没有解决复用问题，也没有自动
   证明结果对应当前前台。公开结果必须说明与采用操作的顺序和失效关系。
5. Rotom 将宿主事实关联到本次新 run，并核对实际部署、native HOME/scope 与前台绑定。
   只有证据一致才报告 `restored`；超时或连接丢失为未知，不重新派发，也不把等待预算结束
   解释为宿主一定失败。后续继续输入仍有独立的可输入与接收确认门槛。

**完成的含义有限且明确**：指定历史会话在官方 writer 保护下完成加载、初始化并绑定到前台。
不要求证明模型已执行任务、所有后台工作永久健康或退出时的最终封口；这些属于其它时点的事实。
后续撤销使当前控制资格失效，但不抹掉之前已经确认过的加载事实。

### 公开接口可以保持很小

优先考虑在已有公开 `ChannelUi` 的读取/订阅机制上增加初始化结果，或提供具有同等语义的
保留结果 Promise；具体名称由上游决定。概念上只需要：本次启动身份、pending/committed/failed
状态、成功来源为严格 resume、实际 session/cwd、对应绑定代际，以及有限失败分类。
晚加入者能取得结果，读取时能核实它仍属于该 channel 生命周期和绑定；切换、重载或 owner
撤销后，旧成功不能被用来证明新的前台，即使 session ID 再次相同。
结果须能在正常聊天启动期间取得，不能要求用户先切换到观察用 scene。若 `ChannelUi` 的
可获取范围不能满足这一点，应选择公开插件服务或启动调用者可取得的结果，不能借用内部 getter。

初始结果与后续观察可以共用现有 generation/version/subscription，但必须核实组合语义。
首版不向上游要求完整事件重放、持久审计日志或 Rotom 批次协议。若观察有缺口且无法补齐，
Rotom 保留未知；不能因为精简上游接口而取消现有无遗漏观察或失效检测要求。

将来若需要复用，可另行扩展 Core：为确切 Agent 生命周期提供创建者共享的初始化结果，
TUI 等待其成功后再复用。不能仅按 session ID 缓存成功，因为旧 Agent 退出后同 ID 可以
对应另一个初始化过程。这个扩展不作为首版严格恢复的前置。

## 能力验收边界

公开启动契约仍须满足下表；其中拒绝复用是推荐的首版选择，而非要求首版同时支持两种策略：

| 能力 | 必须说明的语义 |
| --- | --- |
| 严格目标策略 | 明确指定目标；缺失、writer 冲突或加载失败均失败，不转新建、最近会话或 safe-mode 冷启动 |
| 既有 agent 策略 | 允许受控恢复在精确复用点拒绝既有 agent；若允许复用，则返回其已提交的初始化成功结果，不能只返回 registry 命中 |
| 完成结果 | 官方 resume/setup/全部会影响成功的发布监听器已完成后，报告实际 session、cwd、绑定身份及 `resumed` / `reused` 来源；失败有固定分类 |
| 当前状态与订阅 | 插件晚加入也能读取当前结果；snapshot 与事件之间有可核验代际和序号，失效、切换及回滚不能沿用旧成功 |
| 生命周期边界 | 结果绑定相应 agent/owner；区分初始化成功、可输入、后续停止最终封口，不把它们合成一个 ready 布尔值 |

Rotom 自己生成 run ID 并用父子通道关联结果，不要求上游实现 Rotom 的任务、批次或授权协议。
原生 writer 仍由官方恢复事务取得并持有；上游契约不要求 Rotom 预抢同一把锁，也不绕开 JSONL 平台限制。
返回结果不需要包含消息正文、完整 trace、凭据或会话文件内容。

## 现有版本的替代路线与停止条件

“新进程 + 封闭受管配置”是可检验的另一条假设：若能证明实际加载的完整插件组合只有 TUI
会打开目标，且公开前台绑定严格发生在该官方 resume 成功后，就可能无需新增上游接口。
但新进程本身没有这种保证：Core 的配置式 Agent 可以在启动时创建/恢复，用户层配置和其它
插件也必须纳入证明。当前 Rotom 启动模板没有提供这种完整组合的排除证据，不能把它当作已
可用的开关。要选择这条路线，须先明确支持的受限配置与漂移拒绝规则；不能静默禁用用户插件。

本轮并行核对了两个具体替代入口：

- 固定版本包的公开 `runProfile` 返回 `{ ctx, shutdown }`，等待 `boot`、Loader 和 required-entry
  audit；现有调用链未提供精确 session 初始化的返回结果。挂载成功、进程退出和加载完成
  是不同事实，不能仅凭该 Promise fulfilled 宣告恢复成功。包缓存的身份关联记录弱于从
  当前完整锁重建，这部分仍是有限源码证据。
- 公开 `TuiSceneProps.channel` 确实有 `resumeTo(sessionId): Promise<ResumeResult>`，可以
  等待一次指定会话切换。其磁盘分支保留 preset/route/setup 并等待官方 resume，但已有 Agent
  的分支会采用 live target，不能仅凭调用可 await 就断言经过严格重新加载；
  当前目标不操作、采用已有 Agent 和从盘恢复都返回同样的 `{ ok: true }`，公开
  `ResumeResult` 没有来源字段，因此也不能在返回后据此筛掉复用结果。
  `tui/session-switched` 则是通知而非发起命令的接口。
  见 [公开 channel 签名](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/adapter/ports/channel-ui.ts#L554)
  和 [切换实现](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/channel/session-resume.ts#L145)。
  内部启动 placeholder 提供了一条有条件的实现路径，但本轮未证明它在公开 scene 可调用时
  具有可用 agents，也未证明与原始 pending 启动的竞争语义；不能把它视作已公开的延迟启动模式。

任何后启动切换方案还须解决起始状态，不能先随意创建空会话再切换来满足“目标缺失不得
新建”的要求。没有新的接口或路径证据时，不再重复靠等待、额外 nonce 或读取次数尝试
制造初始化成功证明。

已整理[上游 issue 草稿](upstream/dsh-strict-startup-proposal.md)，包含严格拒绝复用、公开结果的
最小语义和验收矩阵；两个文件均尚未发送，当前不计划提交。此路线是可选研究，不属于交付依赖。
T042/T047 可围绕现有官方入口推进有界交接与状态分层；T053 独立验证真实交接、加载人工观察
和 writer 竞争。提案、内存模拟及人工观察都不能单独证明机器可信加载确认或开放自动继续。

### Core 内存创建反例的隔离执行

新增手动探针 `tests/manual/dsh_initialization_probe.mjs`，仅使用公开 Core 根导出和 Cordis
生命周期 API，不进入默认测试。它挂起 `agent/created` 的 Promise gate，确认 registry 已
可查询目标而创建仍未完成，然后分别释放成功或抛出合成错误；没有按固定等待时长推断提交。

2026-10-24 在独立 PID/网络命名空间、空继承环境、临时 HOME、只读运行包挂载下执行，两个
case 均符合预期，退出码 0：成功返回同一 Agent；迟到失败使创建拒绝并移除 Agent/Session，
两条路径的 dispose 观察均符合预期。先前一次隔离启动因旧版 bwrap 不支持 `--clearenv` 而在
加载包前失败；改为由 Python 以空环境启动后通过，未修改探针或上游包来适配结果。

这是缓存 Core `0.2.1-rc.2` / Cordis `4.0.5` 的行为实验。8 个直接包的版本及冻结锁 integrity
字段与候选一致，186 个缓存文件在执行前后保持一致；公开 npm 归档下载失败，逐成员字节比对
未完成，完整运行包来源准入也未完成。因此不把这次实验升级为已验证官方归档、TUI 启动、
持久化加载、外部 writer 或恢复验收。它只为“registry 可见早于初始化成功”补充有界执行证据，
T042 及生产恢复能力仍未完成。

## 候选版本的验收

后续任何版本或接口组合必须先给出固定公开来源和完整依赖来源，再通过以下隔离及独立原生验证：

- 指定存在的目标只恢复该目标，实际 session/cwd 与请求关联；缺失和外部 writer 冲突均可靠失败。
- 同进程已提交 agent、仍在初始化 agent、后续监听器失败分别测试；拒绝策略不能被复用分支绕过。
- 插件晚订阅、启动结果产生时切换、owner 撤销、事件缺口和旧 run 消息均不会误报本次成功。
- 实际受管 profile 配置使用目标 runtime/native HOME/scope，继承的 backend handoff 和 retry 不会改变目标。
- 完成回执不释放原生 writer；宿主关闭时才按官方生命周期排空并释放。排空失败不得虚构最终封口。
- 普通 resume 不发送继续文本，不恢复到其它 pane，也不停止其它进程。

本地假宿主和私有 IPC 测试只验证 Rotom 观察与拒绝机制，不能使该上游能力自动成立。
未找到满足严格回执条件的公开组合时，`restored` 与自动继续保持关闭；官方恢复交接可在范围、归属、cwd、writer 安全边界和对应验收成立后独立交付。
