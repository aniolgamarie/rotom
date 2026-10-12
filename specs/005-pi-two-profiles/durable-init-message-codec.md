# 初始化消息纯codec：root冻结候选

2026-10-07，root采纳下面proposal第1–6节的九个exact message schema、原record public cap、元数据格式和三False外观；第7节的source／principal／origin／clock／真实grant与IO gate继续pending。root另用固定stdlib字面量独立复核9行overhead，P为216B、S为60B、最大canonical payload保守33204B；空R/E只用于算式，不是合法codec正例。原Node五消息4096B及所有旧guards/source保持。

首包仅允许新增 `src/agentcfg/pi_durable_init_message.py` 和 `tests/test_pi_durable_init_message.py`，API为 `InitMessage`、`capture_init_message`、`encode_init_message_frame`、`decode_init_message_frame`。所有DTO无IO／callback／sourcevalidator／随机token／授权／发送或阶段推进能力。当前为待独立设计复核的限定candidate；复核通过后root另给executor具体实现任务包。不得先实现launcher/index/current-source/principal或启用factory。

以下原proposal作为exact字段和边界的规范依据；其“root裁决”在本候选限定采纳范围内已作出。input原报告完整保存，首包不生成正式声明或角色。formal7/100、全部产品gate及严格计量前AUTO OFF保持。

# Durable init message schema：纯codec候选proposal01

2026-10-07，executor配置gpt-6.1-sol / medium；无子代理。仅提出数据schema、大小算式和下一包文件范围，未独立批准schema/代码。STOP交root。未改repo、import仓库、执行测试/GET/SDK/Node/native/account/network；只读指定源及root追加授权的直接owner_record，并用stdlib JSON对固定字面外壳作长度算术。该算术中的空对象是2B占位，不是合法record/message fixture或通过证据。

输入路径纠正：指定durable-service-registration.md不存在，按rg --files找到durable-service-registration-record.md；指定pi_durable_service_registration.py不存在，root确认用已接受pi_durable_registration_record.py并允许直接owner_record确定process范围。这是路径命名纠正，不是产品实现失败。没有探source/launcher/principal或扩大到其producer。

## 1. 边界、表示与共同标量

提议独立schema1，9个exact type值对应既定7阶段/双方向。不是Node的hello/bind/bound/close/closed五消息，不修改其4096B codec/window。

- 每条wire为exact原dict、exact键集。schema=exact int1，type=exact原str指定literal；拒bool冒int、子类、unknown/missing字段、浮点/指数/nonfinite、arrays、surrogate及外来hooks。序列化sort_keys/compact separators/ensure_ascii=False/allow_nan=False，UTF8；payload不带LF。frame=4BE payload长度+payload，payload1..65536B，完整frame5..65540B；流窗口65541仅是额外一字节尾数据探测上限，不能让codec接受尾帧。
- H：exact原str，恰64个小写ASCIIhex。不同字段仍有不同语义；合法H不证明来源、请求唯一、grant、OFD或持久化。
- T：原issuer另行产生的32B随机opaque secret，以64个小写ASCIIhex传递；codec只核格式，不生成随机数、不称H hash就是token。token只处于原私有内存/匿名pipe，所有DTO token字段repr=False；不进日志/状态/通用digest/异常，不生成token摘要。清理释放私有引用不声称全Python内存/traceback已擦除。
- U：exact int0..2**64-1；G/D：exact int1..2**64-1。schema/fd不能用bool。两端Python，U使用JSON整数而非Node安全53限制或浮点。policy_generation/cancel_generation可0；deadline_monotonic_ns、index_generation不可0。实际clock epoch/time namespace/取消/当前policy来源后续IO核，合法数值不授权限。
- S：exact dict(device:U,inode:G)，沿原StorageIdentity。它只是目录/lock/slot的分别标识，不能混同对象或证明OFD；不同用途的S不自动要求相等。
- P：沿原LinuxProcessIdentity的exact8字段：platform=linux；boot_id为36B小写UUID；pid/pgid exact int1..2**31-1，ppid exact int0..2**31-1，uid exact int0..2**32-2；start_time为canonical十进制str0..U64/最多20B；namespace=pid:[positiveU64]/最多26B。不是无限new int。独立pure小校验可直接按这些原scalar规则捕获public LinuxProcessIdentity，不调用私有_process，也不捏造owner record验证P。
- R：原十三字段ServiceRegistration object wire，完整经public capture_service_registration再public encode_service_registration复核（capture本身未核32768B），独立捕获。必要时public decode/encode clone；不复制或放宽十三字段schema。路径必须同时沿原字符及UTF8最多4096B/控制/反斜杠/段规则，不仅4096字符。
- E：原public OwnerRecord object wire，capture/encode完整复核，且stage=acquired、writer=None，沿原16384B上限；controller=P。slot/acquired P不是pid查找授权；其原Popen/heldpidfd/observer/source比较只在后续私有actor。
- C(type)缩写仅展开四键 `{schema:1,type:<literal>,context_id:H,token:T}`。context_id是本次原私有会话关联，不是跨进程对象指针或可查回任意Full来源的能力。

提议所有自有消息DTO为frozen/slots，writer_lock_verified/database_allowed/can_take_over恒False，公开构造器/合法frame/nonce/digest无任何permission。所有失败fresh自有Conflict("Durable初始化消息无效")，actualcause/context None；foreign异常不改、不携原JSON/token/JSONDecodeError.doc。不要借display-only fromNone冒充链清除。

## 2. exact九消息（不存在未列键）

| type /方向 | 完整键集与域（C按上文展开） | 静态语义 |
|---|---|---|
| slot / child→parent | schema,type,controller:P,slot_identity:S,fd:exact int3,close_on_exec:exact True | controller预留3的独立metadata；无context/token，因为尚未收到offer。实际original child/slot/source必须parent绑定后核，不从P或True得到fd所有权。 |
| offer / parent→child | C + initialization_request_id:H,initialization_identity:H,source_identity:H,policy_digest:H,policy_generation:U,cancel_generation:U,deadline_monotonic_ns:D | 独立child能保存实际有界deadline/policy/cancel关联与任务/request摘要；不嵌任意originDTO或完整inventory。不消费grant、不创建目录。 |
| offer-ack / child→parent | 同offer的11键，type改offer-ack | 完整echo已捕获offer的非type字段，避免仅token相符掩盖漏接deadline/policy/source/请求。仍只是原接收者准备事实。 |
| fresh-storage / parent→child | C + registration:R(stage=reserved),index_generation:G,initialization_request_id:H,initialization_identity:H | 整条首次reserved记录，包括SID/path/原index identity；init两字段须匹配原offer与父私有reservation。index_generation只是原reserved发布关联，不是expected磁盘cap。 |
| acquired / child→parent | C + service_id:H,reserved_registration_identity:H,record:E(stage=acquired/writer=None),lock_identity:S,fd:exact int3,close_on_exec:exact True | E保存原deployment/storage/epoch/controller完整metadata。lock_identity与E.storage_identity是lock文件/目录两个对象，不错误要求相等。actual acquired持久/OFD/fd3回执不能由这些字段证明。 |
| registered / parent→child | C + registration:R(stage=registered),index_generation:G,reserved_registration_identity:H,acquired_record_identity:H | 完整registered字段便于与原reserved11immutable+实际E.storage_identity比；保留原init/privatecontext，不仅比SID。仅metadata；零Node。 |
| registered-ack / child→parent | C + service_id:H,index_generation:G,registration_identity:H,acquired_record_identity:H | 完整registered/E原captures的有界echo关联。parent收ACK仍不等于协调close成功。 |
| release / parent→child | C + service_id:H,index_generation:G,registration_identity:H,acquired_record_identity:H | 与已保存整条registered R/E和原context精确关联；由原父producer在retire/quiescence/明确close/current核后仅发送一次。不加coordinator_released/approved布尔假cap。 |
| release-ack / child→parent | 同release8键，type改release-ack | 阶段receipt，只是原会话已消费release关联，不代Node hello/bound、实际wait或DB准入。 |

source_identity只绑定双方各自original local full-source captures；不是公构JSON的source证明。其actual producer/canonical语义和两actor实际local current.launch/lock/receipt/inventory/selection/四roles/Python完整核验仍pending，不能从context_id/hash查回另进程原对象。**pure offer可先编码，但实际origin handshake/source/principal未闭合时所有相关IO factory保持false**。不把完整257/18498 inventory塞进64KiB，也不因省略wire inventory而省略local full-source重核。若最终origin transfer需要新增wire字段，root须再修schema/上界并审查，不能塞一个任意dict或“全部已验证”True。

## 3. identity与跨帧关系：不产生cap

reserved_registration_identity/registration_identity分别是SHA256(原public encode_service_registration(R)完整bytes，含其一个LF)；acquired_record_identity是SHA256(public encode_owner_record(E)完整bytes，含LF)。只hash原非秘密record，不hashtoken或整个含token offer/frame。C、SID、generation及这些digest都只是关联数据。

未来私有expected窗口/actor必须保存完整独立Offer/R/E/P/S captures而非只保hash：

1. slot匹配原Popen/heldpidfd/observer/3原预留；offer-ack逐值等原offer除type，parent原grant尚未消费时零FS。
2. fresh的context/token/init两字段匹配原offer/privategrant；R全文匹配原source/首次binding/state_root/deployment/原absence→created index捕获，reserved publication真实完整回执先于首可能freshwrite。纯codec不证明这些producer事实。
3. acquired E.controller对应原slot P和当下真实observer；E.deployment_identity对应原R.initial_deployment_identity，S实际原fd3/lock source另核；E.epoch/持久acquired由原controller producer，不从任意E重建资格。
4. registered R.service_id同原reserved，除stage/storage_identity之外11项完整相同，storage_identity对应原E.storage_identity，index_generation=reserved G+1且不得wrap；acquired/reserved hashes与original captures原bytes相同。init request/identity留在privatecontext原capture，不因R无该两字段而丢失。
5. registered-ack/release/release-ack逐值绑定同原SID/G/R/E/context；旧stage、重复、错误窗口永久拒绝，不能把相符合法frame当重放许可。release前retire/indexIO静止/close/source、release后原storage/3/source/cancel/deadline仍actual actor核。

这些是后续窗口/actor的验收义务，不纳入单message capture的来源签发。Node五消息与这里字段/uint64/token完全隔离，Node不继承两个initfd，后续Node packet仍原4096B和既有decimal storage字段。

## 4. 编码上界：65536充分，但不宣称上界一定可达

采用canonical UTF8 JSON，outer无LF。完整R原public encoder32768B含一个末LF，因此嵌入**JSON object**时R_body≤32767；E_body≤16383。不是把JSON作为str再次escape，也不能用R capture成功代替R encode cap。剥去LF后保留原canonical object字节：同sort/compact/ensure_ascii=False规则的nested object不会再次escape。公共encode回执后可仅stdlib解析其native dict再嵌入；不私用旧wire helper。

路径上界不能按3B估算：未经UTF8限制的4096astral字符可16,384B，PythonJSON quote/backslash/control的escape又各不同；旧路径实际禁backslash/C0/C1/surrogate且UTF8≤4096B，允许的ASCII双引号仍2B，所以单合法path保守encoded string≤2*4096+2=8194B。五path的独立最大组合可以超过32KiB，并不保证整record合法；因此实际outer算式采用**已执行原public record cap**，不是声称每个合法string组合都可装进帧。state_root/storage_path耦合仍原codec核，不放宽4096规则。

固定ASCII P在全范围上界216B（5B linux、36B boot、3个10位pid族、10位uid、20B start、26B namespace及标点keys）；S上界60B（两个20位整数+fixedkeys/标点）。所有H/T各64B固定ASCII不需escape，U/G/D各最多20个十进制字节。

下表outer固定外壳已按actual exactkeys、max type literal、上述最大ASCII scalar和compact/sorted/noLF JSON算术核过。R/E位置的`{}`仅2B长度占位；扣2后加原body上限。不代表空object是合法message或运行了repo codec。

| type | 无R/Epayload上界，或outer去body overhead | body硬上界 | payload保守上界 | 4BE+payload |
|---|---:|---:|---:|---:|
| slot | 361 | 0 | 361 | 365 |
| offer | 665 | 0 | 665 | 669 |
| offer-ack | 669 | 0 | 669 | 673 |
| fresh-storage | 434 | 32767 | **33201** | 33205 |
| acquired | 480 | 16383 | 16863 | 16867 |
| registered | 437 | 32767 | **33204** | 33208 |
| registered-ack | 496 | 0 | 496 | 500 |
| release | 489 | 0 | 489 | 493 |
| release-ack | 493 | 0 | 493 | 497 |

全候选canonical payload≤33204<65536（余量32332），frame≤33208<65540。E采用原16KiB cap是宽松保守界；不把这个数宣称为真实acquired E可达最大值。receive可含合法JSON whitespace/不同keys顺序，但仍rawpayload≤65536、structural limits和original canonical R/E cap必须通过；sender只能canonical输出。未来追加字段或改变JSON规则须重新核上界。65536不是PIPE_BUF atomic承诺，沿原唯一writer/offset/framing规则。

## 5. encode前capture与decode资源边界

提议下一purecodec用一个自有frozen/slots InitMessage（union fields；inactive字段强制None，encoder不能静默丢其值；token repr=False）或root选择equivalent exact variant classes。本proposal建议union形式沿OwnerMessage接口减少API面；所有外观3False。公开API候选仅capture_init_message(value)、encode_init_message_frame(message)、decode_init_message_frame(data)。本包不接callbacks/sourcevalidators/FD/path IO，不提供take授权或sender函数。

- Capture先exact dict及常量arity，再dict.items：top最多11keys，各层dict≤13keys、keys先exact str/≤32chars后hash/compare/get；未知键拒，不自动修复。不接受list/tuple/Mapping/自定义str/int/property hooks。
- schema逐variant精确键集，bounded native scalar先核；任何字符串先exact str与本字段length上界，再ASCII/UTF8/path验证。原R路径最多4096chars预限，UTF8实际≤4096B由原公开capture验证。任意Caller string可在编码前拒，不先json.dumps整体再发现过大。
- 最大container-depth=3（top→R/E→binding/identity/P），value-depth=4；dict总数≤6；value/container node最多33（registered），无arrays。设置额外统一node cap48，**包括container/scalar不计fixedkeys**；最终exactschema仍决定实际最大33，不用cap48接未知结构。每层keycounts有静态上界。
- 先bounded native结构capture，R/E走原public capture→encode并核字节cap，P/S自有小scalar校验构造原public types；不call旧private helper、不为process造fakeowner record。不把known oldOwnerMessage 128B string/4096 frame规则复用于R/path。
- Encoder先exact InitMessage及原nested classes再任何getattr，抓未初始化slots固定拒；重构全部native wire、inactiveNone检查、capture重验，只有完成所有bounded验证后用canonical JSON并再checkpayload≤65536。R/E嵌入object，禁止asdict/foreignrepr/json default callback。成功独立DTO不得保Caller mutable dict/list。
- Decoder先exact非空bytes、header4、1..65536且完整长度吻合，再strictUTF8。可用有限lexical preflight（正确忽略string内escaped delimiters）在json.loads前拒arrays/containerdepth>3/objectcount>6，再object_pairs_hook逐层duplicate和arity拒；parse_int canonical十进制最多20digits/U64，parse_float/parse_constant全拒。随后exactschema/48node/nativecapture/R/E caps；JSON/BOM/duplicate转义同键/nonfinite/溢出/deep/unknown/extra frame均固定ownerror。preflight不是另一宽松JSON parser，完整grammar仍json.loads；错误不带JSON doc或token链。
- frame/window累计有界65541；这里只定义wholeframe decoder，后续InitReplyWindow纯stream窗口需另proposal/审查，不能照抄旧OwnerReplyWindow的4096而改constant就宣布原producer绑定成立。

## 6. 下一包唯一文件范围及默认验收建议

建议root下一步只授权NEW `src/agentcfg/pi_durable_init_message.py` 和NEW `tests/test_pi_durable_init_message.py`，不动registration/owner codecs、oldOwnerReplyWindow、guards、schemas/manifest/launcher/current-source/principal/IO/docs。纯codec先闭合9exactshape/types/cap/canonicalbytes/DTO independent/3False；不实现真实actor、授权或stream IO。随后窗口是单独两NEWfiles（尚不授权），实际source/privatecontext/launcher/pipe/pidfd/locks另一gate。

默认验收同次newinitmessage suite+原registration_record、owner_record、owner_message相关suite。Independent projections/actuallength arithmetic与可行合法max边界分开：quote/astral/UTF8路径、record capture合法但publicencode超32768拒、E实际合法publiccap、candidatefield常量overhead；不能以非法placeholder算术当合法codecpositive。9shape正例、wrongtype/unknown字段/eachmissing/foreignhooks0/slots/freshchain/foreignerrorpreservation、nativeU64含max与bool拒、P范围、frameheader/deep/duplicate/nonfinite/尾字节、token repr/log不泄漏应直接覆盖。仅tmp/defaultDTO/bytes，不启动host、signal、pipe或SDK；actualsource/crypto/lock/nativequalification均false。

## 7. root裁决和remaining gates

本proposal未独立批准。请root决定采用上述9exactshape、offer与ack完整metadataecho、acquired full E、registered full R、64KiB cap以及2NEWfile纯范围。没有需要扩大当前读取或lock/log方案的不定：65536已足够。

仍pending的不是可由codec补齐的权限：source_identity如何由父/子原local fullproducer/canonical captures绑定，controller原privatecontext的origin handshake、真实共同Linux monotonic/policy/cancel验证、principal/原grant/lastsource/current验证、原channel/Popen/heldpidfd/one-shot窗口、实际sender/lifecycle。root补充metadata只让独立child保存值，不把数字/ID反查跨进程原对象或授grant。Pending时IO gate保持false；不在offer嵌unfrozen任意originDTO，不更改正式7/100/productgates/AUTO OFF。

## 输入首末pins（阅读结束稳定）
- specs/005-pi-two-profiles/durable-controller-private-channel.md: `ad404c4158874919048c4c003bbd4deb478cf21afed2d2c93ec9cd969d393c54`，15900B，first=last。
- specs/005-pi-two-profiles/durable-service-index-publication.md: `81f418753cbfab56f7822e06705b601351cdc1a47e5a895e321380d944502a10`，14646B，first=last。
- specs/005-pi-two-profiles/durable-service-registration-record.md: `488a11439723a92975faa8811adb9fc651fee9ceed991e4f1a8b57e6da92d51a`，8598B，first=last。
- src/agentcfg/pi_durable_registration_record.py: `b00d250abc988a6faf813b5e329e94dfdcdcd8927d9313b6ad3e9e17b5e4e691`，6202B，first=last。
- src/agentcfg/pi_durable_owner_message.py: `390fe2829e2e3880beb1e5ac5a29b249c76433b8303233fcbd8d2ea94de0c705`，6971B，first=last。
- src/agentcfg/pi_durable_owner_channel.py: `64d55086b4eb5e7a0ab1bcfdd10bebdcdd8de86125a438475cf607346ddb89a8`，4050B，first=last。
- src/agentcfg/pi_durable_owner_record.py: `bedbdd58306590752c9937aa94f387e7ea4d7e768c5067da6c18ac7c5b5ad867`，6138B，first=last。

所有算式属于stdlib自有文字构造/长度核算，不是产品codec测试或sourceproducer资格。只O_EXCL0600写本MD，STOP。
