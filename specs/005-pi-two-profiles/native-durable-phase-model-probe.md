# Durable Harness／phase Models 原生合成探针准备决定

2026-10-06，主代理根据已验收的公开 driver／候选矩阵和 SDK-simple 缺省设计，决定先准备以下八场基础组合。本文是自有探针的实现范围；当前没有冻结运行 plan、没有新的原生授权，也没有运行 SDK。SDK-simple 实现仍须完成稳定独立复审；只有复审接受并准备固定材料后，才申请本探针的独立显式授权。所有历史原生授权已经闭合。

## 范围与公开路径

只在当前 Linux x86_64、固定 Node 24.14.0、Durable 1.0.1、实际 chord／pi-ai 1.0.2、断网 bwrap 中验证公开 Harness 对自有 phase Reader／Models 的真实调用。每场独立临时数据库和 HOME／XDG，候选包、探针及自有模块只读挂载，只有自有 work 目录可写。固定依赖与系统身份、严格 JSONL、typed 全值 oracle、父运行前后完整 inventory、已启动失败与 not-run 的区分沿用已验收 kernel7 准备方式。不得修改旧 kernel／fd／守卫来源或上游包。

使用公开 Harness.open、root、Conversation.submit／compact／commit、getTask／waitForTask／inspect／close，以及公开 SQLite 适配。不得调用私有 commitWith／setTask／scheduler 方法，不直接执行 TaskDefinition phase，不手写 checkpoint，不改 afterResponse 或 retry classifier。元数据 getModel 与底层自有 streamSimple／completeSimple 入口分别计数。

固定 settings 为 retry.enabled=false、stream.maxRetries=0、transport=sse、thinkingLevel=off；generation 禁止自动阈值／后台压缩，manual compaction 用公开 history 写入和明确 keepRecentTokens／reserveTokens 取得真正的 summarize。若实际为 no-op，不得算 complete 路径覆盖。所有 Model 字段是符合公开结构的合成纯 JSON，固定有限正整数 maxTokens；不用真实 provider、认证或模型。原 pi-ai 事件流 factory 可以实际使用，底层 Model 实现是自有固定流／响应，不调用官方 Models 的认证或网络实现。

存储通过原 initializer 核 WAL／FULL。在自有 nodeSqlite facade 中捕获公开 openNodeSqliteDatabase 的原返回对象，原 receiver 和原参数传递；不改 SDK 对象，不扩大 initializer 的接口。该原数据库同时供公开 SqliteStorage 和原 createModelAttemptStore 使用，账本不复制 SDK 任务队列。verifyOwner 在此探针明确是合成恒 true，不签产品 owner。账本初始化及所有方法使用原公开 callback transaction；不以 fake commit 计数代替实际写入回执。

每场合成意图、logical task、attempt、route、budget 均由固定自有 fixture 事先决定；首次真实 phase 的原 native identity 只用来关联该意图，不能产生新的权限、attempt 或预算。全三次 authorize 的规范 envelope 必须相同，包含所选 cap；在实际底层入口内部确认原 committedNow=true 已返回，并从同一个原账本只读观察相应 sending。合成控制面与产物不具有真实账户、权限或输入计量资格。登记的自有 RootTask 本文只提供完整 metadata，正文必须零调用；只读工具和业务 backend 本八场也必须零调用。

## 固定八场与 oracle

| 场景 | 原公开触发／切点 | 必须观察的结果 |
| --- | --- | --- |
| generation-success | 新明确 input 的真实初次 generation | 三次 authorize、一次原 prepare、一次原 sending 真回执、stream 入口一次；缺省 cap 规范为固定值；同原任务已知终态，原 result／settle 持久事实后返回 |
| generation-denied | 同一合法初次请求，由自有 authorizer 明确拒绝 | 确实进入 authorize 一次；prepare／sending／stream／complete 全零，固定拒绝；不能把 parser 失败算授权拒绝 |
| generation-error-no-retry | 初次请求的自有底层流返回合法 error，合成文字含 503 | stream 一次、三次 authorize，持久失败 result／settle；公开 SDK 看见 dispatch-unknown，未发第二请求；不伪造自动 retry 正例 |
| compaction-success | 公开写合成历史后真正 manual compact／select／summarize | complete 一次、stream 零、三次 authorize、原真 sending 回执；原 positive cap／cacheRetention=none、公开 summary 结果及账本事实 |
| compaction-denied | 真正 summarize 的 authorizer 明确拒绝 | authorize 一次；prepare／sending／complete／stream 全零；真实 compaction Task 与 summarize 路径有独立观察 |
| compaction-error-no-retry | 真正 summarize 的自有 complete 返回合法含 503 error | complete 一次、stream 零、失败事实持久、公开 SDK 不再 summarize；原错误清理保持 |
| generation-lost-sending-ack | 原账本 commitSending 确实提交后，自有 facade 丢返回回执 | authorize 两次、prepare 一次、原 sending 真回执一次、底层入口零；账本仍 sending／unknown 占用，不能伪造 not-sent 或退款 |
| generation-replayed-sending-ack | 自有 facade 同原 ledger、同 attempt 连续调用原 commitSending 两次，仅把第二个回执交 dispatcher | 两次原方法返回分别 true／false，实际 sending 只首次变更；dispatcher 拒第二个回执，底层入口零，账本 sending／unknown 占用保留 |

数字是本次具体路径的待验证 oracle，不是已通过证据。若 SDK source 推翻预期的公开 Task／Submission 终态结构，必须在执行前给主代理精确来源及最小差异；不得放宽为“有输出即通过”。error 原文只有固定合成值，通用日志不输出 SDK 异常、路径、SQL 或请求正文。已经发生的原 sending 真回执不能因外层丢回执或返回 false 被抹除。

## 输出与父侧约束

每场输出一行有界 JSONL，并在 work 中 O_EXCL、0600 保存完全一致的 state。明确 schema、case、四版本、WAL／FULL 读回、nativeStarted、固定完成阶段、原 native task／conversation 正整数、所观测的公开 task kind／state、原规范 cap、counter 和顺序 trace、账本只读 projection、合成正文／backend 零次、cleanup 状态。NativeID、SDK checkpoint attempt、original signal、self envelope、ledger attempt 分别记录；没有原 Runtime／ChordContext 的完整引用观测，就明确 unknown，不从重构对象补原身份。三次原冻结 envelope 的同一引用与完整规范值仅在 worker 私有内存比较；state 只输出实际比较产生的 matched、受选 options／cap、原 native identity 与 sameSignal，不输出 messages／请求正文或正文 hash。Task／summary 正文也只作私有完整匹配，公开输出固定 metadata 与实际匹配布尔，不能写常量 true 冒充观察。

父侧校验完整键、类型和值，bool 不等于 integer；候选系统／自有源／manifest 的原完整清单在运行前后相同，work 工件逐场封闭清单。每个 case 的 stdout／stderr／state／post inventory 原始材料保存，不相加不同 execution 的测试数。不以 exit0 推导 namespace 全树 IO／物理停止。清理失败使已启动场景成为失败，不能误记未运行或成功。

## 自有实现与默认检查

新增 scripts/pi-probe-durable-phase-model.py／.mjs、tests/test_pi_durable_phase_model_probe.py 和 tests/fixtures/pi/durable-phase-model-probe/manifest.json／oracle.json。这些文件由单一 executor 写入；主代理独占本文件、plan 与状态记录。旧 kernel、SDK、自有 accepted runtime 模块和 guards 均不修改。

默认 Python 检查只用临时目录、fake subprocess 和固定全值输出／inventory，不 import Node worker 或 SDK，不运行 bwrap／Node／SQLite／模型，不读账号或访问网络。覆盖 plan/source/system 身份、exact argv/env/mount、八场 typed oracle、非零／stderr／截断／多行／字段漂移、启动后 finally／post 失败、closed artifact inventory、超时与重复执行。保留第一次完整源码与测试，再首次运行；真实缺陷才留完整旧源／同新测试的行为失败，不制造不存在导出或缺文件的假 red。测试命令为原 pytest 守卫下仅新增 Python 文件；具体正常属主命令和实际结果另记录。

完成默认检查与稳定材料复审后，prepare 只读取并固定材料，不运行 SDK。实际新目录、完整 plan SHA、源与候选／系统身份、命令、八场 oracle 及弱边界全部可审查后，才按 AGENTS.md 的独立真实 smoke 要求申请授权。收到明确授权才 run-native；以后同边界必要修复重跑须保留每次实际材料和失败。

真正工具等待、明确新用户输入、取消／迟到事实、genuine summarize checkpoint 的关闭／重开恢复继续按已验收候选矩阵准备，不由本八场推导通过。running retry 正例在固定隐私清理和 retry=false 下不可合法证明。本探针不完成 RootTask 正文／业务根、长期 owner／ready／released、崩溃／冷 owner 恢复、实际模型／账单／严格 input_tokens 或 Full。自动审核关闭，正式 7/100 和所有产品 gate 保持 false。

## 当前 review01 的实际固定材料

2026-10-06：上文首稿 SDK-simple 待复审为历史阶段状态；该组件已验收。八场自有准备的 UTF-8 capture 缺口已用完整旧源／相同最终84项真实81通过、3失败复现，最小修后84通过，root／独立稳定增量开放P1/P2=0，归档 `durable-phase-model-probe-default-review02/`。这些是 fake 默认证据，不是实际 SDK 运行。

实际 prepare 已在正常属主 UID1002 完成，exit0、stderr零字节；它只读取来源并写新的临时 plan，没有启动子进程。具体目录为 `/tmp/pi-durable-phase-model-native-review01-normal-owner`（0700）；只含原 `plan.json`（0600、单链接、3014516 bytes）。原 plan SHA256：

`fbfea36d7b76c3c32d14fbd07bf5d025756ecca6152ddc5d465bfda434186a0f`

实际 prepare 匹配当前 Durable257、Pi closure18498条目以及12份实际自有来源；原两项 source chain、固定 Node／bwrap 文件和 `/usr`、`/lib`、`/lib64` 的目录身份也记录。不是整个系统目录递归散列。Parent为 `8ee2b835492af86662a1bd815391c516b3d2af08e991343050d85a8855ae9003`，worker为 `e6dd993812c8d6c9eb1a9fe0c1e836db4619ba52c0e49ba1705cb7efa550972f`；两份 fixture 和七份 runtime 原记录详见实际 plan。原 raw prepare 日志与摘要为 `/tmp/pi-durable-phase-model-native-prepare01-{stdout.log,stderr.log,report.md,hashes.json}`。当前没有 started／execution／work 工件，没有新的原生授权；正式执行之前还要对固定材料稳定复审。

实际 prepare 命令（已执行，零 SDK 调用）：

```bash
/usr/bin/python3.11 -I -S -B scripts/pi-probe-durable-phase-model.py prepare --directory /tmp/pi-durable-phase-model-native-review01-normal-owner
```

待独立授权的实际命令（尚未执行）：

```bash
/usr/bin/python3.11 -I -S -B scripts/pi-probe-durable-phase-model.py run-native --directory /tmp/pi-durable-phase-model-native-review01-normal-owner --native-durable-phase-model-probe
```

该命令只按原 plan 顺序跑上述八场：公开 Harness 初次 generation／真正 manual summarize 的 success、明确授权拒绝、清理后的503错误不重试，以及 generation 原 sending 已提交后丢ACK／重放ACK拒绝。`nativeAuthorized=false`、`nativeStarted=false` 保持原冻结 plan 字节，收到外部授权也不改 plan；执行另留 started／逐场原stdout-stderr-state／execution 工件。每场30秒、合计240秒，stdout单行64KiB、合并输出1MiB，来源只读、空宿主env加固定白名单、断网 bwrap、仅各场 work 可写。失败后不启动后续场景；必要同边界修复须保留失败原材料并另建新 plan，不能覆盖旧工件或扩场景／账户／网络／部署。

这里会真实加载固定公开 Durable／pi-ai／chord SDK，并使用临时 SQLite 和自有固定合成 Models。它不启动 Pi TUI／Codex，不读取账号、调用真实模型或外网，不部署。verifyOwner 恒true只是合成输入；不签真实持锁、owner／ready／released、崩溃恢复、完整Runtime／ChordContext引用、全进程树／IO停止、输入计量／输出／费用或 Full。namespaceTermination 和物理终止仍 unknown，产品gate与7/100不变，自动审核继续关闭。

单独授权的依据是 [AGENTS.md](../../AGENTS.md) 测试边界原句：“真实 smoke 为独立显式步骤，需用户明确授权”。已经闭合的 kernel7、FD6 等历史授权没有覆盖这次 Harness＋phase Models组合；此处不复用它们。
## review01 实际结果与授权闭合（2026-10-06）

用户已明确授权当前 fbfea plan，正常属主按冻结命令执行一次；parent exit0、stdout0、stderr0，八场均 started／observed／complete／exit0，各 stderr0，无修复或重跑。root 与独立 executor 对稳定原工件限定审查开放 P1/P2=0，七十三输入归档 `durable-phase-model-native-observed-review01/`，当前八场及同边界必要修复授权闭合。原 plan 字节与准备 flags=false 保留不变；实际启动由 started／execution／guest state 记录。

生成与真正压缩的成功、合成合法 503 错误各 authorize3、prepare1、原 true ACK1，分别仅 stream1／complete1，result／settle1；错误清理为原固定终态且无 retry。两拒绝各在实际 authorize1 后 prepare／send／Model／result／settle0。丢 ACK 原 true 后 Model0；重放原 true,false 后 Model0；二者 sending／unknown、calls1、reservedCostUnits 字符串 `"10"`、settled 字符串 `"0"` 保留，未退款。真正成功摘要核原 completed.result.submissionId→write.done.entry→summary.head 为 beta；no-op 不通过。

八份原 stdout／state 字节相同、严格 typed 双 oracle 各自通过，51 个 0600 单链接普通工件和 73 个 0700 目录闭合。67 工件／来源 pins、十二 current sources、两个 source-chain 与固定系统身份精确匹配；实际 parent 前后完整 257／18498 清单由 materialIntact=true 记录，复审未重复全量候选树。数据库仅 bytes/hash 保全，不在复审中加载 SQL。原 envelope／signal 由固定 worker 私有全引用／规范值比较；拒绝只观察一次、ACK 异常只观察两次 authorize，不冒称三份。metadata getModel 为自有 forwarding facade 计数，底层 Model 入口不等于真实网络发送。

本八场不包含恢复三场，不覆盖 RootTask 正文／backend／owner／ready／released／冷恢复／真实账号模型／外网／部署／严格 input_tokens 或计费。Runtime／ChordContext 完整引用和 namespace／全树 IO 物理停止继续 unknown，cap64 不提供真实输出账单硬界。默认 84 项与原生 8 场不相加；正式 7/100、产品 gate 和 AUTO OFF 保持。
