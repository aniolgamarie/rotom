# RootTask 原提交内容观察边界

状态：有限纯组件最终94项守卫默认检查及稳定独立增量复审通过，root验收归档`durable-submission-observation-default-review02/`。原68绿在最终定点复核发现非目标UserInput类型校验P2；真实旧源同94套件70 passed/24 failed，修后94 passed/0 failed，计数分开保留。只验收纯值关系与结构，不证明实际公开读取来源、完整RootTask正文或authority。

2026-10-06，主代理根据已验收的正文12份和原提交13份公开来源，先实现纯观察校验器，再接公开读取与RootTask编排。它不启动宿主、查询数据库或改变状态。完整Root input中的请求、授权、路线、预算与原child ownership仍由可信控制面复核；本组件只核精确原Submission与native text的关系，不能授予执行权限或证明完整原envelope。

## 已决定接口

新增自有`src/submission-observation.ts`，仅导出同步`captureDurableSubmissionObservation(expected, observed)`。expected闭合字段为`childConversationId`（正安全整数）、`requestKey`（1–200个受限ASCII ID字符）、`submissionId`（null或正安全整数）、`text`（合法Unicode UTF-8最多64KiB）、`whenBusy`（steer/followUp/reject之一）。text直接作为原native UserInput字符串，不与数组、转换后的上下文或摘要做等价替换。

observed闭合字段为`submission`、`inbox`、`entry`，均为原公开读取的普通/null原型JSON副本或null。可信SDK Draft必须在外层用原公开copyJson提取；业务Proxy、accessor、symbol、未知字段、undefined、非有限数字、非法Unicode、循环、稀疏数组、子类/非普通原型、toJSON均拒绝。不会读取getter、触发Proxy trap、改动或冻结调用者/SDK值。各输入先完整有界复制，单次所有JSON累计最多1MiB、16384节点、64层深度，Inbox最多4096项；没有放宽选项，超限固定失败。仅自有副本规范比较，忽略普通/null原型及对象键顺序。

成功输出仅为深冻结自有小对象：`schema=1`、`binding=matched|unavailable`、`reason`（matched为content-matched，unavailable按下面固定枚举）、`nativeStatus`、`nativeSubmissionId`、`inputEntryId`、`answerEntryId`，四项原ID/状态未知时null；`originalEnvelopeVerified=false`、`authorityVerified=false`、`mayResubmit=false`固定。不返回正文、reason/detail原内容或任何摘要，不以这些字段作为许可。无原Submission为unavailable/record-missing；即使known ID，也不推导未受理。

## 原记录与内容核对

原Submission必须type=input；id、conversationId、requestId分别核expected已知ID、child ID及稳定key。原schema按SDK1.0.1严格逐状态校验：queued无entry/answer/reason/detail；placed只有entry；done有entry和answer；unanswered有非空合法Unicode reason（UTF-8最多4096bytes）、可选entry/detail，无answer。可选字段省略与值为undefined不同，未知字段失败。detail完整安全JSON校验但不输出。合法记录和expected关系不一致固定报`submission-input-conflict`；不合法结构或超限报`submission-observation-invalid`，均不包含原异常/值。

错误分类先核结构，再核语义。Sub.type的已知枚举为input/write；合法write的queued/done/unanswered原状态字段组合可校验，但它与本输入契约冲突，永不matched。Entry的kind/单条model.role结构先核有界非空字符串，随后不是pi.user/user为conflict；此有限结构不声称覆盖其他SDK Message所有字段。record缺失或queued时若附entry，仍做完整安全JSON、narrow字段和数值检查，不核不存在的Sub.entry关系，也不能补正文证据缺口。

所有提供的Entry model.content及Inbox input.content（包括未用于目标核对的来源）都必须符合固定pi-ai1.0.2公开UserInput：string或text/image块数组。text块闭合type=text、text:string及可选textSignature:string；image块闭合type=image、data:string、mimeType:string。未知块/字段、错误类型拒绝，全部仍受同一JSON资源和Unicode限制。只核公开字段形状，不解码图片、解释签名或认证其语义；合法块数组不转换为text，也不替代所选目标的精确原字符串。原68项候选在定点复核发现这个P2前只做非目标safeJSON，未验收为最终；补具体旧源行为反例后再验收。

queued只能从`InboxDoc.items`核精确同Sub.id的item。Inbox必须闭合items数组；每项id为唯一正安全整数，输入mode=steer/followUp、闭合id/mode/content，write项闭合id/mode/entry且entry为安全JSON普通对象。完整items先校验，不接受重复ID。目标mode必须等于whenBusy规范后值（steer对应steer，其余对应followUp）；这只核SDK规范模式，不证明原whenBusy。目标content必须与expected.text逐值同类型相等。无Inbox或目标已消失返回unavailable/inbox-unavailable或queued-item-missing；提供entry不弥补queued记录的内容缺口。

placed/done/unanswered-with-entry只能从精确原Sub.entry读原UserEntry；原entry闭合id/conversationId/kind/model及可选byTaskId，不接受data/head/edits或未登记字段。id与Sub.entry、conversationId与child、kind=pi.user；model恰一个闭合role/content/timestamp，role=user、content精确expected.text、timestamp非负有限数。byTaskId若有仅正安全整数，不能核作Root身份。原entry缺失返回unavailable/entry-unavailable。禁止用编辑后context、贡献消息、另一个可见entry或answer正文替代原input。

unanswered无entry返回unavailable/input-not-retained；reason/detail不恢复正文。非queued时传入的Inbox仍安全完整校验，但不替代原entry。全部数据必须由外层精确原公开读取获得；多次读取的跨commit竞争、错误的读取来源、伪造的完整记录和可信控制面的当前性不由本纯函数证明。

## 后续编排必须保留的未知窗口

正文将原完整请求、唯一child ID、固定native内容/key永久绑定在Root input/checkpoint。task-owned conversation创建与Root checkpoint可同public runtime.commit；handle.submit与保存返回SubID不能同public commit。后续发送前必须先持久化不可重发的提交意图，明确回执之后才进入一次原submit。恢复到已声明提交但缺明确回执时只观察同child/key，不能重提、换key、创建新child或Root；原记录缺失/queued缺item/无entry unanswered保持unknown，需后续显式对账。此文不批准完整phase/wait/cancel/owner方案。

实际执行正文可以使用经资格的公开等待；status/result/watch不能调用submit/wait/resume。waiting.on只允许真实TaskId，不能以ConversationId/SubmissionId或conversation-owned generation伪装直接Root子Task。SDK静止、terminal/completing与物理停止、模型结果和预算结算分别保留。

## 默认验收

仅在既有临时HOME/XDG、断网与子进程守卫下测试自有纯代码，不加载SDK、真实账号或模型。必须覆盖四状态的完整合法原记录、缺失和跨读取缺口、精确ID/key/child/text/mode冲突、字符串与块数组不等价、done answer与input区别、byTaskId不当Root、重复Inbox、无entry unanswered、未知/继承/getter/Proxy/稀疏/循环/Unicode/资源超限；验证零trap/getter、固定错误、输入未冻结/修改、输出不含正文和永远不得重提。root在写入完成后核稳定diff，独立executor复核受影响边界；不勾完整T083/T084或产品gate，不消耗已闭合的kernel7授权。
