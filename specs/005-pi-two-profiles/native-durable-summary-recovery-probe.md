# 真正 summarize 的 orderly close／公开重新打开准备决定

2026-10-06，主代理根据 `durable-summary-recovery-exact-public-static/` 十八输入限定以下三个合成候选。本文是新的设计草稿，尚未独立设计验收、授权实现、冻结原生 plan 或取得原生授权。当前待授权的 fbfea 八场基础组合不包含此恢复组合，本设计不改变那十二份固定来源。正式7/100、产品gate和自动审核关闭不变。

## 原公开入口和原事实

没有 Harness.reopen 方法。只能用原 initializer 成功关闭后的同一路径构造新的公开 storage，先 `storage.task(originalTaskId, context)` 被动读回原 running／summarize，再以新的 Models／Reader 调用公开 Harness.open。该 open 会持久转 pending 并保留原 checkpoint，且调度默认暂停；open可能维护其他任务，不能统称只读。getTask／inspect／conversation及原Conversation.context／entries只在本组合中作被动查询，不调用 wait、resume、compact、submit 充当查询。真正执行恢复须单独调用公开 resume，然后 waitForTask／waitForIdle；wait自身也启调度。

真正 checkpoint 必须由原 select 从两个公开被动 UserEntry 合成历史形成；沿用 model cap64／window8192、keepRecent0／reserve80、thinking off、retry false／maxRetries0、stream sse／maxRetries0、cacheRetention none。公开 compact 仅首次调用，不能在重开后创建新 compact/task，不能手写 checkpoint、直接执行 phase 或调用私有 storage／scheduler API。选中的 firstKept必须原 beta entry、前段非空，恢复成功必须真实模型complete入口、原summary submissionId→write.done.entry和summary.head指向原 beta；no-op不通过。

选择公有 HarnessOptions.now 的同一个原固定合成时钟函数，返回固定安全整数1234567890；历史两message时间固定1／2。它只使本探针重建请求可进行严格私有比较，不提供真实时钟、计费或预算资格。三次authorize的原冻结envelope引用／全规范值及同signal仍在每个新dispatcher内检查；跨factory只要求实际观测的完整规范envelope值相同，新envelope引用和新signal必须不同，原signal已aborted。旧Runtime／ChordContext完整引用不可观察，继续unknown；不从checkpoint反推出这些引用、messages或grant。

## 合成意图和 attempt 由原控制面预先决定

fixture先固定唯一 logicalTaskId、scopeId、policy／registry／source、route、maxCalls1、maxCostUnits20和reservation10。首次原native identity只关联已有合成意图；不据TaskID、SDK attempt1、pending状态或原ledger缺省生成权限。两个潜在永久ID A1／A2在fixture中预先固定，不能由native编号或重开次数派生。CP的SDK attempt1与账本永久attempt不是同一个序号，不能声称native attempt递增或自动重试。

第一、二场首次authorize只保存真实输入并等待原signal，未返回任何grant；没有prepare／sending，也没有持久A1。第一场fresh控制面另按本合成fixture明确允许一次A2；仅在完整成功close、held authorizer已结束、实际空账本检查、原部署／源／意图及完整规范输入全部匹配时，三次返回相同A2 grant。这里模拟的是事先限定的自有控制面许可，不是根据空row恢复权限；不将缺row改成not-sent、不伪造退款或原A1已取消。第二场fresh控制面明确拒绝，证明真正恢复已到authorize后零副作用。

第三场首次A1已真实prepare／commitSending，但第三次authorize尚未返回；这时sending／unknown及call1／reserved10仍占用。完整close和Model入口零不释放这份未知预留。fresh控制面根据原A1持久unknown拒绝，零A2 grant／prepare／sending／complete；不把没有本地Model入口当作可自动退款或再次发送的通用证明。不先删除旧attempt或重建预算。

## 三个固定场景

| 场景 | 原公开切点 | 必须实际观察 |
| --- | --- | --- |
| summarize-before-send-fresh-bounded-authority | 首次第一authorize前发送hold，成功close，fresh storage读原running CP，Harness.open为pending，明确resume | old authorize1且prepare/send/Model0；fresh新signal与原同task／CP／完整规范请求，authorize3、prepare1、真sendingACK1、complete1、result1、settle1；A1不存在，A2settled，原budget calls1/reserved0/settled2；真正summary结果绑定 |
| summarize-before-send-denied | 同一真实hold／close／fresh原task恢复，fresh第一authorize明确拒绝 | 全程old1＋fresh1次authorize；prepare／sending／Model／result／settle0；A1/A2都缺省；原task真实faulted／dispatch-unknown，零summary；不是parser或source失配冒充授权拒绝 |
| summarize-unknown-sending-denied | 首次第三authorize在原trueACK之后hold，成功close，fresh同task原CP恢复 | oldauthorize3、prepare1、sending1且原true回执、Model0；close前和fresh读回A1均sending/unknown、calls1/reserved10/settled0；freshauthorize1后明确拒，零新prepare/send/Model/result/settle；A1预留不变、A2缺省，原taskfaulted，零summary |

数字是设计待证预期，不是运行结果。三场分别独立临时路径/数据库/逻辑意图，第三场不得借第一场的空账本例外。成功和拒绝须符合当前公开compaction终态（成功completed.result.submissionId，无entryId；拒绝抛错faulted.error.message固定dispatch-unknown），不放宽为“终态即可”。

## hold、关闭和 fresh 的次序

每次hold仅在原authorize首次或第三次的明确定点，进入后以私有promise通知driver，并保存实际原TaskRecord/checkpoint/envelope/signal。driver用原BACKGROUND_CONTEXT等未aborted清理context作被动查询、核actualcheckpoint与ledger。held authorizer必须响应其原signal一次、解除订阅并以固定自有错误结束，禁止永不返回的hold。实际public Harness.close使原scheduler abort并join；关闭中的原step不写Task outcome。等待完整close成功和该原held-authorizer的settled barrier全部完成之后，才退役旧wrapper／ledger、打开同路径新Db。public close取消等待、仅调用close、EOF、定时睡眠或oldsignal.aborted单独都不算完成。

新initializer捕获新原publicDb，原ledger mode=active（核原已存singleton与部署身份，不创建、修复或重置）与新SDK storage共享这个Db。原关闭成功回执不是崩溃／断电／冷owner证据。原初始化设置仍实读WAL/FULL，不能嵌套session commit在Db transaction callback内。旧Db关闭后不继续调用旧storage／ledger读回，不把两个活Db或fake投影当同原持久恢复。

fresh Harness构造前读原storage.task并保存完整CP私有规范值；open后getTask再次读pending并与原CP逐值比较。fresh原Reader／Models全新，源码／原函数及当前model/registry身份由固定材料独立绑定，不能声称checkpoint保存了原Reader对象或版本字符串就是源码身份。被动读回期间新增authorize／prepare／send／底层Model计数必须零；只在显式resume后匹配新phase真实invocation。第一次新authorize必须私下比较重建原完整envelope值；不匹配就固定失败，不能忽略timestamp/messages/options或就地重算输入身份作为许可。

## 准备实现与验收边界

后续只新增自有恢复parent／worker、fake Python父测试和固定manifest／oracle，不修改已固定八场来源、旧SDK或guards。借用已验收严格UTF8 bytes／bytearray、typed闭合双oracle、O_EXCL0600输出、700目录、readonly来源和empty宿主env＋固定guest白名单；实际计划必须覆盖全部worker静态/动态imports。每场30秒、三场90秒、stdout64KiB／合并1MiB，失败保留原started、rawstdout/stderr/state和闭合工件，停止后续场景，不声称namespace／全树IO物理停止。

默认测试只允许自有临时文件／fakeprocess／固定投影，无Node／SDK／SQLite／网络／信号。第一次完整source及test在首次默认执行前捕获；只将完整旧源＋相同最终回归的真实行为失败记red。设计与默认稳定审查后才prepare实际新plan、来源/system/命令；按AGENTS.md:42再请求此三场独立原生授权，不复用fbfea或FD6 grant。

本组三场无RootTask正文／工具／业务backend／真实账号模型／外网／部署；不签真正owner／ready／released、SIGKILL恢复、磁盘故障、远端停止、费用、严格input_tokens或Full。实际结果偏离公开源码预期时由root决定最小同范围修正，不能修改上游／retry classifier或放宽安全目标。

## 当前 review01：已形成具体 plan，待独立材料审查和原生授权

本节更新首稿的阶段说明。`active` 模式设计已复审，自有新增五文件及默认准备组件已稳定验收；64 项默认检查通过（0.58 秒），首轮 59 项另存，不相加，没有行为 red。root 与独立 executor 对原 CP、完整 close＋held-settled 双 barrier、fresh 原 Db、被动零调用、显式 resume、完整请求与 unknown 预算顺序的限定审查开放 P1/P2=0。四十七输入归档 `durable-summary-recovery-probe-default-review01/`；默认只运行 own fake Python，尚无三场 SDK 运行证据。

正常属主运行自有 `prepare` 已 exit0／stderr0，实际全量 257 Durable／18498 closure 清单与固定 manifest 匹配；十二自有来源、两个 source-chain 和固定系统身份写入 plan。root 再只读核固定 source／system／invocation 和私有工件，没有再次运行 SDK／SQL／Node／bwrap。当前目录只含 0700 目录内的 0600 单链接 plan，`nativeAuthorized=false`、`nativeStarted=false`；没有 started／execution／case／work。

- 目录：`/tmp/pi-durable-summary-recovery-native-review01-normal-owner`
- plan：`/tmp/pi-durable-summary-recovery-native-review01-normal-owner/plan.json`
- plan SHA：`d61799a7451795436d280e6805f1359b9901ab34326edf7ae2b33dbf7473db62`
- plan 大小：2997708 字节
- 当前 parent：`63cd928f5aaaf3066e5926605677ead1fbf8ece1f62bd44103db82cba59dd2e1`
- 当前 worker：`3bca378ad2c3a00a1034f00cc316582bad85a5be14c290abdc01e84435760160`
- 当前 oracle：`b273afaeff8aadcf986f5d7d0be6015e1a5f01f327c2184b8623abeafe90284b`

审查材料为 `/tmp/pi-durable-summary-recovery-native-prepare01-report.md`、同前缀 `hashes.json` 与原 stdout／stderr 日志。原已接受 4aae 设计在 `/tmp/pi-durable-summary-recovery-native-design-before-concrete-plan.md` 和默认验收归档保留；追加本节不改 plan 的十二份运行来源。

通过具体材料独立审查且取得本组三场明确授权后，唯一执行命令为：

```bash
/usr/bin/python3.11 -I -S -B scripts/pi-probe-durable-summary-recovery.py run-native --directory /tmp/pi-durable-summary-recovery-native-review01-normal-owner --native-durable-summary-recovery-probe
```

只执行上述三个固定场景和同边界必要修复重跑。每场 30 秒，总 90 秒，stdout 单 JSONL 最多 64KiB，合并输出每场最多 1MiB。bwrap 断网，固定候选／自有来源只读，仅临时 SQLite／HOME 可写；不启动 Pi TUI／Codex，不读真实账号，不调用真实模型／外网，不部署。当前八场授权和历史 FD6 均不覆盖此组合。AGENTS.md:42 要求「真实 smoke 为独立显式步骤，需用户明确授权」；此三场尚未申请或取得原生授权。失败保留真实 started 与原始工件，在新排他目录 prepare 固定来源，不放宽 oracle、安全目标或扩大场景。

hold-settled 只证明原自有 hold 的 finally／barrier 已完成，不证明所有 SDK Promise、进程树或 IO 物理停止；共同 wait 后的两个 trace 标签也不证明两事件独立时钟先后。成功 fresh A2 是预限定合成许可，CP、缺 row、同 task 或 attempt1 均不产生权限。SDK close／新开、unknown 预留、完整请求和真实摘要的数字仍为本组三场待测目标；不签 owner／cold／crash／费用／严格 input_tokens 或 Full，正式 7/100、产品 gate 和 AUTO OFF 保持。

具体材料随后独立审查开放 P1/P2=0，三十输入归档 `durable-summary-recovery-native-prepared-review01/`，当前 doc 和 prepare 时历史 4aae 设计分别 pin，不把追加文档记成运行来源漂移。已发本组三场独立授权请求，尚待明确回复，未执行 native；上文「尚未申请」是材料形成阶段事实。其他自有实现和默认检查继续。


## 当前执行结果（2026-10-07，授权已闭合）

2026-10-07 Recovery3 d61799明确授权后一次按固定原run-native执行，UID/EUID/GID1002/1002/100，2026-10-07T08:05:26.882898Z–08:05:34.954913Z；inner0/stdout0/stderr0、parentFailed=false/materialIntact=true，全3started/observed/complete/exit0，12own来源与原plan端点相同。root核全部实际raw/state和typed oracle/dynamic规则，scout核48工件21files/27dirs字节副本，46输入receipt `8059bd7f417bca109a35c94726dc33d986fcb220f346924e89eca29be6e1f879`；固定task10/conversation1/history6,8，freshDb先running/summarize后paused pending/passive0、explicitresume；成功仅新预限定A2一次complete并settled2/calls1/reserve0，summary12→entry11/head8。拒绝prepare/send0；unknown原A1 sending/reserve10/calls1在close/passive/final恰等、无退款/A2。namespaceTermination/runtimeReference/chordContextReference仍unknown，不推allPromise/物理停止，非crash/takeover/费用/严格计量/产品资格；未修/未重跑，本exactgrant闭合，原default64与native3分列。
