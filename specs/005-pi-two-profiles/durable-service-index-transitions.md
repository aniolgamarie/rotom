# 服务索引的有限状态变更

2026-10-07，root 在纯快照及固定账户只读组件已接受之后，冻结磁盘发布前需要的逻辑不变量。本包只新增纯数据模块和默认测试；不实现索引锁、目录创建、持久写者、初始化 issuer、controller、Full 来源解析或数据库。纯合法变更仍不能替代原授权及磁盘来源。须先经独立设计审查，再授权两文件实现。

## 最小职责与接口

新增 `src/agentcfg/pi_durable_service_index_transitions.py`、`tests/test_pi_durable_service_index_transitions.py`。复用原 public `encode_service_index`、`decode_service_index` 和自有纯类型；不调用旧模块私有 helper、不复制 wire schema、不修改旧 codec／readonly／guard。公开两个入口：

- `capture_initial_service_index(snapshot)`：接收 exact 原 `ServiceIndexSnapshot`；经原 public encoder 与 decoder 重新捕获独立合法快照，并要求 generation=1、恰一服务、该服务 reserved、恰一关联且为该服务完整初始关联。返回独立快照，三个权限外观仍为 False。
- `capture_service_index_transition(previous, following, operation)`：operation 为 exact native str，值仅 `reserve-service`、`register-storage`、`associate-instance`。两个输入均为 exact 原 `ServiceIndexSnapshot`，各经原 public encode/decode 验全类型、容量、32768B registration 和16MiB整体上限，再使用独立捕获数据比较。返回本包自有 frozen/slots `ServiceIndexTransition(previous, following, operation, service_id)`，三个权限外观恒 False。

operation 的原类型及允许值在任何原 encoder 调用之前检查；两个 snapshot 的 exact 类型均须在任何原 encoder 调用和属性访问之前检查。初始入口也先检查其 snapshot exact 类型。encode/decode 成功后才比较对象；public constructor、未初始化 slots 或 caller object 均不增加权限。原 encoder 的类型／容量保护不放宽，所有新失败为新自有 `Conflict("Durable服务索引变更无效")`，实际 cause/context None，不修改外来异常、保留回调或输入正文于错误。不承诺 traceback locals 全局清理。

选择验证完整前后快照，而非接受可变 patch 或执行 callback。这样未来写者可将原完整读取、授权绑定、确定操作和全文持久回执分开核验；本包只证明所提供的两份数据满足以下关系，不证明 previous 来自当前磁盘、不阻止磁盘回滚、不做请求幂等 lookup 或业务重试。

## 所有后继共有的不变量

following 的 schema、platform、account_home、account_identity、index_identity 与 previous 完全相同。previous generation 必须小于2**64-1，following generation 必须恰为 previous+1；无 wrap、跳世代、原世代重发或相同快照 bump。服务 ID、初始化请求 ID／identity、首次 binding／instance／state_root／storage_root／deployment 和既有实例映射不能随更新换掉。

每次只进行以下一种精确变更；不允许组合增加服务并绑定旧服务别名，也不允许顺便改变另一条 registration。旧 service 和 association 的保留按捕获后的完整 native 数据逐项核对，不能只比 service_id、对象身份或摘要。数组输入排序已由原 codec 规范，调用者的原 dict/list 不被保留。每种变更最终恰一个 affected service_id；它只是元数据，用于未来私有写者与原 grant 比对，不能从这个返回值创建 grant。

## reserve-service

following 恰比 previous 多一个 ServiceIndexEntry，所有旧 entry 全字段不变。新 entry 的 registration 必须为 reserved，storage_identity=None；初始化请求 ID 和 service ID 均由原 codec 验唯一，initialization_identity 合法。following 恰多一个 association，所有旧 association 完整不变；新 association 必须指向新 service，binding／instance／state_root 恰与其完整初始关联一致。affected service_id 是这条新服务。

新的 service/association 总数仍遵守64／512上限；满容量拒绝，不挤掉旧行。既有 association 改指向、旧初始化请求换新 ID、重新 reserved 已登记服务，或给新服务同时加多个 alias 均不属于此操作。相同原请求的只读查找在本包之外；即便相同内容，也不能调用 transition 生成另一次写回或 fresh storage 许可。

## register-storage

服务和 association 数量／ID集合完全相同，所有 association 全字段不变。恰一 entry 的 registration 从 reserved 改为 registered，取得原 schema 允许的非空 StorageIdentity；十三字段中除 stage 与 storage_identity 外的十一字段，以及该 entry 的 initialization_request_id／initialization_identity 完全不变。其余所有 entry 完整不变。affected service_id 是这条服务。

这里只验证 storage_identity 的纯值及与原记录的关系；真实 storage 目录、原 controller acquired／fd3／锁与完整持久回执另核。registered→registered、registered→reserved、原同态无变化、改 storage root／首次 deployment、两个服务同时登记或顺便增加 alias 均拒绝。失败／丢 ACK 不能依此操作重写未知数据。

## associate-instance

所有 entry 全字段及服务集合完全不变。following 恰多一个 association，所有旧 association 全字段不变；新增项指向 previous 已存在的 service。affected service_id 是它指向的原 service。原 codec 验绑定为 pi-full、canonical 三项路径／域分离 association_id、唯一键、引用及每条初始关联保留。

reserved 与 registered 服务都可以形成这种纯数据关系，因为该函数不证明服务 ready；产品是否允许新增关联必须由另一次显式原服务授权决定。已有键重指向、新服务、删除旧别名、增加两个别名、修改 entry 或世代以外字段均拒绝。profile/provider/runtime替换不能用 association 操作删除首次登记、reset预算或生成空库。

## 默认验证及后续发布

仅临时默认纯 DTO／bytes／虚构物理元数据，零文件／锁／proc／线程／subprocess／SDK／Node／模型／网络。所有旧测试与原守卫保持。合法控制包括初始 reserved1、两个以上旧服务的 reserve、reserved→registered、向两种stage服务加一个alias；断言独立捕获、原输入未修改、三个外观False及affected原ID。正例的预期差量由测试独立构造，不调用本包私有 helper。

负例分别改一个不变量：初始世代／数量／stage／多alias；未知operation／外来str及外来snapshot先拒零encoder；错account/index／跳世代／uint64溢出；删除／替换旧entry、初始化身份／首次metadata变化；reserve不加初始关联、多alias、重用请求或达到上限；register无变化／同态／逆向／两服务变化／改immutable／改association；associate删旧／重指向／两个新增／改entry。原 codec 会先拒绝的错wire场景须标明其层，不当作本包关系逻辑的独立反例。forged exact slots／nested foreign hooks按旧 encoder边界和新类型切点验证，fresh异常链与外来异常保持要有直接断言。

默认验收同次新suite、旧service_index及registration suites；未实现的collection error只记未实现，若新反例揭示旧已存在组件的实际失败，由root决定有限修复范围和同一最终套件red→green。稳定后root验收关键关系，独立executor审最终diff；不因为纯默认通过就开始目录／flock／进程或所谓真实初始化。

后续磁盘写者仍需独立冻结固定index.lock的原对象、首次账户basename absence与受控mkdir、原授权消费和controller fd3确认、原完整读取与expected文件身份、发布可能已发生时的unknown、fsync／readback及原私有ACK。本包不为这些未闭合接缝提供 fake capability。d61799三场仍待该组独立授权，旧八场不复用；正式7/100、产品gate、严格计量前AUTO OFF保持。
