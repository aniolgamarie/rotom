# 执行与权限公开语义契约

日期：2026-10-04。本文规定用户和适配层可观察的行为，不规定新的 CLI 名称、传输协议或存储实现。实现必须使用未修改的上游、公开扩展/配置/API、官方 CLI 和 Rotom 自有适配代码。

## 1. Profile 启动与诊断

实现必须为 `pi-base` 和 `pi-full` 提供 Rotom 管理的启动选择，并能只读报告：有效 profile、RuntimeIdentity、ConfigIdentity、主模型绑定、加载的插件/工具/Skill、权限模式、隔离后端及覆盖矩阵、活动执行和不可用原因。

诊断不得刷新认证、启动服务、调用模型、探测 Full 私有依赖或读取秘密正文。Base 诊断不能因 Full 未安装而失败。未知字段、身份不一致、策略不可表示或运行包漂移均失败关闭。

具体命令名沿用或扩展现有 `agentcfg` 入口，由实施阶段依据现有接口确定；本文不创建尚不存在的子命令。

初始候选为官方Pi v1.0.1，使用其公开CLI/bin/exports；旧锁0.84.4及旧入口只能作迁移基线。具体提供者与替换生命周期见[能力提供者契约](capability-providers.md)，持久请求与服务恢复见[Durable服务契约](durable-service.md)。

## 2. 权限准入接口

每个受管工具调用遵循以下逻辑接口：

1. `prepare(intent) -> PreparedOperation | deny`
2. `decide(prepared, context) -> ApprovalDecision`
3. `issue(decision, prepared) -> ExecutionPermit | blocked`
4. `consume(permit, currentContext) -> ExecutionLease`
5. `observe/cancel/reconcile(lease) -> physical status`

`prepare` 必须先执行 hard deny、角色 ceiling、工具注册、根/argv/网络绑定和隔离可用性检查。模型审查只能出现在 prepare 成功之后。未注册工具、无法表达的 deny、隔离缺失或策略不一致不能进入 reviewer 以求放行。

`issue` 和 `consume` 必须复核 operation digest、session、cwd、policy generation、取消 epoch、实际 reviewer 选择和目标身份。permit 一次消费；重复、过期或不一致返回明确冲突，不重新执行。

### 撤销语义

- `awaiting-review`、`awaiting-human`、`permitted`：撤销立即使结果/许可不可执行，迟到响应被丢弃。
- `starting`：若无法证明尚未发送，进入 unknown 并保留资源；不得假定撤销成功。
- `running`：发出 cancel，仅在真实终止和资源回收证明后报告 canceled。
- 修改配置或切换审批模式不能把已运行进程描述为已撤销；它只阻止下一动作并触发取消流程。

### 自动 reviewer

Base 默认不调用 reviewer。Full 的 reviewer 在运行时可由用户启用或关闭，但 reviewer 能力、关闭态零调用和启用态质量验收都是 Full 交付必需项；不能因默认关闭而跳过。启用时必须显式绑定获准模型路线，并满足：

- 接收完整但必要且脱敏的 prepared operation、cwd、当前用户限制和上下文身份；
- 返回封闭结构 `allow | ask | deny` 和固定原因类别；
- 无工具、单次、有 deadline、无隐式 retry/fallback/跨 Provider；
- hard deny/必须人工项调用数为零；有效 ask/deny 不再换模型复审；
- 无 UI 时 ask 保持 blocked，不能转 allow；
- 模型 allow 只能减少硬策略范围内的提示，不能扩大 OS 能力；动态脚本不因文本相同永久缓存批准。

有效 reviewer ask/deny、超时、Provider/transport 故障、协议无效、取消和无 UI 必须具有不同机器可读终态及审计原因。它们可以按固定策略都收紧为不执行，但不能在展示、统计或质量评测中混成“模型 ask”。取消后的迟到响应只追加 discarded/canceled 账本事实和实际调用计数，不得覆盖取消或发放许可。

审批输入或审计不得包含 token、API key、OAuth 数据或这些秘密的散列。需要判断秘密路径时仅传递路径类别、能力标签或其他非秘密事实。

## 3. OS 执行隔离

每个宣称受隔离的入口必须在覆盖矩阵列出执行后端、文件读写根、网络、环境、临时目录、Unix socket、子进程和未覆盖项。最低交付为目标平台上真实验证的一条受管 Shell/子进程及文件路径；后端不可用时返回 unavailable/blocked，禁止回退到宿主直接执行。

仓库当前可复用的产品基础是固定命令进入 supervisor 后由 Linux `bwrap` 或 macOS policy 执行；`pi_validation_sandbox.py` 只属于验收 harness，PID namespace 只证明进程收束的路径不能写成完整文件/网络隔离。具体支持范围必须以实现后的产品入口和 OS 事实证据为准。

受管工具隔离的信任边界包括锁定的 Pi、加载扩展和 Rotom 控制面，只防模型误操作与恶意项目脚本。整 Pi 隔离必须在 Q3 给出基于真实行为的最终“支持路径”或“当前不支持及原因”决定，不能只写未声明或以后研究。若决定支持，必须从真实 Pi 入口验证恶意测试扩展直接文件/进程/网络行为；tools-only VM 或 shell wrapper 不能替代该证明。

## 4. 普通命令与文件操作

- 日常文件工具保持 Pi 的预期读写/edit 语义，但物理 IO 由受管执行路径完成并受相同 permission snapshot 约束。
- 固定 build/test/lint/editor 可绑定精确 argv、cwd、timeout、读写根与网络能力；显示别名和精确 argv 必须解析为唯一同一绑定。
- 日常 Shell 不能被迫先创建数据库任务；若允许任意 Shell，必须单独定义其审批、sandbox 和未覆盖 shell 语义，不能把固定 argv 的证据外推过去。
- 输出捕获有界且保留 truncation；退出码、测试语义和终止状态分开报告。
- `.git`、认证目录、运行包和工作区外秘密默认不可写。符号链接、祖先替换和路径别名必须在所声明威胁模型内有负向验证。

## 5. 委派核心

Pi 与 Codex 调用相同逻辑操作：

- `submit(requestId, DelegateRequest)`
- `status(runId)`
- `message/continue(runId, input, requestId)`
- `cancel(runId, requestId)`
- `result(runId)`

实施可映射到已有 CLI/RPC，不要求另建服务。共同语义如下：

- 相同 requestId 与相同规范请求返回同一 run/结果；相同 ID 不同请求报冲突。
- 返回真实 backend、native identity、实际模型、会话/resume 身份和受控用量；不从模型文字或 UI 标题推断。
- continue 只作用于同一 run；后端不支持时明确 unsupported，不创建新 run 冒充继续。
- cancel ack 只表示已接收。`canceled` 需 termination evidence；未知保持 protected。
- 后端错误、超时、取消和协议完成均不得被外层成功响应吞掉。

模型委派不能凭请求字段自授角色、工作区、预算或网络；可信父控制面生成并签发这些身份。执行器只获得任务所需的最窄能力。

## 6. Writer、Inspect/Fix 与可信验证

所有受管写入入口在写入前必须获取规范 `WorkspaceIdentity` 的 Writer lease。Base、Full、受管 Pi 进程、delegate 和 Durable 使用同一冲突语义；无法证明旧受管 Writer 已终止时返回 busy/unknown，不启动第二个受管 Writer。用户编辑器、未受管 Pi 或其他本机进程不保证配合该锁；其外部修改必须由输入/根身份复核观察，使相关证据 stale，并按操作阶段拒绝、重准备或报告冲突。

本计划不预设新的事务引擎。实施必须复用或扩展现有跨进程 lease/存储事务，并在启用受管 Writer 前通过一个硬 gate：两个独立受管进程对同一规范工作区同时 compare-and-acquire 时恰有一个成功；在提交前、提交后未回执、owner 崩溃和锁繁忙切点均不得出现双受管 Writer。若现有事务不能给出这一保证，对应 Full 写入能力保持 blocked，由主代理重新选择机制。

现有`workspace_leases.py`只直接识别本机Git工作树。非Git工作区通过显式受管根登记和独立于profile HOME的协调锚扩展；未登记/身份冲突保持拒绝，不能以初始化Git或跳过租约解决日常编辑。两种根类型均需跨profile/独立进程/别名及恢复检查。

Inspect/Fix 的公开结果必须区分：计划、执行事实、checker 结果、Reviewer 结论和最终接受。Worker 不能写 checker 的实现、冻结 argv、通过阈值或权威配置；这些若在 Worker 写根内，检查必须拒绝作为 trusted evidence。

可信检查至少拒绝：非零、零测试、全跳过、缺所需 test ID、缺输出/终态、错版本工件、输入或未跟踪文件变化、策略/checker 变化及过期结果。退出 0、模型说完成或故障关闭都不是通过。返工最多两轮；耗尽后返回未完成及剩余发现。

所需 test ID 由可信配置 `required_test_ids` 明确列出；启用时仅接受 JSON 的逐项 `test_results`，ID 唯一、状态与聚合计数一致，所需项必须全部 passed。旧绑定未声明该字段时继续采用原聚合计数契约，不声称已核验具体测试 ID；模型不能增加、删改或猜测必需集合。

## 7. Durable 只读任务

Full 提供按需持久任务语义：

- `submit(requestId, readOnlyTask)`、`status(taskId)`、`message/continue(taskId, requestId)`、`cancel(taskId, requestId)`、`result(taskId)`；
- 一个存储 owner，重启先取得所有权并对账 native identity；
- 前端退出不取消任务，也不新增授权；重连按 taskId 找回同一任务；
- 服务端执行权限、预算和凭据边界，客户端字段不能放宽；
- 只读任务不能写业务工作区或运行任意 Shell，但可写服务状态、日志及任务专用产物目录；将产物应用到项目是新的受管操作；
- 响应丢失用 requestId 查询，不重复 submit；发送/终止未知时保持 unknown/blocked；
- 取消请求、取消确认、真实停止和资源回收分别可观察。

Durable 服务未运行或损坏时，Base 和 Full 的普通编辑仍可用；明确请求 Durable 时返回 unavailable/blocked，不静默改走短期 Writer。

存储接管同样是发布 gate：必须验证单 owner 的原子取得、旧 owner 存活拒绝、提交结果未知时保持保护、迁移/恢复失败不开放写入。具体锁和事务接口由实施阶段根据已选 Durable 后端的公开能力确定，不能用 PID 文件存在或进程退出码代替。

本轮选定SQLite和本地socket服务作为初始设计；未知模型发送的保护必须覆盖SDK恢复/重试/压缩入口，status/result/watch只读且不启动scheduler。不能直接把SDK的resume成功当作安全恢复；具体顺序以Durable服务契约为准。

## 8. 快照、证据与预算

执行或验收开始前产生 `InputSnapshot`；结果引用该快照、RuntimeIdentity、ConfigIdentity、checker 和平台。变化检测覆盖相关未跟踪文件及未受管外部修改。证据有效性使用 `current | stale | invalid`：current 的非零、零测试、全跳过或断言失败仍是必须保留的有效失败证据；invalid 只用于损坏、身份错误或不可核验记录。只有 current 证据在规定层级由独立 oracle 满足成功条件后才能支持 passed。

用量接口显示 known/estimated/unknown/reserved 及覆盖范围。只有可观测且可控制的请求才能执行硬预算；重启、resume 和 profile 切换保留累计值。发送状态 unknown 时不释放预留。不得用模型调用数推断 SDK 没有隐式 retry，必须从 transport 或受信执行边界验证。

## 9. 升级、回滚与失败

- 冷安装、重复部署和失败回滚不得覆盖用户差异、认证、活动实例和持久状态。
- 新运行包先在隔离实例验证；活动执行存在时不自动切换或终止。
- 配置回滚不自动降级数据；持久数据迁移先备份并实际恢复验证。
- Full 高级组件失败不污染 Base，也不阻塞 Full 的普通直接路径。
- 未支持、需要登录、证据 stale 和未运行分别报告；不能因验收环境不足改写为 passed。
- 本轮必需平台已由用户冻结为当前 Linux x86_64。P0 核实具体内核、发行版和隔离运行时；Mac、其他架构及 WSL 仅按需登记，未执行不阻塞总交付也不记通过。
- 真实 Pi、账号、付费模型与人工终端体验属于独立授权层。默认测试只能使用临时 HOME、虚构 provider、假子进程、合成项目和网络阻断。

## 10. 能力提供者替换

R37要求稳定用户行为和权限边界，不要求所有插件实现同一内部接口。包专有配置及调用语义由相应能力适配器承担，不能散布到共享Skill、审批策略或任务状态机；复用已有清单记录版本、来源、兼容性、状态所有权与替换步骤。无替换需求的原生功能无需额外包装。

候选替换必须先用同一套正常/拒绝/取消/故障契约在隔离实例验证，核对实际加载集合与卸载后残留；移除只作用于受管且无活动或恢复引用的资源，不删除账号、会话或用户文件。共享能力变化对两profile执行相关回归；更换来源需显式记录，不自动追随市场或弃维护公告。

旧run、permit、任务及证据继续引用原提供者身份。切换使相关旧证据失去当前通过资格；不能把旧许可交给新提供者消费，不能将未知任务自动重跑。状态格式兼容须有明确验证，不兼容时选择已验证迁移、保留旧实例或阻塞，不承诺任意插件间透明会话迁移。

至少一组等价提供者替换、一次中途失败恢复及不兼容候选拒绝构成M07演练。默认隔离层可用两个提供者替身证明选择/适配/恢复机制，正式支持的每个组合仍需其真实入口与适用验收层证据；替身通过不证明真实插件兼容。


## 11. T013 接入决定（分阶段接入，完整身份与决定来源待完成）

现有 `PermissionAccess.check/approve/take` 是可复用的准入顺序，但旧 native gate 的非 block 返回值没有可靠的决定来源，不能补记为 human。新扩展自己的显式 UI 选择才记 human；已配置规则、会话授权范围内的自动决定记 deterministic-policy；reviewer 只记录经控制面核验的模型结果。旧 session-yolo 提示模式不自动迁为新权限授权。

受信 SDK 适配器使用实际工具事件的 toolCallId 作为稳定 requestId，键同时包括监督者 activation、profile 和 session。缺 ID 不接受有副作用重试，不每次用随机 requestId 掩盖重复。operationId 由监督控制面首次准备时生成，模型输入不能指定或覆盖。重试复用同一个完整规范请求；角色、cwd、用户限制、策略、运行身份、deadline 或取消 epoch 改变时，旧请求保持冲突/失效，不能悄悄重新批准。监督者重启使旧许可失效；已经消费后的外部活动由原 ExecutionStore 记录对账，不重建内存许可后重发。

policy generation 和 cancel epoch 分开：前者跟踪权限规则或审批模式变更，后者使取消后的迟到决定失效；lease grant generation 继续表达物理执行撤销。三者不能互相替代。session、角色和真实用户来源从可信宿主/管理连接取得，工具参数仅表达操作内容；不从模型声称的角色、user 文本标记或项目文件推断授权。

prepare 只解析最终参数/argv、验证根与工作区身份、单一策略、角色上限和后端能力，并形成不可变准备对象；不取得 Writer、不启动 helper/模型/服务。旧普通写 prepare 提前分配租约的行为在新入口退出。模型审查或人工等待结束后，可信控制面签发一次许可；consume 在串行控制区先失效该许可，再复核并通过原 ExecutionStore 持久化分配意图、取得 Writer 和启动。分配失败不会把许可恢复为可再次执行；未获回执按 operationId/lease 查询和对账。没有终止证明不能释放已启动或未知 Writer。

文件、固定命令及未来普通 Shell 必须分别形成最终准备对象；服务和 MCP 外层许可不能覆盖内层未审查操作。内层公开工具事件有自己的 requestId/parent 身份和相同准入流程。未选 readseek 等入口明确不注册；已选但不能表达权限或后端未知的入口在 prepare 失败，不能只返回 service 字样跳过约束。

准备对象公开投影仅容纳非秘密参数、受控资源类别和秘密引用；原生账号材料不参与通用摘要。正文若需在控制面临时持有，不能写入通用日志或错误，也不能因为散列合法就认定没有秘密。摘要负责变化检测，一次许可的权威来自受信控制面登记、上下文复核和原子消费，不能凭模型提交的摘要或句柄获得执行权。

内存基础模块`pi_operation_admission.py`已实现受信准备结果的闭合校验和一次许可账本，但尚未接入旧工具入口。adapter须从SDK真实toolCallId、ctx session/cwd、注册角色闭包、manifest.profile_id及已核验supervisor握手构造context；ConfigIdentity与真实用户意图引用必须补齐后才能接入，不能拿manifest_digest或模型字段凑数。resolution只能由受信准备器在硬策略、根身份和后端检查成功后形成，不能直接透传模型JSON。当前基础分支表达guarded-files-v1文件和linux-bwrap-v1固定命令/私有脚本Shell，网络deny、无服务；这些名称本身不证明OS后端可用。Shell准备部分与尚未接线的边界见下节。

私有正文保存在有界内存中，以规范JSON字节作幂等相等比较；公开对象只引用控制面生成的随机private_input_ref，operationDigest不包含正文或正文散列。序列化前先核算包含转义及UTF-8的大小，避免超大正文在拒绝前生成完整副本。operationId和permitId由控制面生成；同一activation/profile/session/requestId保持同一完整请求身份，旧请求不会在撤销或消费后重新签发。消费先不可逆作废许可，再核对完整许可、当前上下文和重新检查后的resolution；进入原ExecutionStore的后续分配失败不能恢复许可。实际工具、UI来源、会话结束后的保密回收及与ExecutionStore联动仍是T013必需工作；基础模块的线程竞争检查不是OS Writer或产品权限证明。

ConfigIdentity的实际接入不能只复用候选generation或已部署manifest_digest。后者已覆盖profile/options/声明策略，但未覆盖宿主实际采用的非秘密native设置、当前cwd下实际加载资源及项目收紧快照。安装收据的resource_manifest_digest描述包内资源清单，loaded-manifest描述本次选择，两者不能互换。旧capture仅支持theme/defaultProvider/defaultModel，也不代表其它影响行为的native配置已完成投影；主模型还须分清声明默认、保存偏好及实际会话选择。身份形成必须从受信已部署/已加载观察构造，认证正文及其散列始终排除。当前没有完整项目权限快照接口，后续须显式实现；项目说明文本可以影响指令上下文，不能因被计入资源摘要而获得权限授予能力。

文件执行生命周期现接入独立的`ordinary_prepare_deferred → ordinary_consume → IO`路径。七个文件工具在主会话`PermissionAccess.take`或子角色执行时的prepare之后消费；prepare不调用ExecutionStore.allocate、不写ordinary-operations记录，票据为`state=prepared, lease_id=null`。consume在原SupervisorService串行锁内先烧掉准备态，复核文件权限配置快照、父宿主generation、cwd/根身份及已加载资源，再调用原ExecutionStore；写操作用新分配generation重建grant，读和所选资源复用父宿主lease。stage/read/stat/list/实际helper均拒绝未消费对象；实际I/O仍核对绑定manager与当前上下文。关闭监督者时不再接受prepare/consume，status和放弃纯准备仍可用。

消费回执丢失只查询`ordinary_status`，不重发consume。只有同operation/path/write/request_digest、consumed态和非空lease能继续；分配或元数据落盘结果不明保留unknown，普通finish不能删除潜在Writer。分配已提交而UUID未返回时，status按exact execution_id及原owner/分配描述只读定位唯一匹配lease；身份不符或多匹配拒绝，找不到记录也不宣称安全释放。返回定位信息不改变unknown态、不重新分配或回收。纯准备的取消/过期不分配Writer；同ID重试保留原终态，异请求冲突。当前控制面最多128个活动准备/执行、4096个请求记录，私有比较字节总额32MiB、单请求1MiB，超限拒绝而不淘汰旧ID。私有表示复用准入账本的严格编码器，先核算大小再序列化；普通记录不含正文或正文散列。会话退役清理仍须随正式session绑定完成，不能靠淘汰旧ID模拟清理。

这一阶段只修正主文件入口的执行顺序；其权限快照并非ConfigIdentity，也未将旧native gate结果改记为human。稳定SDK requestId/profile/session/意图、policy generation、cancel epoch和完整permit仍须通过正式扩展接入`OperationAdmissions`。旧高级helper的`ordinary_prepare`、command/readseek路径尚保留兼容，不能据此宣称所有入口都延迟分配或完整T013已完成；新profile必须按所选能力替换或排除这些路径。只读文件工具不依赖用于写helper的AgentManager，全进程沙箱证据仍独立。

## 12. 注册根与物理重叠协调的实施决定

以下为T014–T016的协议约束，逐层测试完成前不表示已经开放非Git或新的受管Writer。

账户协调目录选为可信OS账户home下的`.agentcfg-workspaces`，不从环境`HOME`、XDG或profile目录推导。`pwd.getpwuid(euid).pw_dir`仅用于可信控制面定位；默认测试及独立worker必须显式注入临时账户根，不能访问真实账户home。账户目录与协调目录均验证dev/inode/uid和安全路径，协调目录0700、记录0600；受限执行不挂载该目录为可写。账号home变迁属于控制数据迁移，不通过环境变量或自动清空登记解决。

首次显式登记与后续准入以账户目录fd的短时flock序列化，顺序固定为账户协调锁在先、Git目录锁在后；不反向获取。只读查询使用只读锁且不创建目录、文件或登记。锁不支持或繁忙分别返回明确的不可用/busy，不退回进程内锁。登记本身不授予工具、文件写入或执行许可。

非Git根的登记保存规范路径和dev/inode/uid，rootId绑定协调锚和物理身份但不含boot/profile/HOME。符号链接和可核验的同inode别名归并到原登记；根路径被替换、原路径失联、协调锚改变或登记损坏均拒绝写入，不把新目录自动接到旧身份。子目录查找按实际祖先inode匹配已登记根。父子根可以登记，但它们的写入不能各走独立租约。控制目录自身及其祖先/后代不得登记为业务写根，不自动初始化Git。

所有新受管Writer（含Git）在同一账户协调锁下复核活动claim。物理根相等或任一根处于另一根的实际祖先链即冲突；不能只比较路径字符串或最近`.git`。同一个ExecutionStore分配的多个重叠根属于同一Writer，按完整owner/allocation上下文幂等核对。无关且可核验的根可并行执行；无法核验的活动claim保持保护，不凭超时、PID或失踪文件推定释放。

claim持久化闭合的不可变allocation_context及其摘要，包含owner、task/attempt、完整planned_workspaces、运行/策略/候选身份与原allocation_journal_digest；读取时重新校验类型、未知字段和摘要，完整日志存在时复用ExecutionStore的allocation_digest算法。generation及观测心跳不属于不可变上下文。摘要是完整性检查，不是授权。释放证据必须绑定同一上下文的journal摘要，不能将有摘要的证据接到空上下文。

持久顺序复用ExecutionStore：先持久化完整allocating意图，再持久化账户claim，随后写Git原有marker（非Git使用协调目录下标记），最后把句柄写回执行日志并确认。任何提交后未回执都可按原allocationId查到保护，不产生新Writer。启动前同时复核claim和marker；仍按原`starting/spawn_committed → spawn → process identity → active`顺序。释放先保存可核验的终止证据及局部released标记，再撤销对应账户claim；每一步都比较完整owner和generation，旧释放不能删除新占用。局部标记未写成而账户claim已提交时，只能凭同次分配的never-started证明清理。重启不自动删除保护。

generation核对区分准入与撤销：reserve/activate/assert和同Writer豁免必须精确相等；可信ExecutionStore的cancel/recover_stop会提升grant_generation，使旧执行权限失效。仅release可用同一完整owner/allocation上下文且不小于global/local各自已存generation的新代终止证明释放；证据必须精确绑定传入的新代，两个released记录及proof引用一并保存新代。局部释放已成功、全局尚未成功时仍可按此规则恢复；旧代永远不能覆盖更高代。该接口不向模型开放，不另造恢复授权队列。

分配失败的补偿会遍历完整planned_workspaces，其中可能包含尚未成功预留的根。仅在`missing_ok`、完整同次never-started证明有效、global和local都不属于本allocationId时，release无修改返回未释放，随后ExecutionStore可持久化该次未启动失败并保留原准入错误。任一同allocation标记的owner/context/generation不匹配仍拒绝；不清理外国占用，不把有启动提交的任务归为未启动。

旧版活动执行可能没有账户claim，迁移准入必须先核对既有实例/恢复记录和Git marker；未知旧Writer保持阻塞，不能仅创建空索引后宣称已覆盖旧执行。旧程序不认识新协议的兼容范围须在激活检查中明示，不允许新旧控制面在同一物理覆盖范围同时获得写权。现有Git marker及旧运行资产保留用于诊断/恢复；登记基础模块完成不等于该迁移边界已完成。

非Git身份沿用worktree_path/canonical_worktree_identity通用字段，使用`workspace_kind=registered-root`和`registered_root_id`区分，git_dir_path/git_dir_identity必须为null；Git旧形状保持原样，两分支不能混合解释。登记身份包含协调锚，工作区摘要同时绑定boot快照与登记ID，账户claim的稳定键排除boot。局部租约存于协调锚`workspace-leases/<rootId>`，复用相同终止证明和global/local顺序，不复制调度队列。身份查询只读持账户SH，已经持有账户EX的路径使用同一registry快照，不重入公共查询；maintenance把已核验身份返回同步调用者。

OpenSpec维护由Pi guard在同一锁内给出元数据位置：Git仍在git-dir/agentcfg-project，非Git在协调锚project-metadata/rootId。生成器仍在进入业务写保护前使用独立stage；提交阶段不再次查询身份，不启动子进程。仓库自有checkpoint实现是文件快照，非Git以registered_root_id补充范围绑定，不强迫业务目录Git化。依赖Git/common-dir的功能独立拒绝，不能让普通文件或固定命令因此失败。

## 13. 官方会话工厂与配置身份投影的实施边界

`official-session.ts`通过公开`createAgentSessionFromServices`组合自有`ResourceLoader`和`SettingsStorage`，不覆写SDK/Session/ModelRuntime方法或原型。其调用者必须提供经准入的工具定义、扩展factory、官方初始化器的runtimeHandle和可信policy/project约束摘要；工厂本身不签发工具许可，也不是独立CLI或部署激活入口。正式启动器、控制面来源和所有工具/用户Shell的执行准入未接通前，不能将这个工厂视为安全产品入口。

主模型在创建SDK会话前确定：最近显式`model_change`优先；无该条目的旧会话使用公开SessionContext记录；新会话使用合法原生默认选择或共享main绑定。选择必须仍属于受管模型集合且可解析。显式选择消失、旧会话缺模型或默认值不完整均拒绝，不采用SDK的物理响应模型/default-provider回退。该恢复规则刻意比原生默认恢复严格，避免仅因上次物理响应来自另一路线就自动换账号。注册虚拟选择仍保留自身身份；实际虚拟路由、请求计量与账号路径需在后续发送边界另外核验，不能由本工厂推定通过。首次创建结果若声称fallback、路由或显式thinking不符，释放尚未交付的Session并失败。

不能用`before_provider_request`或`before_agent_start`抛错作为fail-closed发送闸门：官方1.0.1会报告这类扩展异常并继续。工具阻断使用公开`tool_call`明确结果；会话切换阻断使用明确`{cancel:true}`；这些执行桥接另由T013/T019及US2接入。工厂的模型选择校验只证明初始化/恢复未走SDK自动fallback，不证明所有后续请求都受控。

资源加载使用显式路径和关闭发现的公开选项，不碰`DefaultPackageManager`或legacy启动器。实际extension路径及resolvedPath、skill文件、prompt文件、theme.sourcePath、AGENTS和APPEND输入逐项复核；加载前后与后续读取均检查原内容快照。reload不悄悄更新旧选择的身份；改变选择应重建会话。显式`systemPrompt:""`用于关闭SYSTEM.md发现，官方将其返回值规范化为`undefined`，校验须遵循这一实际公开行为。公开加载诊断的error与路径不一致都失败。

私有设置只通过公开`SettingsManager.fromStorage`处理实例的settings.json，项目原生设置不参与发现或覆盖。已知字段和嵌套字段闭合；自动发现数组只能空，未知字段及重复JSON键失败。生效策略为project trust never、telemetry关闭、cache warming off；snapshot复核当前manager与规范磁盘设置一致。跨进程排他依赖host租约，本存储不是独立多进程锁。editor/shell目前仅接受单一绝对无空白路径；含参数命令、代理字符串、tracking/device标识等不能未经秘密边界设计进入摘要，非空值明确拒绝。只读迁移仅支持已核对的queueMode/websockets/旧skills空目录形态/retry.maxDelayMs，旧新键冲突拒绝，不读取时自动改盘；保存只接受现代形态。

`await configurationSnapshot()`先完成运行时来源检查，再投影当前cwd、有效settings、已加载资源摘要、当前模型ID及非秘密行为描述、thinking、实际工具子集和部署`model_configuration`摘要，结合可信policy/project约束摘要产生与Python`config_identity`相同形状的身份；同时返回独立RuntimeIdentity。工具集合扩大、当前模型不再可解析、资源漂移或settings未稳定时拒绝产生身份。认证文件、token/API key及其散列不进入该投影。摘要只用于变化检测：实际Provider实现、请求时认证来源、完整项目权限、session/requestId、用户意图和cancel epoch仍需由正式控制面组合并交给OperationAdmissions，不能把调用者传入的hex或本方法返回值当作许可。

新profile的`model_configuration`由与models.json相同的Python helper生成，按原生route记录logical_id、auth_kind、owner、credential_ref和非秘密config。API-key config含api/baseUrl/models，apiKey只留在原生文件中作为确定的环境变量引用；OAuth的config/credential_ref为null，不假造原生账号或动态端点。仅新profile将旧compat.reasoningEffortMap提升为官方1.0.1的顶层thinkingLevelMap：旧映射提供默认，显式映射按字段覆盖，disabled写null；显式映射与disabled相交仍报错。旧profile产物及reference ownership语义保留。

`official-models.ts`核对部署的provider集合、binding及模型集合；私有models.json必须与部署的非秘密config及规定环境引用精确相等，额外Provider、headers、modelOverrides、嵌入密钥、命令引用或未知字段都失败，不自动清理。读取上限1MiB，严格UTF-8和全层重复JSON键检查，父目录0700/文件0600/owner/单硬链接/O_NOFOLLOW要求保留；OAuth可缺文件，但父目录必须已核验。settings复用同一有界解析及缺文件语义。

API-key实际公开Model按官方compositor的缺省规则补全后与部署声明比较：name=id、reasoning=false、cost四项零、contextWindow=128000、maxTokens=16384；不错误继承同名内建模型的其他行为。公开ModelRuntime.getError必须存在且返回undefined，空串、组合/加载错误或抛错均以固定错误失败，不把SDK静默回退的基础Provider当成功。创建前、扩展加载后和每次snapshot重新检查配置；每次getModel查询后立即检查getError，防止延迟availability错误越过下一步扩展加载、会话创建或身份快照。SDK字段/错误原文不进入通用异常。

OAuth的安全公开Model字段绑定当前有效描述及原生owner/route；它不读取auth文件、getAuth或环境秘密。headers只作完整Model的私有内存相等比较，既不投影也不散列；改变header值不会产生账号内容的摘要。其他可影响行为的字段有显式闭集：不支持的非空sampling参数、chat-template/routing等任意扩展对象明确拒绝，不能静默忽略再签发相同身份。后续Provider替换须扩充该非秘密字段契约并通过对应兼容测试。

此模型层只绑定声明、磁盘配置及公开模型数据，不证明stream函数、扩展动态注册或请求时账号路由。受信Provider实现及RuntimeIdentity、启动器对ModelsConfigStore/环境引用的实际接线、正式发送和工具准入仍是后续必需项；本阶段不运行真实模型，不使T009/T010或产品gate完成。

## 14. Base/Full 普通文件执行的实施边界

新profile的普通write/edit/rename在消费文件票据后直接通过自有Supervisor执行，不构造AgentManager或派生模型任务。同一票据在首次异步操作前进入executing，只允许一次stage/start；start回执丢失只读inspect/reconcile，不重发启动或凭猜测调用abort_allocation。取消与超时只请求撤销并等待同lease、明确解除保护且verified的终止证明；证明缺失或身份错配保留unknown，不能finish遗忘潜在Writer。RPC、执行观察及取消观察各自有界，执行/取消期限使用单调时钟。

执行成功还须核对私有退出回执的lease和process_identity、exit_code，以及结果记录的schema、lease和operation_id。状态目录从经验证的Supervisor控制文件`<stateRoot>/activity/control/control.json`推导，不能假定机器的state_root位于instances_root之下；真实证据损坏时不回落到实例目录的同名文件。此路径布局不是账号或模型授权。

普通文件模块仅导入纯文件/类型/查询原语。可选MCP/Web适配器加载时主动登记其只读工具查询，查询仍执行原有工具归属与选择检查；同runtime同能力的不同查询实现拒绝覆盖。未加载可选适配器时普通模块不因此导入启动器、服务运行时或Full控制器。旧profile的高级执行兼容路径仍待迁移；该阶段不代表正式profile已激活、原生搜索语义已全部接通或权限许可链已完成。

Python普通监督者同样按构造时的冻结manifest选择控制器：plugins中的pi-readseek/pi-web和resource_ids.extensions中的git-checkpoint分别控制Readseek、Web和checkpoint；基础文件/命令常驻。未选控制器不导入、构造或tick，对应可选RPC在provider导入前返回固定code5。MCP、editor/review、Git状态与服务报告的既有适配也先核对各自所选plugin/resource。查询错误不因格式化消息而导入未选Codex实现。

固定程序分派和工具RPC分别把关：Codex登录及Pi/Codex委派程序必须已有选定的DelegateController，Task Keeper的workspace/check程序必须选定task-keeper，checkpoint程序必须有选定控制器；未选时在读取可选实现前拒绝。正常选中路径继续使用原有resolver、参数/权限核验和已选tick顺序。此处没有重写ExecutionStore的事务或恢复协议。

选择只在新activation构造时确定，不因旧数据目录存在或后续改动manifest而自动启用。缺plugins或非法结构失败，不能解释为全选；未选不触发扫描、迁移、删除旧目录或自动停止活动执行。旧租约与未知Writer仍由原ExecutionStore及用户恢复入口保护；保留文件哨兵不等于已完成旧实例迁移或全平台恢复验收。

## 15. 官方模型运行时初始化边界

`createOfficialRuntimeInitializer`用于正式启动器已经准入的实例启动，不供只读诊断/render使用。每个宿主进程创建一个工厂；并发调用、后续`/new`共用其唯一初始化结果，失败保留同一个失败promise，不自动重试账号创建。部署声明克隆并冻结，工厂创建及首次执行都检查原models.json；成功结果包含原生modelRuntime、异步check及非秘密configurationDigest，不签发执行许可。

SDK只通过公开ModelRuntime.create创建。所有路线显式使用内存ModelsStore、allowModelNetwork:false与refreshOnCreate:false，不把初始化当模型/认证发现。API-key-only路线显式使用空的公开InMemoryCredentialStore，模型配置中仅确定性的部署环境引用；含原生OAuth时显式传本实例authPath，由SDK保留账号锁、刷新和写入语义。OAuth的其他owner当前明确不支持。API-key路线不可被账号文件或运行时Credential抢占，OAuth路线不可变成api_key。未选旧记录原样保留，但非法原生格式不能被静默忽略。

配置内容来自已验证的冻结部署声明，Linux下用自有私有临时文件建立只读FD、unlink后传proc路径。SDK重新打开的是这个inode；不把预检原文件名等同于SDK消费相同字节。成功FD随宿主存活，不向会话暴露提前关闭；失败关闭前核对FD仍指向自有inode，避免误关复用的外来描述符。后续check同时核对FD身份/有限字节、原部署文件和公开Model/getError。它不是memfd seal或沙箱，不抵抗同进程恶意代码；控制目录与受限工具的隔离仍由US2证明。

异步check在公开listCredentials之前与之后读取当前私有账号文件，只比较provider/type元数据与声明所有权；不调用getAuth/getAvailable/refresh，不输出账号正文或其散列。格式错误、私有属性错误、metadata不匹配和SDK错误均固定错误失败。OAuth正常token轮换不改变configurationDigest。此检查不证明token内容的稳定，不锁住之后的模型发送，必须由正式控制面在其适用的会话/操作边界调用；普通快照或调用者持有的摘要本身不产生执行权限。

会话工厂强制接收runtimeHandle并捕获其modelRuntime/check/configurationDigest，拒绝省略检查函数或无效摘要，不提供跳过检查的参数；handle必须来自受信初始化器，形状校验不能证明任意外部函数实现可信。每次创建会话（含同工厂的`/new`）先await check，再读取settings或加载扩展；handle摘要必须与该会话的部署模型声明一致。资源reload后、SDK创建前重验；SDK返回后通过异步configurationSnapshot再次检查才交付，失败则dispose新会话。之后的每次snapshot也必须await，检查期间不能提前交付身份。该组合已用自有真实模块与冻结假SDK测试，但仍不是正式CLI或请求发送闸门。

## 16. 文件许可到实际租约的实施接线

`FileOperationAdmissions`在OrdinaryOperations上安装唯一桥，与SupervisorService共用串行mutex。受信同步context_provider按稳定requestId提供当前会话/用户意图/配置/策略代际/取消epoch/时限；桥核对真实activation、运行包、profile与当前主角色。该回调不是模型工具参数，不得做异步请求或在持锁时反向修改控制面；其实际SDK/控制发布入口仍待完成。桥没有新增外部RPC，构造和source=human字段本身不能替代真正的人类决定证明。

prepare调用原deferred文件准备器及preview，实际核验硬策略、根、角色ceiling和Writer目标；从其结果派生PreparedOperation，不接受调用方自报resolution。准备及issue均零Writer分配、零执行记录落盘。当前桥把requires_human固定为true，后续完整确定性策略和Full reviewer须在硬策略上限内接入；这不是最终自动审批功能的替代品。输入正文只在有界内存中比较，公开身份仅含随机input引用和非秘密投影。

消费前重读可信上下文、原根/策略及物理准备状态，再不可逆消费账本许可，最后调用原OrdinaryOperations.consume进入ExecutionStore。失败不恢复许可。分配提交后回执丢失继续保持unknown，status只读定位原分配，不能重发、自动abort或遗忘Writer。账本consumed表示许可已消费，不等于进程已开始、完成或停止。revoke只撤销尚未消费的许可；活动执行仍须原取消与终止证明。物理准备若已被ordinary_finish关闭，不得再次issue许可。

现代profile的ordinary_prepare、ordinary_prepare_deferred和ordinary_consume旧RPC不能绕过该桥；内部准备/消费需要桥对象身份，模型不能提供这个令牌。新profile在正式上下文/许可入口接通前明确不可用。旧profile保持旧行为；这不代表命令、MCP、Web等其他入口已经迁移。已选资源读取同样绑定桥，并在消费时检查原选定内容；只读操作复用父宿主租约，写操作只有消费后申请一个Writer。

最终工具wrapper所用`captureOperationInput`先按规范UTF-8 JSON计量（最多1 MiB、深度32），再构造独立深冻结副本；相等比较保留完整私有编码，不生成正文hash。非法值、accessor、稀疏/扩展数组、非安全整数、无效surrogate及Proxy均固定错误拒绝；Proxy在反射前拒绝，不运行其trap。toJSON函数不执行，普通同名数据属性遵循JSON语义。该原语现已接入下节自有execute wrapper；真实SDK组合证据仍须另验。

## 17. 受信 UI、文件工具与会话退役的控制协议

`FileAdmissionControl`只由modern profile的HostSupervisor构造，复用同一SupervisorService mutex。现有私有通道先核验peer UID、manager能力、运行中的lease/generation和进程存活；控制器额外核对host kind及完整OWNER_KEYS。manager身份不证明SDK session或真人，session、当前配置和确认决定由仓库自有SDK适配器提供。以下端点不是模型工具；模型参数不能选择context、control_id、request_id或审批source。

| RPC | 封闭参数 | 效果 |
|---|---|---|
| ordinary_admission_open | control_id, session_id | 绑定本次会话控制器与manager；同ID不可绑定另一session |
| ordinary_admission_prepare | control_id, request_id, context, tool_name, input | 当前可信上下文及最终参数准备；返回账本PreparedOperation |
| ordinary_admission_issue | operation_id, context | 受信UI确认后调用，服务端固定human来源；不接受调用方source字段 |
| ordinary_admission_consume | permit, context | 从服务端permit映射定位原operation，最多一次实际租约消费 |
| ordinary_admission_status | operation_id | 只读返回admission状态与普通执行绑定摘要 |
| ordinary_admission_cancel_request | control_id, request_id | 即使open/prepare尚未到达，也保留取消墓碑 |
| ordinary_admission_retire | control_id | 先关闭整个控制器，再逐请求撤销未消费准备；重复退休可对账清理 |

控制器最多128个、请求最多4096个、控制层私有比较内容最多32MiB；请求ID跨控制器不可重用，不通过淘汰旧墓碑腾出重放空间。首次准备失败、同ID正文/上下文冲突、确认或消费时上下文变化都不能通过恢复旧参数重新获权。时限在准备时须处于未来且不超过300秒。closing拒绝open/prepare/issue/consume，仍允许status/cancel/retire。取消、退役和状态查询不把consumed/unknown改为已停止，也不释放其Writer。控制层能释放自己的正文副本；底层账本/普通输入的整体退休回收仍受既有容量约束，完整回收与恢复保留策略尚未完成。

`official-file-admission.ts`在最终`ToolDefinition.execute`捕获参数，同一native工具ID只能进入一次。prepare、issue、consume使用受信闭包重读的异步configurationSnapshot/策略generation，以及实际ctx的cwd/session、SDK AbortSignal和本地cancel epoch。每次await后检查取消与wall/单调时限；消费回执后再核对一次配置，漂移时只取消已明确识别的lease，不交付执行票据。正文副本直接传给原生read/write/edit和自有其余文件execute，不回用可变参数；许可票据由OrdinaryOperations私有WeakSet接收一次，现代入口不再调用旧raw consume。

本阶段只接公开`ctx.ui.confirm`严格true，要求hasUI===true并传递取消signal/timeout；UI仅显示工具、目标、destination和cwd，不显示正文或正文摘要。`user_intent_ref`指本次仓库生成的UI确认请求，不冒称原始用户prompt身份。interactive/rpc/extension等源标签及tool_call_id均不是人类权限凭据。RPC UI客户端必须受信；`human`表示这个通道作出确认，不是SDK或监督者对生物学真人的独立证明。自动确定性许可和Full风险reviewer仍待接入，不能把当前一律确认当最终产品策略。

prepare后通过只读status取得账本ID到普通执行ID/path/write/request_digest的绑定。consume只发送一次；回执丢失仅查询status，只有同账本consumed且执行绑定精确相符、实际执行状态consumed时才继续。unknown、身份不符或状态不可得时不重试、不start、不finish、不凭猜测abort Writer。已知已消费票据在取消/漂移后可inspect其lease：未spawn的allocating才abort_allocation，其余走cancel并保留终止证明责任。

`official-file-runtime.ts`逐session组合现有官方初始化/会话工厂、七个文件工具和新准入；命令factory不参与这个文件组合，未迁移入口不隐式启用。配置快照由自有闭包持有，SDK丢弃额外factory字段不会丢失准入绑定。返回自有公开runtime facade，只转发公开属性/方法，不修改SDK实例、方法或原型。facade持有唯一原生beforeSessionInvalidate回调，先同步退役准入，再执行TUI设置的清理回调；TUI重设回调不会覆盖退役。用户取消switch/fork时保留当前会话。并发会话替换明确拒绝；dispose先本地退役，再await公开session.abort，最后原生runtime.dispose，失败结果保留且不自动重发。

上述组合仍是正式CLI的待安装组成件，不是当前默认启动器。原生文件搜索语义、正式profile/schema/选择安装闭包、CLI/TUI/RPC实际组合、运行中终止和系统沙箱证明、自动审批及其它工具接线继续未完成。只读SDK源码与假SDK/假进程测试不能替代这些真实验收。

生命周期约定适用于受信前端通过runtime facade切换/退出。为兼容公开SDK，facade仍暴露原生AgentSession；受信调用者若直接调用`runtime.session.dispose()`就绕过了这一约定。SDK没有公开disposed状态可供事后可靠检测。当前核对的TUI/Print路径调用runtimeHost.dispose，未发现产品路径直接绕开；不为对抗任意同进程受信代码而修改SDK或增加代理拦截。后续CLI/RPC入口必须继续核验退出调用链，此限制也不能冒充整个宿主隔离。

## 18. 日常 Shell 准备、租约与私有输入边界

`pi_shell_preparation.prepare_shell`读取受信调用者选定的`tool:<id>`后端绑定、已解析权限和根声明。该绑定选择Shell可执行文件、项目根、读写根和最大时限，具体脚本无需逐条登记。脚本允许UTF-8多行、管道、重定向和命令替换，不通过拆词或字符串黑名单推断权限；空输入、NUL、无效Unicode和超过65536 UTF-8字节明确拒绝。命令allow仍受deny优先及根上限约束。`permissions`的保留名`project`指向本次选定项目，显式声明冲突失败。

准备结果分为`resolution`、`private_input`和内部`physical`三部分。公开的`shell-command`目标仅含固定command_ref、可执行文件path/dev/inode/uid/sha256和timeout，不含脚本或其散列；原始脚本仅留在有界私有输入。账本对同一requestId的私有字节作幂等比较，许可消费返回原始副本，不接收执行时替换脚本。文件身份、根、权限快照、时限或上下文变化使旧许可失效；并发与重复消费沿用一次许可规则。

该函数不取得Writer、不写记录、不启动进程，也不证明`linux-bwrap-v1`实际可用。其`workspace_keys`为空，写操作在补齐实际工作区身份前不能进入账本。`ShellOperationAdmissions`现由受信组装者选择manifest中的Shell绑定，以实际WorkspaceLeases识别结果补齐工作区，再进入一次许可账本；prepare和issue不分配租约。所选绑定不能继承固定命令的额外args或interactive语义。当前`requires_human=true`是组件阶段保守默认，R11的已授权正常操作按策略直行、Full模型审批继续必需。

桥强制要求受信`backend_preflight`回调，输入仅有公开resolution/physical，不含脚本；返回值严格绑定runtime/helper/plan身份，每次issue、consume与取脚本前重验。它是宿主内部接口，不接受模型或RPC传入回调/后端证明。当前没有生产实现或默认factory，HostSupervisor仍不构造Shell桥；真实helper/安装身份、完整mount计划、嵌套Git元数据、路径别名和祖先替换必须由后续后端实现并验证。测试替身的固定摘要不能当作后端已可用。

`FileAdmissionControl`可由受信组装者注入Shell factory；每个请求固定唯一bridge，按服务端permit映射分派，拒绝重复permit归属和跨bridge消费。consume重验后先不可逆消费许可，再为每个Shell（包括只读Shell）分配独立external执行租约，绑定父host执行；只有声明写根时申请Writer。分配前先记unknown，分配回执丢失或操作记录写入失败均不能重发许可、自动重试或回收。status只按原始完整allocation及owner只读定位；不匹配或多个匹配明确拒绝。账本consumed不意味着执行已开始或已终止。

私有RPC `ordinary_shell_take_input`只接收operation_id；对应lease已running、generation及完整分配身份匹配、worker和父host进程存活、监督者未关闭时，才能一次取得原始脚本与已绑定的resolution/physical/backend。resolution提供批准时的根身份，physical另含cwd_identity；不让worker按当前路径重新生成批准身份。manager、其他worker、未消费、unknown、已撤销或过期操作均不能取正文。成功交付清除桥中的副本；账本的幂等比较字节仍受容量限制并保留至activation结束，不声称完整内存擦除。取消和会话退役禁止后续交付，但不把拒发输入当作停止进程的证据，也不释放实际Writer。

取脚本会重验实际策略、根与后端，但消费后的SDK会话上下文依赖受信前端显式cancel/retire，不会凭保存的context自行发现所有会话变化。正式Shell前端尚未接线，必须在启用时验证配置/会话/取消变化到退役的完整调用链。当前组件和私有RPC路由通过假后端/假进程及真实临时ExecutionStore测试；尚无实际worker取脚本执行、默认工具注册或现代安装闭包证据。

`pi_shell_script.sealed_script`现对原始UTF-8脚本建立0600、CLOEXEC的memfd，完整写入后添加并核验WRITE/GROW/SHRINK/SEAL四项密封，rewind后交付；无内核支持时固定失败，没有磁盘临时文件回退。`pi_shell_sources.pin_shell_sources`核对公开投影和实际目录/cwd/可执行文件身份，持有独立CLOEXEC FD，异常或作用域结束关闭自己拥有的句柄；它只表示源身份，不签发许可或构造可启动argv。可执行文件拒绝符号链接、硬链接及不安全属主/权限，使用同一FD计算文件身份并复核；不声称普通文件内容或整棵目录树在交付后不可变。

现有固定命令会在prepare分配租约，并将包含原始输入的摘要和固定argv写入记录，因此不直接扩展该路径携带私有脚本。私有worker现已组合上述FD组件，持久启动参数只含操作/租约/运行身份引用，内部exec路径已有替身验证；跨进程实际交接和隔离执行尚未原生验证。固定bubblewrap0.13.0的公开`--bind-fd`/`--ro-bind-fd`会解析proc FD路径，并在挂载后核对设备号/inode、失败关闭；两者递归包含子挂载，因此不能仅凭根FD声称deny/别名/socket已经覆盖。公开`--seccomp`可读取固定过滤器FD；现有自有生成器只产生目标Linux x86_64的cBPF字节，尚未安装到内核或交给helper执行。

固定源码的`--ro-bind-data`从FD当前位置复制至EOF并关闭该setup FD，调用方必须rewind，且不能假设其他控制FD会一并关闭。其复制文件位于私有tmpfs，不据此承诺不可换出或绝不落盘。组件测试已观察本进程FD密封、清理及一次许可响应到FD准备，但尚未执行helper或Shell。完整实现与真实验收仍须证明控制FD清理、子挂载/deny/别名、Unix socket限制、挂载顺序、输出/取消及后代终止。

`pi_shell_mounts.compile_mount_plan`是内部只读编译器，消费严格的resolution/physical，返回目录和可执行文件挂载、系统目录链接、deny遮罩、cwd身份和seccomp摘要。physical必须保留`readonly_paths`，包括未选为可见根的策略只读路径；读权限声明不等于只读上限。系统根和注入mountinfo仅为受信组装/测试接口，不能来自模型。该函数仅编译时持有源FD，返回值不含FD或可执行argv，不授予后端可用性；执行器必须重新核验并持续持有最终实际使用的句柄。

编译器按mountinfo的设备与文件系统内位置投影deny和只读上限，禁止通过bind别名暴露整个HOME、Git元数据或绕开只读限制。源目录的严格子挂载一律拒绝，嵌套.git遮罩并跳过内容；工作区硬链接和特殊文件拒绝，普通链接不跟随。扫描与深度有界，已扫描目录变化失败。遮罩目标必须已存在、非链接且类型匹配；不创建业务占位。最终执行必须先挂父源、再挂子源、最后应用遮罩；不能让后来的父挂载遮住保护，也不能借helper自动创建目标写入业务目录。这些编译检查不冻结目录树，不能代替执行前复核和OS正反验证。

固定过滤器检查x86_64架构并拒绝x32，拒绝socket/connect/bind、io_uring、挂载及跨进程访问入口；clone禁止其可表达的namespace标志，clone3返回ENOSYS以允许库回退。legacy clone低8位是退出信号，不能与只用于unshare/clone3的NEWTIME混淆。其余syscall默认允许，匿名socketpair保留；过滤器必须与空根、PID/用户/网络/IPC等命名空间、能力清理、no_new_privs和继承FD白名单组合。当前仅有独立字节码解释器证据，不能称为内核隔离已通过。

### 18.1 私有worker和执行组装

`pin_mount_plan`在上下文作用域内持有与计划相同的实际源FD；`compile_mount_plan`仍只返回关闭FD后的公开计划。执行组装必须重编译并匹配已批准plan_digest，固定helper的同一个FD须满足当前属主、单链接0700、Linux x86_64 ELF及已批准摘要。脚本、过滤器和每个文件遮罩分别采用独立密封memfd；源码FD不因这些密封而变成不可变文件树。

`compile_argv`仅接受闭合计划和精确FD集合，保留`/.rotom-shell`、`/proc`、`/dev`、`/sys`，创建私有HOME/tmp、固定环境、用户/PID/网络/IPC/UTS命名空间，清能力并禁止后续用户命名空间。父源先挂、子源后挂、遮罩最后，Shell以`--noprofile --norc`读取固定私有脚本路径；不额外启用`-e/-u`改变原脚本语义。该尾部需要被选程序遵守Bash契约，原生正控制仍是开放入口前的门槛。

受信`ordinary-shell`解析器仅对已消费且未撤销的对应完整allocation产生启动描述，核对活父host、初始代际、准备快照和运行包命令/脚本收据。它不再消费许可或重新分配；未知字段、重复JSON键、入口或收据漂移拒绝。`SpawnCommand.process_scope`由该受信路径固定为`linux-pid-namespace`并写入启动绑定，RPC不能自行指定。每个Shell都有独立外层PID范围，复用现有登记→running持久化→开门顺序；不加入Pi已有的PID命名空间。外层绑定宿主根仅供可信Python引导，脚本必须经后续独立完整隔离边界。

worker先核对选定运行包helper及本地PID1，取回输入后核对响应中的操作/租约/代际和同一出生身份。它移除控制环境并关闭一次RPC连接，在单线程PID1中复核全部FD、密封与偏移，关闭非白名单FD；仅源/数据FD可继承，helper FD保持CLOEXEC，通过`os.execve(fd, argv, {})`直接替换当前进程。只允许作用域内创建的对象尝试一次；失败或意外返回均拒绝，不重试或回退宿主执行。固定bwrap源码显示其外层monitor不执行内层`setsid()`，不会因此改变登记的PGID；这仍需实际运行验证。

运行时限从首次构造命令计算，重复start不延长，过期后拒发私有输入。监督器tick对过期或撤销且已有权威进程身份的保护租约请求取消；已取消请求幂等，不递增代际；没有进程身份的未知/未启动分配保留保护，不自动abort、重试或释放Writer。运行中输入已交付也必须执行超时取消。只有原有Host.poll取得完整终止和输出证据后才能回收资源。

以上已接通内部启动与tick，默认Shell factory/真实backend_preflight、正式运行闭包、模型工具与前端输出尚未启用。当前测试使用真实临时存储/FD和假spawn/exec；没有执行新helper、安装过滤器或运行Shell，不构成T033及产品gate通过。

现代Base的`runtime_files`现显式列出`pi-shell.py`及九个Shell自有模块，安装器的命令表固定声明`ordinary-shell`，缺入口在生成锁、读取锁和安装时均拒绝。所选来源仍经过原始/安装字节摘要与0600文件收据；缺传递依赖不能借当前checkout补足。此包装不注入factory、不提升candidate、不生成正式modern manifest，也不证明整条动态入口已运行；Linux原生后端及完整产品验收保持未通过。

### 18.2 原生诊断及跨用户命名空间身份缺口

`native-shell-probe.md`固定了三个组件场景及放行前身份握手。先登记leader/wrapper，再接收可信worker提供的uid、UID map、user namespace及系统属主；闭合schema、有界输入、映射范围无重叠且root/当前uid身份保持才能写G。不兼容时记为identity-map/unavailable并关闭gate、停止已登记进程；没有执行helper，也不能签发passed。此诊断不消费产品许可或Writer，不伪造receipt，不能替代完整生产链路。

当前root-owned系统路径只允许uid0/当前用户的检查与非root user namespace单UID映射存在兼容性P1。探针已具备记录实际差异的能力，但生产身份交接设计尚未解决。合成测试证明overflow拒绝，固定新helper源码证明默认映射逻辑；二者不能冒充当前系统bootstrap内的内核运行结果。后续须先取得明确授权的本机观察，再为跨namespace的已批准路径/FD及属主身份确定可核验契约；不允许通过放宽全局祖先属主、重写批准快照或关闭校验来绕过。

后台停止场景须同时满足真实正控制、活跃心跳、放行后10秒内完成已登记namespace的stop、非零退出及停止后计数稳定。心跳自然完成至少30秒，禁止用它自行结束冒充取消成功。此处仅为组件探针的证明条件，生产超时/撤销和Writer回收仍按原租约契约单独验收。
