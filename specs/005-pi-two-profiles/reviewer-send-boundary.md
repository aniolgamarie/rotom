# Reviewer 发送提交接线约束

日期：2026-10-06。这是 T052 产品 factory 尚未接线部分的约束。自有可选发送gate已完成离线组件验收，账户ticket/RPC与Host factory仍未组合，未启用reviewer。transport/wire-fetch的计数表示进入注入send函数的本地次数；它不证明Provider网络跳数、重试或真实账单。

## 持久提交与本地调用分开

顺序必须为持久 reserve/claim → 原 SDK attempt → 最终 wire 验证 → 原 authority/scope/current 的持久 commit_send → 唯一平台发送 → facts/finish。不能把异步 commit RPC 直接藏在现有 send 回调中，再把 wire-fetch 的回调进入计数称为实际平台调用：commit 若失败，外层已经记1，但内层平台 fetch 尚未被调用。

后续实现需要在最终 wire 验证之后、平台调用计数之前设置显式私有提交 gate。它只持有原控制 ticket 的闭包，不取得认证、prompt、工具执行回调或模型选择的权限字段；只认可 exact true 的确认成功。第一次 fetch attempt 已烧掉，gate 失败、回执未知或取消后都不允许 SDK 第二次发送、换路线或重新 commit。等待 gate 不持有服务/账户锁跨网络或 SDK await。

gate 等待期间必须持续观察取消、双时钟和配置，等待结束再次核验。原请求 body 必须为已验证的不可变字符串；headers 等可变对象须在私有内存捕获后重新核验发送副本，防止 await 前后漂移。不能只 shallow-copy init 然后假定原 Headers 未变；不记录正文、认证或其 hash。静态接缝审查确认现有validator只返回boolean，不导出规范化捕获；它只接受原 method/headers/body/可选原SDK signal，不接受 wrapper 的 redirect。应在私有捕获副本复核后，才添加 redirect=manual 与合并signal，不能把出站wrapper init交给原严格validator。具体捕获和 revalidation 接口仍须在实现阶段审查。

## 失回执与保守结算

原持久账本 commit_send 会把 requests 从0改为unknown，并保留预留。即使 gate 成功后本地取消使平台调用数为0，持久 committed 行也不能改成 not-sent 或释放预留。当前 ledger 明确拒绝 committed 与 requests=0 的组合；保留这个不变量，不为适配新 gate 削弱它。

拥有者须独立记录“是否尝试过 gate／是否收到成功回执／实际进入平台函数次数”，再只读核对原账本。确认仍 reserved 且实际零调用才可 finish requests=0；commit 已持久或回执未知时保守报告 requests=null，未完成终止/计量证据仍保留预留和意图锁。T 的本地 not-sent usage 投影不能直接覆盖 committed 账户事实。已观察平台调用1时才可 mark_sent；mark_sent/finish 失回执只对账，不重新发请求或签许可。

## 验收目标

默认反例必须涵盖 invalid final wire 零 gate、hard/human/input-unqualified 零 gate、authority/scope 在提交前失效、写前失败、写后失回执、gate 永不结束但取消及时结束、gate 回执后取消、headers 等待期间变化、第二 fetch attempt、晚到成功/拒绝、平台同步抛错和 facts 回执丢失。断言同时检查实际平台函数计数、持久 send_state/requests/预留/意图锁及原许可零签发，不能用同一生产方法反向生成 oracle。

## 当前组件证据

`beforeSend`仅由可信factory闭包提供，不收请求参数。wire-fetch先验证原wire，捕获私有不可变method/body string/规范化header strings与原SDK signal，复核副本后才调用一次gate。只接受exact true或原生Promise的exact true回执；thenable/proxy和Promise自有constructor固定拒绝，不读其getter。等待期间及回执后核验取消/current/期限；迟到ack只更新事实，不继续发送。最终再核验原schema后才加wrapper拥有的redirect=manual与合并signal。

gated snapshot分别保留gate_attempted、gate_acknowledged与requests；平台同步抛错仍为一次本地入口。transport在gate尝试之后即使本地requests=0，也保持usage unknown/null，不能把账户committed/未知事实写成零费用。无gate的既有snapshot形状保持。gate失败与未知没有账户对账能力；未来factory仍必须保留原ticket、只读核对持久状态，再按本页约束finish，不能把fake ack当真实提交。

新增44项加wire/transport/shared/request关联302项在一次默认guarded运行中346通过；稳定三文件独立审查未发现剩余P1/P2。未采集改前行为红，首次误写测试路径的ENOENT只是命令错误。实际测试仅假SDK/假发送/假提交回调，未访问账户、官方SDK或模型；证据归档`risk-send-commit-gate`。持久authority/scope失效与提交回执未知的组合、实际Node/Python RPC和产品factory仍待验收，正式任务7/100。

官方共享SDK11 review01因transport/wire-fetch来源变化失效，新review02已静态重准备。该探针不传gate，仅验证完整共享Model与请求/SSE形状，不覆盖此提交gate。受影响来源的历史通过不能视为新gate、账户组合或完整Host factory通过。

## 已验收的只读账户观察

账户`get`与`for_settlement().get`仍走原updating/ready持久操作流程，不能把它们称为纯读取。新增显式`ReviewerAccountLedger.observe(operation_id)`在原账户共享短锁内要求ready sentinel、登记根/成员/物理身份及本次读取的原ledger字节与stat绑定完整一致，只返回原行副本；不构造ledger、不写入、不修复或初始化。它不复查live authority/scope，过期或退役不会抹掉原事实，也不会取得发送或结算能力。updating/部分状态仍拒绝，不能从失败读取推断零请求。

新增23项与账户/authority/scope关联124项在一次默认guarded运行中147通过；独立稳定审查无剩余P1/P2。实际提交写前异常保持ready/reserved可观察，账本写后失回执保留updating/committed unknown并拒绝观察，预算和请求事实不清零。21项改前缺接口行为红已留存，另两项写切点用例是实现后增加。材料仅真实临时文件与合成账户；原Decision ticket绑定比较、在观察前关闭ticket以拒绝迟到commit、gate报告归并及跨语言产品factory仍未组合。证据归档`risk-account-observation`，正式任务仍7/100。

## 已验收的原ticket传输结束归并

`ReviewerDecisionControl.conclude_transport`只接受封闭五字段outcome/platform_requests/response/gate_attempted/gate_acknowledged，调用由可信私有控制面承担。platform_requests为精确整数0/1、标志为精确bool；来源、模型或执行权限不能从报告选择。合格报告在原mutex内先不可逆结束原ticket并保存仅次数/标志，再observe原operation ID，精确比较原binding、session/intent scope、attempt已claim及非终态。原ticket关闭后，迟到的commit_send/mark_sent/conclude均不能续用。

reserved只有确证本地0且未获成功ack才能finish requests=0；committed与本地0只保留requests=null及预留，不能改not-sent。已观察本地1时先mark_sent，随后finish requests=1；valid还须原gate attempted/acknowledged均true及原fresh资格才可签许可。绑定/事实矛盾固定拒绝、不写原行。observe/mark_sent/finish失回执均烧ticket、撤原Admission，固定安全reconciliation unknown；不重读修复、补发、清预留或再次签发。原conclude行为保持，新入口保留已观察非valid取消/超时/传输失败事实，候选valid在fresh失效时discarded。

真实临时authority/scope_required账户/原Admission加合成私有平台事实的七模块一次252通过（59新增、193关联），缺API改前1项失败与完整日志保留，稳定独立审查未发现剩余P1/P2，归档`risk-transport-settlement/`。它仍不证明gate/计数caller provenance或实际平台流量；自动策略、bridge permit消费、Node/Python私有RPC、canonical Host factory与进程域终止仍未组合。原观察组件段落中的“待组合”是其历史边界，本节闭合仅Python内部原ticket/持久事实归并。

实际进程桥把child SDK fetch作为私有frame送回父侧，由父侧`createReviewAttempt`的wire.fetch等待beforeSend后才进入注入平台send。因此gate和原ticket应保持父侧私有闭包，不能加入workerData/run帧。process.fetch_requests记更早的child fetch帧，wire.requests记父平台函数入口，两者不能互换。新的共享Model/process/gate默认组合六模块一次202通过（21新增、181关联），仅自有PassThrough/EventEmitter假进程及假SDK，生产源码零修改；稳定新测试与11受测源码SHA复核无P1/P2，归档`risk-shared-process-gate/`。它覆盖失败/取消gate时child fetch1而父平台0、ack后失效、晚到ack、平台同步抛错1、第二fetch阻断及封闭run无gate/ticket；fake terminate true不证明OS终止，仍未组合Python原ticket/RPC或启用factory。

## 已验收的父侧结算报告投影

`compileReviewTransportSettlement`只把可信父控制器保存的最终快照编译成Python入口的五字段报告，不认证caller或快照。原生plain data与own descriptors逐项捕获，Proxy/getter/未知字段拒绝；原四字段binding与expected binding精确匹配。schema1、settled、已知outcome、本地平台计数标签及0/1次数须成立，wire.requests须一致。既有零调用快照无gate两字段时投影false；有时必须成对精确bool，ack不能先于attempt。晚到ack且平台0仍为0，不推导committed、not-sent或费用。

候选valid须原八字段、source=reviewer；捕获primitive后只选原七wire字段序列化，再通过原协议parser核验。五字段response不含source、ticket、permit、prompt、key、模型或usage；异常只输出固定错误。非valid候选必须null。新68与关联158在一次四模块guarded默认运行226通过，稳定两文件独立审查无P1/P2，归档`risk-transport-projection/`。新组件临时拒绝stub的1项行为红明确单列，未称旧T缺陷；实际positive仅自有fake SDK/send。父侧实际attempt身份、原ticket私有保存、账户observe、Node/Python通道与factory仍由后续组合承担。

原Decision许可到原File/Shell bridge的消费接缝已另以九模块一次360项与稳定审查验收，见[reviewer-bridge-permit.md](reviewer-bridge-permit.md)。其可选native control注入统一原service mutex与canonical Admission，只对核对后的原scoped row调用原bridge.issue固定reviewer来源。未知签发不变成discarded，不删除未知映射或重签；requires_human生产默认仍true。上述早期章节中“bridge permit消费未组合”为当时阶段边界；当前闭合的是Python内部原对象组合，真实自动策略/Node-Python RPC/factory仍未闭合。
