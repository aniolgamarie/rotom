# 私有 risk-review 协议与传输组件（T049/T052 离线阶段）

本包提供 `parseReviewResponse`、`createSingleRequestFetch`、`createReviewRequestValidator`、`createReviewAttempt`、`createIsolatedReviewSdk`和`createReviewHeaders`。没有新增第三方依赖或配置启用入口；import/创建组件均不加载SDK。显式SDK适配器首次stream才加载caller指定安装切片的公开SDK入口，平台fetch仍须由受信控制面提供。Base 声明、正式锁、运行文件清单未改变；不能据此启用自动审批或完成 US3。

raw 是最多8192 UTF-8字节的单个平坦JSON对象，恰有七个字段：schema_version=1（数字token必须为整数literal `1`，不接受小数或指数写法）、request_id（32小写hex）、operation_digest/context_digest/reviewer_identity（各64小写hex）、decision、reason_code。expectedBinding 由可信caller提供，恰为四个绑定字段，全部逐字段匹配；模型不能添加source、human、自报授权、自由文本理由或未知字段。

固定决定/原因对应：

- allow：authorized-in-scope。
- ask：ambiguous-intent、unverifiable-input、needs-human。
- deny：outside-user-scope、destructive-change、untrusted-authorization。

专用有界扫描器拒绝重复键（包括转义后重复）、嵌套、数组、非法unicode、NaN、bool版本、围栏/前后文本、超限和错绑定。只对单个string token使用JSON.parse。失败固定错误 `PI_RISK_REVIEW_PROTOCOL_INVALID`，不带原文、自由理由或底层异常。expectedBinding 必须是普通闭合数据对象，不调用getter/Proxy；返回复制且冻结的八字段候选：七个wire字段加控制端固定source="reviewer"，不修改caller输入。

source="reviewer"仅标明候选通过wire校验，不证明真实调用来源或其决定正确。真实用户来源、hard-policy/角色上限、绑定仍current及许可一次消费必须由未来可信编排负责；下述单attempt传输只接收这些受信事实并实现本阶段时限/发送边界。解析结果不是 ApprovalDecision、permit、执行票据或人类授权，不能直接执行、释放Writer或自动放行。

纯模块默认验证入口为仓库隔离 runner：

```text
node scripts/test-pi-mock.mjs agents/pi/packages/risk-review/tests/protocol.test.ts
```

测试使用临时HOME、网络阻断和假进程，只解析合成数据，不启动SDK/Pi/Codex/模型/第三方宿主。package的test脚本引用同一runner。真实传输/评测和启用态仍 not-run；后续提供者协议差异或许可/锁边界须由主代理决定，不能放宽parser换取兼容。

## 固定SDK接缝与最终请求校验

固定Pi AI 1.0.2公开`@earendil-works/pi-ai/api/openai-completions`提供`streamSimple`，公开`normalizeContext`构造transcript。当前默认测试用对应fake，不导入真实SDK。直接provider入口避免Models的credential-store/refresh路径；实际认证仅在未来获准入口由SecretStore解析，key只放私密transport和HTTP Authorization，不进入模型输入、通用identity、metadata或异常。

SDK/OpenAI 7.19.0源码证据表明默认stream缺全程deadline/字节上限，且显式key不阻止OPENAI_CUSTOM_HEADERS/ORG/PROJECT参与headers。受信适配器须固定模型/路线、干净元数据headers与key；不能从ambient env或SDK最后的headers反向产生expectedHeaders。发送前validator核对exact endpoint、六字段body和完整headers；未知headers、组织/项目/cookie、授权或平台metadata覆盖均零send。全部JSON层拒重复键及非法Unicode；max_tokens仅接受canonical正整数且不超过配置cap，保留SDK合法context clamp。

最终fetch校验不能保护SDK在fetch前的日志。SDK还读OPENAI_LOG、ADMIN_KEY、WEBHOOK_SECRET等ambient项；debug日志可能在请求校验前记录环境自定义headers。新的单Worker桥固定env仅OPENAI_LOG=off，stdout/stderr只drain/drop，SDK初始化发生于该环境内；不读取/复制宿主环境、不临时改process.env、不monkey patch SDK。测试中SDK包仍全为自有fake，官方SDK初始化及隐私动态行为尚未验证。

wire-fetch首次调用即耗尽尝试，实际send最多1，强制manual redirect并拒3xx或redirected=true的2xx；HTTP错误不读取自由错误正文。Response body按需逐块核额、最多配置字节，stall/abort/expired和迟到Response均关闭原body而不无限等待cleanup。response_bytes仅为接受并交给SDK的字节，不代表远端响应总量或计费。平台send须遵守manual、无内部retry；该接缝不能观察代理/远端隐藏的hop或收费。

## 单attempt生命周期与未完成边界

createReviewAttempt构造时只捕获有界固定配置，run首次才处理传输；同一handle反复run复用原promise/终态。Base、关闭态、硬拒绝、角色ceiling、必须人工及非自动风险均零SDK/send。资格来自受信prepare，不接受模型自授；当前完整产品资格/策略接线仍待T051。此模块不是全局request registry，未来必须由activation/session/operation控制器复用同一attempt，容量有界且不淘汰旧ID后重发。构造后尚未run的handle持有外部abort监听器，须由该控制器有界保留，并在弃置/退役时abort；run结束或signal abort后移除监听器。

wall deadline与首次run固定的monotonic ceiling同时检查，墙钟回退不能延长attempt；watchdog覆盖fetch/body/SDK iterator stall。current查询必须严格true，取消/过期/漂移后候选为空，实际已发送的1次不会归零。固定SDK options无tools、retry/fallback、routing/sampling覆盖或任意onPayload/onResponse，仅内部onProviderStreamEvent读取必要metadata；没有工具dispatch或执行回调。异常固定分类，不保留原文。

SDK message.model只是请求模型拷贝，不能当远端证明；raw callback需来自已有本地send且已交付body的该attempt，并逐chunk核对model。remote_model_verified仅表示Provider返回的model字段与冻结请求一致，不证明服务商内部实际权重/路由。缺usage、非法计数和SDK初始0仍为unknown；合法累计usage仅记reported，缓存计数缺失为null，SDK本地cost被忽略。Provider自报用量不是实际账单，费用/预留仍需冻结价格与可信账本结算。

snapshot只含绑定、路线/价格identity、分类、计数、reported/unknown usage、有界事件和时序，不含prompt、key或其散列。已取消后的迟到usage可更新最小记录，不能更新决定；外层须查询最新snapshot，不能仅保存早期取消回执后把未知费用丢掉。elapsed/model_wait/local为单调区间，model_wait表示等待SDK流（包括网络/SDK异步处理），不声称是服务商纯计算时间；时钟异常保留null。正常终态主动关闭残余body不改变已有valid候选。

上述结果仍为候选，父控制面在issue/consume前必须复核真实用户、hard-policy/角色、完整PreparedOperation、当前epoch、授权路线及deadline，并用原账本一次消费。无UI ask保持blocked、deny不经等价改写翻案；这些决定/票据接线、真实SDK适配/加载、持久预算账本、授权质量/性能和产品启用仍未完成。本包永不签product gate，也不释放Writer。

## 单Worker SDK桥与验证范围

createIsolatedReviewSdk({anchor,workerFactory?})返回sdk、close和只读snapshot。anchor必须是受信安装收据所属slice/package.json的绝对路径，不能是任意SDK子包自己的package.json。工厂/normalize零Worker/SDK；首次stream创建唯一Worker，重复stream失败且不换Worker。context为父侧私有opaque对象，child才用公开normalizeContext构造SDK transcript。API key和固定context/options只经私密run消息交给受信SDK，不放入模型输入、workerData、通用元数据或错误。

Worker通过公开import.meta.resolve(specifier,anchorURL)定位PiAI provider与transcript导出；先验证两个file URL均在当前slice、根/anchor/目标身份未变，再import，缺包不得借祖先依赖。完整包版本、source digest和传递闭包的真实性仍由安装收据caller保证，本模块的路径/stat检查不能自证发行物。Node v24.14.0的第二parentURL参数是公开但非标准接口，必须显式固定--experimental-import-meta-resolve；Worker只用该flag和空argv，不继承宿主loader/flags。未来版本不兼容须重新验证并失败关闭，不能退回require条件或私有dist路径。

SDK custom fetch通过有界闭合IPC回父侧原fetch接缝，Response.body通过公开ReadableStream transfer交付，不整段buffer、不回退网络fetch。SDK首fetch耗尽尝试，metadata逐条await seq ack背压；仅最小model/usage及一个终态回传，中间delta、thinking正文、SDK默认usage/cost丢弃。snapshot.fetch_requests表示进入父fetch接缝的次数；createReviewAttempt.snapshot().requests才是本地平台send调用数，两者在最终validator拒绝时可分别为1和0，都不证明远端实际收费次数。

取消立即使迭代不可用，并开始自有Worker终止；正常done后的cleanup不改成失败，非法二次请求等失败仍sticky。close/iterator.return等待terminate承诺，实际worker_terminated为独立事实；失败/未知终止不冒充已终止，也不能用于释放预算/Writer。确认前保留固定error捕获和stdio丢弃，避免迟到error抛入父控制面；确认后释放监听器。延迟用量可能在线程终止时丢失，已送请求保留、缺用量仍unknown，不能因此退费或补0。

默认七模块目前367项通过：243协议/传输、47fake Worker/entry、13组合用例、64header基线。组合用例中的9项运行真实自有Node Worker，但只加载临时自有import-only假SDK；四项资格负控零Worker。环境污染、实际跨线程stream、父校验、响应上限、取消计数、metadata背压与祖先借包均有事实证据，没有官方SDK/Pi/Codex/账号/HTTP/模型调用。V8 resourceLimits不是外部内存硬上限，Worker也不是文件/网络OS sandbox。

createReviewHeaders只接受显式受信Linux x64、内核release、Node v24.14.0、OpenAI SDK 7.19.0、timeoutMs及私密key，生成复制冻结的12字段基线；不读取环境、SDK请求或认证库。Pi UA不含Pi版本，SDK timeout毫秒截断为秒。最长8192字节ASCII key加7字节Bearer前缀后为8199；请求与IPC仅Authorization采用此上限，其他header仍8192，总量仍各层有界。最长key已通过header/fetch及真实自有Worker组合；多一字节、其他header超限及末尾CR/LF分别拒绝。未来官方SDK形状有变化必须重新验证，不能自动扩展allowlist。

Node还会从父线程克隆setEnvironmentData的数据；env选项不覆盖此通道，公开Worker options没有逐Worker禁用它的选项。固定依赖与Base代码的静态扫描未发现可执行get/setEnvironmentData引用，只能记静态缺引用，不能证明父map为空或通用凭据隔离。受信固定SDK的请求形状/日志边界、真实初始化、认证路线和完整产品privacy gate必须分别核验；需要更强进程隔离时使用受管独立进程，不通过修改宿主全局map或私有Worker接口清除。
