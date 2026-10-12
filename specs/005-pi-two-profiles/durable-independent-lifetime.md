# Durable 独立服务寿命与来源保护：方向候选

2026-10-07，root 根据原锁持有链与九源 maintenance/reconnect 证据修正尚未实现的 lifetime 接缝。本文不是 IO/锁/schema/角色实现授权，也不改变已通过的九消息 codec 和纯回复窗口；下一包须冻结新的 service activation、source hold、私有引用和恢复接口后才能实现。

## 原目标与已发现的接缝

Full 的 Durable 任务必须在前端正常关闭后继续，并支持后续前端按原服务、请求和 Task ID 重连。关闭前端不等于取消任务、销毁 SQLite、换 source/provider 或清预算。显式停止、来源漂移、未知退出和冷恢复分别处理。

现有普通 Pi 路径不满足该目标：caller 的 `subprocess.run` 同步等待 HostSupervisor；host 退出后 supervisor 请求取消非 host running 执行，等待 protected activity drain。普通 run 的 lifecycle/assert_inactive、新 supervisor 的 assert_mutable 与跨 activation allocate 都拒绝旧 protected activity，因此不能把再次 run 当作 attach。instance_fd 是物理实例 EX guard，其父 context 明确 LOCK_UN；lease_fd 是 state instance.lock 的执行协调句柄，不是 runtime 专属保护。Pi 的 runtime 更新由该实例与状态锁及 protected activity 检查保护，不存在已核独立 Durable runtime lease。

先前 private-channel/lifecycle 设计保守地把 parent EOF 与 Node 停止相连，但没有定义完成初始化后的独立服务寿命。只让旧 HostSupervisor 永久等后台任务，会同时留下终端、重连、普通活动 owner 和实例 EX 的问题。该接缝不能由多复制一个 fd、合法 R/E、source hash 或 service status 解决。上述是静态发现，未观察当前产品实际启动失败，也未做新的 OS/宿主探针。

## 选定的职责路线

现已规划的独立 controller 继续作为唯一 storage/OFD guardian、原 Node 创建者及持 pidfd 的 owner；完成明确的独立 service activation 后，它负责服务寿命。初始化 issuer/交互 HostSupervisor 不成为永久后台 Keeper，不新增通用 manager/任务队列。Durable 排队仍属于选定官方 SDK，Task Keeper 和普通执行权威不合并。

初始化和 active service 分开：slot/offer/fresh/registered/index-close/release 仍只完成原初始化前缀和最多一次 zero-SDK Node launch。release 或 release-ack 不表示 service active/DB/task/model grant。新的 activation 必须在完整 Node hello/bound、原存储/角色/current/source/issuer 检查和 source hold 写者交接之后由原受信 issuer 明确一次批准；guardian 才能建立自己的私有 service context 和 DB/受限 admission。其完整原 SDK Model、credential resolver、account/model/task budget 与取消来源必须在 guardian 自身有真实出处，不能留下对已退出前端 callback 的依赖。缺任何项保持 zero DB/task/model；不能用 serialized Model/JSON/accepted flag 代替 private activation。

本路线增加一个独立的 activation/写者交接阶段，exact 字段、帧数、类型、nonce、deadline、原 source/issuer API、send/postpure/ACK 与失回执状态尚未冻结。当前九消息实现只被接受为初始化前缀；禁止通过把 release-ack 改名为 ready、偷加布尔或 callback 达成后续能力。未来 grammar 改动须单独设计与稳定 diff/default/native 验收，旧证据不外推。

activation 完整消费前，parent EOF/取消/超时按原生命周期拒绝或停止，Node 尚无 DB。明确授权的独立寿命转换完成后，前端或初始化 pipe 正常关闭本身不能取消服务；未用初始化入口永久退役，guardian 不从迟到消息恢复 grant。其自身 source 漂移、明确授权的 service stop、owner/Node 异常则沿原 held pidfd、quiescence、closing/released 及 unknown-held 规则。不能为“后台化” double fork 或丢掉 original Popen/Node owner；terminal/group/stdio 继承与正常关闭行为还须公开 API/native 资格。

## 持久 source hold 是保护，不是启动权

增加专门的、有界、非秘密来源保护记录，绑定原物理 instance、state、固定旧 runtime、原 FullSourceView、初始化 request/context 和原 guardian。它保护 active、starting、可能启动和 unknown，维护不得删除/修复/替换原 source。不是普通 execution lease 或 grant，不能纳入现有 host-exit 自动 cancel/drain/reclaim，不能从该记录重建原 Popen、private Full reference 或 DB 权限。

原 trusted initializer 在首可能 controller Popen 前取得并持久该保护意图，防止 manager/caller 崩溃后普通 host recovery 清完旧执行而遗忘独立 child。此处允许自有 managed activity bookkeeping；它与消费业务初始化 grant 后才允许的 Durable account control-anchor/service-index/storage 创建分开。旧 private-channel“零持久目录”在此精确为零这些业务目录，不能将新增 bookkeeping 误称零写入或拿它授权业务副作用。bookkeeping 的固定目录/文件/schema/cap、校验/发布/锁序和生成者尚未冻结。

source hold 的写者也只能一个。parent 初始化写者在实际 publication/quiescence/close 完成前，guardian 不更新同一 record；新的授权 activation/交接发生后，只有原 guardian 可建立并持有自己的 writer，parent 永久退役。具体交接不能靠状态字符串或 socket ACK 推断 close；须跟 index 已接受的 separate-close barrier 同样有实际原 owner 回执。source hold 本身没有 token、credential、私有 generation 或其摘要；完整非秘密内容与 physical file 身份另冻。

guardian 只有在原 Node 真退出、DB/所有 producer 静止、原 storage released 持久回执与需要的 close-only 都明确之后才能发布来源释放并退休 hold。任何写/fsync/close/退出未知仍阻止变更，不按 deadline、EOF、manager 死亡或 busy 查询推断安全。不借父原 instance/state 的 LOCK_UN 释放 guardian 的保护，也不让清理 marker、换 profile/state/runtime/SID 重置旧 Task/budget。具体顺序、锁查验和发布临时状态必须下一包逐切点审核。

## 普通前端、维护与恢复

普通前端 launch 与 source mutation 使用不同的明确 purpose：原 host/普通 protected execution 限制保持；单独 Durable source hold 只保护源和所有权，不把健康的新前端当第二个 writer。新 Full 前端需独立当前 Full source/initializer/admission 验证后，以原 service ID/socket 协议查询或附着；registered R/status 只供定位，不能成为请求或恢复许可。换 provider/runtime 不能对活动服务自动换源。Base 普通编辑不加载 Full resolver/package/source hold discovery；其 cold 路径零可选访问。作用于同一物理实例的维护仍必须遵守共享来源保护，不能以选择 Base 绕过该保护。

apply/setup/rollback、依赖 sync/repair/activate 及其他实际源删除入口须在同一 compare-and-acquire 边界核 source hold，不是检查后无锁再改。ordinary recover 的 allow_active 和单 execution lease stop plan 不得清掉新 source hold。新的显式 Durable stop/cold recovery 是独立操作与授权，保留 original R/SID/request/budget，只有实际匹配来源/owner/存储及可靠终止/关闭证据才允许释放或新 epoch。manager 死亡与找不到 PID都不允许自动重试、接管或 clear。不同命名删除路线仍缺完整映射，不能称“所有入口已覆盖”。

## 实施验收边界

必须先关闭 exact FullSourceView/installed validator、独立 initializer principal、fixed sealed Python/Node/helper 闭包与 source-hold/activation 接口，再分唯一 writer 实施。默认临时 fixture 和真合法对照覆盖 init 各切点 crash/lost ACK、一次 launch/activation、未 active 的 EOF zero DB、active 的前端退出和重连原 ID、parent writer 未 close 不能交接、source hold 阻止维护但不阻止健康前端、普通 recovery 不清新保护、unknown 保留、最终释放顺序、无第二 launch/预算退款/Model切换。fake guardian 必须真实消费 activation 并进入受限 service state后再丢回执，不能用 inert fake 骗出零副作用。

真正 controller/Node/SDK/多前端/manager death/maintenance/source hold/held lock/recovery 组合须新的明确 native 授权；旧 fd6/Harness8/SDK/RPC 不覆盖。当前只修设计方向，不签 source/issuer/DB/模型/产品资格。正式7/100、全部产品 gate、strict metering 前 AUTO OFF 保持；尚未闭合的接口不会阻塞与其无关的普通编辑组件实施。
