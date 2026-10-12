# Durable 模型 attempt 账本的第一批持久实现

状态：2026-10-06以下非发送存储组件已实现，76项既有隔离默认测试通过（1.95秒），root及独立executor稳定复核无组件P1/P2，归档 `.cache/pi-two-profiles/run-20261004/durable-model-attempt-store/`。T085整体、公开Models包装、owner/严格资格、真实SDK/传输和Full gate仍开放。

## 存储及权限边界

账本组合受信 `SqliteDatabase` 的公开 `transaction/get`，每笔事务只用 callback 提供的 `SqliteExecutor`。不访问 SDK 的内部 db、队列或连接，不修改 SQLite adapter、宿主或 vendor。数据库来自未来服务工厂保留的原公开 facade；当前 storage initializer 不增加输出，不通过 `storage.db` 取它。

同一 facade 的公开契约保证 unrelated operations 等待 transaction 完成。账本使用独立自有表 `rotom_model_attempt_ledger` 的单份 schema1 JSON 文档；SDK 原任务、提交和会话表保持唯一任务权威。账本只含逻辑任务引用、native task/conversation 观察、模型路线及预算/调用事实，没有待执行队列、任务正文或认证正文。最多 4096 个 attempt / task 及 8 MiB 文档；行及预算引用永久保留为墓碑，容量满拒绝新记录。

`createModelAttemptStore({database, deploymentIdentity, mode})` 惰性单次初始化。deploymentIdentity 为小写 SHA256，mode 必填 `create`、`active` 或 `settlement`。只有控制面明确核实新存储后选择 create，才能在公开事务中建立初始表/文档，表已存在则拒绝；create 初始化后提供 active 的本地方法。active 只打开已存在的文档，不在表/行缺失时重建。settlement 也只打开已有文档，不能建表、预留或提交发送。每笔事务内先读回 journal_mode=wal、synchronous=2；没有这些设置就拒绝新持久操作。这里验证设置，不声明磁盘断电、文件目录所有权、服务 lease 或真实 SDK 已通过。create 字符串本身不证明是新数据库，未来受信工厂负责其准入，恢复流程只能选 active/settlement。

公开 API、数据、方法身份都捕获并复核，拒绝 Proxy/getter/未知字段及通用 Object/Function 原型补齐方法。事务 callback 不调用 owner/RPC/SDK/网络或外来 hook。外层 current owner、账户/任务预算权限及发送资格仍由未来控制面核验；账本不能签发这些能力，也不把 metadata ID 当权限。用户已决定保留严格reviewer输入上界，计量未验证前自动审核关闭；本组件不改变该决策。

## 不可变身份与累计额度

`prepare(input)` 的闭合输入为 attemptId、taskId、phase（generation/compaction）、nativeTaskId、nativeConversationId、registryIdentity、inputIdentity、policyIdentity、route（provider/model）、budget（scopeId/maxCalls/maxCostUnits/reservationUnits）。native ID 为原生正 safe integer，三个 identity 为小写 SHA256；attempt/task/scope 标识为 1–200 字符 ASCII `[A-Za-z0-9][A-Za-z0-9._:-]*`。路线每值为非空且非纯空白原生字符串，最多 256 UTF16 字符 / 1024 UTF8 字节，无 Cc/Cf/Cs 字符，允许 Unicode 和 slash。无 prompt、密钥、headers、路径或外来回调。

每个 taskId 永久绑定唯一 budget.scopeId 和原 maxCalls/maxCostUnits，scopeId 不得另绑一个 taskId；同 attemptId 的所有输入完全相同才是重放。新 attempt 不能修改已有 task 的额度，不能复活旧 attempt。每个任务最多一个 outstanding attempt（prepared/sending/result-recorded）；有未对账调用先阻止新增，不自动另建 attempt 试探。native task/phase 是调用身份，与逻辑 taskId 分开，不假设 SubmissionId 等于 taskId。

成本单位、reported token 和额度使用原生非负 safe integer；reservationUnits 为正，maxCalls 为正且不超过 4096。聚合用 BigInt 计算，输出成本总数为规范十进制字符串，避免多个 safe integer 相加溢出。prepared/sending/result-recorded 持有一次调用和完整成本预留，settled 使用一次调用及 reported estimated cost，not-sent 为零调用/零成本；墓碑仍保留。不从缺失用量推断零，不把本地 reported estimate 称为真实账单或发送前严格上界。

新 prepare 同事务核对累计调用和 charged cost 后写入。settlement 超出原预留或额度时仍记录可信旧事实并投影 overBudget，后续 prepare 拒绝；不能因已发生事实超预算而丢掉用量。任何已记录 observedRoute 与原 route 不一致或为 null 的结果保持预留，阻止该任务新调用，不能换模型隐式结算。

## 状态与回执丢失

状态为 prepared → sending → result-recorded → settled；prepared 另可 → not-sent。sending 以后绝不回退 prepared/not-sent。sending 无结果投影为发送 unknown，成本仍 reserved。重开只读取这些事实，不自动提交、重发、清零或换 provider。

`commitSending(attemptId)` 的首次事务返回 `{attempt, committedNow:true}`；重放返回 committedNow=false，任何重放都不提供再次派发的依据。先持久 sending、等数据库 transaction Promise 在 commit 后成功返回，未来调用者才可越过自己的发送入口。commit 成功但返回丢失时调用者没有成功返回，不发送；重开看到 sending 仍按 unknown 对账，不能凭“可能没发”回退。

`notSent(attemptId)` 只允许 prepared 首次转换，已 not-sent 的重放幂等返回原事实，其他状态拒绝；commitSending 对 not-sent 也必须拒绝。它保守地把没有 sending 的本地记录转为 not-sent，是受信控制面记录的 no-send 事实，不认证所有 Provider 物理发送都已被覆盖。它不释放 Writer 或物理资源。sending 的 abort、进程退出、SDK 空闲和响应缺失均不能调用此转换。

`recordResult(attemptId, {resultRef,outcome,observedRoute})` 只接受 sending，resultRef 为非秘密 SHA256 内容引用，outcome 为 completed/failed/canceled。observedRoute 为 provider/model 或 null；它是 caller 提供的观察而非 metadata 的自动复制。重复同结果返回既有事实，不同结果冲突；结果无 usage 时继续完整预留。

`settle(attemptId, {usage,estimatedCostUnits})` 只接受已记录且 observedRoute 完全匹配的结果。usage 为 input/output/cacheRead/cacheWrite 四个原生非负 safe integer，不接受总量或账单正文。相同结算幂等，不同结算冲突；estimatedCostUnits=0 仅来自明确可信事实。已结算与 not-sent 不再变为 sending。

`observe(attemptId)` 与 `snapshot(taskId)` 在初始化之后只通过 public get 读取原文档，不写入、不修复、不重新生成身份。close 只退役本地门面，不关闭共用 facade、取消 SDK 或证明物理终止。

## 持久失败与默认验收

SQL 值使用参数绑定，读到的 JSON 必须是本模块规范序列化的闭合文档；重复 key、未知字段、损坏身份/引用/状态/金额、重复 scope 或超限文档一律失败。每次事务核验完整文档，预算由原行重算，不用另一个可漂移累计缓存。

本模块可识别自己产生的语义异常。只有 public adapter 以完全相同的 callback 异常对象拒绝 transaction，才能按其公开契约认为正常预算、重放内容或状态冲突等语义失败已回滚；若异常不同、SQL 方法失败、rollback/commit 失败或方法漂移，则永久退役门面并返回固定 persistence-unknown，不暴露原异常/SQL/任务正文。已有文档缺失、损坏、schema/deployment 不符也永久退役，不能作为可修复的普通冲突。初始化失败永久缓存，不能在同门面重新建账本。只有显式 create 初始化创建原来不存在的表；create 已存在表属于 store-exists 已知语义失败，仍不能借此打开或使用旧账本。

默认测试仅自有模块与 Node 内建 SQLite（临时 HOME/XDG 数据库），不导入/执行任何第三方 SDK。自有 fixture 实现公开 facade 的事务排队契约，用真实 SQL 验证持久重开、并发幂等和额度竞争、提交后丢 ack、rollback failure、只读查询、满盘/写失败及永久 unknown、不复活与不自动重发。使用既有 `scripts/test-pi-mock.mjs` 的 bwrap/网络/子进程守卫，禁止放宽守卫。这个层级不等于官方 adapter/Harness 的 native 合成或真实模型验收。
