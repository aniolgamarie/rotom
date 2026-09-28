# Data Model: termcfg

本模型描述非秘密同步事实。所有路径均在加载机器配置时校验；公开来源与私人目标使用不同信任边界。对象字段名称供后续契约与任务引用，不要求持久化采用某一种语法。

## 1. MachineSelection

| 字段 | 含义与约束 |
| --- | --- |
| `machine_id` | 单一路径段 ID；与 agentcfg 机器文件独立 |
| `target_home` | 当前用户拥有的绝对目录；默认当前 HOME，显式测试可指临时 HOME |
| `components` | `zsh`、`tmux`、`mihomo` 的子集；空选择合法，只用于查看组件 |
| `private_state_root` | 当前用户独占的状态与备份目录；不得位于公开仓库 |
| `platform` | 检查得到的 OS、架构和必要能力；不得仅信任用户填入值 |

机器文件本身是 0600 普通文件，私人父目录为 0700。未知字段失败；不保存订阅 URL、controller secret 或会话状态。

`OperationLease` 位于固定私人 XDG 状态根的 `termcfg/leases/machines/<machine_id>.lock`，不从尚未读取的机器配置推导，因而首次 `init-local` 也能先锁定。锁文件为当前用户所有、单硬链接的 0600 普通文件，父目录逐级 0700；配置中的 `private_state_root` 保存备份和 journal，不可重定向活动锁。通过 no-follow 打开并取得内核非阻塞独占文件锁；PID/时间戳仅供脱敏诊断，不作为解锁依据。`init-local` 新建或编辑、`apply`、执行型 `rollback`、`sync` 与会修改租约/状态的 `service` 操作在读取可变状态前取得同一机器锁，保持至状态提交或写下 `recovery_pending`；占用时返回 4，不等待或终止持锁进程。只读 `plan/doctor/status/rollback --plan-only` 不修改状态，报告观察到的活动操作或未检查。

`RepositoryLease` 另位于固定私人 XDG 状态根的 `termcfg/leases/repos/<仓库规范路径摘要>.lock`，为当前用户所有、单硬链接 0600 普通文件，父目录逐级 0700；`machines/` 与 `repos/` 两个目录不相交，任意合法 machine_id 均不能与仓库锁同路径。它按规范化仓库路径跨本机所有机器选择共享，不是机器锁。`lock` 在共享模式下读取旧锁身份，联网准备期间释放，再以非阻塞独占模式取得仓库锁并复核旧锁身份后原子提交；另一维护者已提交则返回 4，不以“后写覆盖前写”作为成功。`sync` 在机器锁内取得仓库共享锁读取完整锁快照，下载时可释放；激活和提交所选 core/待生效状态前重新取得共享锁并复核快照身份，保持到本机状态提交。执行型 `apply` 先取得机器锁，在锁内重算并复核预览、展示目标与影响及收集确认；确认后再取得仓库共享锁，复核锁、来源、目标和状态身份，保持两锁到配置提交或持久恢复记录。统一锁顺序为机器锁先、仓库共享锁后；`lock` 只取仓库独占锁。只读 `plan/doctor/status` 不创建锁文件，依靠原子读取和执行前复核。仓库共享锁冲突或快照过期返回 4，保留已验证缓存但不提交过期版本选择或 HOME 覆盖。

## 2. Component & SourceArtifact

`Component` 包含 `id`、公开来源版本、目标列表、必要/可选环境条件和平台范围。首版 ID：`zsh`、`tmux`、`mihomo`。一个目标只属于一个组件；选择集合合并后发现重叠即失败。

`SourceArtifact` 包含仓库内相对路径、内容摘要、预期文件类型/权限、源提交、许可信息。公开 shell 配置与 mihomo mgr 均可作为来源。mihomo core 与远程插件是版本化 `LockedAsset`，包含不可变版本/提交、平台键、官方来源、长度、SHA-256、解包方式和必要入口/资源；若未锁定对应平台，组件环境状态为 `unsupported`，不从 PATH/latest 兜底。`lock` 显式生成完整锁，`sync` 只消费现有锁并在当前用户独占的 0700 版本化运行包目录安装，配置 `apply/rollback` 不覆盖或回退软件包。下载归档、元数据及非可执行资源为当前用户所有的 0600 普通文件；声明的可执行入口为当前用户所有、无组/其他访问权且带执行位的 0700 普通文件。暂存及激活后均核验目录形状、属主、硬链接/符号链接边界、摘要与 mode；运行包不存私人配置或秘密。

## 3. TargetRecord

| 字段 | 含义与约束 |
| --- | --- |
| `component_id`, `target_id` | 唯一所有权键；目标路径由声明清单生成，不来自不受限 glob |
| `relative_path` | 相对 `target_home` 的受限路径；特殊 runtime/package 路径单独声明 |
| `kind` | 目标预期为普通文件；旧 symlink 仅可显式接管并保存链接本身 |
| `mode` | 部署后权限；`.zshenv` 和私人状态为 0600，公开配置/脚本按清单核实 |
| `source_digest` | 确定性非秘密期望字节的摘要 |
| `baseline` | 上次受管版本的目标身份和摘要；不存正文 |
| `after` | 本次成功同步后的目标身份和摘要；不存正文 |
| `adoption` | `none` / `approved`；仅针对本次预览中的具体未受管目标 |
| `status` | `absent`、`unmanaged`、`unchanged`、`update`、`drift`、`conflict`、`pending` |

目标身份至少含文件类型、属主、设备/inode、mode 和变更标识；通过非秘密准入后才计算并记录内容摘要用于检测改动，不能单靠 mtime/size。未通过或无法判定的旧目标只记录阻断原因，不计算或输出正文摘要。来源和目标中的秘密正文不得进入 `TargetRecord`。

## 4. Preview & EnvironmentReport

`Preview` 记录机器选择、来源/锁身份、逐目标操作、备份需求、预计影响、目标读取身份、未受管接管需求、`.zshenv` 覆盖确认和只读生成时间。它只在私人缓存保存无秘密元数据；执行前必须重新读取来源、状态、目标并比较，不得把旧预览当写入授权。确认可以绑定本次预览身份，缺确认或身份变化均停止。交互式 apply/rollback 可在同一次命令内展示预览并确认，不要求手工复制 ID；非交互 apply 使用应用预览 ID，非交互 rollback 使用 `rollback --plan-only` 生成的独立回滚预览 ID。

`EnvironmentReport` 对每组件保存 `required_blockers`、`optional_degradations`、`unverified`、`ready` 和 `next_action`，并汇总 `overall_ready`。只读计划与诊断不自动安装程序、不探测真实订阅。文件存在、核心可执行、服务健康、配置已生效是不同事实。

## 5. EffectState、BackupSet & TransactionJournal

`EffectState` 在 US1 即作为严格校验的非秘密私人状态建立：记录机器 ID、下一次启动选用的锁定 core 身份、已部署的公开配置身份，以及分别持久的 `pending_core_effect` 和 `pending_config_effect`。`sync` 成功选定新 core 后，在同一机器活动锁内提交 core 待生效原因；`apply` 成功且确有公开代理配置变更后，在其事务提交时记录配置待生效原因。失败或无变化不新增原因，不能仅因文件存在而声称服务已经使用新版本。US3 的 `ServiceLease` 与健康检查只负责核验和清除相应原因。状态不含私人订阅、有效 YAML 摘要或密钥。

`BackupSet` 按组件保存最近一次**成功且有实际变更**的配置应用前版本；每个目标保存原不存在/普通文件/旧链接状态、必要权限、私人备份路径和完整性摘要。单次 `apply` 中所有选中组件的既有配置目标均先完成备份并核验，才允许第一笔目标写入；任一备份失败则本次调用零覆盖。含秘密或无法安全归类的目标不得生成普通 `BackupSet`；用户先迁出秘密。版本化 core/插件软件包不进入配置 `BackupSet`。

`TransactionJournal` 记录预期前后状态、逐目标阶段与恢复动作，阶段为：

```text
prepared → backed_up → writing → committed
                       ↘ recovery_pending → recovered
```

`prepared` 前必须取得 `OperationLease` 并完成环境、所有权、来源和确认检查；本次所有组件均达到 `backed_up` 前不得写任何目标；`writing` 开始后中断须保留 journal。恢复先复查当前目标身份，只逆转仍符合本次操作预期的目标；外部改动导致冲突，不能覆盖。`committed` 才轮换上一版备份并安全清理更旧的成功配置备份集合；无变化应用不轮换。成功 rollback 消费该组件上一版备份，不降级 core 或插件。

多组件选择先完成整次调用的预检查、全部备份及校验，再按组件事务写入；备份阶段任一组件失败时所有目标保持原样。进入写入阶段后的组件失败不应把其他组件的状态伪报为成功。输出必须逐组件报告实际结果。

## 6. MihomoPrivateRuntime & ServiceLease

`MihomoPrivateRuntime` 位于当前用户独占的 0700 私人运行目录，存放由 mihomo mgr 持有的订阅、凭据、路由、有效配置、日志和统计；其中含秘密的普通文件为当前用户所有且权限 0600。`termcfg` 普通记录只保留公开基础配置摘要及 `private_ready` 布尔/原因码；不读取私人值作为 plan 输出。显式服务操作可在受限进程内读取私人值，以结构化 YAML 序列化器生成并校验仅供该次运行使用的 0600 私人有效配置；它是启动时的私人运行注入资料，不进入普通渲染产物、摘要、日志、状态或配置备份。

`ServiceLease` 只记录本管理器启动的 core 的 UID、PID、进程开始身份、可执行文件/锁身份、**非秘密公开基础配置摘要**、控制端身份与状态；不得对包含私人订阅或 secret 的有效 YAML 计算或保存摘要。状态：

```text
stopped → starting → running → stopping → stopped
            ↘ failed     ↘ unknown/external
```

PID 复用、可执行文件变化、属主不符或外部系统服务均成为 `unknown/external`，禁止 `stop/restart` 接管。`sync/apply` 已在 US1 更新 `EffectState`，两者均不触碰运行中进程；`status` 分别展示这两个待生效原因，合并展示时可称 `pending_effect`。显式 start/reload/restart 后需分别核对进程可执行版本、健康和安全可观察的公开配置加载证据，才能清除相应原因并标为 `effective`；不能证明有效配置已加载时为 `unverified`，不得以私人有效 YAML 摘要填补证据。控制 API 可能要求私人 secret，输出只报告原因码。

## 7. 核心不变量

1. 未选择、未声明或未取得所有权的目标没有写入路径。
2. 来源内容和预期目标内容均为非秘密；未知/疑似秘密目标在普通备份前被拒绝。
3. 先完成所有备份、再覆盖文件；覆盖失败不能抹去备份或 journal。
4. 不因文件同步启动、停止、重载或重启服务；服务操作不覆盖配置文件。
5. `status` 不用“文件已同步”推断“服务已生效”；无证据即 `unverified`。
6. 同一机器的可变状态和目标写入必须在一把内核独占活动锁内完成；只读命令不冒充持锁操作已完成。
