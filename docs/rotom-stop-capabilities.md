# Rotom 停止通道能力

状态：已准入精确 Linux managed DSH 的 `stop_only`，仅限完整运行包锁
`e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d`、由兼容版本新启动且成功登记原 host/control endpoint 的运行。
任务进度为 86/117；完整停止维护编排没有因此完成。
Pi、OMP、其它平台、旧 run、force、setup/maintenance execute/restore 均未准入。
T054 已准入的同锁 Linux DSH `resume --here` 保持有效，加载待确认、零自动继续。

## 当前用法与停止边界

`instances list` 返回完整 run ID、启动时保存的 deployment/runtime 摘要和历史会话线索。
先对同一明确机器/profile 的所选 run 做只读预览，再用当前 plan-id 明确请求停止：

```sh
./rotom agent --machine workstation --profile dsh-default instances list --agent dsh --format json
./rotom agent --machine workstation --profile dsh-default instances stop --run 11111111111111111111111111111111 --run 22222222222222222222222222222222 --dry-run
./rotom --no-input agent --machine workstation --profile dsh-default instances stop --run 11111111111111111111111111111111 --run 22222222222222222222222222222222 --plan-id PLAN_ID --wait-seconds 30
./rotom --no-input agent --machine workstation --profile dsh-default maintenance status --batch BATCH_ID --format json
./rotom --no-input agent --machine workstation --profile dsh-default maintenance cancel --batch BATCH_ID --format json
```

以上 scope/run 为虚构示例；替换为列表中的完整目标、刚审阅的 PLAN_ID 和结果中的 BATCH_ID。
非交互实际请求缺 plan-id 返回 2，不匹配返回 4；交互请求在锁外展示当前完整计划再确认。
计划摘要本身不是批准。ready 计划仍须复核部署、原 manager/host、私人 endpoint 和原租约，
先保存所选完整人工恢复快照及 fence，再逐项单次投递；默认等待 30 秒，可选 1–300 秒，
整组共用同一绝对截止时间，不逐项延长。实际停止等待未知或到期返回 4，并保留 batch 和已写事实，
不重发、不强杀、不自动恢复，也不发送继续文本。精确组合或当前现场不支持时返回 5。

`maintenance status` 只读；manager/host、目录、版本与 session 来自保存快照，
confirmed session 也只显示 historical，unknown 不补造。它们不证明当前会话加载或可恢复。
`maintenance cancel` 只取消尚未投递的活动项，或对已确证停止的收尾记录作明确对账；
可能已发送或 unknown 的项目不取消、不重试，已完成批次不重复写入。
setup 目前只有 `maintenance plan --operation setup --run ...` 只读计划；
`maintenance plan --batch`、execute 和 restore 不因此开放。完整参数见各命令 `--help`。

## 当前原生验收

已授权的隔离验收使用未经修改的锁定官方包，经默认普通 runtime 启动三项，逐项登记后同时保持活动。
真实 CLI 首轮只停前两项；第三项的 owner、manager/host 出生身份保持原样 active，inbox 无请求、
journal 无派发，共享 EX 仍不可取得。随后独立新 plan 只清理第三项。
三个 manager 均退出 0、owner 为 idle_confirmed、termios 恢复、两个原 inode 租约可取 EX，
全程输入为零，源码未变。该结果不证明并发启动、会话恢复、完整外部 writer 覆盖或维护许可。
证据与失败分类见 [默认入口的精确停止验收](../specs/008-rotom-command-experience/main-review.md#62-dsh-默认入口的精确停止验收)。

## 历史阶段：只读计划与内部保存器

以下保留实现顺序、旧失败及当时尚未接入默认控制的结论；当前准入范围以上两节为准。

纯计划与审阅回归 **130 passed**；CLI/help/交互 **3269 passed**，最终窄检查 **91 passed**；
现场预览初验 **17 passed**，范围与会话状态最终定向 **6 passed**，正式 CLI/临时部署组合
**3 passed**。结果存在重叠，不相加为全库结果；没有真实宿主、信号或原生恢复。

内部完整计划保存也已实现：v2 人工快照嵌入规范计划，与选中完整记录、部署、Registry 和全集摘要
相互校验；原 v1 格式及 API 保留。`save_reviewed_snapshot` 只接受 ready 计划和已有 StopReview，
真实布局与 owner CAS 通过后，在首个写入前消费审阅，再按原顺序持久保存快照及 fence。
首写失败不还原审阅；孤儿快照不能重建批准，文件不能自动重放。codec 和旧数据回归 **169 passed**，
已审阅保存及既有持久化 **69 passed**。保存器仍不独立证明外部 writer 覆盖或当前 host 能力，
生产入口不调用它；实际停止、维护、批次对账/取消及原生准入仍未完成。

## 历史阶段：平台机制与宿主语义

Linux 可以使用进程文件描述符定位一个进程：[Python 3.11 的 os.pidfd_open](https://docs.python.org/3.11/library/os.html#os.pidfd_open) 从 Python 3.9 提供，要求 Linux 5.3 或更新；[signal.pidfd_send_signal](https://docs.python.org/3.11/library/signal.html#signal.pidfd_send_signal) 从 Python 3.9 提供，要求 Linux 5.1 或更新。组合使用仍须满足两者的环境要求，并处理运行环境拒绝调用的情况。

这些公开接口提供稳定的信号目标，不证明 Agent 的优雅退出、会话保存或全部相关后代退出。未来生产适配还须在启动时捕获官方 host 的确切身份与句柄，并验证 manager 如何继续观察释放。不能事后按进程名、目录、进程组或重复查询 PID 猜测目标。其它平台当前没有本功能的已核实停止通道，保持 unknown。

## 历史阶段：DSH 启动与关闭的源码证据

Rotom 的 `agents/dsh/templates/launch.mjs` 直接导入 `@deepseek-ai/dsh/profile-boot`，
在当前 Node 进程内等待 `runProfile(...)`。已检查的 Core `0.2.1-rc.2` 缓存包中，
`lib/profile-boot-C14i-8IN.js` 的这条路径调用 `boot` 并挂载插件树，没有另行 spawn/exec。
因此 Python 启动的这个 Node 子进程可以作为 host 身份的候选绑定点；这不证明插件不会创建后代。
候选中的本地受管 DSH 普通运行与恢复共用 `Popen` 启动边界，已接入身份捕获与显式可信工厂的停止服务接缝；默认启动不提供该工厂。

固定 TUI `0.16.1` 源码 commit `73ff99fbed56563bf154d719effd09f9f9725349` 的
`bin/dsh-tui.js` 还包含标准 CLI 启动 `dsh --profile` 或 Node host-entry 的路径。
它们不是 Rotom 上述直接 `runProfile` 路径，不能用标准 CLI 的父子关系代替受管启动证据。

Core 的 `SIGTERM`/`SIGINT` 处理进入 shutdown：正常路径处置整个插件树，最长等待 5 秒；
重复中断、处置失败或超时可能强制退出。缓存 JSONL persistence 插件的根 teardown 会等待所有打开句柄关闭，
写句柄正常关闭会先 drain，再释放 lease。单个 `session/disposed` 事件发起 close 并不等待它完成。
因此收到信号、调用退出入口或单个进程结束，均不能替代独立的全部后代和 writer 释放观察。

上述缓存文件与 Git 对象已经记录并复核 SHA256，证据保存在私人任务记录。
TUI 固定 commit 已核对；Core/JSONL 缓存尚缺与官方归档的字节级来源核验。
这是源码路径证据，未执行真实宿主或信号，也没有准入自动停止。

## 历史阶段：DSH 启动的子进程观察

候选中的本地受管普通运行与恢复在 `Popen` 返回后、任何 wait/poll 或启动通知前尝试绑定当次直接子进程。
仅支持 Linux、单线程、默认 SIGCHLD 且仓库启动路径无并发收割者的有限条件；
核对当前 manager、child PID、PPID、boot/starttime，取得不可继承 pidfd 后在采样前后检查退出事件。
这一限制遵循 [pidfd_open 的子进程回收前提](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)，
不声称覆盖外部原生信号处理器或任意多线程宿主。

句柄在原 wait 期间保留，只关闭自身 pidfd，不发送信号或等待/收割 child。
登记采用 owner 非阻塞锁，锁内再次核验句柄和当前 manager，只更新该 active/managed DSH 的
host 观察与观察时间；保存的 session/cwd 事实不变，`protocol.control` 仍为 null。
OMP 的合作 owner 不走此接口，避免绕开双向摘要事务。SSH、未登记及自定义启动路径沿用原派发方式。

捕获或登记的普通错误只给固定提示，原宿主继续等待，退出码照常保存；
未知不会触发终止、重试或继续输入。已有控制异常不被句柄关闭时的第二次异常覆盖；
若原等待已正常结束后出现新的控制中断，仍传播该中断，已保存的退出事实不被改写。
这里的身份记录是观察，不是停止许可，缺乏完整资源退出证据时仍保持 unknown。

普通受管 DSH 从 `subprocess.run` 切换到显式 `Popen`/单次 `wait` 后，等待异常不再触发
Python `run` 的自动 kill 清理。普通等待异常返回冲突（4），启动调用失败仍返回依赖错误（5）；
控制中断传播，已经继承的租约和未知归属继续保护资源。共享生命周期与恢复回归 **75 passed**，
普通运行及并发锁专项 **18 passed**；均为假子进程，不证明真实停止能力。

## 历史阶段：共享等待期限

内部 `ControlDeadline` 已通过 49 项隔离测试：默认 30 秒，范围 1–300 秒，
同一阶段的全部所选实例共享一个单调绝对截止时间，逐项处理和轮询均不重新计时。
stop 和 ready 各自构造独立预算；无效或倒退的时钟保持保护。
内部 `wait_for_release` 现已复用该预算，按精确 run 与完整 manager 身份逐项观察，
完整后代观察先由可信 record 回调持久保存，再计入本轮 confirmed；记录结果不明立即返回 4，
不重试该记录。最后一项保存后才到期也返回 4，保留已发生事实，不继续维护。
observer 必须非阻塞且来源/时效可信，fsync 可跨过期限，循环不声称提供硬实时中断。

`confirmed_runs` 只表示该后代观察已保存，不证明 manager 的物理/状态/包 SH 已释放，
不等于 stopped_confirmed/resources_released 或维护许可。相关三套 **112 passed**；
真实临时 Registry/文件锁加虚构观察的集成 **3 passed**，验证三选二、仍持 SH 阻止 EX、
记账后响应丢失保留事实但不重试。初次不同属主沙箱的 7 项祖先 UID 拒绝单列为环境失败，
在原属主执行环境重跑通过，没有弱化门禁。
这些机制未接入生产控制、实际观察通道、Batch 状态或 ready 循环；T072 整体仍待完成。

## 历史阶段：私人请求与逐项派发记录

候选通道采用单线程私人文件 inbox，在等待宿主的间隙处理请求。内部请求 codec、私人文件 inbox、处理器与派发记账已有隔离实现，
显式候选服务可以组合原句柄的单次信号方法；尚未接入生产批准/控制路径或完成整体停止维护验收。每个请求只允许 graceful-stop，绑定
精确 run、manager/host、request/batch/plan 和同 boot 单调期限；没有任意命令、输入或强杀字段。
严格 codec 与停止审阅回归 **143 passed**，只证明数据边界，不证明批准或期限仍有效。

当前 manager 的内部派发记账先不可覆盖保存 intent 并读回，再返回一次 sent 结果记账对象。
同 run 已有 intent 时，换 request ID 也不能重开。缺少 sent 结果保持 unknown；结果写入失败
或响应丢失不恢复对象，旧文件不重建对象。sent 只表示可信调用方报告信号调用返回，
不等于宿主/后代退出、会话封口或资源释放。临时文件与虚构 manager 的新套 **21 passed**，
覆盖重复请求、两段写入失败、中断、目录替换与当前 manager 变化。

候选单线程等待循环已有 **38 passed**：同一 child 的有界 wait 片段后处理一次服务，
服务普通失败后停止处理请求，仅继续等待该 child，保留原退出码；控制中断原样透传。
循环本身不约束 service 的耗时，接收端必须有界并自行核验请求期限。与真实临时派发记录
组合的 **4 passed** 验证重复请求不重复假发送、发送或结果记账不明后停止服务、已写事实不回滚。
这些检查使用假 child 和假发送列表，未接入默认启动路径，也未设置整个 TUI 的总超时。

候选 manager 请求处理器已把原启动句柄、严格请求、单调期限与派发记录组合起来：
可信 verify 回调负责当前来源/批准/批次/资源核验，意图落盘后再次复核，随后只调用注入通道一次。
没有内置原生信号或生产工厂。新处理器及旧记账共 **52 passed**；补充过期请求后的时钟倒退
边界先行失败，修复后受影响新套 **32 passed**。发送后超期仍保存 sent，外层独立判断超时；
sent 始终不等于退出或资源释放。

inbox 使用每 run 的 0700 私人根、0600 不可覆盖文件，endpoint 固定物理根、随机 nonce、
manager/host 身份与 binding；每根最多 128 个请求，拒绝未知文件、替换根、重名及不匹配请求。
发布后同步父目录至根再读回；同步失败留下文件，不能视为未投递。它不提供批准或自动重放。
inbox 与请求格式联合 **178 passed**；inbox→处理器→等待循环的 **4 项组合测试通过**，
使用假内核、假 child 与假发送，覆盖过期、重复及意图落盘后替换 endpoint。

关键发布路径随后发现并修复父目录项同步遗漏：停止意图、恢复请求、协调域和 owner 登记
均在发布后同步祖先，并重核文件与命名根，才返回后续操作所需的对象。OMP 同步失败保留
owner_pending 和已写 owner，不进入 dispatched 或启动宿主。该修复不改变普通 Tree 的创建
语义；测试验证调用顺序和故障处理，不能代替真实断电与平台耐久性验收。

生产接收端仍需核对私人根/请求来源、有效批准与意图、期限及原启动句柄。现有 live 接受只支持
OMP。DSH 的包和 native HOME 在实例目录内，正式路径只有实例/状态两把运行租约；同一实例的
所有运行共享这些资源，不同实例的相同 lock identity 不代表共享同一个包。DSH 接线需要核验
自身的完整 owner 集合、目录包含关系与原写入门禁；所有生产控制仍保持关闭。

## 历史阶段：DSH 部署核验与登记互斥

候选只读检查借入实例/状态两把 SH 的 fd，核对当前部署绑定、代际、实例标记、无 pending、
精确基础 argv 及字面量 HOME/DSH_HOME、本地执行路由，再核对实例内运行包与 HOME 的
物理目录。额外打开的目录 fd 只用于核验，由本函数关闭；没有第三把包租约。
复用原运行 guards，并额外比较已保存 launch.mjs 的唯一 FILE baseline；不读取当前仓库锁
或模板，不解析秘密。新套 **59 passed**，只证明当前保存部署的关系，不能据此推断历史
追加参数、完整包内容、完整运行集合或外部 writer 的覆盖。

内部持久停止意图与新运行登记共用 owner 锁，对完整记录集合前后复核后不可覆盖发布。
上层必须已按原顺序持有实例/状态 SH；首次发布前回调不得取 Domain、Registry/owner 或物理锁。
文件存在时新登记和普通维护均拒绝，损坏文件也保留保护，已有退出/unknown 仍可记账。
它只阻断操作，不授予停止或维护许可；没有默认创建、自动删除、超时释放或重放。

49 单测与 6 正式入口组合 **55 passed**，受影响运行记录/OMP/启动回归 **147 passed**。
组合部署检查后最终 **11 passed**：预览后的部署漂移拒绝发布，已发布意图在 owner 退出后
仍拦截 run/resume/apply/sync/rollback。全部临时部署与假进程，没有真实停止；计数存在重叠。
完整恢复清单、生产批准、资源覆盖及批次取消/对账尚待接线，默认自动控制继续关闭。

内部人工快照现已与持久意图绑定：复用完整 RunRecord 保存明确所选项，未知 host/session/cwd
原样保留，同时记录完整 owner 集合摘要。DSH 没有已证明的协调域时不构造 Domain 或 Batch。
同一 owner 锁内重新核对全集及所选记录，先不可覆盖保存/同步/读回快照，再发布带摘要的
v2 fence；最后重核两者关联。同批已有快照先于回调被拒绝，失败后保留已发生事实。
独立快照读取允许返回孤儿历史，不表示已接受、已停止或可恢复。v2 fence 关联丢失/损坏时
读取拒绝，文件存在性继续阻断；v1 保留原阻断语义。默认入口不创建快照或意图。

内部 `save_manual_snapshot` 已统一部署复核、快照和意图发布。调用方维持原实例/状态 SH；
函数先核实借入 fd、冻结输入，再在 owner 锁前和锁内核对所选项的部署布局。历史 session
信息原样保存，未选 legacy/unknown 只参与全集 CAS，不因此被采纳或视为空闲。

快照 codec 与既有接受格式联合 **146 passed**；新持久化边界 **57 passed**，既有 fence
回归 **49 passed**；真实两锁的临时部署与正式 Python 入口最初组合 **21 passed**。
统一操作的新套加原检查定向最终 **20 passed**，入口改走它后的受影响分支 **10 passed**。
没有真实宿主/信号或自动继续，未取得工具原生停止与恢复准入。

当前 manager 的内部请求检查已连接人工快照：同一 owner 锁内核对明确目标、batch/plan、
host/manager、当前完整记录及部署布局；观察期间记录、快照或意图文件被替换时拒绝。
其它已选项退出不妨碍对剩余项的单项检查。该函数只返回历史记录，仍需独立停止批准、
与操作相符的资源检查、当前原句柄、endpoint 和期限检查。setup 要求完整资源覆盖；DSH v2
stop_only 按本页开头的所选目标规则核验。关联套 **35 passed**，最终锁断言
定向 **1 passed**；组合停止服务 **6 passed**，旧 fence/store 回归 **106 passed**。
派发意图后关联失效保留 unknown、不发送或重试；正常假发送也不记为退出/恢复完成。

## 历史阶段：2026-10-26 版本展示与原生材料核验

版本展示及停止/维护规则的隔离回归 **210 passed**，实际临时部署预览及两类快照集成
**77 passed**，最终版本/help 回归 **215 passed**，均退出 0；计数有重叠，不合计为全库通过。
DSH v2 尚未发行；此次计划语义变化使旧 v2 plan ID 失效，旧快照严格拒绝而不自动迁移或重放。

用户已明确授权使用锁定、未经修改的官方 DSH，在隔离临时范围内实际启动并验证。
本轮核对 Core 0.2.1-rc.2、TUI 0.16.1、Node v24.14.0、pnpm 11.19.0；六份本地 vendor
归档的 SRI 匹配。现有缓存只有 TUI 0.15.0，不能代替当前锁。官方 registry 和锁定镜像的
直连下载均超时；显式经过配置代理时 CONNECT 成功，后续 TLS 报 SSL_ERROR_SYSCALL，
归档均为零字节。随后沿标准已登记机器的非秘密部署清单找到当前锁的已安装包，运行包缺失
不再列为阻塞；既有受管收据、锁字节及源/副本全树摘要匹配，Core 20、TUI 3287 个原包文件
与对应锁 SRI 键的本地 pnpm 索引逐文件匹配。没有重新下载或重算官方 tgz 的 SRI，TUI 目录内
额外嵌套依赖不属于这 3287 个原包文件的索引证明。全程不改上游源码或日常运行包。

独立手动入口 `tests/manual/dsh_stop_native.py` 已实际通过一次零输入启动/停止：当前官方
Core 0.2.1-rc.2/TUI 0.16.1、精确 Node v24.14.0，私人 HOME 与唯一虚构本地模型配置。
通过正式 `runtime.run` 租约/登记及共享 `dsh_process.launch` 的显式测试工厂，使用原 pidfd
单次 SIGTERM；持久派发为 signal_sent，宿主退出 0，原 manager 的完整后代观察写为
idle_confirmed，两个原 fd 对应 inode 均可重新取得 EX，终端状态恢复。没有强杀、重试或
继续输入。零提示词启动没有创建 session，故该轮未执行恢复，不能算 T053 或完整 T082 通过。

后续另建私人 scope，以本地模拟模型生成合成历史，并实际通过受控 Rotom resume 入口
核对新 run、原 ID/cwd/历史、加载 unknown 与继续 not_sent；恢复没有写入 stdin。
原两个 run 都保存了与此次部署/锁完全匹配的启动版本。缺失目标在宿主派发前拒绝。
恢复期间另有官方 TUI 自动回顾请求；旧零请求假设导致的失败保留，修正后正例已通过，不将有限
恢复事实扩大成停止维护通过。最终 T053 已补齐活动 TUI 拒绝及释放后恢复，并完成独立外部 writer 拒绝/重取验证；完整记录见
[实施审查](../specs/008-rotom-command-experience/main-review.md)。

准备阶段的根盘空间不足、共享祖先可写导致 Tree 拒绝均独立记录；实际验收改用可信私人临时
目录并重新校验全树摘要，没有放宽原检查。默认测试不执行此手动入口，生产控制仍未开放。

## 历史阶段：候选停止服务与共享启动生命周期

`StopService` 在当前 manager 内建立一次新 endpoint，借用原 host，组合 inbox、请求处理器和
单次 pidfd 通道；批准核验前后都复核 endpoint。处理成功后不再读新请求，任一不确定结果永久
停用服务；保留请求与派发记录。close 只撤销服务，不关闭借入 host、不删除文件。

共享 DSH 启动函数允许可信 Python 调用方显式提供工厂。host 登记、恢复启动记账及派发通知
全部成功后才构造服务；工厂/处理普通失败继续等待同一宿主，不再派发。退出时先撤销服务，
再关闭原 pidfd，收尾异常不覆盖已有等待/控制异常。默认 runtime/CLI 不提供工厂，control 仍空。

服务 **44 passed**，共享生命周期新增 **35 passed**；受影响六套回归 **196 passed**。
实际 Python 普通 run/resume 调用链与临时真实部署、锁、owner、恢复请求及 stop journal 的
组合 **13 passed**，分别覆盖正式两锁和测试注入的三锁。内核、宿主、批准及后代观察仍为 fake；
没有真实信号、原生停止或日常准入证明。结果有重叠，不相加为全库结果。

## 历史阶段：有限模型已经核验的行为

`tests/fixtures/rotom/stop-channel-probe.py` 只接收测试注入的 opaque handle、假通道和受信观察回调，没有真实进程后端。它绑定单个 run、manager 和 host 的完整身份；host 与 manager 的 PID 必须不同。

- 先接受精确请求、调用保存意图的回调，再复核 manager 和 host，最后最多发送一次优雅停止请求。回调只模拟持久化成功或响应丢失，不证明真实文件落盘。
- 回调或发送结果不确定时保留 unknown；再次请求、查询或超时都不能重发、升级为强杀或停止 manager。
- host 退出不等于全部资源可写。只有同一 run、同一 manager 的完整 `ReleaseObservation` 才接受释放；缺覆盖、相关后代存活或 manager 丢失均保留 unknown。
- 假通道精确选择三个实例中的两个；第三个实例和 manager 保持不变。此结果不代表真实宿主已经接受停止。

验收命令与结果：

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_stop_probe.py tests/test_descendant_release.py
```

本次为 **52 passed，退出码 0**，实际 argv、源码摘要、故障 RED 和日志保存在私人任务记录。既有 `DescendantScope` 测试使用假内核；真实 Linux 观察仅适用于其已声明的完整覆盖条件。本原型没有新增任意进程树扫描器，也不能清除 manager 丢失后遗留的旧 unknown。

## 历史阶段：尚未准入的边界

停止前恢复清单的内部机制已有独立隔离证据。`stop-acceptance` 只保存所选实例的完整 v2 元数据，
包括原 session 观察、启动/会话目录和部署身份；未知值原样保留，当前仅允许预先选择人工恢复方案。
在新 OMP 协调域中先保存不可覆盖的 0600 清单，再提交带摘要的资源意图。清单缺失、变化或不安全时，
后续意图派发拒绝；中断留下的清单/意图不自动删除或重放。数据保存本身不证明实际 owner、部署或进程仍相同。

这一阶段的相关协调回归为 **325 passed**，清单 codec 与既有计划/批次数据测试为 **196 passed**；
完整 envelope 大小边界修正后，受影响事务套件重新运行 **33 passed**。
这些测试使用临时私人目录、文件锁和虚构进程身份，没有发送信号。实际现场核验及停止执行仍待接线，
不能把清单、意图或测试计数当作停止/恢复准入证明。

随后增加内部 live 接受路径：借用可信调用方已持有的实例、状态及包 SH，
在短协调事务中取得所选 owner 的非阻塞锁，重读当前完整记录、同 scope 关联及物理对象，
并让 owner 锁保持到意图提交完成。独立修改 owner、替换状态锁或其它资源、缺失或未知关联，
都会拒绝接受；失败不回落到仅检查元数据的入口。原事务重构后 **33 passed**，
新集成路径在状态锁竞态修复后 **12 passed**。这些检查不捕获 host 或发送停止请求。

stop_only 未选第三项只核对协调表中的共享引用，不宣称重读其 owner 文件；
共享包 setup 则必须包含全部活跃引用并实读每个所选 Registry。
live 接受现已在协调锁前核验当前部署代际、绑定、runtime/native HOME、无待恢复部署，
并复用正常启动的受保护文件及凭据引用检查；不读取调用者环境或解析凭据。
部署漂移与锁顺序的新增 8 项先行失败后，结合原 live 事务共 **20 passed**。
这不检查完整运行包内容，也不证明宿主身份；稳定 host 句柄和停止执行仍待接通。

内部停止专属审阅现已绑定完整计划、batch 与创建进程。可信调用方须先完成展示/显式请求策略，
approve 精确返回 True 才发出一次性内存对象；不能从 plan_id、清单或 JSON 生成批准。
reviewed live 入口在现场检查后、首次写入前消费；写入/提交/响应失败或中断都不恢复对象。
旧 metadata 接受不提供此批准，停止审阅也不替代独立 setup 写入批准。新审阅与计划回归
**77 passed**，事务新套 **15 passed**；原有 live/部署接受 **20 passed**。这些计数有重叠范围，
不代表完整停止工作流或 CLI 已开放。

能力矩阵在 `tests/fixtures/rotom/exit-capabilities.json`，所有工具的 `production_admitted` 均为 false。生产停止仍需要完整生命周期事务、已批准目标集合、启动时句柄绑定和独立真实验收。物理包锁暂时空闲、单个 PID 消失或启动标识变化，都不能独立证明旧运行的全部写入者已经退出。

默认行为继续拒绝未经证明的自动停止/维护。会话封口与进程释放是不同事实，释放观察不能证明目标 session 已保存或可以严格恢复。

## 历史阶段：原启动句柄的单次终止原语

绑定对象另有内部 `send_sigterm_once()` 候选方法：先消费单次状态，再沿原 snapshot
核实 manager、child、出生身份、pidfd、单线程及默认 SIGCHLD 条件，只向捕获时的 pidfd
发送一次 SIGTERM。使用公开 [Python signal API](https://docs.python.org/3.11/library/signal.html#signal.pidfd_send_signal)，
siginfo 固定 None、flags 固定 0；没有用户指定信号、按 PID 重开、进程组发送或强杀升级。
捕获、普通 snapshot 和默认运行路径仍不调用该方法；生产控制准入没有变化。

成功仅表示该系统调用返回，不证明 Agent 完成 shutdown、会话封口或后代/资源释放。
普通错误、API 不可用、控制中断或异常返回均不恢复本对象的发送资格；控制异常原样透传。
复制共享同一对象和单次状态，禁止序列化；发送成功后原 pidfd 仍用于观察及显式关闭。
调用方仍须先核实本次批准、期限与现场关联，持久化 intent，再显式调用这一层。

新边界 **24 项有效 RED → 86 passed**（含原 host suite）；接入私人 inbox→处理器→等待循环
的假 pidfd 通道后，相关五套 **167 passed**，覆盖正确顺序、仅发一次、响应丢失保留 unknown
及原 child 退出码。全部 API/内核均为 fake，没有发出真实信号；不得据此开放某工具的优雅停止。
