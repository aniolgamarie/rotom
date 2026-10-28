# 验证指南

**历史当前终端验收（2026-10-27；不涵盖新增位置路径）**：官方 DSH/Pi/OMP 贯穿公开 CLI 的停止、实际配置更新、停止清单及原会话恢复均已通过；main 新 Pi 锁的 Base/Pro 另经完整闭包和原生验收。OMP 退出与查询的短锁竞争已修复并复验；候选仍需人工批准合入 main。详见[验收记录](tool-workflow-validation.md)。

## 当前候选的并发与交接边界

驻留 parent 在 child 存活时不轮询 owner/Domain，退出后才核验出生身份及完整释放。active 位置只是按 child/manager 身份关联的候选，不能代替原位 parked/saved run 门禁。Domain 写事务默认仅首锁前等待 2 秒，显式 deadline 不续期；外部只读默认 NB，仅合作启动 package_guard/check_omp_launch 两处显式读预算。OMP 资源/anchor 选择和预留同写事务完成，提交后才返回 token，通用 reserve CAS 保持。停止最终查询复用原截止点，过期只作无竞争观察，不重 close/信号。V1 accepted 后正常清 pending，驻留包装使用 accepted 前最后核验的 caller。

最终十二组无 trace 位置原生验收已通过，准入限六个精确 Linux managed 组合；此前完整隔离快照14,153 passed / 13 skipped（共14,166个唯一测试）；共享预算修正另有3740 passed / 4 skipped和官方Pi Base双会话原生复验，前一快照 `14102 + 13 skipped` 保留为历史。功能尚未合入 main，T125 待人工批准。

## 当前候选验证与操作

候选实现、分组回归及稳定差异审查已完成；基于 main `45953f0`，保留在分支 `feat/tool-maintenance-workflows-20261026`，尚未合入 main。合入须另经人工批准。官方 Pi/OMP TUI/PTY、隔离回归及受影响复验见[验收记录](tool-workflow-validation.md)。

逐阶段命令、TTY/非 TTY、取消及旧批次兼容见[维护流程指南](../../docs/tool-maintenance-workflows.md)。候选三工具 stop_only → 关本次 fence → 最新独立 setup 批准/原全门禁 → 逐项当前终端恢复。Pi Claims 仅合作进程；OMP 同 ID open 不取锁，竞争首次写入可能分叉新 ID；都显示加载待确认，零继续。

Herdr 新标签页与薄驻留原 pane 候选已经实现；最终十二组无 trace 原生验收全部通过，现仅开放六个精确 Linux managed 组合的两种位置。两种位置只面向已停止且已完成 setup/update 的完整 maintenance workflow，普通 --session 位置恢复不开放。普通 shell 启动退出后返回 shell，旧普通实例不升级。仅停止 Agent 并保留 launcher/pane 才能等待原位恢复；launcher/pane 丢失或身份不明时改用当前终端或明确接受的新位置。统一严格加载回执、原生 TUI 自动继续及 Pi Pro 委派不在本轮承诺内；`pi-pro` 普通 profile 的停止、更新与恢复兼容性保留。详见[原位置能力指南](../../docs/rotom-pane-capabilities.md)。

最终集合按分组及受影响完整文件复验对账：13,561 passed / 12 skipped，未解决失败与未覆盖均为 0；这不是一次未中断的全绿运行。原始失败和精确范围见验收记录，不累加重叠组。该阶段为 93/125，新增停止历史阶段为 97/129；T125 的 main 人工整合仍待批准；历史勾选含义保留。

## 历史恢复验收口径（2026-10-24）

首版真实执行现有官方显式 session 恢复到用户选择的终端，沿用已部署 runtime、native HOME/scope、原目录与租约。分别验收请求目标、启动派发、实际加载确认、继续发送。缺严格初始回执不再阻塞启动实现；已发起而未确认时应显示“已发起恢复，加载待确认；请在 TUI 检查；未发送继续”，不得写 `restored` 或把未知写成 `failed`，不自动重试或超时强杀。

范围、归属、cwd 或原生 writer 冲突防护不足仍拒绝自动派发并给出人工操作说明。直接在官方 TUI 操作属于人工交接，人工观察不升级为可信回执或自动输入许可。自动继续默认关闭，完整目标、加载、ready、writer 与接收能力另行准入。

T042 改为现有官方入口、实际 HOME/scope、writer 和状态边界调查及原型。T053 已完成 Linux 固定组合的受控交接、合成历史、缺失目标、活动 TUI 和外部 writer 拒绝验收，机器态仍待确认；额外请求已定位为 TUI 自动回顾，T054 精确组合的默认入口及独立原生复验已完成，不等待新上游接口。缓存 Core 两个内存 case 不是恢复验证。严格回执提案未发送、当前不计划提交，仅属可选历史研究，不是交付依赖。以下旧阶段记录不重新计为新范围通过。

T117 已完成对应隔离契约更新：安全官方交接能力充分、但没有严格加载回执时，只派发一次，保持加载待确认、零继续、零自动重试，超时不强杀；保留范围/cwd/缺失目标/writer 冲突负例。当时总数117、完成86；这是历史快照，当前任务状态以 tasks.md 为准。T096/T101/T102 仅完成零发送与人工分支，T053 已完成固定组合的真实交接验证，T054 已独立核验实际准入接线；完整停止维护尚未完成。

## 历史 DSH 精确停止（main 基线阶段）

该 main 基线阶段的 `stop_only` 当时仅准入 Linux managed DSH、完整锁
`e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d` 和新启动后成功登记的原 host/control endpoint。
默认普通 runtime 的三实例原生验收已通过：首轮真实 CLI 仅停止前两项，第三项 owner/出生身份
仍 active、inbox 空、journal 无记录、共享 EX 仍忙；独立新 plan 再只清理第三项。
三项均 exit 0、idle_confirmed、termios 恢复、原 inode 租约释放、输入为零且源码未变。
[完整证据](main-review.md#62-dsh-默认入口的精确停止验收) 不扩大为并发启动、会话恢复或维护准入。
该历史阶段为 86/117；当时已验收的基础范围已合入 main，完整维护控制 CLI 尚未开放。后续 workflow 与本次位置候选分别见本文开头，不沿用该历史状态判断。

内部维护已保存首次同步前的目标部署摘要，并提供只读现场观察，见[第 72 节](main-review.md#72-目标部署绑定与只读现场观察)。
隔离检查包括目标契约、apply 后的命名锁/owner/资源复核，以及只读观察的竞争、pending 和结果不升级。
观察匹配不证明历史执行成功，不清保护或代替 journal 恢复；内部观察本身不授予维护控制能力，当前只读 CLI 范围见下文。

明确成功后的内部人工交接另见[第 73 节](main-review.md#73-成功维护收尾与人工恢复交接)：需要独立批准和新一轮完整现场核验。
交接只结束本批资源意图，保留人工待恢复清单和原维护结果，不执行恢复。未知、部分成功、pending 和目标不匹配仍拒绝。

先用完整机器/profile/run 做 dry-run，再显式提交当前 PLAN_ID；实际结果含 BATCH_ID 和 status/cancel 命令。
默认 30 秒、范围 1–300 秒，全部所选项共用同一绝对截止时间。
实际停止等待未确定或到期返回 4，保留 batch/快照/派发事实，不重发、不强杀、不自动恢复或继续。
status 只读；cancel 仅取消尚未投递项或对已确证停止项收尾对账，不能清除 unknown 派发。
该历史阶段的 setup/maintenance execute/restore、Pi/OMP 停止及其它平台、旧 run 和 force 当时仍未准入；
T054 的精确 Linux DSH `resume --here` 保持已有准入，加载仍待确认。

### 历史原生阶段与恢复证据

2026-10-26 用户已授权锁定、未经修改的官方 DSH 在专用隔离范围实际启动/停止验证，不再以缺授权列阻塞。直连及代理取包失败后，已从标准登记部署取得符合锁的已安装包副本；真实单宿主启动/单次精确停止/后代和原锁释放/终端恢复已通过有限验收。该轮零提示词、没有 session，因此不算恢复通过。此授权不涉及日常实例、真实账号/模型调用或自动继续。

同日另用本地模拟模型和合成历史实际验证受控 Rotom resume：原 session/cwd/历史可见、新 run、加载 unknown、继续 not_sent、恢复 stdin 为零；缺失 ID 在启动前拒绝。额外本地模型请求已通过公开 hook 定位为 TUI 自动回顾；旧零请求断言失败保留，修正后正例与最终活动 TUI 占用拒绝均通过，T053 已完成。外部 writer 冲突及释放后重取也通过独立验证，完整事实及失败见 [实施审查](main-review.md)；没有使用真实账号或真实模型。

日期：2026-10-23。状态：实施中；统一入口与严格记录层已有隔离阶段证据，整个功能未完成，DSH 当前终端恢复已有独立原生验收；T039 真实 zsh/Tab 已在本指南末尾所述的临时范围通过。
下文区分已有候选隔离验收、旧阶段 RED 历史和未来任务，不能将规划表或隔离通过当作日常原生准入。
历史承接阶段从 `109e2e7` 建立工作树并运行相关隔离回归，采用当时主线 OMP `18.12.6` 锁；旧 `39a9389` 工作树及原阶段证据保留。当前整合与后续增量的基线见 main-review。承接阶段没有执行第三方宿主或原生验收；后续已授权的 T039 单独记账。参见 [承接记录](main-review.md#6-实施承接与隔离验证)。
依据：[规格](spec.md)、[CLI 契约](contracts/cli.md)、[入口部署](contracts/entry-deployment.md)、
[生命周期](contracts/lifecycle.md)、[数据模型](data-model.md)。

## 旧 Linux OMP Domain 批次的只读维护状态

基于 main `18c342f` 的增量只开放现存 setup batch 的 status。显式公开 profile 的工具声明必须为 `omp`，
不按名称前缀识别，也不自动发现历史 batch/profile；local 或机器配置仍沿所选路径读取，不扫描其它机器。
没有显式 profile 继续走 DSH 原 status。将下例的 `BATCH_ID` 换为现存完整 32 位小写十六进制 ID：

```sh
./rotom --no-input agent --local /path/to/machine.toml --profile omp-default maintenance status --batch BATCH_ID --format json
```

支持 `auto/human/json`，不读 stdin、不写入、不启动宿主。JSON 将原 `operation_result` 与查询 `exit_code` 分开，
`protected` 只说明本批资源意图；当前资源核验看 observation，不能据此声称全局空闲。
原操作成功但未交接仍返回 4；completed 且当前目标/资源核验通过返回 0；unknown/pending 返回 4，
既有非零操作结果保留原退出码。初始未派发即取消且观察正常返回 0 仅说明取消，异常观察仍为 4。
逐项 manual 不等于会话已恢复，`continue_status=not_sent`。后续命令只有同一精确范围的 status；
这些旧 Domain 批次不支持新 workflow 的 stop/execute/restore/cancel；本命令不创建批次或完成交接。

CLI/DSH 控制回归及静态 help/parser 的稳定代码验收为 **336 passed**；fixture 对齐真实
`target-matches` 拼写后，新 CLI suite 为 **21 passed**。两轮有重叠，不累加，不作为宿主原生验证。
T077/T078 仅部分推进，仍为 **86/117**。

## 当前可执行的文档核查

在任务 worktree 根目录执行，仅检查文档和差异：

```sh
git diff --check
rg -n '^#{1,4} |待实现|阶段|未验证' specs/008-rotom-command-experience
rg --files specs/008-rotom-command-experience
```

预期：diff 检查退出 0；标题、状态和相对链接指向本功能及 007 来源材料。
逐项打开本指南顶部链接，确认产物存在；这是文档检查，不能记为行为测试或 R8 通过。
完整计划阶段结束前，主代理须补齐所有被引用契约。

## 实施阶段的现有离线回归

以下文件当前存在。这些命令可在已准备的仓库 `.venv` 中复制执行；不执行 `uv sync`
或下载依赖，不复用真实 HOME。没有 `.venv/bin/python` 时记录“环境不足未验证”，由实施阶段
另行准备环境。不要将不存在的 `test_rotom_*` 混入这组命令。

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_cli.py tests/test_entry.py tests/test_sandboxed_entry.py tests/test_cli_presentation.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agentcfg_interaction.py tests/test_cli_environment_interaction.py tests/test_termcfg_interaction.py tests/test_termcfg_interaction_failures.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_work_cli.py tests/test_work_entry.py tests/test_runtime.py tests/test_lifecycle_leases.py
```

预期：退出 0，兼容入口与已有范围行为保持；实际结果须在实施后记录，不能预填通过。
沿用 [tests/conftest.py](../../tests/conftest.py) 的临时 HOME/DSH_HOME/XDG、空 PATH、
网络阻断、假子进程和外部文件哨兵。新增测试不恢复通用进程/信号/网络权限；
模拟 TTY 用可注入 `isatty` 和选择器，不分配真实 PTY。

## 历史阶段隔离套件与当时状态

下表区分原阶段证据与本轮承接后的隔离结果，实际 argv、源码摘要和原始日志保存在私人任务记录。
所有新检查沿用临时 HOME/XDG、网络阻断、假子进程/事件和文件哨兵，不执行第三方宿主。
存在文件不等于对应机制已经完成；49 条会话契约的 5 项索引通过、44 项恢复/事件契约失败保留为旧契约历史结果。此后 T117 已完成修订测试，恢复协调器与事件跟踪已有候选隔离实现；当前任务为 86/117，不据此宣称整库 GREEN；T053 的独立真实恢复交接已验收，T054 默认入口亦已独立验收，停止能力仍分别核验。后续候选机制与验证范围见 [main-review 第 48–51 节](main-review.md#48-停止服务与-dsh-启动生命周期组合)。

| 已有套件的可执行命令或未来文件 | 状态与验收内容 |
| --- | --- |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_cli.py tests/test_rotom_defaults.py` | 已有隔离阶段证据；三工具短启动、默认矩阵、严格偏好、原生尾部及旧入口 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_interaction.py` | 已有隔离阶段证据；全部叶子输入门控、TTY/取消/批准与无 fzf 路径 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_help_completion.py` | 已有隔离阶段证据；静态 help、受限 NUL 候选与无副作用 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_entry_deployment.py tests/test_rotom_zsh_completion.py` | 已有事务/静态补全证据；不等于真实 zsh/Tab 验收 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_run_records.py tests/test_rotom_runtime_observation.py` | 严格记录层与 DSH/Pi 基础登记已正式通过隔离验收；OMP 合作登记见下方专项 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_resume.py tests/test_rotom_session_events.py` | T117/T046–T052 已有候选隔离验收；官方交接无回执时待确认、单次派发、零输入/重试、迟到失败/失联/超时不强杀；不是 T053 原生证据 |
| `node --test --test-isolation=none tests/node/dsh_session_observer_probe.test.mjs` | 临时 HOME、空继承环境下 36 passed；仅公开 channel 形状的元数据探针和纯内存宿主事务模型，不证明原生加载 |
| `node --test --test-isolation=none tests/node/dsh_resume_launch.test.mjs` | 临时 HOME、空继承环境下 3 passed；运行仓库 launcher 与临时假模块，不执行官方 Agent 或 TUI |
| `node --test --test-isolation=none tests/node/dsh_session_scene_probe.test.mjs` | 本轮 24 passed；公开 scene 注册、effect 工厂、props 观察和失效清理模型，未安装正式插件 |
| `node --test --test-isolation=none tests/node/dsh_session_attempt_probe.test.mjs` | 本轮支持执行器下 52 passed；新 run 私有 IPC、重放/目标/顺序拒绝、stdout 对抗及仓库 launcher→假 runProfile→scene 接线；最高 metadata matched，真实 HOME 归属和 native load 仍 unproven |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_known_sessions.py tests/test_rotom_instances.py` | 本轮已创建；严格历史会话视图、五类记录、单次机器配置快照、OMP 未登记占用及逐字段可信度 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_cold_start.py` | 已有隔离证据；统一与旧终端入口共用语法工厂，查询辅助模块按需加载模板引擎 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_benchmark.py` | 合成负载、输出隐私边界、固定场景与采样约定；默认不启动基准冷进程 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_resource_keys.py` | 本轮 66 passed；当前物理目录/租约文件身份、严格序列化、无正文读取及替换竞态，不证明域或维护许可 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_omp_resource_lease_identity.py` | 原阶段 9 passed；flock 后命名对象变化拒绝、跨实例共享包和继承 fd 寿命；该项本身不证明合作登记 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_resource_protocol.py tests/test_rotom_resource_coordination.py tests/test_omp_resource_coordination.py` | T113 基础原型及后续意图闭包加固；严格数据/物理域绑定、发布与提交故障、跨实例 unknown、意图 CAS；不开放维护 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_runtime_claims.py tests/test_rotom_resource_coordination.py` | T113 防降级跟进；单独租约或 leases 目录损坏、跨域声明检查、发布/父目录 fsync 失败、metadata-only 与旧格式零创建；不采用已有资源 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_resource_owners.py` | T114 内部 owner 关联；同 ID 双向引用、物理对象/收据替换、共享包 unknown、非阻塞锁及逐提交故障；不开放生产登记或释放 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_resource_release.py` | T115 当前 manager 退出记账；完整观察、pending/owner/released 逐写入故障、同 manager 重新观察后的补记、时间/摘要一致及其它运行/意图保留；不解除旧 unknown |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_stop_probe.py tests/test_descendant_release.py` | T064 停止通道有限模型，本次 52 passed；精确句柄/manager 保留/意图后单次派发/未知不重试，假内核观察不代表真实停止准入 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_pane_probe.py` | T086 单周期驻留模型，本次 58 passed；完整释放后 parked、确切批准与单次启动、响应丢失不重放；不是原位生产准入 |
| `tests/test_rotom_omp_setup_flow.py`、`tests/test_rotom_omp_adapter_admission.py`、`tests/test_rotom_omp_scoped_sync.py` | 全新 Linux 普通 setup/apply/run 与已有 scope 同步已有隔离验证；旧资源不采用、部分登记不清理，不等于原生停止/恢复准入 |
| `tests/test_rotom_omp_observation.py`、`tests/test_rotom_omp_instances.py` | 合作 scope/双向元数据、缺记录非零未知、历史查询不取包锁；不授予控制权限 |
| `tests/test_rotom_maintenance_recovery.py` | 已有共享 cache/跨域/unknown、意图完整闭包和丢失响应等原语组合；T063 整体仍未完成 |
| `tests/test_rotom_maintenance_acceptance.py`、`tests/test_rotom_maintenance.py` | manual 方案的精确恢复快照与持久发布事务；T062/T069 整体仍待完整现场采集、批准交互及控制接线 |
| `tests/test_rotom_maintenance_live.py`、`tests/test_rotom_maintenance_live_store.py` | 临时物理租约、实际所选 owner 及同 scope 引用核验；锁保持至清单/意图提交，尚未提供停止许可 |
| `tests/test_rotom_maintenance_deployment.py`、`tests/test_rotom_maintenance_deployment_store.py` | 当前部署与受保护资源的只读核验先于协调锁；含 fake setup/run 的真实部署产物，未运行原生宿主 |
| `tests/test_rotom_stop_review.py`、`tests/test_rotom_stop_review_store.py` | 停止专属精确计划/批次内存审阅及 live 消费顺序；新审阅与计划回归 77 passed，事务新套 15 passed；无控制/setup 许可 |
| `tests/test_rotom_setup_operation.py`、`tests/test_setup_cli.py` | 共用 setup 核心、原 CLI 文案/批准/失败结果及门禁顺序；不开放维护 runner |
| `tests/test_rotom_spawned_host.py`、`tests/test_rotom_host_registration.py`、`tests/test_rotom_resume_host.py`、`tests/test_rotom_dsh_process.py`、`tests/test_rotom_dsh_run_host.py` | fake pidfd/直接子进程与 DSH 普通运行、恢复共享接线；登记不明仍保留原等待/退出，等待异常不 kill/retry，不准入自动控制 |
| `tests/test_rotom_stop_requests.py`、`tests/test_rotom_stop_dispatches.py`、`tests/test_rotom_stop_inbox.py`、`tests/test_rotom_stop_executor.py` | 严格请求、私人 inbox、逐 run 单次记账及可信回调候选；文件或请求不代替批准、原 host、期限与资源核验，历史阶段默认不接控制；当前精确 DSH 接线见开头 |
| `tests/test_rotom_stop_service.py`、`tests/test_rotom_dsh_control_lifecycle.py`、`tests/test_rotom_managed_wait.py` | 停止服务 44 passed；DSH 工厂与原生命周期组合 78 passed，计数有重叠；只用 fake child/pidfd/发送，服务失败等待同一 child，不 kill/retry，历史阶段默认无工厂；当前精确 DSH 已有默认工厂 |
| `tests/test_rotom_dsh_stop_scope.py`、`tests/test_rotom_run_stop_fence.py`、`tests/test_rotom_dsh_stop_fence_integration.py` | 已有部署包含关系与持久登记阻断候选；正式 DSH 为实例/状态两把 SH，不证明完整运行集合、外部 writer 或停止许可 |
| `tests/test_rotom_run_stop_snapshot.py`、`tests/test_rotom_maintenance_acceptance.py` | 人工恢复快照 codec 与既有接受格式联合 146 passed；保存所选完整历史记录，未知 host/session/cwd 不补造，只读格式不提供许可 |
| `tests/test_rotom_run_stop_snapshot_store.py`、`tests/test_rotom_run_stop_fence.py` | 快照先行、v2 fence 摘要关联与故障保留；store 新套 57 passed，后续 locked reader 兼容组合 106 passed/2.55s（包含既有用例，不相加） |
| `tests/test_rotom_dsh_stop_snapshot.py`、`tests/test_rotom_dsh_stop_fence_integration.py` | save helper 新 17 项加旧 inspect 定向 3 项共 20 passed；入口人工快照分支另 10 passed；布局在 owner 锁前/内复核，零新增批准或控制权限 |
| `tests/test_rotom_dsh_stop_request_scope.py`、`tests/test_rotom_dsh_stop_request_integration.py` | request scope 35 passed/125.55s，增强正例再 1 passed/4.35s（重叠，不相加）；请求组合 6 passed/26.60s；只读核对 v2 关联、当前目标和布局，其它所选项可已退出，不据此授予控制 |
| `tests/test_rotom_dsh_stop_plan.py`、`tests/test_rotom_stop_plan_cli.py`、`tests/test_rotom_dsh_stop_preview.py` | DSH v2 纯计划及审阅130 passed；CLI/help/interaction3269 passed、最终窄91 passed；现场初17、范围/历史定向6、正式CLI组合3 passed（重叠）；历史阶段只有只读预览；当前 DSH stop_only 保留 unknown 覆盖但仍要求已核实控制 |
| `tests/test_rotom_dsh_plan_snapshot.py`、`tests/test_rotom_dsh_reviewed_snapshot.py` | 完整计划快照和原codec169 passed；审阅保存/原store69 passed；布局/全集CAS后首次写入前单次消费，失败保留事实，不签发控制许可 |
| `tests/test_rotom_control_deadline.py`、`tests/test_rotom_maintenance_wait.py`、`tests/test_rotom_maintenance_wait_integration.py` | 共享阶段预算与内部后代观察等待；保存事实不释放 manager SH、不授予维护资格，生产控制/Batch/ready 接线未完成 |
| `tests/test_rotom_continue.py`、`tests/test_rotom_input_probe.py` | 显式人工指引、零发送/正文不落盘与独立输入 fake 原型；不证明自动输入准入 |
| `tests/test_rotom_dsh_stop_client.py`、`tests/test_rotom_stop_control_cli.py` | 最终历史目标/版本展示两套 46 passed；真实临时快照、fake manager/时钟与 CLI，未知不升级实时确认，不能代替原生验收 |
| `tests/test_rotom_restore_capabilities.py` | 驻留候选的隔离机制检查；不代替位置原生准入 |

不存在的未来文件不写成可复制 pytest 命令。实现后记录实际 argv、候选/源码摘要、锁、退出码、
通过/失败/跳过数量与私人证据引用；skip、缺环境、未授权、未实现分别记录。
模拟加载成功不证明实际 DSH 恢复，阶段一静态拒绝不计阶段二完成。
Node 接线检查使用空继承环境和专用临时 HOME/XDG；上述短命令仅表示套件入口，执行时须保持隔离条件。
默认沙箱一次 stdout 捕获异常导致超时，作为环境不足保留；通过记录来自支持执行器的最终稳定源码。
测试自身的遗留 fake Node 子进程已按精确身份清理，未给原生 Agent 发信号；最终 fixture 用显式 finish、
断连和有界自行退出保证该历史 fake 失败路径清理。候选恢复交接、运行中派发与记录机制已有隔离实现；T053 官方原生交接及 T054 默认恢复入口已在固定 Linux 组合通过，该限定范围已合入 main，整合及后续增量见 main-review。停止服务、fence、人工快照与请求核验的早期候选证据保留；当前精确 DSH stop_only 已按上节独立验收，该历史阶段的完整维护/恢复编排与其它组合当时仍未准入；当前 here 候选与位置候选分别按本文开头的范围和独立记录判断。[公开启动结果缺口](../../docs/rotom-dsh-startup-contract.md) 只限制 restored/自动继续，不再作为派发实现的硬前置。

资源身份本轮最终组合为上述两个新套件，加 `test_omp_dependencies.py`、`test_omp_runtime_foundation.py`、
`test_rotom_runtime_observation.py`、`test_lifecycle_leases.py`，共 **186 passed**，退出 0；66/9 项包含在该总数中。
首次磁盘满导致写入和测试无法开始，单独记为环境不足；可用空间自行恢复后再执行，没有清理其它任务目录。
执行器保留临时 HOME、网络/宿主阻断和安全属主检查；这 186 项仅验证物理身份阶段。
后续 T065/T066 的协调及普通入口独立验收见 `main-review.md` 第 39 节，完整维护集成仍未完成。

## 已注册命令与后续能力的验收场景

下表包含既有入口与当前候选分阶段场景；候选支持三工具精确 stop_only、独立普通 setup 与逐项当前终端交接。具体锁定组合与剩余验收以维护指南为准。
以下命令在相应隔离 fixture 的临时目录中由测试调用；不要直接对日常机器执行。
`workstation`、`session-example`、`11111111111111111111111111111111` 等均为虚构标识，`PLAN_ID/BATCH_ID`
必须替换为同一 fixture 实际只读计划的结果，不能从示例构造批准。

| 场景与未来输入 | 预期结果 |
| --- | --- |
| `./rotom --help`；`./rotom agent model key --help`；`./rotom work worktree create --help` | 0；不加载偏好/机器/秘密/会话，不进入菜单；用途、位置、默认和影响齐全 |
| `./rotom --no-input run` | 2；缺工具，不读 stdin/打开 tty/启动程序 |
| `./rotom run pi --profile pi-pro --help` | 0；静态帮助；同样 token 放在 `--` 后属于宿主 |
| `./rotom --no-input run pi --machine workstation --profile pi-base -- --help` | fake 得到原生 `--help`；退出状态原样保留；不读取其它 scope |
| `./rotom agent usage --help` | OMP 原生 usage 获得全部尾部；不截获为门面帮助，不注入保存默认 |
| `./rotom --no-input config set run_profiles.pi pi-pro` | 只保存明确偏好；原子保存冲突保留旧值；未知 key/value 报 2 |
| `./rotom --no-input agent --machine workstation --profile pi-pro model key synthetic-provider` | 无非交互隐藏输入接口则 2，秘密读取为零，不新增 argv key |
| `./rotom --no-input run dsh --machine workstation`，fixture 保存旧有效部署并声明 runtime 待更新 | 使用旧部署；静态更新建议保留实际 profile；不自动 sync/apply 或报缺包 |
| `./rotom _complete --kind profile --tool pi` | stdout 只有合法 Pi profile ID 加 NUL，无正文或路径 |
| `./rotom _complete --kind session --machine workstation --tool dsh` | 缺索引时 0 + 零字节，不创建索引或扫描原生会话 |
| `./rotom --no-input resume dsh --machine workstation --session session-example --here` | 精确 Linux managed DSH 完整锁下核验范围后交接原生恢复；加载待确认、零自动输入，保留原生退出码；未准入组合为 5，缺参/歧义为 2 |
| `./rotom agent --machine workstation instances list --agent dsh --format json` | 未指定 profile 时列该范围全部 DSH；未知占用不消失，进程/会话/位置分别标来源和时间 |
| `./rotom agent --machine workstation instances stop --run 11111111111111111111111111111111 --dry-run` | 三工具候选只读精确目标计划；blocked 也返回 0，不建批次、不请求停止 |
| `./rotom --no-input agent --machine workstation --profile dsh-default instances stop --run 11111111111111111111111111111111 --plan-id PLAN_ID --wait-seconds 30` | 当前 plan-id 不匹配为 4、缺失为 2；精确已准入现场 ready 时先保存人工快照再逐项停止，确证停止为 0，待确认/到期为 4 并保留 batch；其它组合为 5 |
| `./rotom agent --machine workstation --profile dsh-default maintenance plan --operation setup --run 11111111111111111111111111111111` | 当前只读资源引用与阻断原因；第三个未选引用仍保留并阻断 setup，无批次 |
| `./rotom --no-input agent --machine workstation --profile dsh-default maintenance stop --operation setup --run 11111111111111111111111111111111 --plan-id PLAN_ID --wait-seconds 1` | 候选当前流程：漂移为 4，接受后先保留恢复清单再逐项一次派发 |
| `./rotom --no-input agent --machine workstation --profile dsh-default maintenance execute --batch BATCH_ID --plan-id SETUP_PLAN_ID` | 候选普通 setup 独立批准；须先 plan --batch，停止完成不替代原全门禁 |
| `./rotom --no-input agent --machine workstation --profile dsh-default maintenance restore --batch BATCH_ID --run RUN_ID` | 候选逐项当前终端官方交接；加载待确认，不发送继续 |
| `./rotom --no-input agent --machine workstation --profile dsh-default maintenance status --batch BATCH_ID --format json` | 只读保存的目标、版本、历史 session 和当前请求/派发状态，不重发；返回完整 batch 和后续命令 |
| `./rotom --no-input agent --local /path/to/machine.toml --profile omp-default maintenance status --batch BATCH_ID --format json` | 现存 Linux OMP setup 批次只读查询；原操作结果与查询退出码分离，不创建批次、不清保护、不恢复 |
| `./rotom --no-input agent --machine workstation --profile dsh-default maintenance cancel --batch BATCH_ID` | 只取消未投递活动项或对已确证停止的 close 收尾；unknown 保留保护，不重发 |

交互测试还须覆盖根和各命令组导航、编号兜底、自由文本输入、只有一个候选仍不替代批准、
未接受动作取消返回 130、此前独立接受结果保留。JSON 测试分别解析原 schema，
确认 stderr 提示/进度/范围建议未混入 stdout；建议含明确 machine/local、profile 和组件。

## 独立合成性能测量

`tests/benchmarks/rotom_cli.py` 与 `tests/fixtures/rotom/performance.json` 已创建。
这不是默认 pytest：它只执行仓库自有 CLI 的独立冷进程，每场景固定 30 次，
报告 nearest-rank p50/p95/max、退出码、候选/列表正确性及只读文件哨兵。
Python guard 阻断网络、后续进程、信号、procfs 与写文件，不据此宣称操作系统沙箱或原生验收。

在可信属主执行环境使用现有准备 venv；输出目录必须是仓库外尚不存在的私人绝对路径：

```sh
.venv/bin/python -B tests/benchmarks/rotom_cli.py --output /tmp/rotom-cli-benchmark-example
.venv/bin/python -B tests/benchmarks/rotom_cli.py --output /tmp/rotom-cli-list-benchmark-example --phase list
```

默认测量 help 和受限动态补全，列表须显式选择。空配置、32 机器/100 公开配方、
单机器/单配方 1,000 条合成 v2 记录均有版本化负载；不使用真实进程或原生会话。
不清理操作系统文件缓存，也不把同进程函数循环当作冷启动。
help/补全预算为 p95 ≤ 1 秒，列表为 p95 ≤ 2 秒；超限保留失败记录，不修改预算或伪报通过。
原始 argv、环境和测量日志仅留私人目录，不提交到公开仓库。
最近一次正式测量中，100 配方补全 p95 为 0.703 秒、1,000 记录列表 p95 为 1.929 秒，
help 各场景也满足原预算，T106/T107/T108 已完成；完整结果及范围见 [冷启动性能收口](main-review.md#8-冷启动性能收口)。
共享资源增量后于 2026-10-24 重测当前源码的列表场景：30 次，p50 1.234 秒、p95 1.743 秒、最大 1.773 秒，退出 0，预算保持 2 秒。help/补全实现未受本轮 fake 原型影响，沿用原测量；新结果不覆盖其它尚未执行的原生验收。


## 单独授权后的原生验收

真实 zsh、DSH/Pi/OMP、Herdr、信号、PTY、终端输入和账号烟测均须独立明确授权。
本指南不授予该权限，也不以无账号 smoke 或 CI 配置替代通过证据。本会话已于 2026-10-24 获得用户明确授权；T039 已实际执行，其它阶段仍须先满足实现和能力门槛，授权不代替通过证据。
获得授权前单列记录“未授权/未执行”；只有实际执行器或依赖不可用时才记录“环境不足未验证”。
能力尚未准入另行标注，不能用静态/模拟成功开放能力。


授权后按范围验收并单独保存脱敏记录：

1. 阶段一：在专用临时 HOME 和明确授权的 checkout 预览并部署 zsh 入口，实际新终端从不同目录
   调用 `rotom --help` 与 Tab；核对既有绑定保持、显式换绑和回滚。完整命令见[入口部署契约](contracts/entry-deployment.md)。
2. 阶段二：首先在 DSH 的专用会话存储创建可验证会话，执行明确 scope 的 `resume ... --here`，
   核对实际部署、native HOME/scope、原目录、租约及派发目标；在 TUI 人工观察加载，并单列机器加载确认，默认不发送继续。验证缺失目标和外部 writer 冲突不回落新建或其它会话。
   真实官方交接可通过验收且机器加载态仍待确认，不要求新上游接口；仅在可信回执充分时才记录 restored。Pi/OMP 单独验证，不类推。
3. 阶段三：只针对明确选择的合成受管实例验证真实优雅停止、后代与资源退出证明、有限等待、
   未选实例保留及维护/恢复失败对账；停止批准不替代维护部署批准。
4. 阶段四：实施 Herdr 新标签页及 Rotom Herdr 托管新实例的驻留原 pane 恢复，分别验收位置身份、复用防护、Rotom 代际兼容与未知请求对账。
   P-PANE 是逐工具正式开放前的原生验收门槛，不是开始开发前置；当前两种位置均未开放，使用此前已准入的当前终端恢复。
   统一严格加载回执、原生 TUI 自动继续与 Pi Pro 委派不作本轮承诺，恢复后等待人工输入；绝不以按键注入代替公开能力。

## 结果记录与完成标准

每项记录候选 HEAD、main 基线、锁/运行包身份、实际 argv（仅允许字段，不保存完整原生 argv/环境）、
退出码、平台范围、证据日志的仓库外私人位置及脱敏结论。记录分为“已完成”“进行中”
“失败待决策”“环境不足未验证”；另以执行状态单列“未授权/未执行”。
只有实际执行器或依赖不可用才属环境不足；不得将未执行或环境不足写为通过，也不阻塞无关文档工作。

公开报告不含真实用户名、私人绝对路径、主机信息、秘密、认证链接或会话正文。
最终写入完成后核对稳定 diff 与相对链接；若随后修改，重跑受影响检查。
只有相应阶段实现、隔离检查及所需原生验收都满足时，才报告该阶段完成；
分支实现、静态命令和本指南存在均不能替代整合及行为证据。


## 新实例域锚点的隔离验收

T116 专属套件为 tests/test_rotom_resource_scopes.py，仅使用临时合成实例、真实文件描述符与假观察。
覆盖新建声明的持久化顺序、跨域/错误归属拒绝、已有空/旧目录拒绝、锚点与物理对象损坏、提交失败、
普通 lifecycle/sync 防降级，以及同 run 的三资源 owner 登记、派发记账和释放。没有真实 Agent 启停。
此内部接口没有公开初始化/修复命令；不能用它接管日常实例。普通 cache-only 同步保持不创建实例，
T116 单独完成时已声明实例的普通操作维持拒绝；后续 T065/T066 已接通完整新资源的合作入口，
旧历史和部分登记继续拒绝，未据此准入停止、恢复或维护。

## 历史阶段：停止与驻留原型的验收

T064/T086 当时只完成有限 fake 原型，真实停止/原位恢复在该阶段未开放；当前 stop_only 范围见本文开头。两个专属验收分别为 52 与 58 项通过；
当前候选组合检查覆盖只读实例/历史会话、补全隐私边界、运行元数据、文档检查器和两个原型，
共 **424 passed，退出 0**。初次命令漏建 basetemp 父目录而产生 424 个 fixture setup errors，
没有执行测试主体；修正执行准备后在相同源码上取得上述结果，原失败日志保留。
前一阶段 886 项回归的 98 个源码文件摘要全部保持一致，因此复用该证据，不重复运行或累加通过数。
该原型阶段的恢复/事件契约保留 5 passed / 44 failed 历史结果；后续 T117 与候选协调器/事件实现的隔离验收见上表，不能将任何组合结果称为全库通过。

2026-10-27 的独立授权 Pi 核心探针另证明稳定父进程保留同一 PTY、停止/更新后新 run 请求原 session/cwd 的可行性，不能类推为 Herdr 绑定、生产驻留实现或 DSH/OMP 原位验收；当前原 pane 和新标签页的六个精确 Linux managed 组合已另经最终十二组无 trace 原生验收；该历史探针不是本次位置原生验收。


## T039 真实入口验收结果

2026-10-24 经用户明确授权，在 Linux、zsh 5.5.1、Python 3.11.11 的专用临时 HOME/XDG 和两个受信公开源码副本中执行；10 个公开依赖版本全部匹配 uv.lock：

- 四次实际 termcfg 状态转换：初次绑定 A、由 B 发起更新仍保持 A、显式换绑 B、按记录回滚 A。
- 四个状态分别从两处临时 cwd 调用安装入口的 help 与受限 profile 补全，共十六次；合成来源标识确认实际执行的 checkout。
- 两处 cwd 各启动六个新的真实 zsh/PTY，共十二个 Tab 场景：dsh/pi/omp 工具、profile/entry-repo 选项，以及 `--` 后原生参数边界。

所有直接持有的 32 个测试子进程均退出 0。Tab 通过委托原生 `expand-or-complete` 的测试 widget
读取并清空 ZLE BUFFER，不按回车启动 Agent；因此它证明真实补全行为，不代表插件主题或完整交互 UI 已验收。

首轮因原准备环境的祖先目录不可信，在 source_snapshot 阶段失败，尚未部署或启动 zsh。
随后使用新建的私人离线 Python 环境和同版本公开依赖，在全新测试根重新完成验收；失败证据保留，
没有放宽路径校验或修改源环境。当前日常 checkout 的祖先权限也不满足入口校验；本次通过只适用于
受信临时副本，正式部署仍须选择权限合格的源码和准备环境，不能直接沿用本次临时目录。

实际 argv、平台/版本、源码和工具链摘要、逐进程退出码及原始日志保存在私人验收记录；
主线与日常配置未改，没有真实 Agent、会话恢复、模型/账号调用或 Herdr 验收。

## 启动版本与精确停止的隔离验收

2026-10-26，实例列表及 DSH 计划复用 RunRecord v2 的 `deployed_identity`，显示启动时
`deployment` 配置/部署组合摘要及 `runtime` 锁定运行包身份；旧记录显示 unknown，
不读当前配置补填。静态 help 说明版本含义及其不能证明资源释放的边界。
DSH v2 stop_only 保留资源覆盖及全部引用，不以未知外部覆盖单独阻断已核实的所选目标；
setup 继续要求完整覆盖并拒绝未选引用。该隔离阶段尚未准入实际控制；当前精确 stop_only 仍拒绝缺少原 endpoint 或目标未知的情况。

以下命令均使用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider`：

| 测试文件（`tests/` 下） | 本次实际结果 |
|---|---|
| `test_rotom_instance_versions.py test_rotom_instances.py test_rotom_dsh_stop_plan.py test_rotom_stop_plan_cli.py test_rotom_maintenance_plan.py test_rotom_stop_review.py` | 210 passed，退出 0；新增最终 help 用例之前的版本/规则回归 |
| `test_rotom_dsh_stop_preview.py test_rotom_dsh_plan_snapshot.py test_rotom_dsh_reviewed_snapshot.py` | 77 passed，退出 0；临时部署采集及完整计划快照 |
| `test_rotom_instance_versions.py test_rotom_help_completion.py` | 215 passed，退出 0；最终版本与静态 help |

先行 RED 为 6 failed、53 deselected，原因均为尚缺本次目标行为；不是夹具失败。
以上计数有重叠，不相加为全库结果，没有真实 Agent 或信号。
本轮原生材料先核验六份本地 vendor 归档 SRI；随后从标准已登记部署取得当前运行包，
验证既有受管收据、锁字节及完整源/副本摘要。Core 20、TUI 3287 个原包文件与对应本地锁索引
逐文件匹配，不把索引验证冒充重新下载官方归档。真实启动/停止有限证据见
[main-review 第 55 节](main-review.md#55-锁定官方包的真实启动与精确停止)。

## 位置恢复的命令与验收边界

下列命令在已通过最终原生验收的六个精确 Linux managed 组合内开放，仍须重新核验现场门禁。先对同一完整 workflow 批次完成精确停止和独立批准的 setup/update。`--list` 与默认 here 不需要 Herdr；位置分发需要当前受支持的 Herdr 上下文，原 pane 还需保留的受管 launcher。

```sh
./rotom resume pi --machine workstation --profile pi-base --stopped --list --format json
./rotom --no-input resume pi --machine workstation --profile pi-base --stopped --batch BATCH_ID --run RUN_ID --new-tab --format json
./rotom --no-input agent --machine workstation --profile pi-base maintenance restore --batch BATCH_ID --run RUN_ID --original --format json
./rotom --no-input resume pi --machine workstation --profile pi-base --stopped --batch BATCH_ID --all --new-tab --format json
./rotom --no-input resume pi --machine workstation --profile pi-base --stopped --batch BATCH_ID --all --original --format json
```

BATCH_ID/RUN_ID 必须替换为实际完整32位小写十六进制值；示例不授予任何现场操作许可。`--all` 不接受 --here/--run/--session/--list；先拒绝坏记录、不可恢复项或跨 scope/profile/batch，再逐项重查、独立终端交接。JSON 只形成一个汇总；首个失败或未知后剩余项为 not_dispatched，之前事实保留，返回4。重复执行不能重放已有 restore-intent。普通 `resume --session ... --original|--new-tab` 仍不开放。

Herdr V1/V2 新 DSH/Pi 和符合组合的新 tab 恢复可由驻留候选包装，普通 rotom run 不驻留。parked 不持 Agent 单次租约和凭据；源码或位置身份变化拒绝旧容器。加载待确认，零自动继续；Pi Pro 委派不在范围，pi-pro 普通 profile 兼容保留。对应隔离文件包括 test_rotom_pane_records.py、test_rotom_restore_locations.py、test_rotom_restore_new_tab.py、test_rotom_restore_capabilities.py、test_rotom_pane_dispatch.py；此处列出检查范围，不新增任何测试通过计数或原生结论。

## 已停止会话入口的隔离复验

新增入口使用方式见[维护指南](../../docs/tool-maintenance-workflows.md#已停止会话清单与快捷恢复)。以下测试只使用合成会话、临时状态与假宿主，不启动第三方 Agent：

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_rotom_stopped_sessions.py tests/test_rotom_stopped_cli.py tests/test_rotom_tool_session_headers.py tests/test_rotom_tool_maintenance.py tests/test_rotom_tool_workflow_cli.py tests/test_rotom_resume_cli.py tests/test_rotom_help_completion.py tests/test_rotom_zsh_completion.py
```

新入口已另经显式授权的真实全 CLI 停止/更新/当前终端恢复验收；上述命令仍是独立隔离回归，不能替代原生证据。`resume --stopped --list` 只读已保存的停止记录，当前 `--here` 不需要 Herdr；驻留原 pane 与 Herdr 新标签页已有候选实现，但公开准入已覆盖六个精确 Linux managed 组合的两种位置，自动继续不在本轮承诺内。本次文档同步不新增真实宿主或 Herdr 测试授权与执行结果，既有 zsh/PTY 与 Pi 核心探针仅证明各自记录的范围。

显式原生脚本见 `tests/manual/*_tool_workflow_native.py`，使用前先查 `--help`；必须另有真实宿主、隔离目录及停止范围授权。以下为参数模板，NODE_ROOT/RUNTIME/BINARY 必须是已核验的锁定公开运行包；各 OUT 目录须不存在，不能指向真实 HOME：

```sh
.venv/bin/python -B tests/manual/pi_tool_workflow_native.py --allow-host --root OUT --node-root NODE_ROOT
.venv/bin/python -B tests/manual/dsh_tool_workflow_native.py --allow-host --root OUT --node-root NODE_ROOT --runtime RUNTIME
.venv/bin/python -B tests/manual/omp_tool_workflow_native.py --allow-host --root OUT --node-root NODE_ROOT --binary BINARY
```

Pi 准备可下载精确锁定公开依赖，宿主运行阶段禁网。DSH 仅用隔离 loopback 假模型，恢复输入为零但宿主可发辅助请求。OMP 首次使用公开 resume 加载合成历史；退出竞争的原生复验必须关闭 `--diagnose`。详细结果和失败历史见[验收记录](tool-workflow-validation.md)。

## 位置恢复的共享等待预算

完整 workflow 成功更新后，位置恢复可显式选择准备/交接预算；默认30秒，范围1–300秒。

```sh
./rotom --no-input resume pi --profile pi-base --stopped --batch BATCH_ID --all --new-tab --wait-seconds 120 --format json
./rotom --no-input agent --profile pi-base maintenance restore --batch BATCH_ID --run RUN_ID --original --wait-seconds 30 --format json
```

整批只计算一次绝对期限，包含精确目标核验和终端握手，不按每项或socket分段响应续期。交互选择时间不计入。超时返回4并保留逐项事实，后续项不再派发；已有请求可能稍后交接，先查询原批次，不重发或强杀。Agent接管后的任务运行时长不受该预算限制。`--here`、普通 `--session` 和只读 `--list` 不接受此参数。
