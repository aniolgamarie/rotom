# Durable 原任务受理关联

状态：2026-10-06有限组件最终79项守卫默认检查及稳定独立增量复审通过，root验收归档`durable-request-admission-promise-review02/`。此前69项是历史证据；新发现的同步verifyCurrent已拒绝原生Promise未观察P2已修复，普通原生Promise只附拒绝观察且仍同步拒绝，不能作为许可。最终公开Session/SQLite kernel七场实际通过，独立工件复核及root完整材料核对通过，归档`durable-kernel-native-observed-review05/`，具体范围见[native探针](native-durable-admission-probe.md)。对应T083的一部分；不是服务、owner、RootTask正文、恢复、取消或Full验收。

## 公开接缝与权威

固定 pi-durable@1.0.1 的 25 份普通 submit/task 证据表明：Conversation.submit 的 requestId 只比较会话和类型；返回的是 SubmissionId，continuation 的 generation task ID 会变化，LiveDoc.run 最终会清除。因此不能把普通 submit 当作完整输入幂等和永久原任务关联。

新增 20 份公开 task/document 证据支持另一条路径：Harness extends Session，可以直接使用公开 commit/snapshot；在同一 callback 中通过 Tx.doc 取得自有 session singleton 文档、Tx.createTask 创建注册的自有 RootTask，并将新 native ID 写回同一个文档。Session 在底层提交、adopt 和同步发布后才返回 callback 结果。另有 16 份 Storage/Db 证据确认同一非空 SDK batch 的原始 SQLite 事务边界。

本组件选择 SDK session 文档与自有 RootTask 的同批组合，不增加自有 SQL 受理表，也不拦截 Db.transaction。SDK Task 表仍是唯一执行队列；文档仅保留完整规范输入、原 logical/native ID 和受理关联，不复制 queued/running/terminal 状态。文档不随 RootTask 结束而删除，不调用 retireDoc，不支持清理墓碑。

Tx.doc 可能创建缺失文档。因此文档 initial 必须返回未初始化哨兵；active 模式遇到该哨兵拒绝 callback，不能把丢失文档重新初始化。恢复查询只用非创建的 snapshot 和精确 getTask，不使用 Tx.doc、root、submit、wait、resume、Harness.open 或新的 Session。

选定 Chord@1.0.2 来源确认 Tx.doc 返回公开 Proxy Draft；公开 copyJson 可以在 callback 尚未结束时提取普通 JSON 副本，再交给自有闭合校验。业务输入在调用 copyJson 之前拒绝 Proxy/accessor；仅可信 SDK Draft 走该提取路径，不能把 copyJson 当任意 Proxy 的认证器。snapshot 的值不保证 runtime 深冻结，组件复制验证后使用，不改动或冻结原 SDK 值。

## 本轮有限接口

自有 requests.ts 注入可信、唯一的既有 Harness/Session、公开 durable.defineDoc 与 chord.copyJson、已注册 RootTask token、mode 和同步 verifyCurrent，以及固定 deploymentIdentity/registryIdentity/conversationId 和必填 opaque context。context 拒 null/Proxy，不遍历内部；每次公开 commit/snapshot/getTask 均使用同一原引用，不制造 Context。返回 initialize()/submit(request)/lookup(request)/close()，业务输入不提供 Context；断前端或任务取消不能混同服务 Context 取消。组件通过公开 defineDoc 创建并私有持有 token，不向业务/插件暴露。所有 SDK 方法保留原 receiver，并在 await 后核对捕获方法身份。构造不打开数据库、不初始化文档、不创建任务、不启动 scheduler。输入不接收原始 SDK/Harness/agent/settings 或方法回调。

固定文档定义：kind=rotom.durable.requests、version=1、scope=session。initial 返回 schema=1、deploymentIdentity=null、registryIdentity=null、conversationId=null、rows=[]。只有显式 create 模式的 initialize 可以写入绑定身份；active 模式不可初始化。create 在已存在文档时拒绝，不覆盖、迁移或清空既有数据。initialize 成功后同一组件可进入 active；没有受理发生前也要保存初始化写的回执。

设计复审指出：已持久化的未绑定哨兵和本次 initial 的哨兵形状相同，不能只凭值把 create 当新文档。root 修正：initialize 首先用外部 snapshot 拒绝任何已存在值；在唯一 callback 中，公开 initial 还要标记本次私有创建尝试确实调用过它。仅当该标记成立且哨兵精确合法时写绑定；loaded 的旧哨兵没有调用 initial，拒绝且零覆盖。标记是本组件局部内存，不是持久化/owner 证明，没有 IO/秘密；finally 清除。不在 callback 中再调用 snapshot，缺 cache 的公开 snapshot 会排队而死锁。可信唯一文档写者和唯一 Session 仍是先决，不能由标记推导跨 owner 唯一。

固定 RootTask kind=rotom.durable.request、version=1。本文不提供无正文的“正式可执行” token；token 由后续受限 RootTask 注册层提供，离线测试用公开接口替身。受理时 ownership=conversation、conversationId 为配置中固定的正安全整数、background=false。native ID 必须是新正安全整数，且不能复用既有行的 ID。

提交请求只接受以下完整字段：

- requestId：1–200 个受限 ASCII ID 字符。
- input：仅 text；合法 Unicode UTF-8，最多 64 KiB，不修补非法 surrogate 或清空空白。
- grant：sourceIdentity、authorizationIdentity、registryIdentity、policyIdentity、readCapabilityIdentity、inputSnapshotIdentity、artifactIdentity，均为 64 位小写 hex；这些是可信控制面的引用，不是模型自报授权。
- route：provider/model，均为有界非空、不含控制/格式/surrogate 字符的字符串。
- budget：scopeId、maxCalls、maxCostUnits；scopeId 是受限 ID，maxCalls 为 1–4096，maxCostUnits 为非负安全整数。

未知字段、继承字段、getter、symbol、非普通原型、透明 Proxy、循环、不合法数值或超限均拒绝。先复制与验证，再按 own data property 规范编码；编码不调用 toJSON。单请求规范编码最多 256 KiB。返回值深冻结自有副本，不冻结或改动调用方对象、SDK token、Draft 或 TaskRecord。

请求身份由 deploymentIdentity、grant.sourceIdentity 和 requestId 的规范元组确定，taskId 为 rotom-durable: 加该元组的 SHA256。inputIdentity 是完整规范请求的 SHA256。相等判断比较完整规范请求，而非仅比较 hash。registryIdentity 必须与当前部署匹配。身份没有提供发送或文件访问许可。

文档闭合形状为 schema/deploymentIdentity/registryIdentity/conversationId/rows。rows 按 taskId 排序，最多 4096 行，文档规范编码最多 8 MiB；永久保留，不在容量满时删除旧行。每行只有 request/taskId/inputIdentity/nativeTaskId。校验每行的完整 schema、摘要、派生身份、唯一 request key 与 native ID，不接受半行或不一致的身份。RootTask 原 input 固定为 schema/deploymentIdentity/taskId/inputIdentity/request，同样保留完整原请求。

receipt 只包含 schema/taskId/inputIdentity/nativeTaskId/nativeConversationId。它证明 SDK batch 的受理回执，不声称任务仍 queued、正在运行、已结束、已发送或费用为零。

## 提交、回执与不确定窗口

同步 verifyCurrent 只能返回 true，否则固定 current-invalid。检查点至少覆盖调用前、每次公开 await 后、callback 开始、最后文档写前和确认回执前。它核对既有 owner/部署/registry 是否当前；本组件不获取 owner 锁、不进行异步授权，不签与真实持久写原子同步的权限语义。

active submit 先非创建地读取并校验文档，再进入唯一 Session.commit callback。callback 用公开 Draft 提取的普通副本校验完整文档；重复请求先用 tx.task 精确读取旧 native task，在任何 table write 前验证 kind/version/conversation/input、无直接 task owner、background=false，再返回同一 receipt。同 key 不同完整输入报 request-conflict，零 createTask。

新请求完成文档容量与身份检查后，才调用 tx.createTask；将 native ID 与请求写入文档的 rows，并返回私有 callback receipt。同 batch 失败不返回 accepted。不要在 createTask 后调用 tx.task 或其他禁止 read-after-write 的 table 查询。

未知 SDK 错误、错误回执、callback 已 staged task 后的异常、close 或 verifyCurrent 失效均封闭该组件的新初始化与 submit，固定 recovery-required。只对本组件在创建任务前抛出的普通固定校验错误保留活跃状态；current-invalid 无论发生在哪个检查点都封闭。初始化回执必须严格为 callback 私有返回对象；submit 同样验证原 callback receipt，拒绝 SDK 替换结果或 callback 未运行却成功。不能把未知 SDK 错误包装成 StorageRejected 或 proof-not-sent。即使 commit 已落盘但返回丢失，也不再 createTask、换 requestId 或重新 bootstrap。

close 只封闭本组件，不关闭共享 Session、数据库、模型、owner，也不宣称物理停止。正在提交的 callback 在公开 await 后检查封闭状态；已经持久的记录不回滚。close 后或 commit 未知时查询可以尝试公开非创建读；不能由成功查询自动解除 recovery-required 或自动提交。新的活动组件由未来 owner/recovery 层显式构造。

lookup 只返回精确的既存 receipt；缺文档、缺 task、身份不符、查询失败均 recovery-required。一个健康文档没有请求行时只返回 not-found（不是 proof-not-accepted）；不得据此重新提交未知请求。查询不观察或报告 execution state，不推进任务，不丢弃已落盘的 native 关联。

## 后续 RootTask 与运行边界

本轮只实现受理与精确关联。RootTask 正文仍需固定 phase/abort/agent/预算和 registry 身份。公开 task-owned conversation 可以让 standard generation continuation 保留通向 RootTask 的 conversation owner 边；直接 generation Task.owner 不会在所有 continuation 中保持不变。这两种关系不能混用。后续采用哪种正文以及恢复时的 authority gate，由 root 单独决定。

SDK scheduler 可能在 commit 返回前启动工作。Doc 与 Task 同批可保证已提交关联先于任务表调度，但不能替代每次执行和 Models 发送的当前授权检查。模型计量未取得严格发送前输入上界资格；自动审核仍关闭，真实发送仍未开放。

另12份公开正文来源确认：owned conversation与Root checkpoint可同runtime.commit；bound handle.submit与存SubID各属下一独立提交。实际SDKinput字段是content，不是text；TaskRuntime.waiting只能等TaskId，不能填ConversationId/SubmissionId。submit和Submission.wait会resume，即使去重submit也先resume。因此未来正文必须持久绑定原child/key/完整输入，未知ack后的缺记录不允许自动重提。此次requests不实现这些正文切点。

## 离线验收

使用现有 test-pi-mock.mjs 临时 HOME/XDG、断网与网络/子进程守卫，仅自有公开接口替身；不导入或执行 SDK，不开真实 Harness，不读账号。替身真实实现串行 commit、暂存后原子采用、task/doc 同批、失败前后切点和查询计数；测试不能仅回调返回即声称持久成功。

覆盖初始化/active 丢文档、相同请求并发一个 createTask、完整字段冲突、旧 native ID 精确校验、terminal task 原 input 保留、提交前失败、已提交丢回执后 lookup、异步期间取消/close/owner变化、迟到成功/失败、坏存量/身份/容量、Proxy/getter/toJSON 零执行、原 receiver、零查询推进和未知不能重建。SDK Draft 对接只按公开提取接口模拟，真实原子/崩溃/owner/SQLite 恢复仍需独立显式验收。

最终命令为固定Node执行 `scripts/test-pi-mock.mjs agents/pi/packages/durable-service/tests/requests.test.ts`，正常属主require_escalated保留既有临时HOME/XDG、只读仓库、bwrap断网及网络/子进程守卫；69 passed/0 failed/0 skipped，7509.569262ms。仅Node内建与自有串行原子adopt Session/Tx、Proxy Draft/提取替身，未执行SDK、SQLite、scheduler、模型、账号或部署。

最初52/63/65项绿结果均是历史阶段，不累加。root在65阶段稳定审查发现initialize缓存Promise绕过关闭/当前权限/方法漂移；实际旧源加四个相同测试为65 passed/4 failed（8362.255355ms），入口复用缓存之前新增当前write check后，同69项全部通过。in-flight关闭的新initialize入口立即拒绝，原未完成提交仍按其自身迟到边界收尾。旧源码、原绿/红日志、同测试SHA、最小差异和独立复审保留在归档 `durable-request-admission/`。源码SHA为 `0ab4060efd2159efff804120c6996193e3218083163a9a91b2f1886d66951b3d`；accepted依赖和守卫未改，正式T083不勾选。
