# Rotom 原终端位置恢复能力

状态：原 pane 和新标签页恢复尚未开放。T086 已完成公开接口比较和有限 fake 原型；2026-10-27 另以官方 Pi 验证了稳定父进程保留同一 PTY、停止/更新后创建新 run 的核心可行性。该探针没有接入 Herdr、生产驻留控制端点或工作区绑定，不能算原 pane 功能验收。

## 已选择的交付范围

下一阶段交付两种位置：Herdr 新标签页，以及由 Rotom Herdr 入口新建的受支持托管实例的原 pane。原 pane 采用薄驻留启动器，只管理官方 Agent 的启动、退出和明确请求后的恢复；不修改 Agent，也不向 TUI 自动输入。

- 对已经完成该工具驻留验收的 Rotom Herdr 新实例，入口默认保留启动器；停止 Agent 后原 pane 显示“等待恢复”，释放单次运行资源，明确请求后使用新 run 请求同一 session 和原 cwd。
- 普通 shell 的 `rotom run` 仍在 Agent 退出后返回 shell。仅在 Herdr 内启动、刚启动、直接运行官方 CLI，或仅升级配置，都不使旧普通实例获得原位能力。
- launcher 或 pane 关闭、被复用、归属未知或管理代码不兼容时，不能原位恢复；保留停止记录，提供当前终端或经过用户接受的新位置。
- 新标签页需要 Herdr 的可核验公开 API。逐项记录创建、交接、失败和未知；可能已经创建的请求先查询，不自动重复开页。恢复后等待人工输入。

help 和命令提示必须区分“当前未开放”和上述启用条件。实现后的只读能力诊断与停止计划还须逐项解释：可用、不支持、launcher/pane 丢失、身份或请求结果未知，并给出准确范围的下一步；没有观察证据时不造出可用结论。这些诊断属于 T085/T091/T095/T135–T138 的待实现验收，不是当前已存在的结构化字段。

统一的严格加载成功回执、原生 TUI 自动继续不在本轮承诺中。已有观察可以展示准确的 session/cwd，但缺回执仍是“加载待确认”、`continue=not_sent`，不会因驻留而升级成已恢复。Pi Pro 委派独立于本功能；`pi-pro` 作为普通 profile 的停止、更新与恢复兼容性仍在维护范围内。

## 两条路线的能力边界

| 路线 | 已有公开能力 | 本功能还需要的证据 | 首版判断 |
| --- | --- | --- | --- |
| Herdr v0.9.5 原生恢复 | reporter 提交 session 引用与 `resume_argv` 后，server 重启可在原逻辑 pane 和目录恢复 Agent | 逐项维护后的精确恢复请求、跨 server 的新身份核实、实际 session 加载与请求结果对账 | 保留平台自身恢复语义，当前不能据此开放逐 pane 的原位维护恢复 |
| Rotom 现有 manager 的驻留扩展 | 本仓库可以在单次运行之外保留启动器，不需要修改上游 Agent；官方 Pi 的稳定父进程/同一 PTY 核心探针已通过 | 三工具分别验证完整退出与资源释放、parked、私人控制端点、代际与一次请求消费、管理代码身份，以及真实 Herdr 绑定和故障路径 | 已选实施路线；生产实现及逐工具原生验收前不开放 |

当前保留用户明确接受的新位置或人工恢复。旧单次实例不会在线转成驻留容器。原位能力不足不授权关闭其它实例、重启整个 Herdr server 或向 pane 注入命令。

## 核心可行性证据与缺口

2026-10-27 的隔离 Pi 探针使用未经修改的锁定官方程序和真实公开 CLI：稳定父进程保留同一 PTY，停止旧 run 后完成实际 setup 更新，再以新 run 请求原 session/cwd；父进程跨维护存活，两次宿主退出 0、终端属性还原、恢复输入 0 字节。源码摘要、原始命令与日志保存在私人任务记录。这只证明启动器保留终端的核心路线可行，不证明 Herdr 端点、绑定、重复请求、生产代码更新兼容，也不类推为 DSH/OMP 的驻留验证。

生产工作仍为 T085/T087–T095；新标签页工作为 T135–T138。T134 仅完成当前 help/拒绝信息与规划核对，不表示上述实现完成。任务及历史替代关系见 [tasks.md](../specs/008-rotom-command-experience/tasks.md)。

## Herdr 公开来源与解释

[固定 v0.9.5 的集成说明](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/add-herdr-support.mdx) 说明 reporter 可提交原生 session 与恢复命令，server 恢复时执行它。自定义集成须先通过 `pane.report_agent` 持有相应 pane；恢复可由 `resume_agents_on_restore` 设置关闭。命令数组仍需符合上游参数限制，不能由 Rotom 拼接任意 shell 文本。

[同版本的 pane schema](https://github.com/herdrdev/herdr/blob/v0.9.5/src/api/schema/panes.rs) 声明 `pane.report_agent` / `pane.report_agent_session` 的 `resume_argv`。这项能力与 [公开 Method 枚举](https://github.com/herdrdev/herdr/blob/v0.9.5/src/api/schema.rs) 一起核验；该枚举没有 `pane.restart` 方法。不能只看 Rotom 的 allowlist 或部分 fixture，就推断上游没有其它能力。

[同版本 socket API](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/socket-api.mdx) 区分 pane 的保存目录与可选 `foreground_cwd`；`layout.apply` 创建替代布局，不保留原 PTY 或进程。请求 ID 用于匹配响应，公开契约没有把它定义为可在丢包后重放的幂等键。`pane.run` / `send_input` 的成功只确认进入队列，不能证明 Agent 收到文本或加载了目标 session。

pane 身份必须结合 server 代际和实时观察；“原逻辑 pane”不证明重启后外部保存的旧 ID 仍可使用。工作区移动和 pane 关闭也须重新核实，不能按标题、焦点或 PID 猜测。

## 驻留候选的不变量

驻留 manager 只管理启动和退出，继续使用官方 Agent 与本仓库现有 runtime。单次 run、manager 容器和原生 session 是独立身份。

- 宿主及相关后代完整退出、单次运行租约全部结束后，才能进入 `parked`；不能保留旧环境、秘密或运行包对象。会话封口缺失与进程释放分别展示。
- 恢复请求绑定 container、generation、op、新 run、部署与确切 SessionRef；先保存请求意图，再消费一次许可。响应丢失先只读对账，结果未知时不重发。
- 管理源码或控制协议变化后，首版要求明确的新位置；旧 manager 不能混用新模块。旧单次实例首次采用须重新审阅。
- 普通恢复默认等待输入。“继续”有独立的目标、文本和就绪批准，不能由 Herdr 入队响应代替 Agent 接收确认。

合成核验输入保存在 `tests/fixtures/rotom/pane-capabilities.json`。它们不证明真实原位恢复已经可用；准入仍须满足生命周期契约及 P-SESSION、P-EXIT、P-PANE 的独立验证。

## 驻留模型的隔离结果

`tests/fixtures/rotom/resident-pane-probe.py` 是单个停止/恢复周期的有限模型。它不提供端点、进程、信号、PTY 或输入实现，不是可直接挂入生产的驻留启动器。

模型将 container 代际、manager 出生身份、代码/协议、端点身份以及 server/pane/cwd 固定在同一绑定中。每次受信回调前后核实绑定；pane 重用、目录移动、manager 丢失或代码变化不能沿用旧批准。

进入 parked 需要同一旧 run 的完整退出观察，以及实例、原生 HOME、运行包三类租约均已释放的明确假观察。成功后模型清除旧运行上下文引用。历史模型将缺封口作为自动恢复限制；当前交付沿用日常官方交接规则：严格封口/加载回执不足不单独阻断已准入的明确交接，仍须核实目标、目录、部署和该工具 writer 防护，并保持加载待确认、零自动输入。

恢复仅接受深拷贝保存的精确批准：先调用保存意图回调，再消费一次许可，最后调用一次启动回调。任意阶段响应丢失保留 unknown，重复请求不能再次启动。模型仅在匹配新 run 和确切 SessionRef 的 loaded 假观察后转为 running；这不是生产交接的前置，也不能将容器有活动子进程等同于 session 已加载。队列接收不算加载完成，普通恢复不注入继续文本。

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_pane_probe.py
```

本次 **58 passed，退出码 0**，含“运行包租约尚未释放却错误进入 parked”的有效 RED 与修复后结果。命令、源码摘要及日志保存在私人任务记录。回调顺序通过不代表真实落盘、真实许可消费或官方 session 加载；端点鉴权、稳定终端绑定和真实驻留生命周期仍待后续任务。T087 及之后的生产实现门槛保持不变。
