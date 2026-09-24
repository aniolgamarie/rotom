# 配置参考

[文档首页](../README.md) · [上手指南](getting-started.md) · [机器Schema](../config.schema.json)

当前配置schemaVersion为7，数据库schema为3，两者独立。配置路径优先使用`PI_TASK_KEEPER_CONFIG`，否则为`$PI_CODING_AGENT_DIR/task-keeper.json`，再否则为`~/.pi/agent/task-keeper.json`。相对路径与~按实现规则解析；对执行文件、状态目录和项目路径优先使用明确的绝对路径。

JSON输入与默认配置合并，不必抄全量Schema。数组通常整体替换；分类规则有下面专门的优先级。示例：[普通会话](examples/ordinary.json)、[受管演示](examples/managed-demo.json)。它们不含凭证；受管示例须替换模型和Node路径，并配合演示项目使用。

## 开关与角色

| 字段 | 默认/规则 |
|---|---|
| enabled | false，总开关 |
| features.interactiveRecovery | false，普通会话恢复 |
| features.managedWorkflows | false，inspect/fix、B和定时 |
| features.crossProviderFailover | false，实际恢复中的可用性切换 |
| features.semanticReplanning | 默认不开启，有限诊断步骤 |
| usage.enabled | 包启用后默认true，独立于恢复/选模/B |
| secondOpinion.enabled | false，新任务默认，可被用户任务级开关覆盖 |
| modelPolicy.automaticSelection | false，可显式--auto-model启用 |

routes以本地路线ID映射provider、model、accountBinding、quotaGroup、transportDomain、network和protected。accountBinding当前只支持`provider:<provider-id>`，由Pi解析账号；同一provider不在这里新增多账号连接器。

allowedRoutes限制全局路线，projectRouteApprovals用repository ID或显式`*`允许项目使用。角色scout/worker/reviewer分别绑定route及profileRef。profile有tools、requiredCapabilities、timeoutMs、maxModelTurns、toolTimeoutMs、thinking及可选minimumContextTokens。受管scout/reviewer使用read/grep/find/ls，worker再加write/edit；这些用户配置的工具名由adapter映射到受控工具。

当前受管网络仅认证direct；其他网络配置即使结构合法也不等于可以执行。同一账号的共享额度需要将相关route绑定到同一quotaGroup；普通会话也需共享时再设置对应quotaBindings。示例中的两个池不自动证明供应商有两份独立额度。价格或模型名不能代替能力认证。普通恢复`primaryRoute=null`时使用Pi当前模型，已有明确primaryRoute则保留该绑定。

## 分层恢复

`recovery.policies.defaults` → `providers.<provider>` → `providers.<provider>.models.<model>`覆盖标量和退避数组。分类规则按模型→供应商→全局、层内声明顺序检查；正确性约束仍优先于自定义临时分类。

| 字段 | 新策略默认 |
|---|---|
| quotaBackoff | 1m、5m、15m、30m、1h |
| repeatLast | true，重复最后一段；false用尽后阻塞 |
| maxLocalInterval | 1h，只限制本地退避含jitter |
| positiveJitterRatio | 0.1，范围0–1 |
| maxWait | 24h；null允许持续等待临时配额，仍受其他期限限制 |
| requestTimeout | 2m，单次请求，含完整响应流 |
| maxNetworkAttempts | 2；0不自动重试网络错误 |
| unknownReset | pause；可显式configured-backoff |
| respectRetryAfter | 只能为true |

```json
{"recovery":{"policies":{"providers":{"YOUR_PROVIDER":{"quotaBackoff":["1m","5m","30m","1h"],"maxLocalInterval":"1h","maxWait":"24h","models":{"YOUR_MODEL":{"requestTimeout":"5m"}}}}}}}
```

duration仅接受正整数ms/s/m/h/d，结果1–2147483647ms。尾值若为2h，maxLocalInterval也须至少2h。服务端要求的等待不被本地上限截短。requestTimeout覆盖受管worker/B/压缩的每次HTTP；工具执行不计该计时，整个child仍有profile总时限，任务deadline也可能更早到期。

quotaBindings条目使用provider、可选model、quotaGroup和可选transportDomain。模型精确匹配优先；它定义明确的共享关系，不由同名模型推断跨服务共享配额。未绑定的当前模型按provider认证引用+model建立独立配额域。

旧route/quota配置可能带recoveryPolicy指向`recovery.policies.legacy`；它保留quotaGroups旧曲线、recovery.maxWaitMs/requestTimeoutMs等，再应用provider/model覆盖。根目录的旧兼容config.example.json展示了这种引用；新配置可像受管示例一样显式给出policies，采用新默认值。

启用lightCanaryEnabled后允许小型无任务代码探测，但成功仍须尝试原请求，不能当成任务成功。恢复链recovery.chain使用唯一stage ID、route及bounded/forever等待；仅受管恢复链可以跨路线，备胎需受保护并继续共享原预算。

## 检查、工作区和预算

verificationBindings的每项提供executable、args、environment、timeoutMs、kind、parser、minimumTests与inputs。支持build/tests及exit-code/json/tap解析。测试须有非零真实计数；JSON的典型结果为：

```json
{"tests":2,"passed":1,"failed":1,"skipped":0,"failureCategory":"implementation"}
```

只有可信的implementation分类允许相应有限自动修复。inputs列举工作树内可变的验收逻辑及传递依赖，不能省略外部脚本；它不等于全部被测源码列表。内联Node检查逻辑按固定参数处理。命令须真实验证用户目标，不能用总是成功的占位程序替代。

workflow.requiredChecks中的根required不能被模型删减；optionalChecks只能引用可信检查，allowPartial默认false，risk默认unknown，reuseReviews可关闭审查复用。检查逻辑变化需要显式approve-checks，模型绑定变化使用refresh-bindings/approve-bindings流程，普通resume不代替审批。

| 限额字段 | 默认 |
|---|---:|
| limits.activeJobsPerRepository / activeChildrenPerHost | 1 / 3 |
| limits.parallelReaders / writersPerJob / heavyVerifiersPerHost | 2 / 1 / 1 |
| limits.semanticAttemptsPerImplementationTask / semanticReplansPerTask | 3 / 1 |
| limits.dispatchedStepsPerJob / jobsPerWorkScope | 16 / 16 |
| limits.semanticAttemptsPerWorkScope / dispatchedStepsPerWorkScope | 3 / 16 |
| budget.protectedAttemptsPerWorkScope / backupAttemptsPerIncident | 12 / 4 |

writersPerJob=0禁止受管写任务，正值仍保持单writer策略。预算约束受保护请求，包含原生重试和受控辅助调用，不是货币硬上限。示例使用protected=true；不要把普通主会话恢复理解成主会话严格请求预算。minimumRequiredStageAttemptReserves保留必要审查请求余量，未知请求占用不自动退回。

sharedMutableDirectories可声明检查的外部共享输出根（绝对路径且已存在）；别名指向同一目录时共同互斥。这不授权子模型读写外部目录，也不协调插件外程序。scheduling.agingMs默认60000，priorities.inspect/fix默认0，范围0–100，只承诺同父就绪队列的有限公平。

## 第二视角与定时选模

secondOpinion包含model、profileRef、reviewTask、focus、maxExchanges。model可为已授权路线ID或provider/model对象；缺省采用reviewer。reviewTask是可信文本，不加载文件/模板引用。maxExchanges默认2，允许0–16，实际仍受更早到达的原预算/步骤限制；0只初审，不回应修订。

timePolicy包含timezone、windows、admissionBoundary和missed。timezone为IANA时区，默认宿主时区，在提交时固定。windows默认空（全天），每项为days（1–7，周一为1）、start/end（HH:mm），跨午夜按开始日所属星期。admissionBoundary只支持task-start，missed只支持pause。没有任何deadline前的窗口会拒绝启动。

modelPolicy包含candidates、defaultPreference、preferByTime、ranking、history。候选使用路线ID或provider/model对象。时段规则的priority降序、声明顺序打破平局，取第一条匹配规则的orderedCandidates。ranking可为ordered或history-cost；选择后记录候选拒绝原因、时间、样本和报价。默认不开启自动选择。

history默认30天、minimumVerifiedTasks=5、minimumSuccessRate=0.8。比较纳入已终结失败/取消投入；未知费用、不同币种、低样本或不可比合同会解释回退。已知低于质量门槛的候选不能靠回退重新放行。当前任务未实测输入时只采用唯一、完整的历史参考输入档，不能伪称知道当前任务复杂度。

## 用量与价格

usage.defaultRangeDays默认30，按任务开始时间过滤；不自动清理历史。priceBooks每项有id/provider/model/accountPlanRef/currency/source/effectiveFrom/effectiveUntil/timing/timezone/rates/windows。时间须含时区；timing为request-start、response-end或unknown。rates为每百万token的十进制字符串或null，四桶为input/output/cacheRead/cacheWrite。重叠版本或费率窗口拒绝，不自动抓价和换汇。

```json
{"usage":{"accountPlans":[{"provider":"YOUR_PROVIDER","model":"YOUR_MODEL","accountPlanRef":"standard"}],"priceBooks":[{"id":"standard-2027","provider":"YOUR_PROVIDER","model":"YOUR_MODEL","accountPlanRef":"standard","currency":"CNY","source":"user-maintained example, replace with actual quote","effectiveFrom":"2027-01-01T00:00:00+08:00","effectiveUntil":null,"timing":"request-start","timezone":"Asia/Shanghai","rates":{"input":"1","output":"2","cacheRead":"0.1","cacheWrite":"1"},"windows":[]}]}}
```

上述费率是演示数值，不是供应商报价。accountPlans按模型覆盖provider默认，重复同一匹配键拒绝。未绑定为null；明确套餐缺报价时费用unknown，不用通用目录价冒充套餐价。每个generation保留原套餐引用和报价，历史重估另列。

没有适用的通用价目时保留已观察SDK目录估算；已知不发送才可确认零消耗。SDK缺省零和只知最后一次重试usage不能推定免费。统计开关或价格变化不修改执行授权。

## 项目限制、证据与状态

项目.pi/task-keeper.json仅支持enabled/features/allowedRoutes/limits/budget/workflow/evidence的收紧，不改用户账号、模型绑定、验证命令、价格、时间窗口或选择策略。项目没有deadline字段，deadline通过用户任务选项指定。

evidence.packetByteBudget默认65536 UTF-8字节，项目可收紧；必要事实放不下时阻止发送，不截掉失败。可选telemetryBindings读取用户0600观测文件，匹配账号、桶、来源、时效与最低余量；读取成功不等于服务端预留额度。

storage.path默认`~/.local/state/pi-task-keeper/runtime.db`，状态根0700、文件0600。状态必须在源项目外；更改文件名不产生独立预算。升级/回退见[状态维护](state-maintenance.md)。

v6迁移预览：`node --experimental-strip-types scripts/config-preview.ts /absolute/config.json`。它不覆盖文件。移除旧cascade启用项，保留原数据；新功能不从旧历史推断授权。全部字段的结构限制以[Schema](../config.schema.json)及实际doctor/准入结果为准。
