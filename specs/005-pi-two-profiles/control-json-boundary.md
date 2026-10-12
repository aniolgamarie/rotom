# 自有控制通道 JSON 边界修复决定

2026-10-06，root 接受 scout 的四源 frame／endpoint map 和五源测试／注入 handler 补充证据。现有 read_frame 将 bytes 直接交 json.loads，UTF16BE＋encoded LF、decoded duplicate、nonfinite／overflow 在共同解析层不拒绝；endpoint 的 Tree.read 也未传 max_bytes。peer UID、有效 capability、闭合 message 和后续操作校验仍在，这些格式观察不证明权限绕过。MCP 同类问题已有真实默认反例与最小修复，因此限定修复这个相邻共同入口；不全量重审权限或改变业务 schema。

2026-10-07 当前结果：两文件修复已完成稳定 root 与独立 executor 审查，开放 P1/P2=0，47输入归档 `control-json-boundary-default-review01/`，receipt `8d0562b44559c93ceca368afa98ccf10754450cd13b42370f9a0e0f458e03956`。完整旧820源＋同最终76项实际43失败／33通过（2.16秒）至新76通过（1.58秒，新52＋原Supervisor／Batch24同次）；第一71项红／绿另次保留，无fixture／环境／API缺失伪red。坏fake真实 `_connection` 八场旧serviceSpy1→新0，只证明格式在dispatch前被拒，不签真实权限绕过或服务资格。依赖当前control的MCP35项另0.40秒通过，11输入 receipt `50e8ff97771a61af63d09c306bf48bcfbe0c9a727da092ded57051c10efb45a3`，与76不相加。原accepted c4bb设计及old／first／stable source全保存，以下约束对应同一最小修复；当前结果不把后续文档SHA当历史c4bb。SDK／native／owner／Full与正式任务gate未变化。

## 唯一改动边界

唯一代码写入范围为 `src/agentcfg/pi_control.py` 与新增 `tests/test_pi_control_json.py`。保留 read_frame／request／peer_uid 的 public signature，保留 MAX_FRAME=1MiB、raw 单 LF readline 上限、top-level dict、消息及 endpoint 既有字段、版本／socket 身份规则、peer UID 与 capability 顺序、输出 json_bytes、30 秒 timeout、原 cwd 恢复和异常／退出语义。server、普通／delegate handler、Tree、认证、MCP 和所有 SDK／owner／runtime 来源不改。

新增同模块自有 private JSON decoder，供 read_frame 和 endpoint 共用：先 exact bytes 类型及 1MiB 上限，再 strict UTF-8 转 string 后 JSON parse；不编码自动探测、不剥 BOM。全层 object_pairs_hook 拒 decoded duplicate，parse_constant 拒 NaN／±Infinity，parse_float 用 float＋math.isfinite 拒 1e999，普通 finite float 保持。泛型 helper 不增加 LF 要求；read_frame 原先要求 LF，endpoint JSON 可无 LF。不新增通用 depth／node／surrogate 语义或改变既有 method schema。

private decoder 只抛固定自有 ValueError，不留 parser 原文／key／value／JSONDecodeError.doc／cause／context。退出 parser except 作用域后再固定拒绝；不得修改 caller 正在处理的异常。read_frame 在原 readline 返回后、任何 truth／len／endswith 操作前先检查 `type(data) is bytes`，不符则抛固定「监督消息格式无效」且清 cause/context；正常 exact bytes 的原空值／长度／LF 文案保持。read_frame 维持既有长度／格式／非对象的固定 Conflict 文案，所有自有 Conflict 清 cause/context；endpoint parse／既有身份检查范围内的错误仍映射固定「监督端点身份已改变」，不留该范围内原解析／OS异常或 caller 秘密链。不要以 from None 隐藏链代替清除实际 __context__；不承诺改写 Tree 构造／进入或后续 socket 等原有其他异常。

endpoint 改为原 `Tree.read(endpoint.name, max_bytes=MAX_FRAME)`；真实读取由 Tree 既有上限执行，不先无界读取再检查 len。仅此读取调用抛出的原 Conflict 单独捕获，在退出 except 后抛固定「监督端点身份已改变」并清 cause/context，超界时零 stat／socket，不修改原异常对象。记录缺失或非 private mode0600 保留原「监督端点记录缺失或不安全」文案，自有 Conflict 也清链；不增加或放宽其他权限／认证／schema 规则，不扩大 Tree 构造／进入和后续 socket 异常的映射。正常 UTF-8 endpoint 与 frame、finite float／key order／JSON空白及原 top dict 保持兼容。

## 默认验收

新测试用 BytesIO、fake Tree／socket／peer／os 和自有 service spy，无真实 socket、线程启动服务、业务子进程、SDK／SQL／host／账号／网络。测试真实 read_frame 的 UTF16BE＋LF、BOM、escaped-equivalent 根／嵌套 duplicate、NaN／±Infinity／1e999、malformed／非对象／无 LF／超界、bytes subclass hooks0，以及合法 UTF8／finite float。source-based format例须由完整旧源＋同最终套件真实执行成 red，不称权限绕过。

endpoint 测试须证明读取 max_bytes、上述格式错误在 stat／socket／peer／connect 前拒绝，正常输入保持 socket 原身份／peer 与 cwd 恢复次序；错误 main 类型／文案／cause/context 如实。服务路径可用 fake connection＋已验证 peer／capability 和 spy，确认不合法 JSON 零 service.reply／handler，而正常合法消息仍走原 dispatch；不为了测试创建真实 listener 或启动宿主。原测试覆盖直接 service.reply 与 batch 的有效 frame，不能冒称原先已覆盖 malformed wire。

相关命令为正常属主 Python pytest：新 `tests/test_pi_control_json.py`、既有 `tests/test_pi_supervisor.py` 与 `tests/test_model_delegate_batch.py`。`test_pi_host.py` 若出现确切受影响证据才补，不因无关代码重复全量。原 guards／旧 tests/assertions 均保持；允许标准 fake 过程，不运行第三方宿主或另行原生探针。实现前完整 old source／新 tests 及 readonly pins O_EXCL0600 捕获；首轮 fixture／环境失败单列，完整 old＋same-final actual behavior red 至 green 保存，稳定写入后 root 与独立增量验收。

此包修纯解析和有界读取，不增 new capability，不改变 grant、事务、锁、恢复、预算或 SDK admission。恢复三场 d61799 的十二来源不含此模块，不能将修复当其授权或 owner／Full 资格。若发现前提不成立、需要 auth/schema 扩大或同一失败两种有效尝试不解，由 root 决定。另一个唯一 writer 的纯 owner-message codec 稳定 STOP 后才交此实现，避免并行 source 变更混淆证据。
