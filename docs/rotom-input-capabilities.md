# Rotom 输入接收能力调查

日期：2026-10-24。状态：T097 的公开接口调查与独立 fake 原型完成；原生验收未执行，自动继续未开放。
本轮范围为 TUI `0.16.1` / commit `73ff99fbed56563bf154d719effd09f9f9725349`，
Core `dsh-v0.2.1-rc.2`。不据此判断其它工具、版本或平台。

## 接收与完成分别判断

自动继续需要证明本次批准的输入被确切目标接收；它不要求等待模型执行完整个任务。
函数返回 `void` 本身不足以否定接收确认，仍须检查公开事件能否唯一关联本次调用。
接口调查也不代替新 run、前台 session、input-ready 以及 writer 排他覆盖的证明。

| 路径 | 已核实的事实 | 当前边界 |
| --- | --- | --- |
| TUI scene 的 `channel.submit(text)` | 提交时捕获 session 和绑定 generation，异步派发前拒绝过期目标 | 返回 void，不接收调用方消息 ID，也没有与该次文本关联的公开接收结果 |
| Core `Agent.followup(UserMessage)` | 接收带 ID 的消息，原样传入 inbox；公开 `agent/inbox/inserted` payload 包含精确 agent 与 message | 可形成一次 live inbox admission 的候选回执；不能直接替代前台归属、ready 或 writer 证明 |
| pending 重复 ID | 插入时拒绝已在 pending 队列的重复 ID | 不是幂等成功；没有据此证明跨 pending 生命周期的去重 |
| `whenIdle()` | 描述 agent 整体活动结束 | 不对应特定输入的接收或执行结果 |
| inbox claimed | 带消息和 turn，证明该消息从队列取出 | 不单独证明本次调用的接收，也不证明已进入模型 step 或执行完成 |

## 有证据的候选路线

未来候选可先订阅公开 `agent/inbox/inserted`，为本次明确批准的输入生成唯一 message ID，
仅在持有确切 Agent 且通过前台绑定、ready 与 writer 核验后调用 `followup`。
只有观察到同一 Agent、同一 message ID 的事件，才记录本次 live inbox 接收事实。
宿主事件中的正文不写入通用回执、日志或恢复清单；只保留必要的关联标识和批准文本摘要。

事件并不证明模型执行完成。同步抛错、事件观察失败或父子确认丢失时，可能存在已接收结果；
必须保存 unknown 并先对账，不能根据 `void` 返回或 pending 重复拒绝自动重发。
当前没有可据以开放跨重启幂等重放的证据。

直接 Core 路线与 TUI scene 提交是两种公开调用方式。scene 的文本提交不能仅靠相同文本或时间
窗口关联到 Core 事件；候选必须使用其自己可提供唯一 ID 的公开调用，不猜内部消息生成方式。
TUI scene 的 ready 只描述绑定状态；直接拿到 bare Agent 也不证明当前前台归属或原生 writer 仍有效。

## 固定公开来源

- [TUI ChannelUi 接口](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/adapter/ports/channel-ui.ts#L47)：ready、sessionRef、绑定 generation 与 submit 的公开类型。
- [TUI 排队与派发实现](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/channel/input-delivery.ts#L142)：捕获 session/绑定代际，异步派发时拒绝过期目标；源码调查不构成允许导入的私有路径。
- [TUI scene props](https://github.com/ccch1mneyyy/dsh-TUI/blob/73ff99fbed56563bf154d719effd09f9f9725349/src/dsh-adapter/scenes.ts#L32)：场景取得的 channel 视图。
- [Core Agent 运行时接口](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent/src/runtime-types.ts#L187)：followup 和公开 inbox 事件。
- [Agent 插入与唤醒顺序](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent-loop/src/agent.ts#L143)：先插入消息，再唤醒运行循环。
- [Inbox 插入事件与重复 ID 检查](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent-loop/src/inbox.ts#L181)：插入后的公开事件、pending 重复标识拒绝。
- [Core AgentHandle 与 bare Agent](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/core/agent/src/index.ts#L138)：创建者的处置能力与查询得到的 Agent 不能混为 writer 所有权。

## 隔离原型与能力结论

仓库内 `tests/fixtures/rotom/input-channel-probe.py` 仅注入假 transport；它不是宿主适配器。
测试显式提供新 run、确切已加载会话、同一 Agent、前台代际、input-ready、writer 覆盖和观察完整性。
这些是假定已具备的前提，不能从 bare Agent 或 inserted 事件自行推导。没有增加上游 sequence 字段；
观察缺口由测试显式报告，尚无真实宿主的完整性检测实现。

原型先保存仅含身份与文本摘要的意图，再订阅事件、重核目标，并尝试一次发送。
只有本次发送窗口内的同一 Agent 与 message ID 匹配才可记录 live inbox 接收；
旧事件、重复/冲突、目标变化、订阅或取消订阅异常、观察丢失和响应丢失均保留 unknown。
取消订阅后再次核对目标；未知不重发。正文只在当次调用内存中使用，不写入意图、快照或错误。
严格 UTF-8 编码失败在保存意图前拒绝，不规范化或截断用户正文。

输入与停止假原型合计 **90 passed**；取消订阅后目标变化与不可编码正文的边界各有先行失败记录。
普通日常 resume 仍为零发送。该结果不证明模型执行完成、跨重启去重或真实输入准入；
能力 fixture 中 DSH、Pi、OMP 的自动继续均为 unavailable。

普通恢复交接允许保持“加载待确认”，不再等待上游提供严格初始化回执。自动继续仍需要上述
前台、加载、ready 与 writer 证据，以及独立原生验收。本轮没有启动宿主、发送真实文本或调用模型。
`resume --help`、未准入提示及候选运行中的待确认提示提供人工路径：先在官方 TUI 核对
会话 ID、原目录和历史，再自行聚焦输入框并手工输入或复制所需指令。固定“继续”示例只是说明，
不代表已经批准发送；Rotom 不读取或操作剪贴板、不聚焦其它窗口、不发送按键。
候选已增加独立的人工交互指引：只有显式使用根 `--interactive` 才显示可跳过的菜单，
可选择仅恢复、固定“继续”示例或自定义单行文本。完整参数的默认调用及 `--no-input` 不增加输入步骤。

```sh
./rotom --interactive resume dsh --machine workstation --session example
```

文本先预览，再确认仅用于本次手工复制；不传给恢复后端，不写入恢复请求、运行记录、日志或 JSON。
自定义文本最多 4096 字符、UTF-8 16384 字节，拒绝不可打印字符；合法首尾空格保持原样。
指引发生在启动前，空输入、EOF、Esc、Ctrl-C 或拒绝确认取消本次操作；宿主运行期间不追加菜单读取。
用户仍须在官方 TUI 核对会话 ID、原目录和历史，然后自行聚焦和输入。文字预览不是加载确认或发送批准。
当前日常恢复尚未准入，查看人工指引后仍返回 5；受控候选则继续原有恢复核验并保留原生退出码。
T096/T101/T102 的人工分支已验收：最终 continue/resume CLI 68 条、专属 help 2 条通过；
受管恢复代码的两条 fake 链确认正文不进入原生参数、RunRecord 或 ResumeAttempts，原退出码保持。
恢复/输入模型/维护纯数据的相关回归 240 条通过；这些集合有重叠，不合计成全库通过。
自动输入和真实恢复的门槛不变；没有运行官方宿主、发送真实文本或调用模型。

相关边界见 [生命周期契约](../specs/008-rotom-command-experience/contracts/lifecycle.md#原位置与继续)
及 [严格启动契约需求](rotom-dsh-startup-contract.md)。
