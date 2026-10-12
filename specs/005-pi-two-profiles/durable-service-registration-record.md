# 稳定服务登记与第一包纯记录接口

2026-10-07，root 根据账户锚的六输入收据 `2c2fdfc34a942aada55df31a0f415c1582418ca43dc8144c1c6eb600579eeb41` 和已有 launch 来源设计整理本候选。第一包仅实现纯元数据捕获与编解码，不创建账户索引、存储目录、锁、授权、进程或数据库。索引和私有初始化的生产接口另行审查，不能用本记录替代它们。

## 稳定锚的决定

现有 `<account_home>/.agentcfg-workspaces` 的 registry、claims 与 root row 都闭合，没有 service ID 字段；root ID 主要标识业务工作根，不能拿它当 Durable 服务实例身份。服务使用独立的 `<account_home>/.agentcfg-pi-durable` 控制锚，不修改原 workspace registry 的允许内容或根登记协议。账户根来自可信 manager 的原账户来源，而不是客户端路径、环境 HOME 或当前工作目录。新锚尚未实现，名称不是已支持的用户配置。

首次显式 Full 服务登记分配随机 service ID，固定首次 `<initial_state_root>/durable/storage`。service ID 不由 runtime、provider、profile、部署摘要或数据库内容重新派生。首次 binding、instance、state root、deployment 是历史关联；新选择不能覆盖它们。当前部署的授权和兼容性核验另持当前引用。profile、provider、配置路径或状态路径变化，必须通过 manager 的显式关联／迁移流程引用原 service ID；找不到原服务不能自动分配新 ID 来规避任务或未知预留。更换账户或控制锚物理身份使原引用失配，不能静默迁移。

后续索引设计采用独立 coordinator 和按 service ID 保存的登记记录，避免改动 workspace 协议。索引读写、目录身份、锁顺序、写后丢回执和授权消费尚待冻结；不得从本候选推导一个已可用的 service index 实现。读取旧 service record 不启动服务，也不打开 SQLite。记录的路径、UID、摘要、公开构造器和合法 JSON 都是关联数据，不是授权。

## 纯记录 schema 1

wire 是 exact dict，且仅有下面十三项；每层先捕获原键值并核所有键为 exact str，再作哈希／比较。所有 nested dict 必须是 exact dict，不能触发外来 mapping、字符串、整数、属性或序列化 hook。

| 字段 | 约束与含义 |
|---|---|
| `schema` | exact int 1，拒绝 bool |
| `platform` | exact str `linux`；仅本轮 Linux 记录格式 |
| `service_id` | exact str，64 位小写 ASCII hex；生成职责不在 codec |
| `stage` | exact str `reserved` 或 `registered`；只表示登记记录阶段 |
| `account_home` | 下述 canonical absolute 字符串；原 manager 捕获 |
| `account_identity` | exact dict `device/inode/uid`；账户目录物理关联 |
| `index_identity` | exact dict `device/inode/uid`；固定控制锚物理关联 |
| `initial_binding` | exact dict `machine/local/profile`；machine 为 `[a-z][a-z0-9_-]{0,63}`，local 是下述绝对文件路径，profile 固定 `pi-full` |
| `initial_instance` | 下述绝对路径；首次实例历史关联 |
| `initial_state_root` | 下述绝对路径；首次状态根历史关联 |
| `storage_path` | exact str，必须逐字等于 `initial_state_root + "/durable/storage"` |
| `storage_identity` | reserved 时仅 None；registered 时 exact dict `device/inode` |
| `initial_deployment_identity` | exact str，64 位小写 ASCII hex；历史兼容关联，非完整部署验证 |

物理 identity 的 device 是 exact int `0..2**64-1`，inode 是 exact int `1..2**64-1`，uid 是 exact int `0..2**32-2`。account/index 的 uid 必须相同；codec 不调用 geteuid，也不能据此判断账户来源或所有权。storage 不增加 uid 字段，沿用 owner wire 的 device/inode。

路径先核 exact str；UTF-8 编码长度 `1..4096`，拒绝 surrogate、C0/C1 控制字符、反斜杠、末尾 slash、空段、`.`、`..` 和根路径 `/`。必须以单个 `/` 开头。按原字符串验证，不调用 Path、resolve、expanduser、stat 或做 Unicode／路径归一化；合法字符串也不能证明磁盘对象存在。account_home 的 index 路径固定由 manager 加 `/.agentcfg-pi-durable`，不新增 wire 自由路径。此包只检查 storage 的派生对应，不以纯字面路径证明无别名／目录越界。

reserved 记录不声明任何 storage identity；registered 记录也不声明 owner epoch、存活、持锁、数据库已开或任务已恢复。注册阶段不是任务状态或 owner stage，不能映射成 ready。新的 immutable record 外观保持 `writer_lock_verified/database_allowed/can_take_over` 三项 False。

## 第一包接口与所有权

仅新增 `src/agentcfg/pi_durable_registration_record.py` 与 `tests/test_pi_durable_registration_record.py`；其他源、schema、任务、正式锁、registry 和宿主不改。新自有 frozen/slots `DirectoryIdentity(device,inode,uid)`、`InitialBinding(machine,local,profile)` 和 `ServiceRegistration` 保存独立纯值。storage 复用原公开 `StorageIdentity` 类型；不调用 owner 模块的私有 helper，也不为复用 storage 捏造 owner/controller 记录。

公开函数为 `capture_service_registration(value)`、`decode_service_registration(data)`、`encode_service_registration(record)`。capture 对所有层逐项 exact type、范围、关系验证并独立捕获，不保留 caller dict。decode 仅 exact bytes，非空且最多 32768B，严格 UTF-8／JSON，拒绝重复字段、非有限常量、未知字段、版本和超深结构；错误后不携原输入。encode 仅原 exact ServiceRegistration 和所有原 nested 类型，核 type 先于读取 slot；包括 object.__new__ 的未初始化对象也固定拒绝。重构全部原生 wire 并再次 capture，输出 sorted keys、紧凑 separators、UTF-8、末尾单个 LF、最多 32768B。encoder 不接受任意 callback／dataclasses.asdict／外来 repr。

新函数失败统一抛自有 `Conflict("Durable服务登记无效")`，实际 `__cause__` 与 `__context__` 为 None；不修改 foreign exception，也不在异常正文、返回外观、成功缓存或日志保留输入。这里不承诺 Python traceback locals 的全局秘密清理。codec 的公开函数、构造器和合法 wire 不是 manager capability；后续 resolver 必须核原可信 producer／完整 current deployment／installed receipt，不能把此纯对象当 `RegisteredReference` 授予初始化。

## 首次初始化与已有存储的后续约束

后续 manager 必须先持久保留 service ID 和首次路径的 reserved 记录，才允许一次新目录创建。首次 controller 自有 fd3 预留、原创建授权、原账户／索引引用和部署检查都在任何 Durable 目录创建前完成。目录已经存在（包括空目录或缺 owner）不能重走首次路径。registered 记录只能在原目录创建和 acquired 确认后写入实际 storage identity，且仍必须在 Node launch 前完成本阶段持久回执；任何 possibly-visible write／fsync／读回丢失都保持 unknown，不补写、不换 ID／epoch、不删除目录重试。

这段冻结错误方向和顺序要求，不定义跨文件事务已经成立。reserved 的首次授权消费、controller 到索引写者的私有传递、丢回执后的只读查找、锁先后与跨进程材料都须在 IO 包前明确冻结和审查。既有 registered 只能走已有存储资格／恢复路线，第一包不提供 takeover、旧库初始化或迁移。

## 默认验证与接受边界

第一包使用自有纯 Python、临时 HOME、虚构 account/instance/storage/部署，不运行真实锁竞争、/proc、子进程、Node、SDK、SQLite、模型或网络。先验证两阶段正例／canonical 往返与外观 False，再用独立字段增量覆盖未知字段／版本、bool／范围、UID失配、stage/storage 对应、profile、派生路径、路径别名字符串与控制／surrogate、duplicate／UTF-8／JSON边界、未初始化或 forged nested 类型、输入变异后捕获不变、外来 hook 零调用和异常链 None。路径 tests 只核字面规范，不声称物理别名保护。

同一最终套件只跑新记录与未改 owner record 的相关检查；不存在模块的 collection error 记未实现，不造行为 red。保持默认 guards，不借 codec 测试扩大宿主资格。root 审稳定源码 diff 和测试，再由独立 executor 审稳定版本；仅元数据通过，不勾完 T079/T080/T081/T090。当前正式7/100、Full/owner/数据库与自动审核 gate 不变。
