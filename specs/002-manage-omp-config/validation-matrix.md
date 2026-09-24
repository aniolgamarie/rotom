# OMP 验证覆盖矩阵

本矩阵定义实施后的最低验收覆盖，不记录本轮设计文档编写为功能通过。场景均须按
[验证指南](quickstart.md)记录命令、环境、退出码、断言和证据路径。状态词只允许“通过”、
“失败”、“未执行”或“环境不足”；没有实际运行记录时一律为“未执行”。

## 当前验收边界

2026-09-24 用户确认当前机器无对应平台/账号环境；[范围修订](scope-change-20260924.md)将 Linux arm64/macOS 实机、真实登录、真实 usage、指定模型调用移至[OMP-F01–F05](../../docs/follow-ups/omp-platform-and-live-validation.md)。本矩阵保留这些行用于追踪未验证事实，不作为当前 spec 的完成门禁。当前要求为隔离验收、文档与本机 Linux x64 无账号九行 smoke，均已完成。

## 场景目录

| ID | 场景与主要断言 | 层级 |
|---|---|---|
| V01 | 严格 schema、引用、能力和合并语义；未知/不支持输入返回 2，处理配置时不执行技能或扩展 | 隔离 |
| V02 | 八类配置从声明、确定性 render、plan、apply 到原生发现；主题和快捷键分别取证 | 隔离 + 真实宿主（授权） |
| V03 | plan 展示目标/身份/来源/归属/差异；三方比较、重复 apply 无写入/无备份轮换 | 隔离 |
| V04 | 两个受管配方稳定映射两个唯一原生 profile；HOME=`<instance>/user-home`，`.omp`、XDG、账号/会话、状态、备份和锁互相隔离 | 隔离 |
| V05 | 用户提供 profile/身份环境覆盖以 2 失败；已部署目录/identity/守卫冲突以 4 失败；身份碰撞、改名和状态根规避均被阻止，不回落 default | 隔离负向 |
| V06 | 默认快捷键继承和显式来源可解释；preflight 按固定清单拒绝 cwd/祖先 `.omp`、generic/direct 上下文及 `.env`；opt-in 仅声明根的只读非秘密 skills/MCP 且不能覆盖保护项 | 隔离 + 真实宿主（授权） |
| V07 | `inventory omp --source ABS` 只读写私人 cache 的 `disposition.json`、allowlist `local-overrides.toml` 和扫描后的候选资源包；review-required 不自动导入且不写来源/仓库 | 隔离 |
| V08 | secret/auth/trust/session/log/cache 哨兵不进入 render、plan、capture、摘要、异常、备份；完整技能包资源关系保留 | 隔离 |
| V09 | OMP 扩展逐项兼容；受管 auth broker 禁用；不以 Pi 可用推定 OMP 可用 | 隔离 + 真实宿主（授权） |
| V10 | 锁定无补丁的官方 v18.3.0/固定提交、standalone binary SHA 与包摘要；关闭宿主/marketplace 自动更新；sync 暂存验证后激活，失败保留上一包且不用全局安装 | 隔离依赖替身 + 真实宿主 smoke（授权） |
| V11 | validate/render/plan/default doctor 离线；sync/apply/run/login 分离；run 不隐式安装、部署、登录 | 隔离 |
| V12 | 原生 usage 的 argv、调用者完整 cwd/env/PATH、stdout/stderr/退出码透传；不读 workspace/secrets、不写 rotom 状态；缺程序为 5 | 隔离假进程 |
| V13 | 受管 usage 复用 runtime gate，以 neutral cwd 执行 `omp --profile NAME usage ...`；身份冲突为 2，跨 profile 哨兵零变化 | 隔离假进程 |
| V14 | usage 覆盖未登录、不支持、部分失败、缓存/窗口及国内智谱/Z.AI/Kimi/OpenAI 区分；缺失不写零且不抓 Cookie | 隔离假输出；真实 usage 转 OMP-F04 |
| V15 | 漂移、双方冲突、活动实例、pending 分别通过显式 apply/rollback 恢复（不扩展 recover pi）及配置回滚；非受管新增数据保留，成功 rollback 消费备份 | 隔离故障注入 |
| V16 | 目标非空/异主/链接/权限冲突、另一管理器写入及恢复未完成按 4/6 契约失败，无接管 | 隔离负向 |
| V17 | 新受管身份显式登录；旧认证/会话不复制；auth broker 不跨 profile | 隔离哨兵；真实登录转 OMP-F03 |
| V18 | DSH/Pi 全量回归及跨工具哨兵零变化；OMP profile 不重解释既有 profile | 隔离回归 |
| V19 | 文档、AGENTCFG-F01、需求和证据双向链接；平台、账号、真实服务及 macOS 未验证范围准确 | 静态检查 |
| V20 | 退出码 0/2/3/4/5/6 与可操作错误；原生进程成功启动后保留其任意退出码 | 隔离参数化 |
| V21 | `rotom-` + `sha256(UTF-8 profile.id)` 前 24 hex 的稳定性、合法性和完整 identity 碰撞校验 | 隔离属性/表格测试 |
| V22 | Linux 固定版本宿主只做配置发现 smoke，不登录、不查 usage、不调用模型 | 真实宿主 smoke（独立授权） |
| V23 | macOS 对路径、发现、依赖和宿主行为的同等验收 | 独立遗留 OMP-F02（未验证，不计本 spec） |
| V24 | Linux glibc x64/arm64 与 macOS x64/arm64 平台选择；musl/Windows 首版在安装/运行前返回 5，且不回退全局安装 | 隔离平台替身 + Linux x64 实机；其他实机转 OMP-F01/F02 |

## 八类必交能力

FR-002 的“主题/快捷键”为一个大类，但两项必须分别有样例和原生证据，因此拆成九行。

| 配置类别 | 隔离场景 | 必须成功的原生观察 | 负向边界 |
|---|---|---|---|
| 模型/provider | V01、V02、V08 | 精确 provider/model 映射被发现；真实生成另授权 | 未知 protocol/字段、缺引用、secret 泄漏失败 |
| 模型角色 | V01、V02 | main 和已支持辅助角色解析到所选模型 | 未选模型、未知角色失败 |
| 规则 | V02、V06 | 两份已声明规则被目标 profile 发现 | 未声明 HOME/project 规则不参与 |
| 完整技能包 | V02、V08 | `SKILL.md`、脚本、资源及相对引用完整发现 | 断链、越界路径、配置期执行失败 |
| 提示词 | V02 | 命名提示词可由目标 profile 使用 | 未支持字段失败 |
| 主题 | V02 | 选中主题生效 | 不修改 default profile |
| 快捷键 | V02、V06 | cycleForward=Ctrl+P 和 history.search=[] 生效，获准继承来源可解释 | 未声明继承/来源失败，不合并账号状态 |
| 扩展 | V01、V02、V09、V10 | 固定来源且经 OMP 兼容验证的扩展加载 | Pi-only、未锁定或 auth broker 拒绝 |
| MCP | V01、V02、V08 | 原生发现锁定本地 stdio fixture，tools/list 与一次受控调用成功；HTTP 映射另测，外部真实服务另授权 | 无效 transport/凭据组合失败，离线阶段不连接 |

判定规则：九行的隔离证据齐全且相应真实宿主观察全部通过，八类覆盖率才可记为 100%。
SC-001 的原生生效以本机 Linux x64 九行观察判定；其他平台和账号验收转独立遗留，不计本 spec 完成门禁。

## 功能需求覆盖

| 需求 | 覆盖场景 | 关键证据/通过条件 |
|---|---|---|
| FR-001 | V02、V03、V11、V15 | validate/render/plan/sync/apply/doctor/run/capture/rollback 全生命周期，各命令副作用符合契约 |
| FR-002 | V02、V09 + 八类表 | 九个验收行均有支持样例；主题、快捷键分别通过；范围外输入明确失败 |
| FR-003 | V01、V03 | 未知字段/引用/覆盖/能力失败；对象递归、数组替换、`[]`、`false` 和原生未受管字段保留均有断言 |
| FR-004 | V03、V15、V16 | 写前差异/归属/冲突可审阅；三方比较、幂等、上一备份和 apply/rollback 两条 pending 恢复路径通过 |
| FR-005 | V04、V05、V21 | 配方与新建原生命名 profile 的稳定唯一绑定；不绑定已有 default/命名 profile |
| FR-006 | V04、V05、V13、V15 | 部署/检查/启动/capture/rollback/usage 使用同一身份；重复拥有或身份变化失败并报告迁移 |
| FR-007 | V04、V13、V17、V18 | 配置、账号/会话、实例、缓存、备份、锁跨 profile/工具哨兵零变化 |
| FR-008 | V05、V13、V21 | 空白、保留名、穿越、重复选择、`OMP_PROFILE`/`PI_PROFILE`/目录覆盖和透传冲突以 2 拒绝 |
| FR-009 | V06 | default/命名 profile、快捷键继承、project/外部发现、覆盖层来源可解释；默认文件不改 |
| FR-010 | V04、V05、V23 | HOME/XDG/`.omp` 有效路径与部署记录一致；重定向或迁移不能维持隔离时运行前失败 |
| FR-011 | V07、V16 | inventory 只读且仅写私人 cache；三类产物齐全，每项有处置/理由；用户手工合并 TOML、复制批准资源并声明后走 validate/render/plan/apply，无 import 子命令 |
| FR-012 | V07、V17 | 只向新环境导入非秘密配置；旧环境与认证/会话零变化；登录仅走显式受管入口 |
| FR-013 | V07、V08 | inventory 执行路径/敏感字段/已知秘密扫描，review-required 不自动导入；capture 只提议 theme/keybindings/modelRoles；认证/trust/会话/日志/缓存不进入提案 |
| FR-014 | V08、V16 | secret 哨兵在公共配置、render、差异、摘要、异常和备份出现次数为零；不可分离数据拒绝 |
| FR-015 | V01、V08、V09 | 技能包完整；扩展逐项 OMP 结论；配置阶段脚本/扩展执行次数为零 |
| FR-016 | V10、V24 | 来源、版本、提交、二进制 SHA、包摘要和锁齐全；自动更新关闭；失败激活或不支持平台不破坏上一包或任一 HOME |
| FR-017 | V11 | 离线命令无网络/安装/部署/启动；lock/sync/apply/run/login 各自显式且不串联 |
| FR-018 | V12、V13、V20 | `agentcfg usage` 参数、stdout、stderr 和已启动原生进程退出码逐字节/逐值透传 |
| FR-019 | V12 | 无 local/profile 也可 PATH 调用；不读 secrets/其他 profile，不写 rotom；缺程序返回 5 |
| FR-020 | V13 | 显式受管选择复用已部署 runtime/身份；global opts 前置；原生参数不被误吞；身份冲突为 2 |
| FR-021 | V12、V13、V14 | 只查询所选原生上下文可访问账号；认证目录跨 profile 读取次数为零 |
| FR-022 | V12、V14 | 无账号、不支持、部分失败、缓存/窗口原义保留；缺失不造零；机器输出不混说明 |
| FR-023 | V14、V19 | 固定版本 usage 入口和 provider 支持有不可变依据；国内智谱/Z.AI 分开；无 Cookie/独立采集 |
| FR-024 | V12、V13、V14 | 只有显式 usage 可触发对应原生网络/缓存/认证刷新；安装/登录/生成调用次数为零 |
| FR-025 | V05、V10、V12、V16、V20 | 管理器 0/2/3/4/5/6 语义和原生退出码参数化验证，错误含可操作修复提示且无秘密 |
| FR-026 | V18 | DSH/Pi 回归通过；其配置、部署、账号、目录和 profile 解释均不变 |
| FR-027 | V19 | 使用、profile、迁入和遗留状态文档互链；AGENTCFG-F01 有证据；无关缺陷未关闭 |
| FR-028 | V01–V24 | 隔离证据与真实宿主/登录/usage/模型证据分层；未执行和 macOS 不计通过 |

## 成功标准覆盖

| 标准 | 覆盖场景 | 量化判定 |
|---|---|---|
| SC-001 | V01–V03、V11、V15、V22 + 八类表 | 一个配置集生命周期闭环；八类覆盖 100%，九个验收行各至少一个样例成功；范围外输入 100% 明确失败；未授权原生生效保持“未执行” |
| SC-002 | V04、V05、V13、V17、V18 | 两个受管配方、default 原生环境、DSH、Pi 的配置/账号/会话哨兵意外变化数为 0 |
| SC-003 | V03、V15、V16 | 重复 apply 的目标写入和备份轮换均为 0；全部冲突/活动/中断用例无静默覆盖且可恢复 |
| SC-004 | V07、V08、V17 | inventory 处置率 100%；secret 在所有禁止产物出现 0 次；旧环境变化 0；新环境复制的 auth/session 0 |
| SC-005 | V12–V14、V20 | 原生/受管 usage 的 argv、输出、退出码对照全部匹配；五类负向结果均可重复 |
| SC-006 | V14、V19、V23 | AGENTCFG-F01 范围 100% 映射；不可复核结论均有限制；平台/账号未验证计入通过数为 0 |
| SC-007 | V04–V06、V13、V19、V21 | 对每个配方，报告唯一给出原生身份、来源、账号作用域和切换保留数据，无需同名推断 |

## 负向与回归最小集

以下要求适用于当前范围内的隔离测试及 Linux x64 smoke；转出平台/账号的实机步骤按 OMP-F01–F05 维护，不再阻塞当前特性完成：

- profile：空、空白、保留 default、路径穿越、规范化碰撞、重复参数、环境冲突、身份被占用；
- project/.env/XDG：默认外部发现关闭，无法关闭的 project 输入 preflight 失败，显式 allowlist 后才加载，XDG/HOME 重定向冲突失败；
- auth：旧认证/会话不复制，未登录不借用其他 profile，auth broker 禁用且不能跨 profile；
- ownership/recovery：非空目标、异主、链接、权限、第二写入者、活动实例、pending、中断、双方漂移、rollback 后非受管数据保留；
- lock/runtime：SHA 或包摘要不匹配、缺包、版本/提交不符、暂存验证失败、全局 OMP 不能替代受管包；
- 平台：musl 与 Windows 返回 5；glibc/macOS 的一个架构通过不能替代另一个架构；
- usage：PATH 缺程序、无账号、不支持、部分失败、原生任意非零、机器输出、冲突 profile 参数、neutral cwd；
- secret：render/plan/capture/异常/摘要/备份逐一扫描，禁止内容命中数为零；
- 回归：DSH 与 Pi 的 validate/render/plan/apply/run 相关现有测试，以及跨工具状态哨兵。

## 当前证据状态

日期：2026-09-24。完整命令、平台、退出码和工作树来源见[最终回归](evidence/regression.md)。下表按验证层分别判定；任务与需求入口见[tasks.md](tasks.md)，并由上面的 FR/SC 表反向定位场景。

| 项目 | 状态 | 说明 |
|---|---|---|
| 全仓隔离回归 | 通过 | 2151 项及 7 个子测试实际通过，退出 0，包含 281 项 OMP 测试与既有 DSH/Pi/公共路径 |
| V01–V21、V24 的隔离/静态部分 | 通过 | 下表列出实际测试入口与证据；不含各场景要求的真实宿主/账号部分 |
| 文档链接与 diff 空白检查 | 通过 | 本地 Markdown 目标存在性与 `git diff --check`；不作为功能证据 |
| V02/V09/V10/V22 Linux x64 九行原生部分 | 通过 | [真实 smoke](evidence/linux-smoke.md)：模型/角色/规则/技能/prompt/主题/按键/扩展/MCP；V06 project opt-in 负向仍仅隔离验证 |
| Linux arm64 实机部分 | 环境不足 | 已转 OMP-F01，不计当前门禁；不由 x64 推定 |
| V23、V24 macOS 实机部分 | 环境不足 | 已转 OMP-F02，不计当前门禁；隔离平台选择测试不能替代 |
| V17 新 profile 真实登录 | 未执行 | 已转 OMP-F03，不计当前门禁；恢复时独立授权，不复制旧账号 |
| V14 真实 usage | 未执行 | 已转 OMP-F04，不计当前门禁；恢复时独立授权，可能联网/刷新缓存或认证 |
| 真实模型调用 | 未执行 | 已转 OMP-F05，不计当前门禁；恢复时需指定 provider/model 的独立授权 |

## 实际证据与 FR/SC 双向追踪

测试路径均相对仓库 `tests/`。表内“通过”严格限定为隔离/静态部分；真实层按上一表处理。

| 需求/标准 | 场景 | 实际测试入口与证据 | 隔离/静态状态 |
|---|---|---|---|
| FR-001–004、FR-015；SC-001 软件部分、SC-003 | V01/V02/V03/V09/V11/V15/V16 | `test_omp_adapter.py`、`test_omp_pipeline.py`、`test_omp_capture.py`、`test_omp_resources.py`；[US1](evidence/us1.md) | 通过 |
| FR-005–010；SC-002、SC-007 | V04/V05/V06/V13/V18/V21 | `test_omp_profiles.py`、`test_omp_discovery.py`、`test_omp_source_gate.py`、`test_omp_migration_flow.py`；[US2](evidence/us2.md)、[回归](evidence/regression.md) | 通过 |
| FR-011–013；SC-004 | V07/V08/V16/V17 | `test_omp_inventory.py`、`test_omp_migration_flow.py`、`test_omp_login.py`；[US3](evidence/us3.md) | 通过 |
| FR-014；SC-004 秘密边界 | V08/V16 | `test_omp_secret_boundaries.py`、`test_omp_capture.py`、`test_omp_inventory.py`；[安全](evidence/security.md) | 通过 |
| FR-016–017 | V10/V11/V24 | `test_omp_dependencies_foundation.py`、`test_omp_dependencies.py`、`test_omp_platforms.py`；[基础](evidence/foundation.md)、[US5](evidence/us5.md) | 通过 |
| FR-018–024；SC-005 | V12/V13/V14/V19/V20 | `test_omp_usage_native.py`、`test_omp_usage_managed.py`、`test_omp_usage_results.py`；[US4](evidence/us4.md)、[官方来源](evidence/usage-sources.md) | 通过 |
| FR-025 | V05/V10/V12/V16/V20 | `test_omp_runtime_foundation.py` 及 usage/依赖/生命周期测试；[基础](evidence/foundation.md)、[回归](evidence/regression.md) | 通过 |
| FR-026；SC-002 跨工具部分 | V18 | 全仓既有 DSH/Pi 回归、`test_omp_migration_flow.py` 多环境哨兵；[回归](evidence/regression.md) | 通过 |
| FR-027–028；SC-006 | V19 与全部场景分层 | [支持状态](../../docs/omp-support.md)、[AGENTCFG-F01](../../docs/follow-ups/agentcfg-usage-command.md)、[实施记录](implementation-progress.md)、[回归](evidence/regression.md) | 通过 |

SC-001 的九行隔离样例与生命周期已通过；[Linux x64 九行原生观察](evidence/linux-smoke.md)现已通过，按修订范围 SC-001 的原生验收已满足；仅该平台计入原生覆盖，其他平台移至独立遗留且仍未验证。SC-002/SC-004 的零哨兵变化与零复制结论来自合成环境；真实登录旧环境保持情况未验证。SC-005 的逐字节结果对照来自明确标记的合成原生输出，真实账号额度或 provider 成功率不在通过范围。SC-006 只关闭 AGENTCFG-F01 软件范围，未把未执行平台/账号计为通过。

本轮自检扩展/包摘要更新后的受影响回归为 57 项通过；上表全量计数属于此前软件阶段，两者执行范围与时间分别见[回归](evidence/regression.md)和[Linux smoke](evidence/linux-smoke.md)。
