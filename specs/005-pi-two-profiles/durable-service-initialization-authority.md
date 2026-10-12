# 首次 Durable 初始化的授权与生产来源候选

2026-10-07，root 根据15输入静态收据 `7e3948581b550f98d2617f183373088ca6f2cd71bcfdb6c05cd87bb4d6986e8e` 以及已接受 service record／owner lifecycle 设计整理本候选。这里决定授权与控制进程的方向，并列出必须闭合的接缝；尚未授权初始化 IO、controller／server 代码包、Full 声明、实际宿主或开库。编解码、摘要、UID、public constructor、文件内容和 client 布尔值都不能独自签发初始化权限。

## 现有许可的适用范围

普通 file／Shell permit 的 context 没有 task_id／instance_id／service_id。其 human 来源是可信 UI 适配器已得到原 `ctx.ui.confirm` 的严格 true；server 的 `source=human` 是该信任协议的标签，不是独立真人身份验证。supervisor 的 manager 身份也不只靠 UID：所选源码验证随机 capability、活动 lease、grant generation 和原 manager 存活。但通道认证不能代替确认，同一个 request_id 也不是初始化的一次消费状态。

因此首次 Durable 创建使用专门操作种类 `durable-service-initialize`，不把 ordinary_admission 的 operation/context 拼字段后当新 grant，不借 deterministic-policy、reviewer、工具结果、用户旧批准或管理员 UID 跳过本操作的明确授权。准备／签发／消费的原私有记录属于同一 manager 控制实例，与普通文件 permit 的私有表分开；它复用控制通道的认证语义，而不复用不完整的普通操作上下文。

## 原请求与原确认

第一条需要持久服务的 Full 显式请求先生成私有 draft。draft 固定请求 ID、canonical 任务输入及摘要、只读业务根／工具集合、模型路线和有界预算、产物位置、当前策略／取消 generation、有效期限，以及下述完整登记引用。它不启动服务、开库或调用模型，不把“看到 storage 不存在”当初始化授权。status／result／watch／普通启动和诊断不能生成 draft 或触发此操作。

确认页面由自有可信适配器展示本次将创建的持久服务、任务和读写边界，并绑定 draft 的原 ID／摘要。Pi 路线使用公开 SDK 提供的原 UI callback，只有 literal true 才能继续；无 UI、取消、超时、错误或确认期间的上下文变化一律拒绝。CLI 路线须是用户明确执行的新初始化／提交入口，并以同一 draft 展示／确认；当前并不存在这样的已支持命令。两条路线最终调用独立初始化签发入口；普通模型 tool call 不能直接携带 `approved=true` 换取授权。

server 只能证明请求来自获准的可信适配器角色、原 draft 和当前上下文，不能从网络字段独立证明真人操作。接受此边界与现有 UI 扩展信任模型一致：加载的宿主扩展和本仓库控制代码属于可信计算边界；任意修改该进程或拥有未受限同 UID 内存／文件权限的外部程序不在此逻辑协议的阻断保证内。受限任务不继承 manager／初始化 capability，也不挂载账户控制目录或认证文件。最终接线必须明确 adapter 的专用 role／capability 注入点，不能让普通 worker 或只读查询端获得初始化 issuer。

## current 登记引用与能力的区分

原 startup caller 必须从原 Workspace 的已解析账户／binding／实例和 deployment.json.current.launch 捕获当前正式 Full runtime；接收 manager 从其原受控启动上下文独立读取并重核本地来源，不从JSON还原另进程的Workspace，详见[双actor来源设计](durable-current-startup-origin.md)；核原 lock、完整 installed receipt／inventory、当前 selection／catalog／bindings、runtime guards、所选固定 source／owner 四角色、deployment 兼容关系。候选、missing／damaged、未知 role 或现代 launch unavailable 一律拒绝。现有纯 ServiceRegistration 和 source identity 只能提供非秘密关联，不能替代这个 producer。

可信 resolver 返回的原 RegisteredReference 保存在 manager 私有表；外部只能引用 manager 生成的不透明 draft／service ID。消费时核同一原引用和当前 validator，不能从 hash／path／公开构造器／合法 JSON 重新创建“等价能力”。首次参数包括原账户物理身份、binding／instance／state_root、完整当前 deployment、请求／task draft、原 lease／manager generation、policy／cancel generation 和 deadline；不得由 client 选择 storage 路径、Node 路径、epoch 或全局服务 ID。index 已存在时捕获其原物理身份；首次 index 不存在时捕获原 account 下固定 basename 的 absence expectation，不能捏造 inode。消费后只有原受控 index 创建者可捕获新 identity，并在同一私有 reservation 中将它绑定到原 absence／grant，不变造或重新签发一个等价授权。现有 modern launch 仍关闭，因此真实 resolver 目前不能发出合法引用；fake 默认验证不解除此 gate。

## 单次消费与受控 controller

server 签发短时随机一次能力，只存于私有初始化状态和原匿名 bootstrap 通道。secret token 不进入 argv／env、登记／owner JSON、通用配置、摘要、日志或异常。完整原 context 与 grant 绑定，消费先销毁私有可用状态，再验证最后切点；失败后也不能重用原 token。取消撤销尚未消费的 grant；消费后取消转入受控关闭／unknown 处理，不发新 service ID 来掩盖原状态。

server 使用自己掌握的固定、已核验自有 Python controller 入口及 source 闭包，创建原 Popen 和 bootstrap 双向通道，再登记原 child／birth／generation 与本 grant。controller 不是由 caller 任意提供的 PID／fd／路径。bootstrap 描述符由 parent 实际新建并显式继承，必须避开未知 fd3；原 controller 首先核自己的 fd3 空闲并预留，发现已有未知 fd3 就失败且不关闭它。Node 后续 pass_fds 仍只有原锁3，任何初始化 token／bootstrap fd 都不能传给 Node、SDK 或后代。

第一包不能只接受任意 pipe 中的“授权”字节。初始化能力必须回到原 issuer 的私有 one-shot 状态核对，且 issuer 检查消息来自自己原 Popen 的 bootstrap 通道／已登记 child，而不是另建 socketpair 的进程。通道中的 nonce 和 challenge 仅补足当前实例关联，不作通用真人或防任意同 UID 攻击证明。实际原 child 身份、EOF／取消、bounded framing／timeout、原 held pidfd 和最后纯核等具体 API 必须在代码包前冻结；不得用 parent PID、SO_PEERCRED 文本、raw fd number 或 caller supplied proof 替代 producer。

## 首次登记与存储的顺序

首次路线的必要顺序为：原请求确认和 current 引用 → 原 controller／private channel，controller fd3 预留确认 → 一次 grant 消费及最后 current／policy 核 → 原账户 index EX 协调，保留随机 service ID 与首次关联 → reserved 登记完整持久回执 → controller 获准一次 fresh storage 创建，取得原 EX 锁并绑定3／持久 acquired → index 中 registered 的实际 storage identity 完整持久回执 → 释放 index 协调并确认 → lifecycle 的 Node hello／bound／ready。任何目录或记录已存在（包括空目录、缺 owner、reserved／malformed 登记）不能自动走 fresh storage。

账户控制锚创建也在明确初始化授权及 fd3 预留之后。首次 state_root 由原 manager 引用，服务 ID 与首次 storage 位置独立于后续 profile／provider／runtime。后续显式关联原 service 不分配新空服务；不兼容部署停止准入。已有服务只读查询不启动 controller，也不打开 SQLite。

index 锁的 owner 在同一次首次窗口中负责 reserved／registered 持久写，controller 不另开 index 锁来形成交叉等待。controller 从 acquire 到 registered ACK 一直持自己的原 storage 锁；Node 尚未启动。可能已经发布、fsync／readback／ACK 不确定时不重写、不清理、新分配或启动 Node；保留原 service ID／路径并进入 unknown。index 的 authoritative intent／association 格式、跨文件写序、首次锚中断、既有 index 中孤立 reserved 与缺 ACK 的只读查找，还没有由本文定义成完成的事务。

下一 IO 设计必须证明：reserved 一旦可能发布，重启后也不会由于 alias 缺失或重新选择实例而分配第二个 service ID；任何未知／旧空锚不会被自动“修复成 fresh”。不能只从某个 record 文件现在不存在推断从未登记。需要先冻结 coordinator／association 的最小权威状态和失败切点，之后才能实现磁盘写者。真实关闭／终止和 unknown-held 沿已接受 owner lifecycle，而不使用 active writer finally 的默认 OwnerRecordScope。

## 后续包与验收目标

实现前仍需 root 冻结三个接口：完整 current RegisteredReference 的真实 producer／validator；初始化 issuer 的专用可信 adapter principal 和私有一次消费；index intent／association／storage 的持久顺序与 bootstrap 具体 API。不得用 permissive fakes 补齐尚未存在的来源。可以并行准备纯 context／channel 对象或只读查询，但公开外观保持无初始化／DB／takeover能力。

默认验证应包括外来／错 role／错 lease／错 instance／错 draft／旧 policy／取消／超时、无 UI／false／迟到 true、同 token 重放及跨 manager 重建、假 Popen／错原通道／提前 EOF／未知3，逐切点确认零目录／零模型和能力已消耗。持久包另覆盖 reserved 发布前后、association 丢失、registered ACK 丢失、parent／controller 退出及原 ID 只读查找，不能靠 fake test 证明原 kernel 持有链。SDK／Node／真实 fd／SQLite 各 native 组合需单独审查材料和明确授权；既有 FD6、Harness8 和已执行验收并闭合的 Recovery3 d61799精确三场 不外推。正式7/100、所有产品 gate、严格输入计量前 AUTO OFF 保持。
