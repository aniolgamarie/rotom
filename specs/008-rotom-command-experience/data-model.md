# 数据模型与状态约束

日期：2026-10-23。状态：待实现的契约；以 [规格](spec.md) 与宪章 3.0.0 为界。
全部新持久对象有整数 `schema_version`，拒绝重复键、未知字段、非法类型及非有限数值。
路径按已有安全原语验证；私人目录 `0700`、文件 `0600`，不保存秘密、完整环境、argv 或会话正文。

## 1. InvocationContext 与 CommandDefinition

两者仅为内存对象，不写数据库。

| 对象 | 字段及不变量 |
| --- | --- |
| InvocationContext | 已注册 command_path、display_prefix、explicit_fields、input_policy、output_mode、已解析 Scope、InputGateway；不携带秘密值 |
| Scope | machine 或 local 来源、agent、profile、component；保留显式/偏好/既有默认来源；显式条件是硬约束 |
| InputPolicy | legacy、auto、interactive、no_input；新门面按三流 TTY 门控，旧入口省略上下文时保留 legacy |
| CommandDefinition | parser leaf 身份、scope_rule、参数位置与 E/T/D/A/N 分类、candidate_source、noninteractive_approval、effects、帮助与示例 |
| TypedInvocation | 校验后的命令及 token 参数；native_tail 独立且不透明，绝不从菜单显示文本反向解析 |

注册表与实际 parser leaf 双向校验；新增 leaf 不允许缺少输入/授权/补全声明。
错误建议从 TypedInvocation 生成，不能替换原结果中的任意命令字符串。

## 2. Preferences v1

路径：`${XDG_CONFIG_HOME:-$HOME/.config}/rotom/config.toml`。
此处是路径规则记法；环境路径为字面绝对路径，不求值 shell 或变量。

```toml
schema_version = 1

[defaults]
agent_machine = "workstation"
term_machine = "workstation"
work_machine = "workstation"

[run_profiles]
dsh = "dsh-default"
pi = "pi-base"
omp = "omp-default"
```

三个管理面分别验证机器引用。省略值表示采用该命令既有回落，不表示复制另一个管理面设置。
set/unset 在短文件锁内复核原文件身份与字节，原子替换；拒绝外部并发编辑、符号链接与不安全权限。
正常 run 和菜单选择不写偏好；show/help 不创建文件。恢复以会话归属为准，work 以固定 binding 为准。

## 3. EntryBinding v1 与 GeneratedArtifact

EntryBinding 的固定目标和交易顺序见 [入口部署契约](contracts/entry-deployment.md)。

| 字段 | 规则 |
| --- | --- |
| schema_version / launcher_protocol | 均为 1；未知版本拒绝，不猜其它入口 |
| repository | 显式可信 checkout 的绝对字面路径；不按调用者 cwd 或 main 分支推导 |
| repository_identity | 可信根目录身份及入口协议来源摘要；Git HEAD 不是唯一内容证明，也不要求启动时读取 Git |
| entry_relative / python_relative | 固定为该协议允许的仓库 rotom 与准备环境入口；不能配置任意命令或 shell 片段 |

GeneratedArtifact 包含 kind=`rotom-entry-binding`、目标 ID、精确 UTF-8 字节、sha256、mode、
generator_version、来源输入/模板摘要和写前身份。序列化 key 顺序、缩进与结尾换行固定。
绑定路径是私人机器信息，不能进入公开产物或公开测试 fixture 的真实值。

新 catalog v2 的 static 类型保留旧语义；生成类型只允许上述固定协议。
term state/journal v3 记录生成内容及其受保护 payload 引用；v2 只读兼容，不自动丢字段降版。

## 4. RunRecord v2 与兼容记录

继续使用已有实例状态目录 `run-owners/RUN_ID.json`，不另建原生会话数据库。
新读取器接受经过完整校验的 v1 和 v2；旧 v1 缺少能力证据时只能用于只读观察/阻塞判断。
不在线改写活动 v1 记录，不把 unknown 转成空闲；旧读取器遇到 v2 必须拒绝，不能吞字段。

| 字段组 | 规则 |
| --- | --- |
| schema_version / run_id / binding_digest | v2；run_id 是单次随机身份；绑定到原有物理实例与部署归属 |
| manager_identity / host_identity | PID、平台 birth identity、可验证关系；host 可未知；稳定句柄仅在进程内持有，不能把 FD 数值持久化后重用 |
| agent / backend / profile / machine_ref | 已解析归属；machine_ref 是非秘密配置引用，不携带整份配置 |
| start_cwd / session_cwd | 分别记录来源与确认状态；原目录无效时不猜调用目录 |
| native_home_ref / deployed_identity | 经过安全路径校验的存储归属及保存的运行/部署身份 |
| lifecycle_state | 保持 active、unknown、idle_confirmed 三种所有权状态；展示的 stopped 不直接写成 idle_confirmed |
| process_observation | 来源、观察时间、身份和覆盖；内核完整释放证明才可确认 idle |
| session_observation | SessionRef、emitter_epoch、sequence、确认级别与事件来源；可缺失/历史/已确认 |
| terminal_ref | 可选 TerminalRef；没有证据时位置未知 |
| protocol / coordination_domain | 合作准入版本、可信协调域锚点；旧/不匹配版本不获得自动控制资格 |

状态转换：登记 → active；完整同身份释放观察 → idle_confirmed；观察不完整、manager 丢失或记账失败 → unknown。
unknown 只能在既有物理 EX 核实路径取得完整 ReleaseObservation 后转 idle_confirmed；超时、取消或用户保证都不够。
展示上的进程退出、会话确认、可恢复位置是三列独立事实，不新增一个含糊的 ready 总状态。

## 5. SessionRef 与 SessionObservation

SessionRef 由 agent、backend、native_home_ref、native_ref 构成；native_ref 可以是后端允许的 ID 或受限引用，
但动态补全只输出允许的标识，不泄露路径值。裸 ID 不是主键。
profile 和 machine/local 限制查询范围；已知归属不受启动默认配方重算。

只读“已知会话”视图来自 RunRecord、受保护恢复清单与已审核的后端元数据接口，不复制正文。
普通查询不全盘发现会话，不为补全创建缓存。未登记显式 ID 须经所选后端公开接口核验。

SessionObservation 记录当前 run/emitter 代际、递增序号、原生会话/目录来源和确认状态。
恢复加载确认与可输入状态分开；决策事件不直接当作已经完成的会话切换。
停止清单只在最终事件流封口且完整退出证明匹配时记录“最终确切会话”；迟到、缺口或强杀时降为历史/未知。

恢复请求中的目标 SessionRef/cwd 与 SessionObservation 是不同事实，不能由前者填充后者。
共享恢复执行器分别保留请求目标、新 run、启动派发结果、实际加载确认和继续结果。
`launch_dispatched` 只证明官方启动已派发；没有加载回执时保持“加载待确认”并交接 TUI，
只有本次实际加载证据相符才为 `restored`。失联或可能执行但派发结果不明为 `unknown`，
不得据此再次启动；确证失败才为 `failed`。这些都是恢复动作的事实，不覆盖 RunRecord 的所有权状态。
人工确认、原生退出码 0、请求中的 ID 和 registry 可见均不能升级为机器加载回执。
没有加载及输入能力证据时 continue 为 `not_sent`，交给用户直接在官方 TUI 操作。

当前无加载回执的候选使用独立的 `resume-attempts/<run_id>.json`（格式 v1），保留 RunRecord v2
兼容边界。记录只含 binding 摘要、新 run/完整 manager 身份、请求 SessionRef/cwd/可选原 run、
派发意图或已启动、观察时间、可选原生退出码，以及固定 unknown 加载状态和 not_sent 继续状态。
目录/文件为 0700/0600，拒绝链接、未知字段/版本、重复 JSON 键和不精确数值；没有正文或 argv/env。
读回只提供历史请求事实；不能由该记录生成 SessionObservation、writer 证据或重新派发许可。
从公开只读元数据取得、此前未由 Rotom 登记的会话以 `KnownSession.run_id=None` 表示，
对应 `previous_run_id` 保存为 JSON null；不编造旧运行身份。新派发仍必须取得严格的新 run，
metadata 的 ID/cwd 只记历史候选，不证明当前会话、加载、writer 空闲或最终封口。

WriterEvidence 记录后端/来源、会话键、有效期或租约身份与覆盖范围；不能将 Rotom 本地锁冒充原生外部 writer 排他。
证据必须覆盖实际启动/发送；不能持久化一个旧的“无 writer”布尔值供未来批准使用。

## 6. StopPlan、Batch 与资源协调

协调根使用已校验 `machine.paths.state_root/lifecycle`，不使用过滤后的子进程 XDG 重算。
物理实例已有 `.agentcfg-instance.json` 锚定 per-profile state_root，须与解析结果相符。
共享资源不能证明属于同一协调域时，自动维护拒绝；旧入口和外部进程仍由物理租约阻止不安全写入。
OMP cache/runtime 可由不同 instance/state 共享，资源键不能只用 machine/profile 或配置路径字符串。
每个物理资源的协调域锚点及 owner/reservation 引用范围必须完整、可信且可复核；
新域或已有资源首次采纳无法证明完整覆盖时，保留未知并拒绝自动维护，不自动接管或扫描其它配置。
T044 的基础观察不创建该协调协议；OMP 合作登记由 T065/T066 的完整协调门禁约束，缺记录不证明空闲。

T112 先实现 ResourceKey 的物理身份部分：`kind`、`device`、`inode` 和规范 JSON 的 SHA-256 `key_id`。
读取时必须通过私人路径边界核对现存目标与调用方 fd；反序列化只验证数据形状与摘要，不能恢复这种现场证明。
同一 kind 的同一物理对象保持同键，路径和 profile 不参与摘要。OMP runtime 采用稳定的包租约文件作为锚点，
不采用激活时会替换的运行包目录 inode。device/inode 只描述本次观察，不保证跨删除重建或 inode 回收永久唯一。
后续 T065 仍须补充不可混淆的归属代际、协调域锚点和完整引用证明；仅有该键不得首次采纳资源或放行维护。

| 对象 | 最小字段 |
| --- | --- |
| ResourceKey | kind、经核实的物理资源归属与摘要；覆盖 instance、runtime、native-home，别名不能分成两把独立锁 |
| LaunchReservation | run/op、资源集合、域、代际、阶段；启动前登记；可能已启动时不能按时限直接清除 |
| StopPlan | 显式 scope、operation 或 stop_only、排序的 run 集合、资源闭包、观察/部署摘要、恢复位置与能力、schema；只读计算 plan_id |
| Batch | 随机 batch_id、revision、原计划/operation、已接受目标、逐项事实、dispatch 状态、原操作结果、review_required |
| ResourceIntent | batch/代际、规范资源集合、意图状态及可选完整 Batch v1 progress；冲突检查与登记在一个短协调锁内完成 |
| BatchPermit | 有限内存凭证：batch/revision/代际、operation、资源与部署/计划摘要、原维护批准及唯一 dispatch ID；在原操作首个副作用门禁核验后消费，不是公开输入或持久可重放令牌 |
| ResumePermit | 精确 batch/代际、后继 run/op、SessionRef、预期部署、位置；一次消费，不是一般 profile 白名单 |

plan_id 是规范序列化快照摘要，不是授权密钥。只读计划不创建 Batch、reservation 或资源意图。

T067/T068 的纯数据核心可先于执行器实现。StopPlan 输入固定 resolved scope（machine/local 与可选
agent/profile 硬过滤）、显式 selected_runs、run 快照及资源快照；输出只保留选中项和其资源闭包。
每项包含观察及部署摘要、资源引用、恢复模式与能力；v1 资源绑定 domain/resource ID、物理域、
generation、ResourceKey、完整引用集合和 coverage。重复标识、跨域及有歧义的物理别名拒绝，
未知覆盖或不满足的恢复选择保留阻断原因，不丢弃未知项来生成可执行计划。
相同控制事实按规范顺序产生相同 plan_id；函数不加入当前时间或随机数。新的观察时刻本身不应
被上层收集器当作目标漂移，控制身份、部署、资源归属或恢复选择的变化必须进入摘要。

未选 run 引用相同资源时，setup 计划阻断；stop_only 保留明确选择的目标，不把共享资源上的
其它 run 自动纳入。人工恢复方案明确不承诺自动恢复；指定原位置但能力不足必须先重新选择。
这些均是快照的数据约束，不代表现场核验已经发生，也不签发停止或维护许可。

Batch codec 保存原计划、精确接受集合及逐项停止/恢复事实，区分维护与启动派发阶段，保留原操作
结果和 review_required。unknown 或可能已派发无确认的状态不能编码成整体成功；stop_only 不得
携带已执行 setup 的结果。codec 不执行状态转换、不写磁盘、不生成 Permit，读取成功不证明
记录中的批准或原生事实真实成立。T069 在完整协调准入之后负责持久化、复核与派发顺序。

StopReview 是内部停止审阅的单次内存对象，只绑定完整规范计划、batch ID 与创建进程，
不增加持久化 schema 字段，不由保存的 Batch/intent 重建。复制保留同一对象，序列化拒绝；
精确匹配后在短内存锁内消费，后续持久化失败不恢复。它不是 BatchPermit/ResumePermit，
实际用户确认策略、现场句柄及维护写入批准仍是独立前提。

DSH 使用独立 StopPlan v2（`protocol=rotom-maintenance-v2`），不虚构 OMP Domain。
coordinator 固定为 `dsh-instance-registry`，绑定 scope 摘要、Registry 物理身份和完整 owner 集合摘要；
资源仅含 resource_id、ResourceKey、reference_runs 和 coverage。scope 必须是完整的单一 DSH profile，
仅选中项进入 runs，全部非空闲记录保留在资源引用中。控制能力不足或缺失 host 均明确阻断。
DSH stop_only 保留并披露 unknown coverage，它不单独阻止精确目标停止；setup 仍因此阻断，
且未选共享引用继续阻止 setup。此规则不改变 v1 计划的完整覆盖要求。
这些字段是数据声明，不能替代原句柄或外部 writer 证明；旧 v1 Batch/OMP 接受格式继续拒绝 v2 plan。
生产只读采集固定报告 coverage=unknown、control_capability=unavailable，不构造停止审阅。

实例列表与停止目标直接展示已保存的 `deployed_identity={deployment,runtime}`：deployment
是启动时所选配置/渲染产物/适配器/锁的组合 SHA-256，runtime 是锁定包组合身份；run_id
区分同一版本的各次运行。JSON 保留完整摘要，人类输出标明启动时登记版本；v1/未登记项为
null/unknown，不读取当前配置来补写历史。不新增时间版本或第三个重复组合 hash，也不把
运行包锁身份描述成每个已安装文件的完整内容证明。版本不改变退出和资源释放门槛。

DSH 的内部人工恢复参考使用独立 `run-stop-snapshot` v1 封套，复用完整 RunRecord v2，
不构造未获证明的协调域或 Batch；v1 不嵌入 StopPlan。字段严格限定 schema_version/kind、binding 及摘要、
Registry 物理身份、batch_id/plan_id、完整 owner 集合的 records_digest、排序 selected_runs、
仅选中项的 records，以及固定 `restore_mode=manual`。最多 1024 条，规范编码不超过 16 MiB。
只选 active/managed DSH；未知 host/session/cwd 原样保存，不从 start_cwd 补造 session_cwd。
解码只能核验所选记录与摘要形状，不能重建未保存的完整集合或证明当前事实。

`run-stop-snapshot` v2 在 v1 封套上只增加规范化的完整 DSH v2 plan，原 v1 API/字节保持兼容。
plan 的 scope、coordinator、plan_id、所选集合、记录/部署摘要、manager/host 与会话历史状态
须与封套及所选 RunRecord 一致。构建时另核对每个资源的引用正是传入全集的全部非 idle 项；
解码无法重建未保存项，不把该声明当现场覆盖证明。含计划的总大小仍限制为 16 MiB。
codec 可保存 blocked 历史计划；内部 `save_reviewed_snapshot` 则只接受 ready 与精确 StopReview，
核对真实部署布局、完整 owner CAS 后在首次写入前消费审阅，再按既有顺序保存快照和 fence。
中断不恢复审阅或从文件重建它；此入口只保存审阅/阻断事实，生产控制仍须独立核验并准入。

上层持原实例/状态 SH 后，owner 锁内核对 fresh 完整集合摘要及所选记录精确相等，
先持久保存不可覆盖的 0600 快照，再发布 `run-stop-fence` v2 及 snapshot_digest。
v1 fence 继续只表示阻断。快照独立读取允许返回孤儿历史；v2 fence 读取必须同时核对快照关联。
任一文件缺失、变化或同步失败都不删除保护、不自动重放；文件存在不表示批次已接受、
已停止或可恢复，也不能产生 StopReview、BatchPermit 或 ResumePermit。

T113 的内部 `resource-coordination.schema.json` 先限定 runtime 子集，schema_version 为 1。
`coordination.json` 位于显式初始化的 `machine.paths.state_root/lifecycle`，保存随机 domain_id、
该目录的 device/inode、递增 revision，以及 resources/reservations/intents。域目录复制到另一物理位置
不能沿用记录；每个 resource_id 还绑定 runtime ResourceKey、cache 定位信息和运行包 identity。
cache 路径只帮助重新打开核验，不能代替物理身份或授权别名。状态为 preparing/ready/unknown；
本轮仅在新锚点发布后登记 ready，缺失/其它状态都拒绝控制。

runtime-anchor 将 domain_id、domain_physical、随机 resource_id 和 ResourceKey 固定在包租约原 inode。
同一严格记录还在 `cache/runtime-claims/<identity>.json` 不可覆盖地保存；独立声明先于租约和域
登记持久化，没有新的数据版本或授权字段。声明存在性只作为禁止旧格式降级的依据；其损坏也保持
拒绝，内部控制还须核对声明、当前租约与域记录一致。普通旧格式读取不创建该目录或声明。
它不保存需要追随的域路径。旧空租约、既存包或另一域记录不能自动采用；随机 ID 防止仅凭回收后的
inode 认领旧记录。独立声明防止单独租约损坏被当作旧格式，但无法防止同用户同时清除所有证据或
回滚整个缓存；不能借保留声明断言已有资源的历史引用完整，也没有自动删除/修复接口。

reservation 保存 run/op、owner_ref（state_root 与 machine/local/profile 绑定）、resource_id 集合和
reserved/dispatched/unknown/cancelled。intent 保存 batch/generation、setup 或 stop_only、资源与明确
selected_runs 集合，以及 active/dispatched/unknown/cancelled。只有 reserved 预留或 active 意图可取消；
dispatched/unknown 不清除，不设 TTL，也没有 release API。完整字段、未知字段和交叉引用由 codec 检查，
原子状态转换由短域锁完成。这些记录不等于 RunRecord、退出证明、批准或 BatchPermit。
后续停止必须带回原 scope/operation/run 集合重算，不靠一个摘要猜原输入。
普通 stop 可 stop_only；恢复后新 run/op/receipt 不能继承旧已消费许可。

**已接受停止的持久进展（部分实现）**：新 stop acceptance 的 intent 增加可选 `progress`，值为完整
`maintenance-batch` v1；首次与 acceptance 的初始 batch 精确相等，和 intent 在同一个
`coordination.json` 原子提交中保存。原不可覆盖 acceptance 文件及其摘要不改写；reader 同时核对
schema/kind/protocol、batch_id、完整 plan、operation 和 accepted_runs 不变，资源/域关联仍须严格匹配。
Batch revision 是独立于 Domain revision 的逐批 CAS，所有进展写入仍在原 Domain 短事务中完成。
旧 intent 缺 progress 时保持原快照只读兼容；进展 API 明确拒绝，不能从初始清单推造当前阶段。

停止前段 API 只接受 active/dispatched intent 和 accepted/stop_requested Batch。
requested 仅保存单次请求事实；完整同 run/原 manager 的 ReleaseObservation 只设 exit_confirmed，
重复事实即使 revision 新鲜也拒绝，不重放写入。mark_unknown 保留全部 facts，推进批次 revision，
将 item/总体进展及 intent 标为 unknown、要求人工复核；旧 Domain unknown 入口同步推进总体进展并保留 facts。
intent unknown 与 Batch unknown/partial 相互绑定；对含 progress 的 intent，旧 cancel 仅可取消完全未推进的初始 progress，
不会清除已有请求、退出或不确定事实。failed/stopped_confirmed、maintenance 和 restore 等后续阶段
只能由其专属转换推进，本前段 API 不接管、不回退到 accepted；只读查询仍可解释合法后续状态。

共享预算等待从原接受快照读取所选 manager，跳过已有 exit_confirmed，新的完整观察逐项按 Batch revision CAS
保存；失联、写后响应丢失或 revision 竞争不自动重试，已保存事实不回滚。unknown/cancelled 或非前段批次在
observe 前拒绝；全部已记录时也检查原绝对 deadline，到期或时钟不明仍返回 4。
返回 confirmed 只表示完整退出观察已持久保存，不证明 manager/实例/状态/包 SH 已释放，
不设置 resources_released/session_sealed/stopped_confirmed，也不产生 BatchPermit、控制或维护许可。
本进展增量不读写 owner、不清意图/预留保护、不调用宿主；setup 资源核验由下述独立入口处理，维护 runner 仍待后续实现。

**setup 资源释放观察（部分实现）**：`confirm_setup_release` 只接收 setup 的停止前段批次，要求原 revision
及全部已保存 exit_confirmed；从当次可信 workspaces 精确选择打开现存锁，不从历史记录追踪其它工作区路径。
自行取得实例/状态/运行包 EX（共享运行包去重），先在短协调锁外重核原部署和受保护文件，再按 Domain → owner NB
核对原资源锚点、全部相关预留/意图、所选原 owner 的精确释放末态及 receipt。所有 owner 和物理 EX 保持到
协调表提交结束，随后释放。成功只将本批各项 resources_released 及 stop_phase、总体 phase 记为 stopped_confirmed，
推进 Batch revision，不设置 session_sealed、维护派发或恢复事实，不修改 owner、预留或意图 phase。

实例/运行包/HOME 的物理身份与原持久锚点匹配；状态锁核验本次取得 fd 与当前命名对象一致，当前接受格式
没有保存历史状态锁 inode。仅有 released reservation/idle owner 不够：manager 写入这些记录时仍可持有 SH；
仅有 EX 也不够：未知/未关联 owner、额外共享引用或其它活动意图仍阻断。返回批次是一次历史观察，不能携带锁
或构造 BatchPermit，后续 setup 须再次经过实际写入门禁。本入口不接受 stop_only，不要求 DSH 精确停止等待共享第三项退出。

**setup 派发前置（部分实现）**：独立 `SetupReview` 在无锁处接受明确批准，绑定完整 stopped_confirmed
批次、原 intent generation 与实际 setup 计划摘要；停止批准不能替代它。`record_setup_dispatch`
重新取得原物理 EX、核验部署和完整 released owner/receipt，再在原 Domain → owner NB 顺序下
重核批次 revision，单次消费审阅，原子保存 maintenance_dispatch_intent 和唯一 dispatch_id。
`maintenance_dispatch.setup_plan_digest` 是可选的严格 SHA-256 字段，not_dispatched 阶段禁止出现；
新派发必须保存，旧派发缺字段仍可作历史读取，但不能据此发行新许可。该字段不包含配置或秘密正文。

只有协调事务明确成功退出后才发行绑定提交后完整批次的进程内 BatchPermit。提交响应丢失时不发行，
许可发行失败时也不重写派发意图；重新审阅旧快照不能越过已有 dispatch phase。所有物理和 owner 锁
在返回前释放，意图、预留及原 owner 保留；普通启动/写入仍被原 guard 阻断。当前只接收 manual 恢复路径，
真实 setup 预览已有共用私有摘要：绑定完整 Plan、工作区目标、锁和候选身份，并在普通 setup 的 sync 前后比较。
`review_and_dispatch_setup` 复用只读 prepared/current_plan，核对 Linux OMP 同一显式 local/profile 的全部 run，
原资源 key/ID、owner 引用、实例/HOME、runtime identity 和缓存路径均与当前 workspace 一致才展示脱敏预览。
批准在锁外接受明确 True，取消/回调异常及普通准备错误保持原契约；完整摘要冻结于回调前，随后只调用一次
原派发事务。新包/新缓存、多 profile 或无法匹配完整批次均拒绝，不按历史路径打开其它工作区。
此审阅接缝只返回派发结果，不自行执行 setup、sync、apply 或恢复，也不消费 BatchPermit。

**限定 setup 执行（部分实现）**：内部 execute_setup 消费同进程派发结果，复用原共用 setup 操作，
仅支持同一原 Linux OMP scope/cache/runtime 及 manual 恢复。原同步 guard 在实例 EX → 状态 SH → 包 EX
下重读完整计划并复核原部署/释放 owner/全部资源引用；Domain → owner NB 顺序下消费许可，
原子保存 maintenance_running/dispatched，明确返回后才执行原同步主体。Domain/owner 锁不覆盖安装。
原 apply 在实例 EX → 状态 EX 后取得包 SH，重新核对计划和原释放事实，再执行原 recover/prepare/transact；
不另套实例或状态 EX，不在维护路径创建缺失根/锁，也不登记新资源。普通入口仍受原活动意图阻挡。

原 SetupResult 原样返回，持久结果只保存 code/status 与规范摘要，不保存配置正文。成功记 maintenance_succeeded；
同步后明确非零结果保留原 code，保守记 partial；已明确进入 running 后的业务异常记 unknown，并原样抛出。
partial/unknown 与原 intent.phase=unknown 同笔更新，所有原资源/预留/owner 保留。结果记账失败不掩盖
原业务异常。若首次消费后的提交响应不明，没有可信新 CAS，保留可能的 dispatch_intent/running 和已消费许可，
给固定提示，不读回升级、不再写 unknown 或重试同步。完成响应丢失也不重跑。

`maintenance_dispatch.target_deployment_digest` 可选且为严格 SHA-256，只能与 setup_plan_digest 一起出现在
dispatched/confirmed/unknown；旧记录缺字段继续可读，不回填。新执行在首次同步前，从当时完整复核的
Plan.current 计算含版本封套的摘要，在消费原许可后与 running 同事务保存。它绑定目标部署契约，
不是批准、执行成功证明或可重放凭证。apply 正常返回后仍持原物理锁，先核验全部释放事实，再核对
命名状态锁、无 pending、实际 current 摘要及受保护投影，随后再次核对状态锁和全部释放事实，才可记录成功。

内部 `observe_setup` 返回 `SetupObservation(batch, target_state, resources_checked, pending_journal, reason)`，
只按本次明确 local/profile 解析同 scope 工作区，不渲染候选或按历史路径打开其它实例。缺目标摘要报告
target-unavailable；有摘要时持原实例/状态/包 EX，在内容读取前后短核对完整批次 CAS、owner/receipt 和共享引用。
pending 存在只报告 journal-pending；无 pending 时核对 current 及受保护投影，报告 target-matches/target-differs；
现场无法确认报告 unconfirmed。结果返回前释放锁；匹配只描述当时部署契约和受保护投影，不证明整个运行包、
历史执行成功或恢复安全，不改结果/意图、不清 unknown、不发行许可、不重试或恢复 journal。
历史未知结果的持久对账、journal 恢复、批量恢复及 CLI 接线仍待实现。

新预留增加 `generation`，取其成功提交后的域 revision；可信调用方可以用 `expected_revision`
在同一短锁中拒绝过期快照。域 revision 是整个域的保守代际，任何协调写入均推进它；
预留的 generation 固定不变并进入 owner 双向摘要，不要求后续派发仍等于全域当前 revision。
旧原型记录缺少此字段时保持只读兼容，不补造代际或获得新合作入口资格。
新资源和选中 run 集合均排序后保存；读取既有记录不因顺序不同重写。

内部 `OmpLaunchReservation` 由可信 workspace 指定的全局 state_root/lifecycle 产生，
不能从 claim 的路径指定协调根，也不把 per-profile state_root 当作独立域。
预留阶段只读取已有独立声明与三个 ready 资源候选，并以快照 revision CAS 持久化；
不取物理 SH，不创建或采用资源，不证明实际覆盖。token 只含不可变标识、代际与 owner_ref 摘要。
调用方取得原实例/状态/包 SH 后，还须在一个短协调事务内重核同一 token、scope 锚点及包 fd；
HOME fd 只固定身份。缺旧代际、claim、完整资源或出现别名/域变更均拒绝；响应丢失保留预留。
此接口尚不派发宿主、创建 owner 或启用 OMP 日常登记。

stop_only 意图允许已知 dispatched 引用中的明确非空子集，第三实例的 owner 与预留不变；
setup 仍要求覆盖全部相交引用。两者遇相交 pending/unknown 等未确认阶段均拒绝。
`ResourceIntent.dispatched` 在控制动作尝试前持久化，表示可能派发；它不表示进程退出或 setup 已开始，
也不是 Batch 的 `maintenance_dispatch_intent` 或 BatchPermit。后续 setup 必须另外通过完整释放与原操作门禁。
详见 [生命周期契约](contracts/lifecycle.md) 的锁顺序、批次转换和 dispatch 前持久化规则。

T114 在 reservation 上新增可选 owner_link：registry_physical、instance/path/key、native_home/path/key、
ownership_digest 与 record_digest。owner_pending/owner_attached 必须有该链接；链接存在时只允许
这两个阶段、dispatched 或 unknown，不能退回 reserved/cancelled。codec 重核路径和 ResourceKey 摘要。
实例键对应 OMP 锁文件，HOME 键对应调用方固定的目录；两者不证明历史完整或原生 writer 排他。

OMP 内部 RunRecord 的 coordination_domain 可保存严格 rotom-owner-link-v1 引用：domain_id、
domain_physical、op_id、link_digest。link_digest 绑定原 reservation 的 run/op、owner_ref、完整包集合
及 owner_link 的物理观察；record_digest 再绑定包含该引用的完整初始 owner 记录，避免跨 run/域拼接。
普通登记继续只接受 null；内部记录仍为 registration=2/control=null，不代表停止或恢复能力开放。
owner_pending 落盘后才写 owner；登记失败、owner 丢失或替换均保留协调阻塞。即使 owner 通过旧接口
已记 idle，关联的 reservation 也不自动释放；必须另走下述 T115 完整观察与对账，不能从 owner 单边结果推断空闲。

T115 增加 release_receipt（observed_at_ns、owner_record_digest）以及 release_pending/released 阶段。
这两个阶段同时要求 owner_link 与收据；收据也可保留在 unknown 中，但 unknown 不能通过当前 manager
的补记入口解除。其余阶段拒绝携带收据。时间必须为精确正整数，摘要指向固定的 idle_confirmed 全记录。
收据用于两份记录之间的提交对账，既不序列化可重放的退出许可，也不恢复已丢失的观察器。

完整观察经当前 manager 出生身份与 run/scope/物理关联检查后，先记录 release_pending；owner 末态
落盘并重新核验后才标 released。只有 released/cancelled 预留不再阻塞本域的资源引用检查，意图仍按
原规则保留。新意图不再选择 released run；已经接受的选择集合改变须重新核对，不自动扩充或修订批准。
未完成预留、其它 active/unknown、损坏引用及现有意图继续阻塞。原生会话最终封口不由释放收据证明。
released 可在同 manager 新完整观察和精确末态重核后重新同步，receipt/owner 时间与正文保持不变，
只推进协调 revision。该路径处理 rename 已完成而 fsync/响应失败，不重新执行停止、启动或维护。

T116 增加严格 scope-claim/scope-anchor 数据对象。claim 包含域 ID/物理根、scope ID、父容器物理身份、
目标实例路径与 owner_ref；锚点另绑定实例目录物理身份、claim/owner 摘要及两个资源 ID/path/ResourceKey。
三份锚点位于实例、HOME 的固定元数据文件及实例锁正文；父目录声明独立存在，用于部分损坏后的拒绝降级。
域 resource 使用 runtime 或 scope 两种严格结构；scope 项携带 path、scope_id、anchor_digest、ready 状态，
kind 仍来自物理 key。字段不包含秘密、任意命令或维护许可，不读取原生账号/会话正文。
同一 reservation 选择三资源时，owner 关联摘要覆盖完整集合；退出只释放 run 引用，不删除资源登记。
首次仅采用新建目标，完整历史与旧 unknown 对账不由这些记录提供。

## 7. ContainerRecord 与 ContinueRequest

仅原位置能力通过后新增 ContainerRecord：container_id、generation、管理进程身份、TerminalRef、
manager_code_identity、control_protocol、受保护 endpoint 身份、state 与已消费 request ID。
状态为 running、parking、parked、resume_pending、unknown、closed；parking 不等于资源已释放。
parked 在全部单次运行租约退出之后，不能保留旧运行包/环境/凭据对象。
旧单次 manager 没有该记录，不能在线推断为 parked；管理代码变化时首版转明确的新位置路径。

ContinueRequest 含新 run/op、SessionRef、批准文本摘要/固定模板身份、目标 ready 证据及
not_sent、dispatch_intent、accepted、unknown 结果。批准文本仅在当次执行内存中，
不持久化到恢复清单、通用运行记录或日志；不能保存模型回应或历史正文。
派发前丢失文本需重新预览批准；可能已派发后的未知结果仍先对账，不能借重新批准重复发送。
dispatch_intent/unknown 不能通过再次发送变成“确认”；没有可靠接收能力时不开放自动输入。

## 8. 保留与对账

pending、unknown、待恢复或可能已派发对象不做自动过期删除；只读状态能追溯逐项事实。
已完成记录首版也不自动批量清理，容量测量不授权删除原生会话。
后续显式清理需另定可审阅范围；配置上一版备份继续遵守原有独立保留规则。
任何元数据损坏、引用越界、权限不符或未知版本都拒绝控制并保留证据，不能重建为空状态。


### 合作运行上下文与提交前绑定

`CooperativeRunLease` 是适配器内部、仅内存的不可变上下文，携带原实例 fd、package guard 与
owner guard。它不是覆盖或控制许可证。runtime 继续持原状态 SH，包 guard 后才进入 owner；
原生子进程继承实例、状态、包三项租约，owner 退出记账期间这些租约仍存活。

`OmpLaunchReservation` 的检查结果不能跨事务当作授权。合作 owner 的 attach 和 dispatch
各自持协调锁时再次比较原 token 的域/物理域、run/op、创建代际、资源集合与包身份；
attach 第二次提交继续要求完整 pending 记录未变。只有确证尚未尝试关联且仍精确 reserved
的 token 可取消；可能已关联、派发或记录未知的状态保留保护，无超时清理或自动重试。

当前 manager 观察不完整时，先持久化域 unknown，再把该 owner 记为 unknown 并更新摘要。
两步失败均保留资源阻塞；只有该 manager 的新完整观察走原 release_pending → owner idle → released
链路。此处不把旧 unknown 或 release_pending 改写为一次新成功退出，也不改其它共享实例。


`omp_scope_write_guard` 仅在已有完整 scope 上持实例物理 EX，并固定 HOME 身份；短协调锁内核对
scope 引用/意图，随后 owner 非阻塞锁核查包括未关联记录在内的全部 owner。它不持协调锁跨部署，
不取得状态锁（由原部署下一步取得），不授予 runtime 修复许可。runtime-only unknown 仍由包门禁
阻断，不能因一个实例的配置可写而解除共享包保护。
