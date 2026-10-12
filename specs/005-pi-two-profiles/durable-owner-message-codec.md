# Dedicated controller／Node 私有消息纯 codec 决定

2026-10-06，root 根据已接受的 owner bind 与 JSON/frame 复用静态包冻结下面的纯 codec 候选。它不实现 launcher、pipe reader、owner 状态转移或 SDK admission；没有授权原生执行。设计复审通过后，只实施自有 Python／Node codec 和隔离默认检查，再逐层接实际启动协议。已有 OwnerRecordScope 外观与原 codec 不改。

当前五文件纯组件已在稳定写入后完成 root 和独立 executor 审查，开放 P1/P2=0，六十二输入归档 `durable-owner-message-codec-default-review01/`，receipt `855780ad9ff15d29dd794c1c84dea0b7bd6f535b8ccd8efb2daeea52ebfbef2f`。Python 同次 130 通过（旧 record 65＋新消息 65，0.93 秒）；Node 独立 51 通过（50.98057ms），不相加为一次组合验收。十个完整 golden frame 的两语言编码逐字节相同。首轮 Python129／Node50 与原 brand 函数捕获前后 Node51 均 green，无实际行为 red；未编造反例。旧 record／scope／guards／runtime 七源及原生八／三场来源字节未改，产品 gate、T081／T090 和真实持锁／开库资格仍未通过。

实现时 root 补充了 native element-kind 义务：仅通用 typed-array getter 能接受改 prototype 的其他 typed array；当前 Node 还保存原 `types.isUint8Array` 函数，通过原 Reflect.apply／types receiver 核真正 Uint8Array brand，再核原 slot getters／非共享 ArrayBuffer。改 prototype 的 Uint16Array 已在首次 suite 拒绝，输入 hooks0；末次只将原 brand 函数捕获，未改变该拒绝语义。归档保存接受时 a729 设计原字节和全部首／末来源，下面定义仍对应同一纯组件；本段是当前结果与补充义务，不把文档后续 SHA 当历史 a729。

## 与持锁能力的关系

消息是元数据。来源必须是未来专用 controller 保留的原 child／原私有双向 pipe；业务参数、模型返回或重构对象不能提供这个来源。encode／decode 通过、epoch／PID 相同、bound ACK、descriptor_closed=true 都不证明原共享 OFD、进程退出、所有 IO 完成或数据库权限。Python 的新 OwnerMessage 三个属性 writer_lock_verified、database_allowed、can_take_over 永久 False；Node 返回独立冻结纯值，不暴露 fd 操作、grant 或准入函数。

已有 owner record 的 storage_identity 是存储目录的物理身份。新消息另带 lock_identity，专指原 lock 文件 fstat 的 device／inode，不把两种 inode 混为一个。真实握手还必须由 controller 对原目录、原 lock path／fd、原 child birth、原 methods／receiver 和原持久回执逐一绑定；这些由后续 root 生命周期包决定，不能让 codec executor 自行补算法。

## 唯一 wire 格式

一条完整 frame 为 4 字节 unsigned big-endian payload 长度加 JSON UTF-8 payload。payload 非空且最多 4096 字节，完整 frame 最多 4100 字节；decode 只接一条完整 frame，头尾长度必须恰好一致。无 BOM 剥除、编码自动探测、replacement decode 或第二帧／额外尾字节。允许 JSON 自身合法空白；不另添加或要求 LF。encoder 输出每层键排序的 compact JSON，无 LF，固定前缀。分片／合包／EOF／时限／重复／乱序由后续私有 pipe reader 处理，此 codec 不接 stream 或发起 IO。

JSON 全层拒绝 decoded duplicate（包括 escaped-equivalent key）、NaN／Infinity、孤立 surrogate、数组、未知字段和非法类型。最大嵌套深度 4（根对象深度 1），最大 value nodes 64（每个对象和 scalar 各计 1，不计 key），每个 key／string 最多 128 个 Unicode scalar。整数 token 只允许 `0|[1-9][0-9]*`；负号、负零、小数、exponent 均拒绝，不因 1.0 或 1e0 解码为相同 Number 而接受。任何数字最终须是安全整数并通过字段范围，bool 不能作为整数；JS native capture／encode 也须对所有 number 显式 `Object.is(value,-0)` 拒绝，不能归一化成 0。Python 仍只接受 exact int。物理 device／inode 使用下面的十进制字符串，避免 JS Number 损失 u64。

Python 输入须 exact bytes；bytearray／memoryview／subclass／字符串拒绝，在 len/decode 前核原类型。Node 输入只接受 exact Uint8Array.prototype 或 Buffer.prototype 的非 Proxy 对象；随后用保存的原 typed-array byteLength／byteOffset／buffer getter 经原 Reflect.apply 验 native internal brand，再用原 ArrayBuffer.byteLength getter拒 SharedArrayBuffer。长度先限界，再用保存的原 Uint8Array constructor 创建独立自有 bytes，通过保存的原 TypedArray.set／Reflect.apply 一次复制后才解析。不能只核 prototype；不得读取输入 own constructor／iterator／species、调用 slice／subarray／toString／toJSON 或执行 foreign hook。SharedArrayBuffer 不作为固定 bytes snapshot 接受，ordinary ArrayBuffer 同步捕获无 await／foreign callback。所有公开失败是固定 `Durable所有者消息无效`（Python Conflict，cause/context 清空）或 `PI_DURABLE_OWNER_MESSAGE_INVALID`（Node Error，无输入属性或 cause）；不保留 JSONDecodeError.doc、原 key／value 或 caller 的秘密异常。

## 五种闭合消息

下表之外的字段全部失败。schema 恒为整数 1，fd 恒为整数 3。这里 fd 只是协议字段，decoder 不打开、关闭、dup、flock 或验证它。

| type | 根字段 | 约束 |
| --- | --- | --- |
| hello | schema, type, writer, lock_identity, fd, close_on_exec | close_on_exec 必须 true；writer 是下述完整 Linux identity，无 owner record |
| bind | schema, type, record, lock_identity, fd, close_on_exec | close_on_exec=true；record.stage=bound，writer 非 null |
| bound | schema, type, record, lock_identity, fd, close_on_exec | 同 bind 的闭合结构；只代表待核私有 ACK，不代表 ready |
| close | schema, type, record, lock_identity, fd, close_on_exec | close_on_exec=true；record.stage=closing，writer 非 null |
| closed | schema, type, record, lock_identity, fd, descriptor_closed | descriptor_closed=true；record.stage=closing，writer 非 null，不造 released |

`record` 的七字段沿用既有公开 OwnerRecord：schema、deployment_identity、storage_identity、epoch、controller、writer、stage；区别仅 wire storage_identity.device/inode 是 canonical decimal string。device 范围 0..2^64−1，inode 范围 1..2^64−1，无 `+`、负号、空白或 leading zero。lock_identity 同样只含 device／inode 两字符串和相同范围。Python 捕获后转换为原冻结 StorageIdentity 整数；encoder 重新验完整原类型／范围再转 canonical string，不经 float。Node 保持这些字符串，不自动转 Number。

deployment_identity 和 epoch 都为 64 位小写 hex。controller／writer 只含 platform、boot_id、pid、ppid、pgid、start_time、namespace、uid：platform=linux；boot_id 为小写 UUID 规范格式；pid／pgid 为 1..2^31−1，ppid 为 0..2^31−1，uid 为 0..2^32−2；start_time 为 0..2^64−1 canonical decimal string；namespace 为 `pid:[N]`，N 是 1..2^64−1 canonical decimal。两 record identity 的 PID 不同、boot_id／uid 相同。codec 不把 PPID、namespace、exe 或退出状态变成额外权限证明；hello 与后续 record 是否对应同一原写者由保留的实际 controller 状态核对。

## 冻结自有 API 和实现边界

新增 `src/agentcfg/pi_durable_owner_message.py` 提供 `capture_owner_message(value)`、`decode_owner_message_frame(data)`、`encode_owner_message_frame(message)`；Python 自有 frozen／slots OwnerMessage 保存 schema、type、writer、record、lock_identity、fd、close_on_exec、descriptor_closed。hello 的 record 为 None；其他类型独立 record，根 writer 为 None；不适用的两个 bool slot 为 None。公开 capture 的输入是 exact dict 的 wire 结构，先核所有 exact string key／data 值再读取／hash，独立捕获原冻结 LinuxProcessIdentity／StorageIdentity／OwnerRecord。encoder 只接受 exact OwnerMessage 并重验全 slots，包括未初始化 slots 的固定拒绝。可调用已有公开 capture_owner_record／encode_owner_record，不导入其私有 helper，不修改旧三个 False 属性或原 scope。

新增 `agents/pi/packages/durable-service/src/owner-message.ts` 提供 `captureOwnerMessage(value)`、`decodeOwnerMessageFrame(data)`、`encodeOwnerMessageFrame(value)`。capture 先拒绝 Proxy／accessor／toJSON，只接受保存的原 Object.prototype 或 null 原型；再用原 descriptor 捕获独立纯值，不接受其他 foreign prototype。只冻结新生成的自有 containers，绝不冻结 caller、SDK 或原函数。返回值的字段和 wire 相同，无额外 enumerable 权限字段；三个资格由接口文档明确保持未签发。只导入 Node builtin types，不导入 SDK、storage initializer、owner、process launcher 或 probe。专用 JSON scanner 是自有新实现，可参考既有 scanner／frame 模式，不假装专用 risk-review parser 可解析 owner 消息，也不扩大其 package export。

这一步只处理完整单 frame，不使用 risk-review chunk reader，也不添加 package export／CLI 接线。现有八场和恢复三场十二 sources 均不包含新 codec；旧 SDK、vendor、guards、runtime 七源、owner record／scope、模型授权与账本实现不改。真实接 wire 与状态转移前另做 root 设计与独立原生 qualification。

## 默认验收与后续切点

新增 Python／Node 默认 suite 和一份 shared golden vector fixture。使用合成 Linux identities，含 u64 最大 device／inode／start／namespace、UID 上界、零与界外；五消息每层 field/type/value、原 schema、record stage 与 writer 必填精确比较；两 encoder 的完整 bytes 与同一 fixture hex 一致。有限 wire 数字 1.0／1e0／-0 必须拒绝，物理字符串 2^64−1 必须原值保留。不能通过 JSON.parse 后重编码把 duplicate／numeric lexical drift 消掉。

拒绝 bad UTF-8／BOM／UTF16、truncated/oversized/multiple/extra frames、全层 escaped duplicate、nonfinite/overflow、unknownfield、array、deep/nodes、surrogate、foreign proxy/subclass/getter/toJSON 与 uninitialized slots；确认输入 hooks0、固定错误不保留秘密原文／cause／context。合法 JSON 空白与普通 key order 必须接受，但 encoder 仍 canonical。测试 fake 值和原 stdlib／Node builtin，复用原 mock runner／guards；允许原 runner 已有 bwrap 隔离封装，仅执行自有新 suite，不运行独立原生探针、SDK／SQLite／第三方宿主／真实业务子进程／信号／网络／账号。只运行新套件与有确切影响的 codec 旧 suite；旧 source／assertions 字节保持，mock runner／guards 的实现和边界不改。

首次完整 source／tests／fixture 在第一次默认执行前 O_EXCL0600 捕获。若发现实现错误，保存完整旧源和同最终 tests 的真实行为 red，再保存最小修复 green；不把设计修订、fixture 错误、import／环境不足伪造为产品 red。稳定最终 diff 交 root 与独立审查。本 codec 通过只记纯 metadata/frame 组件，不勾 T081/T090 或 Full；后续原私有 pipe／bound 持久回执／永久 closing／原 writer wait／locked released／close-only 顺序仍由 root 决定，未知回执不得新 epoch、重新 launch、开库或退款。
