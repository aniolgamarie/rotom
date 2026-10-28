# Rotom 原终端位置恢复能力

状态：最终十二组无 trace 原生验收全部通过，现开放下列六个精确 Linux managed 工具/profile/锁与运行包组合的原 pane、新标签页共十二条准入。普通 --session 位置恢复不开放。下文 T086 有限 fake 模型和早期 Pi 核心探针属于历史证据，不能替代当前实现的真实 Herdr/工具验收，也不因文档更新而新增通过结果。

## 实现与准入范围

候选实现覆盖两种位置：Herdr 新标签页，以及由 Rotom Herdr 入口新建的受支持托管实例的原 pane。原 pane 采用薄驻留启动器，只管理官方 Agent 的启动、退出和明确请求后的恢复；不修改 Agent，也不向 TUI 自动输入。

- 在下列已准入组合中，Rotom Herdr V1/V2 新建的 DSH/Pi Agent 以及符合驻留组合的新 tab 恢复默认保留启动器；停止 Agent 后原 pane 显示“等待恢复”，释放单次运行资源，明确请求后使用新 run 请求同一 session 和原 cwd。
- 普通 shell 的 `rotom run` 仍在 Agent 退出后返回 shell。仅在 Herdr 内启动、刚启动、直接运行官方 CLI，或仅升级配置，都不使旧普通实例获得原位能力。
- launcher 或 pane 关闭、被复用、归属未知或管理代码不兼容时，不能原位恢复；保留停止记录，提供当前终端或经过用户接受的新位置。
- 新标签页需要 Herdr 的可核验公开 API。逐项记录创建、交接、失败和未知；可能已经创建的请求先查询，不自动重复开页。恢复后等待人工输入。

help 和命令提示区分已准入组合与不支持的来源、平台及位置。maintenance plan 和停止交互批准附加 location_diagnostics，逐项解释可用、不支持、launcher/pane 丢失或未知；这只是只读观察，不进入 plan_id、不授予恢复许可。停止清单 location_request 仅投影已有位置请求与 receipt，不重新加载配置或推断可用性。没有观察证据时不造出可用结论。

统一的严格加载成功回执、原生 TUI 自动继续不在本轮承诺中。已有观察可以展示准确的 session/cwd，但缺回执仍是“加载待确认”、`continue=not_sent`，不会因驻留而升级成已恢复。Pi Pro 委派独立于本功能；`pi-pro` 作为普通 profile 的停止、更新与恢复兼容性仍在维护范围内。

## 本轮精确组合验收清单

下列身份以短前缀展示，实际判定使用完整 identity。最终十二组无 trace 原生验收均退出 0，下面六组合的原 pane、新标签页已逐项准入。验收源码身份为 `4b1779e5f99374dc91493e016471b088567ae37d7c5ec659ee40ed9900bc9755`；公开十二条键与验收表逐字相同。main 的 Pi 锁 `a68d9dcf…` 仅作为只读兼容输入，不吸收或修改其本地文件。

| 工具 / profile | 完整锁前缀 | 运行包前缀 | 原 pane | 新标签页 |
| --- | --- | --- | --- | --- |
| DSH / dsh-default | `e4d56f338da80e78` | `e4d56f338da80e78` | 已通过并准入 | 已通过并准入 |
| Pi / pi-base，候选锁 | `62ac8348c3433959` | `d97010399b8648a2` | 已通过并准入 | 已通过并准入 |
| Pi / pi-pro，候选锁 | `62ac8348c3433959` | `2b087056df46cc40` | 已通过并准入 | 已通过并准入 |
| Pi / pi-base，main 保留锁 | `a68d9dcf3346c0c6` | `567d64966f7b4d9b` | 已通过并准入 | 已通过并准入 |
| Pi / pi-pro，main 保留锁 | `a68d9dcf3346c0c6` | `b4beec0dc0f4058f` | 已通过并准入 | 已通过并准入 |
| OMP / omp-default，Linux x64 | `490e6c90d0ef4d89` | `490e6c90d0ef4d89…-linux-x64` | 已通过并准入 | 已通过并准入 |

上述十二组原始验收绑定 `4b1779…`，后续共享预算修正另有绑定其源码的 Pi Base 双会话复验。T141/T142 的当前源码为 `86275882bdcd0a7cbc437a5cf4ee5332c3f4e919f8c72810a7a1735a51da8f55`：OMP 双会话正式流程已通过，Pi 四个既有锁/profile 的新自有来源均独立完成单项3run正式复验，连同OMP共5组18次官方运行通过；本轮没有重跑 DSH 或 V1/V2 四项工作入口，不把旧矩阵和完整隔离快照称作新源码全部重跑。最终状态见[最新验收记录](../specs/008-rotom-command-experience/tool-workflow-validation.md)。

本清单只针对 Linux managed。新的运行包 identity 需重新验收；SSH、其它平台及未列出的组合不继承这些位置能力。Pi Pro 在此指普通 profile 的维护/恢复，不包含委派。

Herdr 新 Agent 入口另有四项正式通过：

| work 入口 | DSH | Pi |
| --- | --- | --- |
| V1 | 已通过 | 已通过 |
| V2 | 已通过 | 已通过 |

OMP 没有默认 work type；它通过已准入的新标签页恢复建立 resident，随后可按同样门禁原位恢复。普通 shell、旧单次实例与普通 `--session` 位置恢复均不因此获得原位能力。

此前完整 delivery-verification 快照为14,166个唯一默认隔离测试：14,153 passed / 13 skipped / 0 failed；共享预算修正另有3740 passed / 4 skipped及官方Pi Base双会话原生复验，见最新验收记录；`14102 + 13 skipped` 属于前一源码快照历史。功能仍在任务分支，尚未合入 main，T125 待人工批准；位置与隔离验收不推导整合完成。

## 从完整 workflow 请求位置恢复

先对同一批次完成精确停止与独立批准的 setup/update，再请求一个位置。旧独立 stop 快照、缺日志残留、取消/未知/已有派发记录不能取得位置许可。以下 BATCH_ID/RUN_ID 需替换为完整32位小写十六进制 ID；命令只在上述精确已准入组合与通过现场门禁的完整 workflow 内执行。

```sh
./rotom resume --stopped --list --format human
./rotom --no-input resume pi --profile pi-base --stopped --batch BATCH_ID --run RUN_ID --new-tab --format json
./rotom --no-input agent --profile pi-base maintenance restore --batch BATCH_ID --run RUN_ID --original --format json
./rotom --no-input resume pi --profile pi-base --stopped --batch BATCH_ID --all --new-tab --format json
./rotom --no-input resume pi --profile pi-base --stopped --batch BATCH_ID --all --original --format json
```

`--all` 必须指定 batch 和非 here 位置，不能带 --run/--session/--list/--here；整批须同 scope/profile/batch，任一坏记录、来源不明或不可恢复项都先拒绝整批。分发前逐项重查，各项独立终端、独立意图；首个失败或未知后停止后续项，未执行项标为 not_dispatched，保留此前结果。JSON 只有一个汇总，全部交接才返回0，否则4。默认 here 仍只交接一项，不争用 stdin。

位置恢复的 `--wait-seconds` 默认30秒，可显式设为1–300秒，仅用于 `--original` / `--new-tab` 的准备和交接。目标明确后开始计时，整批核验、逐项重查、Herdr/bootstrap及原位socket共用一个绝对单调截止时间，不按项目或响应分段续期；交互选择耗时不计入。到期后返回4，保留已发生及未知事实，后续项为 `not_dispatched`。已在期限内发出的请求可能稍后完成，超时不表示撤回，须先查询原批次，不自动重发或强杀。预算不限制已交接官方Agent的运行时长；普通 `--session`、`--here` 和只读 `--list` 不接受此参数。

原 workflow 的 restore-intent 先持久化，再建立目录0700/文件0600的位置请求。request 固定目录 device/inode、精确 session/cwd、scope、workflow/deployment 和 manager 源码身份，不包含任意 argv、环境、秘密或会话正文。新 tab 只调用一次公开 tab.create；payload 使用专用 ROTOM_RESTORE_LAUNCH_V1，ready/committed/handoff 与 child 的 executing CAS 分开。原 pane 通过私人 socket 与 manager 出生身份核验，只发送请求引用，不向 pane 注入文本。响应丢失或写后失败保留未知状态，不重发。

## 两条路线的能力边界

| 路线 | 已有公开能力 | 核验要求与证据 | 首版判断 |
| --- | --- | --- | --- |
| Herdr v0.9.5 原生恢复 | reporter 提交 session 引用与 `resume_argv` 后，server 重启可在原逻辑 pane 和目录恢复 Agent | 逐项维护后的精确恢复请求、跨 server 的新身份核实、实际 session 加载与请求结果对账 | 保留平台自身恢复语义，当前不能据此开放逐 pane 的原位维护恢复 |
| Rotom 现有 manager 的驻留扩展 | 本仓库可以在单次运行之外保留启动器，不需要修改上游 Agent；官方 Pi 的稳定父进程/同一 PTY 核心探针已通过 | 三工具分别验证完整退出与资源释放、parked、私人控制端点、代际与一次请求消费、管理代码身份，以及真实 Herdr 绑定和故障路径 | 六个精确 Linux managed 组合已完成最终原生验收并准入；其它组合不继承 |

当前仍可使用独立于 Herdr 的 here 交接或人工恢复；新位置候选需明确请求和独立准入。旧单次实例不会在线转成驻留容器。原位能力不足不授权关闭其它实例、重启整个 Herdr server 或向 pane 注入命令。

## 核心可行性证据与缺口

2026-10-27 的隔离 Pi 探针使用未经修改的锁定官方程序和真实公开 CLI：稳定父进程保留同一 PTY，停止旧 run 后完成实际 setup 更新，再以新 run 请求原 session/cwd；父进程跨维护存活，两次宿主退出 0、终端属性还原、恢复输入 0 字节。源码摘要、原始命令与日志保存在私人任务记录。这只证明启动器保留终端的核心路线可行，不证明 Herdr 端点、绑定、重复请求、生产代码更新兼容，也不类推为 DSH/OMP 的驻留验证。

生产候选现由 agentcfg/{pane_records,restore_locations,tool_maintenance}.py、rotom/{resident,pane_dispatch,restore_child}.py 与 termcfg/restore_tabs.py 实现。T134 只完成历史提示核对；本次源码、隔离测试和真实位置验收须分别判断，不把历史任务快照当作当前未实现结论。任务及历史替代关系见 [tasks.md](../specs/008-rotom-command-experience/tasks.md)。

## Herdr 公开来源与解释

[固定 v0.9.5 的集成说明](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/add-herdr-support.mdx) 说明 reporter 可提交原生 session 与恢复命令，server 恢复时执行它。自定义集成须先通过 `pane.report_agent` 持有相应 pane；恢复可由 `resume_agents_on_restore` 设置关闭。命令数组仍需符合上游参数限制，不能由 Rotom 拼接任意 shell 文本。

[同版本的 pane schema](https://github.com/herdrdev/herdr/blob/v0.9.5/src/api/schema/panes.rs) 声明 `pane.report_agent` / `pane.report_agent_session` 的 `resume_argv`。这项能力与 [公开 Method 枚举](https://github.com/herdrdev/herdr/blob/v0.9.5/src/api/schema.rs) 一起核验；该枚举没有 `pane.restart` 方法。不能只看 Rotom 的 allowlist 或部分 fixture，就推断上游没有其它能力。

[同版本 socket API](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/socket-api.mdx) 区分 pane 的保存目录与可选 `foreground_cwd`；`layout.apply` 创建替代布局，不保留原 PTY 或进程。请求 ID 用于匹配响应，公开契约没有把它定义为可在丢包后重放的幂等键。`pane.run` / `send_input` 的成功只确认进入队列，不能证明 Agent 收到文本或加载了目标 session。

pane 身份必须结合 server 代际和实时观察；“原逻辑 pane”不证明重启后外部保存的旧 ID 仍可使用。工作区移动和 pane 关闭也须重新核实，不能按标题、焦点或 PID 猜测。

## 驻留候选的不变量

驻留 manager 只管理启动和退出，继续使用官方 Agent 与本仓库现有 runtime。单次 run、manager 容器和原生 session 是独立身份。

- 宿主及相关后代完整退出、单次运行租约全部结束后，才能进入 `parked`；不能保留旧环境、秘密或运行包对象。会话封口缺失与进程释放分别展示。
- Agent 活动期间，驻留 parent 只等待 child 退出，不读取 owner/Domain。容器此时可尚无 run_id；停止前的位置诊断按 child_identity 与严格 RunRecord.manager_identity 的完整出生身份按需关联，查询不回写。这个候选关联不能用于原位交接；退出后核验唯一出生身份及完整 release、记录真实 run_id 才可 parked。原位消费还要求 saved run_id 与目标相同、child_identity 为空，旧 run 的延迟请求拒绝。
- 原位 socket 请求绑定 container、generation 与受保护 request_root；不可变位置请求再绑定 request_id、workflow batch/run、部署、源码与确切 SessionRef，恢复创建新 run；先保存请求意图，再消费一次许可。响应丢失先只读对账，结果未知时不重发。
- 管理源码或控制协议变化后，首版要求明确的新位置；旧 manager 不能混用新模块。旧单次实例首次采用须重新审阅。
- 普通恢复等待人工输入，本轮不提供自动继续。Herdr 入队或交接成功不等于 Agent 已加载会话，更不等于已经收到继续文本。

合成核验输入保存在 `tests/fixtures/rotom/pane-capabilities.json`。它们不证明真实原位恢复已经可用；准入仍须满足生命周期契约及 P-SESSION、P-EXIT、P-PANE 的独立验证。

## 驻留模型的隔离结果

`tests/fixtures/rotom/resident-pane-probe.py` 是单个停止/恢复周期的有限模型。它不提供端点、进程、信号、PTY 或输入实现，不是可直接挂入生产的驻留启动器。

模型将 container 代际、manager 出生身份、代码/协议、端点身份以及 server/pane/cwd 固定在同一绑定中。每次受信回调前后核实绑定；pane 重用、目录移动、manager 丢失或代码变化不能沿用旧批准。

进入 parked 需要同一旧 run 的完整退出观察，以及实例、原生 HOME、运行包三类租约均已释放的明确假观察。成功后模型清除旧运行上下文引用。历史模型将缺封口作为自动恢复限制；当前交付沿用日常官方交接规则：严格封口/加载回执不足不单独阻断已准入的明确交接，仍须核实目标、目录、部署和该工具 writer 防护，并保持加载待确认、零自动输入。

恢复仅接受深拷贝保存的精确批准：先调用保存意图回调，再消费一次许可，最后调用一次启动回调。任意阶段响应丢失保留 unknown，重复请求不能再次启动。模型仅在匹配新 run 和确切 SessionRef 的 loaded 假观察后转为 running；这不是生产交接的前置，也不能将容器有活动子进程等同于 session 已加载。队列接收不算加载完成，普通恢复不注入继续文本。

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_pane_probe.py
```

该历史模型阶段 **58 passed，退出码 0**，含“运行包租约尚未释放却错误进入 parked”的有效 RED 与修复后结果。命令、源码摘要及日志保存在私人任务记录。回调顺序通过不代表真实落盘、真实许可消费或官方 session 加载；候选生产实现已经加入端点鉴权、稳定终端绑定和驻留生命周期；该模型结果不证明生产原生验收；当前生产支持由上面的最终十二组无 trace 原生结果单独确立。
