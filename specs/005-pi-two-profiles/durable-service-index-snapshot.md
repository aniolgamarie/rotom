# 稳定服务索引的单份权威快照

2026-10-07，root 在初始化方向收据 `08ad06493a3f13eaea4813fc3e020fb2527aa8d057cee07fac7ab122abbaec56` 的开放事务接缝上决定使用一份逻辑权威快照。本文冻结第一包纯数据接口；不授权 index／目录写者、flock、controller、bootstrap、Full／正式锁、SQLite、恢复或任何实际宿主。需要独立设计审查后才能实现所列两文件。

## 权威状态与顺序决定

账户控制锚仍固定 `<account_home>/.agentcfg-pi-durable`。服务 ID、首次 storage 位置及历史登记沿已接受十三字段 ServiceRegistration。索引内按 service ID 保存登记，实例关联在相同 snapshot 内；不把 per-service 文件或 alias 文件另设为逻辑权威。固定 `index.json` 是未来磁盘地址，尚未实现。status／只读发现只消费完整快照，不扫描残留记录拼造一份索引。

初始化请求 ID 和输入身份与该服务登记一起保留，便于返回 service ID 前丢回执时按原请求只读查找；它们是非秘密初始化关联，不是 SDK task 队列、任务状态、nonce、批准 token 或模型预算。一个具体实例关联由 binding／instance／state_root 识别并只指向一个 service ID；改 profile／provider／runtime 不能修改首次登记或分配空服务，新的 binding 关联原服务需要新明确授权。纯索引不执行这种授权。

首次受控 writer 必须在原初始化确认／一次消费／controller fd3 预留之后，持原账户与 index 协调完成一次 snapshot1 发布。该快照同时含 reserved ServiceRegistration、初始化请求关联和初始实例 association；没有“service 已发布但 alias 未写”的逻辑切点。完整 persist／fsync／readback 回执之后才允许一次 fresh storage 创建；原 acquired／锁3核验后仅替换同一 service 的 registration 为 registered 并递增 generation，仍在 Node launch 前取得完整回执。失败或可能发布但 ACK 未知保留原 ID／路径，不补写、新分配或启动 Node。

原账户锚存在但缺失／空／畸形 index 不能当首次空状态自动初始化。原 index 已完整发布时，合法 reserved 与 registered 都保留同一初始化请求 ID、首次关联和 service ID；readonly 可报告事实，不从 recordabsence 推断从未创建。新服务的插入必须在原 index 锁下核所有旧关联和初始化请求，保留全部既有行。当前 snapshot 并不证明旧 generation 是否曾发布、可否接管或磁盘回滚，因此 reader 不能自动提高 generation／清空记录，恢复仍要求原 owner／IO 和外部活动证据。

单份 bytes 的发布只减少跨文件逻辑状态，不承诺 kernel CAS、断电原子或“写后丢 ACK 等于未写”。后续 IO 包仍须冻结：index 首次创建和固定协调 fd 的持有／锁顺序，expected 原文件身份、Tree.replace 写前／可能已发布／fsync／读回切点，原调用者／channel ACK，停止后零写及已有 index 的只读打开。纯 DTO 和快照世代都不是写入授权。

## exact wire schema 1

顶层 exact dict 仅八字段：`schema`（exact int1）、`platform`（exact str linux）、`account_home`、`account_identity`、`index_identity`、`generation`、`services`、`associations`。account 路径与两个 DirectoryIdentity 的范围／canonical 约束沿十三字段 service record：uid 相同，device uint64、inode正uint64、uid至2**32-2；generation exact int1..2**64-1，拒绝 bool／浮点／wrap。此包不调用 geteuid／stat，也不证明原账户来源。

services 是 exact list，长度1..64。每项 exact dict 仅 `registration`（原公开 capture_service_registration 接受的十三字段 wire）、`initialization_request_id`（64位小写ASCIIhex）、`initialization_identity`（64位小写ASCIIhex）。service ID 和初始化请求 ID 在此快照内分别唯一，身份摘要不能代替请求 ID。每项 registration 的 account_home／account_identity／index_identity 必须与顶层逐值一致。reserved／registered 原约束不变，不复制 task／budget／owner epoch 字段。超过容量应明确拒绝，不截断或替换旧服务。

associations 是 exact list，长度1..512。每项 exact dict 仅 `association_id`、`binding`、`instance`、`state_root`、`service_id`。binding exact dict machine/local/profile，规则沿 InitialBinding（machine `[a-z][a-z0-9_-]{0,63}`、local canonical absolute、profile pi-full）。instance 和 state_root 使用相同 native canonical absolute路径规则；service_id必须引用本 snapshot 的 service，association_id是以下非秘密域隔离投影的原 canonical sorted/compact UTF-8/LF SHA256：

```json
{
  "schema": 1,
  "kind": "pi-durable-service-association",
  "binding": {"machine": "example", "local": "/example/local.toml", "profile": "pi-full"},
  "instance": "/example/instance",
  "state_root": "/example/state"
}
```

service_id 故意不在该投影中：同一 association 的逻辑键不能指向两个服务。所有 association_id 唯一且必须等于从原三项关联计算的值。每个 service 至少保留一项与其 initial_binding／initial_instance／initial_state_root 完全一致的初始 association，指向自己的 service ID；合法的新别名不能抹去初始关联。不存在的 service／重复或错映射／缺初始关联均拒绝。

wire 数组可不同排序，capture 后独立元组按 service_id／association_id 原 native 字符串排序，encoder 产生唯一排序。每层先 exact dict／list 和全部原键类型，再比较、hash、访问、捕获独立值，不能触发 foreign mapping／字符串／整数／属性／序列化 hooks；不能保留 caller dict/list。路径按原 native字符串验证，UTF-8最多4096B，禁非canonical段、控制／surrogate／反斜杠，不做 Path／resolve／Unicode归一化。unknown字段／版本／平台失败，不删值“修复”。

## 第一包 API 与责任范围

唯一 writer 只新增 `src/agentcfg/pi_durable_service_index.py` 和 `tests/test_pi_durable_service_index.py`。公开 API 为 `capture_service_index(value)`、`decode_service_index(data)`、`encode_service_index(index)`、`service_association_identity(binding, instance, state_root)`；identity helper 仅接受上述 exact原生 binding dict 与两个路径，不接受 callback／registered reference／path对象。计算复用原 public json_bytes／hashlib 规则，测试独立构造投影期望。

新自有 frozen/slots 类型 ServiceIndexEntry、ServiceAssociation、ServiceIndexSnapshot，内部只含独立原生元数据与原公开 ServiceRegistration／DirectoryIdentity／InitialBinding纯对象；不新增第二套 registration schema，不调用 registration 模块私有 helper，也不为验证 association 捏造一个改写过首次关系的 service record。需要复用的路径／binding小校验可在新模块按同一规则直接实现。捕获旧 registration 必须使用其原公开 capture，encoder 用原公开 encode，foreign异常在新边界映射，不修改它们。

decode 仅 exact非空bytes≤16MiB，严格UTF-8／JSON，拒绝duplicate keys、非有限常量／overflowfloat、未知／deep结构，完整capture后才返回。encode 仅原 exact Snapshot／Entry／Association及全部原nested类型，type核先于属性；uninitialized slots也固定拒绝。encoder重建全部原生wire并经capture校验，输出sorted keys／compact／UTF-8／LF≤16MiB，service/association数组按固定顺序。每个registration仍遵守原32768B上限；整个snapshot上限不是放宽该约束。成功外观 `writer_lock_verified/database_allowed/can_take_over` 始终False，public constructor／generation／合法bytes均无授权。

所有新边界失败映射为新自有 `Conflict("Durable服务索引无效")`，实际cause/context None；不修改 foreign exception，不将原输入／token保留在成功缓存／日志／异常正文。这不承诺traceback locals全局清理。零filesystem、目录／锁／proc、线程／subprocess、SDK／Node／模型／网络或默认index创建。

## 默认验收与后续 IO

默认新 suite 和原 service_registration_record suite同次检查；旧 source／tests／guard 全部保持。新纯实现不存在时collection error只记未实现，不能称行为red。新checks覆盖reserved／registered、多service／显式alias、独立association域投影、排序canonical往返、输入变异后捕获不变／外观False、unknown／duplicate／错account/index／uid／range、重复service／request／association、引用缺失／误指向／缺初始association、派生ID漂移、边界容量、字面path别名、JSONduplicate／UTF8／nonfinite／深层／size、uninitialized各slots／forgednested类型、foreign hook零调用／fresh错误链及foreign异常未改。关联ID、generation和记录是data，不以fixture mint原capability。

完成后 root 审稳定diff与证据，独立executor审最终版本；只有纯索引包通过。若需要IO／锁序、实际Full reference／issuer、bootstrap、修改旧schema/helper、扩scope或反复失败两种有效尝试未解，交root决定。任何实际宿主／SDK／fd组合仍需具体独立授权；本包不使用旧8场授权，不执行待授权recovery3。正式7/100、产品gate／AUTO OFF保持。
