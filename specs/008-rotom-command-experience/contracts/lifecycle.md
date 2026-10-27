# 会话、停止与恢复生命周期契约

日期：2026-10-26。状态：本轮分阶段维护候选已通过分组与受影响复验，尚未合入 main；合入须人工批准。P-SESSION/P-EXIT/P-PANE/P-INPUT 仍分别准入。
依据：[规格](../spec.md)、[数据模型](../data-model.md)、[研究](../research.md)。
所有状态为受管事实；收到请求、界面存在和原生退出码 0 不能替代成功证明。

## 当前公开 workflow：按工具分阶段

候选实现、分组回归及稳定差异审查已完成；基于 main `45953f0`，保留在分支 `feat/tool-maintenance-workflows-20261026`，尚未合入 main。合入须另经人工批准。官方 Pi/OMP TUI/PTY、隔离回归及受影响复验见[验收记录](../tool-workflow-validation.md)。

本轮以[工具方案](../tool-workflows.md)替代所有工具统一 Domain 许可的前提。DSH/Pi/OMP stop_only 复用原快照/fence/CAS、一次原 host pidfd 请求及退出核验；恢复清单先于 stop 保存，与 stop 批次同 ID，不能覆盖。Pi/OMP endpoint 为 inbox sidecar，精确绑定 run/manager/host/部署，不改旧 RunRecord.control；新 OMP host 登记通过 owner_pending 与 Domain/owner 双向摘要。旧无通道运行保持人工停止，不从 PID 消失推导退出或释放。

确认停止后按原协议关闭本 stop fence，再调用普通 setup 的最新计划与独立批准，原实例/HOME/包锁、owner、共享引用和 Domain 门禁全保留；新 run 可阻挡，不能扩大 stop 集合。本 workflow 不消费或重新发行旧 Domain batch permit，不把 stop_only 当资源维护许可。

逐项 restore 在当前终端创建新 run，Pi/OMP 使用 HandoffResumeBackend，DSH 原 Host 不变。保留 setup 原结果和退出码；未知不重试，不回滚猜目标。restore-intent/请求派发与加载证据分开；缺回执显示待确认并请核对 TUI ID，始终 continue=not_sent。原 pane/新标签页已选为下一阶段交付但尚未实现准入；统一严格加载回执与原生 TUI 自动继续本轮不承诺。

Pi 公开扩展/helper 在启动与切换前 claim 租约，旧 active/unknown 无 guard 或当前来源不符阻挡；只保证 Rotom 合作进程范围。三来源锁为 locks/pi/session-control.json。普通 --session 完整 ID 核实为精确路径，原生 --resume 是 picker；缺失文件原生会新建 ID，Rotom 先严格重核，外部事后变化仍 unknown。OMP 只读打开不持 writer 锁，固定 session-manager.ts:1103–1128 在竞争首次写入时分叉 sibling 新 ID；不承诺任意外部 writer 提前拒绝。自动输入所需 writer/加载/接收证据不因交接而放宽。

旧 stop/OMP Domain batch 按原 reader 与查询/收尾保留，不升级/迁移/重放。以下共享 session/stop 原语继续适用；明确标为旧 Domain 的协议仅约束既有 OMP 内部路径，不能套作 DSH/Pi workflow 前置。完整命令与验证边界见[指南](../../../docs/tool-maintenance-workflows.md)。

## 共享接口与能力证据

以下为仓库内部类型契约，不是宿主新增 API 或可供用户注入的信任开关：

| 接缝 | 输入 | 结果与限制 |
| --- | --- | --- |
| session resolve | 明确 Scope、工具/ID/过滤、受限已知索引 | 唯一 SessionRef 或缺参/冲突；不搜索其它 HOME |
| backend session proof | SessionRef、保存部署、cwd 规则 | 归属、目录、公开 writer 防护；缺安全派发证据拒绝，加载确认能力单列 |
| resume executor | ResumeRequest、有效 writer 准入、可选一次性 ResumePermit | 复用 runtime.run；新 run；可交接为 launch_dispatched，加载证明后才 restored |
| stop planner | 精确 Scope/run 集合、operation、已验证资源与恢复位置 | 只读 StopPlan/摘要；无批次与意图写入 |
| stop executor | StopPlan、稳定身份、独立停止批准 | 逐项请求/退出观察；不扩大范围，不先停止 manager |
| 公开 workflow runner | 恢复清单、原 stop 快照、最新普通 setup 计划与独立批准 | 关本次 fence 后复用普通 setup 全门禁，保存原结果，不保留跨阶段许可 |
| 旧 OMP Domain maintenance runner | BatchPermit、允许 operation、原操作批准 | 仅旧内部协议，复用既有核心操作与原有物理门禁，返回原结果 |
| container control | container/generation、精确 op/run、已接受恢复引用 | 私人端点、核实调用者；无任意 argv/shell/文本执行 |

能力记录绑定工具/后端、实际运行包与插件来源、平台和公开接口证据；不创建插件市场。
首版维护操作 allowlist 只有 `setup`；独立停止是 `stop_only`。
扩展 sync/apply/rollback 等维护编排须另定资源闭包、批准和恢复依据，不能以字符串直接调用任意命令。

## Session 恢复

1. 静态 help 先返回；固定显式 machine/local 范围，再读取该范围内允许的非秘密索引。
2. 显式工具/profile 为硬约束；未给工具时只有唯一已知匹配可推断，歧义按 TTY 选择或返回 2。
3. 未登记显式 ID 仅经所选后端公开元数据核实；无证明不启动，不改用最近/新会话。
4. 核验受管存储归属与已知会话 cwd 约束；位置参数只选终端。预检时的无 writer 观察不是执行凭证。
5. 复用已部署 runtime 的完整准入、环境与秘密解析、运行包和租约，创建新 run；调用官方显式目标恢复入口，按下述各工具已验证的 writer 行为交接，不统一声称启动时取得原生排他。
6. 启动事实与加载确认分别处理：官方启动已派发即可交接当前终端，缺加载回执时显示加载待确认。
7. 有公开实际加载证据且 SessionRef/cwd 相符才确认 restored；否则禁止自动继续，用户在官方 TUI 自行操作。人工确认不成为机器回执或额外输入许可。

writer 语义按工具分别核验：DSH 沿用原冲突拒绝，Pi 只保护 Rotom 合作进程，OMP 竞争首次写入可分叉。身份不明返回 4，缺少必要公开能力返回 5。
本地会话锁只能排除合作 Rotom，不能单独代表原生 writer 排他。
已经取得的保护不得在检查与加载之间提前释放；manager 退出也不能让仍存活的写入者失去保护。
DSH 排他由官方宿主在恢复事务内部取得并持续持有；Pi 合作租约覆盖受管恢复和切换；OMP 只读打开不取得 writer，首次写入时遵循官方锁与分叉行为。
原生 writer 行为及严格目标须有独立证据，不能把本地合作锁冒充外部排他；OMP 交接允许原生分叉但必须明确展示可能改变 ID。自动输入仍须证明完整排他与实际加载，宿主启动或自报布尔值不足。
加载证明不能只来自本次请求参数或历史索引，也不能以原生退出码 0 代替。
官方交接、加载确认、继续输入分别准入。缺 writer/范围/目录等安全派发证据仍不开放交接；
仅缺严格初始加载回执不阻塞已准入的交接，不以等待上游支持作为 DSH 阶段二前提。
真实验收须验证原历史、缺失目标及该工具实际 writer 行为（拒绝/合作租约/写入分叉）；人工验收不补造运行时加载回执。
派发后失联或确认超时保留已知事实和 unknown，不重试、不强杀、不向终端输入探测/继续文本。
上述状态边界同时用于日常、维护后及原位置恢复；这些入口不能因调用位置不同把待确认改写为 restored。

## 停止计划与结果

DSH 当前采用 StopPlan v2：单一实例 Registry coordinator、完整 owner 摘要和本地三资源引用，
不借用 OMP Domain/代际。只读采集按实例 SH → 状态 SH → owner 非阻塞锁核实当前部署和全集，
读前后比较记录，未选项不变且保留在引用中；旧 unknown 不自动采纳。Pi/OMP 复用精确目标原语并按工具核验布局/endpoint；无可信通道或身份仍 blocked，不能从纯 codec 的 supported/complete 声明取得现场证明或许可。

内部已审阅保存复用原两 SH 和同一 owner 锁：完整 owner CAS、部署布局与计划三资源一致后，
消费既有 StopReview，先持久化嵌入完整计划的 v2 人工快照，再发布带摘要的 fence。
首写失败也不还原审阅；孤儿快照保留历史，已有文件不能重新签发批准或触发重试。
当前 CLI 精确停止在原审阅和现场复核后调用保存路径；静态 help/只读 plan 不创建控制服务或意图。

plan 是无写入快照。停止调用须重复同一 scope、operation、显式 run 集合和 plan_id，
重新计算资源闭包、会话观察及原/新位置能力；新增 run 或目标变化使旧接受无效。
原位置不能满足时，在停止前允许保留运行或先改选恢复位置。
只有接受后才 durable 保存 Batch、恢复清单和资源意图，然后按精确身份发送请求。

纯 StopPlan/Batch codec 不采集现场身份、读取原生会话或获得租约；它们只检查调用方提供的有限
快照、规范摘要和逐项事实一致性。反序列化不能产生控制资格或可消费的 Permit。
未选 run 仍引用选中项的共享资源时，setup 计划应披露阻断；stop_only 仍只包含明确选择的项，
不能扩大集合。三工具 v2 stop_only 可在其它资源覆盖未知时精确停止已核实所选目标，
coverage/reference_runs 仍披露并进入摘要；setup 和 v1 计划继续要求完整覆盖。
未知目标、缺失原句柄或未准入通道仍拒绝，实际接受必须重新核实部署、身份和批准；
版本 hash 或停止请求结果都不能代替维护前的完整释放观察与排他租约。

内部 DSH 人工恢复快照可以独立于完整停止接受保存：复用所选完整 v2 运行记录，
保留未知 host/session/cwd，绑定完整 owner 集合摘要和 Registry 物理身份；不编造协调域。
调用者先持实例/状态 SH，在同一 owner 锁内核对精确集合，先同步快照，再发布摘要绑定的
v2 阻断意图。已有同批快照（含孤儿或损坏文件）禁止重新消费回调或覆盖。
独立读取快照只提供历史参考；没有匹配意图不能展示成已接受批次，存在匹配意图也不提供
控制或恢复许可。缺失或损坏的关联不能降级为 v1、删保护或重试，默认运行不创建这些文件。
内部 `save_manual_snapshot` 封装锁前及 owner 锁内的部署布局复核、快照持久化与意图发布；
输入冻结前先验证借入 fd。调用方仍负责维持原两把 SH，该函数没有停止批准或完整覆盖语义。
只读 `inspect_stop_request` 在同一 owner 锁内复核 v2 意图、所选快照、当前目标、部署和
文件身份，要求已知 host 与当前 manager 精确匹配；返回历史记录而不是停止批准。
其它所选项退出不使单项关联自动失效，也不因此证明整体资源已释放。期限、endpoint、
原句柄及独立批准仍须在派发处核验。

优先使用已准入的官方退出通道；Linux 信号候选必须绑定稳定句柄，发送前复核 birth identity。
若只是可发信号而无法证明宿主优雅退出或最终 session 封口，须明确披露，不承诺同会话自动恢复。
强制终止是另一份精确计划与批准；超时不自动升级。不能按名称/目录/进程组猜控制范围。
manager 作为观察者保持运行，收集原生退出、相关后代、租约及最终会话事件。

`stopped_confirmed` 只要求同身份、完整相关后代覆盖及资源释放，不能把会话证明混入退出事实。
最终 session 事件封口决定清单中的确切会话是否可信及能否自动恢复；封口缺失显示历史/未知，
即使退出已确认也不能承诺确切会话恢复。预先接受的 stop_only/人工恢复路径仍可确认停止，
维护是否继续按其资源门禁和已接受的恢复方案判断。缺退出/资源证明才保持运行 unknown。
强杀、丢事件或未登记活动不因 PID 消失变成 idle。既有 owner 的 unknown 只走可信物理 EX 核实路径。

## 旧 OMP Domain 协作与持续适用的物理门禁

本节的统一资源键/Domain 事务约束继续适用 OMP 内部路径；不是 DSH/Pi 公开 workflow 的采用前提。普通 setup 原物理锁与 owner 检查不因分阶段而放宽。

规范 ResourceKey 及协调域必须与物理实例所有权锚点一致；无法归一的跨域共享资源拒绝自动维护。
旧 checkout/外部入口可能不合作，不能声称意图已阻止所有系统启动；现有物理租约始终是最终门禁。

OMP 的包可由不同 instance/state 引用。本实例的空 Registry 和可取得的包 EX 均不能证明其它引用的 unknown 已解除。
合作控制启用前须证明同一物理资源的唯一可信协调域锚点及完整 owner/reservation 范围；
跨域或首次采纳缺证明时拒绝自动维护，不清 owner、不扫描全部机器配置补齐。
普通 OMP sync 的修复/激活也须核验该门禁；保持其 cache-only 行为，不为同步建立实例或嵌套实例 EX。
该接线在 T065/T066 完成；T044 的基础登记和 US5 只读观察不以 OMP 控制启用为前置。

物理身份基础 T112 可独立实施。OMP 包锁取得后、交给调用方前，再核对命名租约文件与 fd 指向同一
现存安全对象；原有 SH/EX 模式、继承 fd 寿命和 cache-only sync 保持原契约。这个核对能拒绝已观察到的
路径替换，不能阻止任意外部程序在之后改名，也不能将当前 inode 当作永久归属或完整 owner 清单。
首次采纳、跨域别名、reservation/intent 和旧 unknown 的清除仍由 T065/T066 的独立证明约束。

T113 新 runtime 原型使用目录上的短协调 flock。资源租约在协调锁之前取得；域锁内不等待物理锁、
宿主、网络或用户。第一次发布先在私人临时文件持 EX、原 inode 写完非空锚点并 fsync，
随后先将同一锚点记录不可覆盖地发布到 `cache/runtime-claims/<identity>.json`，同步声明文件、
声明目录、cache 根及其父目录链，再用不可覆盖的 hardlink 发布 final 租约名称、删除临时名并
fsync 租约父目录；持该物理 EX 时再写域登记。内部派发/核验要求声明与租约锚点完全相符。
声明发布后绝不自动删除或重建：final 发布失败、域写入失败/记录缺失均保留声明并拒绝重试；
只有尚未发布声明的失败可重新尝试。link 与 unlink 之间崩溃可能留下永久双链接拒绝状态，
须未来显式恢复决策。不允许覆盖先到的旧空租约，也不以声明存在证明首次采用已完成。

reserve 在一个短事务核实资源和无重叠意图后落盘；dispatch 必须由未来合作启动器先取得全部 SH，
在域锁内重新核对锚点和意图、先持久化 dispatched，再执行宿主启动。该内部方法不启动宿主，也不能
自行证明调用方锁模式。intent 使用 domain revision CAS 和完整明确选择集合，reserved/unknown 阻塞；
接受后阻止重叠新预留，派发前再次核实引用。已派发和 unknown 不因取消、取到 EX 或超时转为空闲。
若落盘后响应丢失，记录仍保留派发事实，不重复执行。

普通 OMP guard 在创建租约之前、取得包锁并核对命名对象之后分别只读检查独立声明；任何声明对象
存在或父目录不安全均禁止回退旧格式。它位于 leases 目录之外，租约被清空、删除、换 inode 或整个
leases 目录被替换时仍能阻止降级；缺失租约不会被自动创建为空文件。声明单独丢失时，仍存在的
非空锚点继续走域核验与拒绝路径。

T066 的普通 sync 消费已完整登记的新 runtime：从当前可信配置取域根，只打开已有私人租约。
已有 scope 时先持实例 SH 并验证 HOME，再取得原包 EX，在短协调锁内核对 scope、物理域、声明、
锚点和目标包的全部引用/意图，确认空闲才进入原修复/激活。无 scope 起始却在包锁内发现 scope 时
拒绝，不倒序取实例锁；最终检查后才出现的独立 scope 登记不追溯取消本次包同步。
包 EX 持续到操作结束，协调锁不跨网络或安装。原 sync 调用提供原有操作授权；该上下文不返回
可脱离 EX 重用的许可，也不允许绕 Batch 意图或清 unknown。独立 sync 不创建声明、协调根、实例、
profile 状态或替代租约，也不采用旧包或旧空租约。非合作共享启动仍拒绝新声明。

候选 Linux 普通 setup 在原预览接受后准备全新 runtime，原 sync 后重新准备/比较计划，再于 apply
取得实例 EX 前完成全新 scope 登记；保存原 expected_plan 复核。旧资源保留原路径，不自动采用。
跨资源登记并非全有或全无；部分声明和合作包/旧实例并存时保留证据，已可见混用在部署前拒绝，
最终运行还须严格通过包门禁。run 只使用保存的部署身份进入合作预留/owner/派发链，不读取当前
仓库锁猜测未部署实例；原 argv/stdio/退出码和物理/状态/包 SH 寿命保持。
此候选接线和只读观察已有隔离验证，T065/T066 按资源协调及普通入口范围独立验收；
T062/T063 的完整维护编排及原生控制验收仍单列，未授予维护许可。

这里防范单份租约证据损坏；同用户同时抹掉声明与锚点、回滚整个缓存，或忽略声明的旧 checkout
仍在外部破坏/非合作边界，不能声称覆盖所有系统入口。旧资源没有完整归属证据时明确拒绝首次自动
采用；已有包或空租约均不补造声明，不借包 EX、空 Registry 或新域 ID 接管，也不全机扫描补齐。
没有公开 enrollment/repair 入口；正常 setup 仅准备全新资源，已有历史的首次采用仍拒绝。
不得将候选合作登记或只读查询报告为自动维护已开放。

原则：不持协调锁等待物理锁、宿主、网络、用户或 ready。已有物理/状态/运行包锁顺序保持；
持有它们后只可依次进入短协调锁、owner 元数据锁。禁止持 owner 锁反向进入协调锁或物理锁。

意图的非空显式选择必须覆盖所选 reservation 的完整资源并集；接受与派发均在各自短事务重核。
不能只保留共享包而漏掉实例/HOME，也不能为停止两项额外冻结未选第三项的独占资源。
未选实例与所选实例共享的包仍在闭包中，其 unknown/非终态引用按原规则阻断。

| 阶段 | 顺序 |
| --- | --- |
| 启动预留 | 短协调锁内检查所有资源意图，登记 run/op reservation 与资源代际；释放锁后才取得原有物理/状态/包 SH |
| 真正启动 | 持原有 SH 时，短协调锁重核 reservation/许可与所有相关意图，再按原 owner 锁登记；崩溃保留阻塞事实 |
| 停止接受 | 在短协调锁内按资源代际 CAS 登记本批意图；setup 须覆盖全部相交运行，stop_only 可保留快照内已知 dispatched 的未选运行；重叠意图、未确认引用或快照后新 reservation 均拒绝；不取得物理 EX |
| 等待退出 | 释放协调锁，保留 manager 与原运行观察；用共享阶段 deadline 等待，不提前取得维护 EX |
| 维护操作 | 由既有业务核心在其正常物理 EX 门禁内校验 BatchPermit/资源与当前部署，不另套 EX 再重入同一 guard |
| 释放/后继启动 | 在匹配批次/代际上变更意图；一次性许可只放行精确后继 run/op，仍核验其它批次及原生 writer |

新协议对影响资源、会话或控制计划的变更推进资源代际，和相关 owner 更新在上述短锁顺序内发布。
开始运行的 reservation 不能按超时直接删除；只有证明尚未派发且无副作用才能取消该预留。
只读计划可以在锁外收集事实，接受时使用资源代际和重新核实的快照拒绝竞争；旧协议记录不伪装成新协议。
无法证明的物理占用、未知 owner、其它 pending 部署继续阻止维护，不签发绕过它们的许可。

底层 ResourceIntent 的 active → dispatched 在控制动作尝试前持久化，记录“可能派发”。
它不执行停止、不表示已释放，也不授权 setup；后续维护仍使用独立的 Batch maintenance_dispatch_intent
及一次性 BatchPermit。stop_only 不扩大选中集合，也不因部分停止就将共享运行包视为空闲。

内部停止前清单采用 `stop-acceptance` 格式，包含初始 Batch、精确所选 v2 RunRecord、域物理身份和
采集时全域 revision。当前只允许 manual 恢复方案，完整记录摘要绑定原会话/目录/部署；
它不保存提示正文，也不推导缺失会话或目录。清单仅是历史数据，不恢复当次批准或现场句柄。
持久发布先于意图提交，并在同一个短协调事务中完成；保存文件为 0600 单链接，不能覆盖既有 batch ID。
`acceptance_digest` 绑定整份清单，意图代际为采集 revision 加一。中断残留原样保留，重复提交拒绝；
缺失一边、摘要不符或仅删除意图中的摘要字段，不能回落为可派发的旧格式。
带清单的意图派发还要重核清单、当前引用及协调表所存的 owner 摘要；这仍不是执行许可，
实际 owner/物理对象/host 的现场复核与独立批准不能省略。
早期无清单的 intent 原语保留内部兼容，不能构造可执行 Batch。此阶段不开放停止/维护 CLI。

内部 live 接受路径借用可信工作区和已持有的实例/状态/包 SH，不从清单或 owner 路径选择工作区。
先在协调锁外核验当前 deployment generation/binding、runtime/native HOME、无 pending journal，
复用正常启动的受保护文件及凭据引用投影，结束时再核状态锁身份。检查不调用 backend、
不解析凭据或读取调用者环境，不证明完整运行包仍可执行；检查与提交间依赖原 SH 约束合作部署。
在同一个短协调写事务内，以非阻塞方式取得每个所选 Registry 一次，并核验实际完整 owner、
scope/runtime 物理身份、状态锁及双向关联；同 scope 的遗漏、孤立、pending/unknown 记录不能忽略。
owner 锁保持至协调提交及同步完成后才释放。现场核验失败不能回落到元数据入口。
此检查只在接受时成立，不保存在清单中充当未来证明；不捕获 host、不批准信号或维护，
未来派发仍需自己的现场核验。外部借入 fd 的持锁寿命始终由可信调用方管理。
stop_only 未选中的共享引用只核对协调域中的阶段及关联，不跟随其 owner_ref 路径打开其它工作区，
也不声称已重读其 owner 文件。setup 要求包含全部活跃引用，届时所有所选 Registry 均须实读；
仅停止部分实例的成功不能授予共享包维护权限。

停止审阅和维护写入批准分别取得。内部 StopReview 只绑定规范化的完整计划、精确 batch 和创建
进程；可信调用方负责真实交互/显式参数策略，approve 必须精确返回 True，不能由 plan_id 或
保存的 JSON 代替。回调在现场锁之前完成，reviewed live 接受在核验成功后、首次发布前
一次消费。复制仍是同一对象，不能序列化；消费后的磁盘/响应失败或控制中断不还原批准，
现场检查失败或不同计划/批次则不得消耗原审阅。该对象不签发控制或 setup 许可。

内部 StopRequest 是 16 KiB 上限的严格 UTF-8 JSON，固定 graceful-stop；精确字段为版本/种类、
request/batch/run ID、plan 摘要、manager/host 的 pid 与 birth_id、正整数 deadline_ns。
重复键、未知字段、浮点、非有限值、同一 manager/host PID 和非规范类型拒绝；格式有效
不证明请求来源、批准、时效或句柄有效。期限必须由接收端在同 boot 下核验，不能由 codec 推断。

内部 StopDispatches 只为当前 manager 保存每 run 一份不可覆盖意图及独立 sent 结果；
保存并读回意图后才返回一次结果记账对象。意图存在而无结果时展示 unknown，不能自动重发。
结果绑定 request ID 与原意图字节摘要，当前 root 物理身份改变时拒绝写回。复制仍是同一对象，
不能从文件或序列化恢复；结果写入尝试即消费，异常/中断不还原。可信调用方仅在真实发送
调用成功后记 sent，仍须独立保证批准、host、活动批次和期限。这里只存事实，不授予发送许可。

候选 manager 请求处理器只接受原 SpawnedHost 和可信派发目录，不接受 JSON 句柄。
可信工厂另绑定 run/host/root，verify 回调必须核对当前来源/批准/活动意图/资源关联；
回调只能核验，不能等待用户交互。处理顺序为现场核验、一次 attempted、durable intent、
现场重核、注入通道一次、sent 结果。普通错误固定冲突，控制中断透传，可能派发后不重试。
请求期限用同 boot 单调纳秒核验，剩余不超过 300 秒；即使请求过期也保留最后时钟观察。
发送后期限已过仍保存 sent 事实；外层必须独立返回阶段超时，不能将 sent 当成停止成功。
内存锁不等待竞争；verify/send 必须有界，此候选没有内置原生通道或生产准入。

## 旧 OMP Domain 批次转换、派发与取消

本节保存原内部批次/permit 协议；新公开 workflow 独立保存阶段事件，不把这套状态机自动迁移到所有工具。

每个 run 保存独立停止/恢复状态；批次不能用一个总成功覆盖部分结果。

```text
accepted → stop_requested → stopped_confirmed → maintenance_dispatch_intent
         → maintenance_running → maintenance_succeeded → restore_pending
         → launch_dispatched（加载待确认，continue=not_sent）
         → restored（仅在实际加载证据匹配时）
```

任一可能执行后缺确认的边转 unknown；明确失败为 failed/partial 并保留已发生事实。
维护前必须持久化 dispatch_intent，然后在原业务门禁内校验许可并调用核心操作。
接口重入不可重发可能已消费的 operation；只有已证明未派发才允许重新接受。

维护 runner 从现有 setup 提取共用核心操作/结果接缝，保持原预检、安装、计划复核和 apply 逻辑。
BatchPermit 是由已接受批次派生的有限内存凭证，绑定 batch/revision/代际、setup 操作、规范资源、
部署与计划摘要、原维护批准及唯一 dispatch ID；不能由用户 JSON 或 ResumePermit 构造批准。
在 dispatch_intent 已持久化且原操作第一次副作用门禁核验后消费，只允许同次 runner 的声明步骤
继续复核；崩溃后不能重建一个新凭证重跑可能已消费的操作，先对账。普通 CLI 不需要该凭证，
仍走自己的原有批准与资源门禁。

当前内部派发前置只接受完整退出/释放且 manual 恢复的 setup 批次。独立 SetupReview 绑定完整批次、
原意图 generation 与 setup 计划摘要；重新取得原物理 EX、核验原部署及全部相关 owner/receipt 后，
在 Domain → owner NB 顺序下消费审阅并提交派发意图。新维护派发在原批次内保存严格
`setup_plan_digest`；旧无摘要派发只读兼容，不能恢复内存批准。BatchPermit 仅在持久事务明确返回后发行，
响应丢失不读回重签，重新批准旧快照不重放已派发批次。返回后锁已关闭；真实 setup 预览与独立维护批准
已由内部 review_and_dispatch_setup 连接：复用普通 prepared/current_plan，冻结完整摘要与脱敏预览，
只接受 Linux OMP 同一显式 local/profile、原实例/HOME/缓存/运行包以及完整批次，不隐式选择子集或登记新资源。
回调不持物理/Domain/owner 锁，必须明确 True；普通准备错误、取消和批准异常保持原契约，批准后由原派发事务
重核部署、owner 与 CAS。审阅接缝返回后仍不执行 setup 或消费 BatchPermit。

内部 execute_setup 已连接同一原 Linux OMP scope/cache/runtime 的实际共用 setup 路径：显式传递
进程内执行上下文，原同步 guard 持实例 EX → 状态 SH → 包 EX，重读计划与现场，按 Domain → owner NB
复核并消费一次许可、持久记录 running；明确返回后释放元数据锁再进入同步主体。后续 apply 沿原实例 EX
与状态 EX 顺序，再持包 SH 重核计划/原部署/释放事实，覆盖原 recover、prepare 和事务，不重入已持 EX。
未登记旧资源、新 scope/缓存/运行包、跨 profile 集合不因此获得登记或执行权限，普通 guard 继续拒绝活动意图。

原结果与退出码返回，批次只保存规范结果摘要；同步后非零结果记 partial，明确 running 后业务异常记 unknown
且原样传播。partial/unknown 同事务将原 intent 阶段置 unknown，保留资源和 owner；记账失败不掩盖原异常。
首次消费后提交响应不明时，保留可能的 dispatch_intent/running 与已消费许可，提示核验而不读回升级或二次写入；
完成响应丢失不重跑。这里只接受 manual 恢复；完整 CLI、历史未知结果的持久对账和恢复仍待完成，不代表 T074/T075 全部完成。

首次同步前已完整复核的 Plan.current 以版本封套摘要绑定为 target_deployment_digest；消费原许可后，
与 running 在同一事务保存，不能用新字段改变被消费许可绑定的原批次。旧记录缺字段继续只读，
不会据当前配置回填。apply 返回后仍在原实例/状态/包物理锁内，内容检查前后分别短核验全部 released
owner/receipt、命名资源与共享引用；其间核对状态锁、无 pending、实际 current 摘要和受保护投影。
任一失败不能记成功，原 unknown/响应不明规则保持。

只读 observe_setup 要求显式同 scope 的 local/profile 与精确 batch revision。保存目标缺失时报告不可核验，
否则取得原物理 EX，读内容前后核验批次、资源和全部 owner，不持元数据锁读取部署内容。
pending journal 只报告存在，不解析/修复；current 与受保护投影匹配也只报告当时现场匹配，不将 running/partial/unknown
改成成功，不清意图/预留或签发恢复许可。竞争、损坏或身份变化报告 unconfirmed；控制中断和原配置错误原样传播。
该观察不验证完整官方运行包，也不证明历史 dispatch 是否执行；后续持久对账与恢复必须独立处理。

显式 OMP profile 的 maintenance status 可只读查询同 scope 现存 setup 批次。命令保留原结果/退出码，
分别展示现场观察、人工恢复清单和本批意图保护；manual 不能显示成 restored，continue 固定 not_sent。
原非零维护码优先保留；已完成人工交接且当前目标/资源匹配、无 pending 才返回 0；原成功待交接或任何不确定仍为 4。
初始未派发即取消的正常无目标观察可返回 0，仅表示取消；异常观察仍为 4。查询不写记录、不恢复 journal，
不提供 execute/restore/cancel 的后续执行建议，也不把缺失记录初始化为空批次。

普通 setup 在展示/批准回调前冻结真实计划摘要，同步后从重新准备的工作区与计划复算。
摘要包括完整 current/changes/drift/conflicts、目标 binding 和实例/状态/缓存根、锁与候选身份；
即使公共脱敏计数相同，真实内容或目标变化也返回 4，不进入 apply。摘要不作为公开诊断，
不包含秘密解析步骤，也不替代 apply 原有的物理锁及 expected_plan 检查。
普通 CLI 保持原输出；批次结果封装原 operation 的结果与退出码，进度进入 stderr，
不能将内层 setup 的打印混入外层 JSON，也不能另复制一套 setup。

取消只作用于余下动作，保留已停止项与恢复清单。未派发的本批意图可按匹配代际解除；
可能已执行、unknown owner 或未知维护结果的保护不能仅靠 cancel 消除，先只读对账/原 journal 恢复。

已明确成功且保存目标摘要的 setup 可以通过独立的 complete_setup_manual 收尾：只接受原计划 manual、
全部停止/资源释放及未派发后继，先在原物理 EX 内核验目标和完整 owner/资源现场，再在锁外单独批准人工交接。
批准必须精确 True；冻结完整 batch/revision/generation，回调异常原样传播。批准后重新解析显式同 scope，
取得原实例/状态/包 EX 再核现场，最后在 Domain → owner NB 的同一事务设置 intent.completed 并推进 Batch revision、
逐项 restore_phase=manual。批次仍 maintenance_succeeded，原 operation_result 和清单保留，不把人工交接算成恢复成功。
completed 仅停止本批意图对资源的阻挡；其它 reservation/intent/owner 及原生启动门禁继续生效，没有新恢复许可。
提交异常保留可能已写事实，不自动重试或把 unknown/partial 改成 completed；原 cancel 规则不扩大，也不删除历史。

| 已证明事实 | 恢复依据 |
| --- | --- |
| stop_only 或维护确证未派发，部署仍匹配停止前快照 | 用户审阅的停止前契约，重新校验可用性 |
| 维护成功，部署结果身份已保存 | 本批成功后的契约，重新校验运行和会话 |
| partial、可能已派发或结果 unknown | 原 journal/事实对账后形成新可审阅契约；禁止自动退旧部署 |

## 有界等待及脚本输出

stop/恢复 ready 等待默认 30 秒，`--wait-seconds` 为 1–300 的整数。
整个所选集合在同一阶段共享单调绝对 deadline，逐项执行不得重启完整预算。
此预算不限制 setup 的真实安装步骤或用户交互会话寿命。
内部后代观察循环只消费已构造的共享预算，不重置；精确同 run/完整 manager 的观察先持久记账，
然后计入本轮 confirmed。记录响应不明不重试；记录后期限已到返回 4，保留已保存事实。
这个结果不证明 manager 的 SH 已释放，不设置 stopped_confirmed/resources_released 或签发许可；
调用方须另核实有效意图、观察来源/时效与原物理门禁。同步记录可能超期，循环不声称硬实时中断。
普通当前终端 resume 可在加载待确认时交接原生 TUI，不以机器回执阻塞用户操作；
保留原生退出码且不将 0 当加载证明。脚本批量控制不在同一个 stdin 启动多个 TUI。

超时结束后续自动步骤，保留逐项事实并返回 4；不强杀、不自动接续、不中途改范围。
结果含 batch/revision、requested/effected scope、逐项 stop/restore、dispatch 状态、
原 operation result/code、review_required 与完整 scope 的 next command。
缺参/必要批准为 2，所有权/漂移/未知为 4，依赖或公开能力不足为 5；
维护自身明确失败保留原结果和退出码，不能因外层取消或展示成功而覆盖。

## 原位置与继续

以下是已选待实现的驻留/新标签页契约，当前接口尚未开放。通过 Rotom Herdr 入口新建、该工具已验收的托管实例默认驻留，普通 shell 单次 run 退出返回；旧普通实例和直接官方 CLI 不在线升级。
驻留将 container 与单次 run 分开；原生子进程及相关后代完整退出、完成租约收尾后才 parked，在原 pane 显示等待恢复。
会话事件未封口不阻止已证实空闲的容器 parked；严格封口/加载回执不足也不单独阻断已准入的明确官方交接。
仍按日常恢复核实目标、原目录、部署和该工具 writer 防护，缺回执显示加载待确认、零自动输入。
容器空闲、子进程运行、资源释放与 session 加载确认分别判断，不能用活动子进程代替已加载证明。
控制端点使用私人权限、同用户调用者校验和 container/generation/op 匹配，不接受任意命令文本。
启动请求先 durable 记录，再建立新 run 与一次性许可；回包丢失为 unknown，先查事实，不重发。

work 新建/重绑采用新容器版本，不能复用旧 accepted/receipt，也不能从处于 Herdr 或启动时间较新推断具备驻留。
管理源码或协议身份变化时首版拒绝在旧进程恢复；无租约 re-exec/handoff 是另行验证的后续能力。
终端已关闭、复用或身份不明时保留待恢复，重新接受新位置；不按标题/焦点或按键猜测空闲 shell。

新标签页要求可核验的 Herdr 公开 API，复用受保护 bootstrap 与恢复意图；逐项创建并使用独立终端，保留原 session/cwd/部署及 workflow 门禁。先保存唯一请求意图，再调用创建；分别报告创建、交接、失败或未知，可能已经创建时先查询事实，不自动重开。缺 Herdr 时说明没有执行与同范围当前终端命令，不能静默切位置。

help 和命令提示说明当前未开放及未来适用条件；实现后的只读诊断和停止计划逐项说明可用、不支持、launcher/pane 丢失、身份/结果未知与下一步，不增加无证据的成功标志。Pi Pro 委派不属于本契约，`pi-pro` 普通 profile 仍遵循同一维护恢复门禁。

以下自动继续协议保留为历史附加设计，本轮不实现或开放。“继续”独立批准目标和文本；只有本次新 run、实际加载的确切会话、ready 与 writer 排他均有效时发送。
派发前记录 intent，有可靠确认才 accepted；无幂等/确认的未知结果不重发。
持久记录只保留批准文本摘要/固定模板身份和结果，文本本身仅在当次明确批准的执行内存中，
不复制进恢复清单。派发前丢失文本须重新预览批准，可能已派发后仍先对账，不能重新发送。
没有该能力或加载待确认时保持 not_sent，提供当次文本展示与已准入的聚焦，交给用户在 TUI 输入；
不等待上游增强，不用人工确认、原生 pane input 的存在或焦点正确代替 Agent 接收证明。


T114 的内部 owner 关联遵循物理 SH → 协调 EX → owner EX(NB)。第二层元数据锁忙时立即拒绝，
不能持协调锁阻塞等待 owner。各事务在协调提交及 fsync 完成前保持 owner 锁，提交后才释放。
第一次提交仅写 owner_pending；第二次写同 run ID 的不可覆盖 owner 并保存 owner_attached。
owner 新文件发布后 fsync 失败或后续提交失败均保留 pending/attached 阻塞，不删除记录或重新派发。
显式 dispatch_owner 要求 attached、原 scope 和所有物理 fd、OMP 所有权收据与双向摘要仍一致，
先保存 dispatched 才返回；此函数本身不执行宿主。现有 Domain.dispatch/cancel_reserved 不能处理链接阶段。
该关联原语本身只证明当次映射；候选合作入口另外消费 T116 的 scope 锚点与 T115 的释放链，
仍不提供 BatchPermit。旧 owner 的 idle_confirmed 不能单方面清除共享 reservation。


T115 的 finish_owner/reconcile_owner_release 是内部退出记账接口，调用方持续持有原实例、状态与包 SH，
再按协调 EX → owner EX(NB) 排序；owner 锁覆盖每次协调提交/fsync。只接受精确 ReleaseObservation、
同 run/manager 的完整观察，以及当前进程仍为该出生身份；不接受 JSON 布尔保证或外部声明。
先将固定末态摘要/观察时间保存为 release_pending；成功返回后再把同 owner 写成 idle_confirmed，
同步文件、目录及父目录链并复核所有链接，最后保存 released。自然退出可发生在意图已存在时，
它只解除本 run 的引用，不取消意图；其它运行保留原状态。released 记录保留，不能再次派发或取消。

pending 对账仍须由同一存活 manager 在重新完整观察后发起。只接受原 active 摘要或收据严格指定的
idle 摘要和时间；不重新生成退出时间，不启动宿主。即便上次 owner 已替换，也须重新同步后才提交
released。manager 改变、owner/reservation unknown、目录或来源变化继续阻塞；普通 Registry 单边 idle
不能替代此协议。未知历史的物理 EX 核实及全局域覆盖仍未实现，不因这个内部闭环开放维护。

最终协调 rename 成功后的目录 fsync 失败可能留下可见 released；退出事实及 owner 已先同步，不能
把异常当成动作未发生。reconcile 也允许严格匹配的 released/idle 在同一 manager 新完整观察下重核并
再次同步 owner 与协调记录，推进协调 revision；不写 owner、不换时间或收据、不重发任何宿主动作。
released 对应 active/unknown、错身份、错摘要/时间或资源替换仍拒绝。元数据同步确认不等于重新派发。


T116 内部新实例登记只接受尚不存在的目标；已有空目录或旧实例均拒绝，且不为其留下声明。
可信调用方提供 Domain，该历史容器方案的根生产选择/工作区校验仍未接通。登记先不可覆盖保存父容器中的独立声明，
同步声明目录和祖先，才创建实例、物理锁和隔离 HOME。owner 与实例/HOME 锚点不可覆盖发布，
同一锚点再写入仍未对外开放的锁 fd 并同步；最后持实例 EX 在短协调事务登记两个资源。
不持协调锁等待物理锁或执行宿主。声明、任一锚点或非空锁都使普通入口拒绝旧格式回落；
上述历史容器采用方案若未完成其合作入口，即使域记录为 ready 也不得据此启用；此限制不否定已接通的普通 OMP cooperative run/setup 路径。

scope 验证固定原父容器、实例目录、锁 inode 与 HOME inode，校验 owner 全字节摘要和精确工作区归属。
同域资源集合必须包括一个 runtime 与此 scope 的两个资源；runtime-only、缺项、错 scope 或多项均拒绝。
attach/dispatch/release 重用此检查，退出记账不删除 scope/claim。注册失败前后、响应丢失或 fsync
失败均保留现场；已成功写入的 ready 可以只读核验，但不能通过重新 enroll、取消或重启来补记。
旧资源历史采用、跨旧版本入口的覆盖和旧 unknown 的物理 EX 对账继续门控，不由新 scope 锚点证明。


## 当前终端候选的请求与派发记账

新 run 登记并核验完整配置之后，持原运行租约在独立 `resume-attempts` 目录原子保存 intent，
然后调用 before_dispatch，再创建继承 stdio 和租约 FD 的官方子进程。启动调用成功返回才记录
launched 并调用 after_dispatch；此时可显示加载待确认，不等待进程退出，也不填实际会话。
intent 写入失败不启动；文件已发布但同步/响应失败仍保留 intent，同 run 不可覆盖重试。
目录锁只覆盖短元数据操作，不持它等待宿主或反向取得 owner/物理锁。

已创建子进程后的记账、通知或展示失败只给固定诊断，继续等待同一个子进程，不杀死、不重启，
不覆盖原生退出码。退出后可补记已经观察到的本次启动与退出事实；无法补记时保留旧记录。
wait 自身失联则内存结果为 unknown，不再次 wait 或 spawn；子进程继承的租约仍在，owner 按既有
完整释放观察记账，缺证明保持未知。该候选不设置等待超时，也不发送探测或继续文本。

本地受管普通 DSH run 复用相同的直接子进程捕获与单次等待边界，但不创建恢复请求记录。
仅在已有 active managed 登记中绑定 host 观察，control 仍为空；捕获/登记失败继续原等待。
等待普通错误返回 4，Popen 启动失败返回 5；控制异常透传，不自动 kill 或重试。
SSH、未登记路径及显式启动回调保留原派发逻辑，不从本地传输进程推断远端 host。

实例列表将 requested_session/requested_cwd 与 session/session_cwd 分列。辅助请求记录损坏只令
请求观察不可核实、查询不完整，不抹除独立的进程和会话观察。intent 没有已启动证明，显示 unknown；
launched 及原生零退出仍是加载待确认，非零退出明确失败。所有请求状态均不授予控制资格。

## 关键记录的目录持久化

文件 fsync 和所在目录 fsync 不能替代新建目录在其父目录中的链接持久化。停止意图、
私人 inbox endpoint/request、恢复请求、协调域初始化与 run owner 登记必须先发布文件，
再同步父目录及全部祖先，最后重新核对记录和命名根身份，才能返回派发前置对象。
任一步失败保留已经存在的事实，不将响应丢失解释为未执行。OMP attach 的第二事务在
owner 发布及祖先同步后才提交 owner_attached；失败时保留已持久化 owner_pending，
不取消、派发或启动。控制中断仍原样传播，普通错误不得泄露私人路径或异常原值。

内部 pidfd 终止原语只允许当前原始 SpawnedHost 的一次 SIGTERM，先消费再复核及调用；
失败、控制中断或未知结果不能重发。复制保持同对象，禁止序列化。系统调用返回不证明
Agent 已优雅退出、会话已封口或资源已释放；无工具级原生准入和有效批准/intent 时，
默认启动和 CLI 不调用此原语。
