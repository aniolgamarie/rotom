---

description: "termcfg 同步代理与终端工具配置的实施任务"
---

# Tasks: 同步代理与终端工具配置

**Input**: `specs/003-sync-terminal-tools/` 中的 [spec.md](spec.md)、[plan.md](plan.md)、[research.md](research.md)、[data-model.md](data-model.md)、[命令契约](contracts/cli.md)、[同步状态契约](contracts/sync-state.md)和[quickstart.md](quickstart.md)。

**Tests**: 规格 FR-020、各故事 Independent Test 和项目宪章要求隔离验证，故每个故事包含风险驱动的测试任务。默认测试不得触碰真实 HOME、网络、tmux server 或 mihomo 进程；真实 smoke 独立授权。

**Organization**: 先完成共享结构与安全前提，再按 US1 → US2 → US3 交付。每条任务均指向明确文件；`[P]` 仅用于同一阶段可在不同文件独立推进的任务。

## Phase 1: Setup（共享结构）

**Purpose**: 建立独立 CLI、来源清单和可审计的迁移基线。

- [X] T001 在 `termcfg`、`src/termcfg/__init__.py` 和 `src/termcfg/cli.py` 建立独立 Python 3.11+ 入口，直接使用仓库 `.venv`；不调用 `uv run` 或 `agentcfg setup/run`。
- [X] T002 [P] 在 `terminals/SOURCES.md` 记录旧 `starter` 快照、逐文件 SHA-256、许可证、纳入/改写/排除理由及旧脚本隐式副作用；禁止把旧工作目录设为运行时依赖。
- [X] T003 [P] 在 `schemas/termcfg/machine.schema.json` 与 `schemas/termcfg/catalog.schema.json` 定义严格机器选择和目标清单格式，未知字段、无效 ID、重复目标及不受限路径必须失败。
- [X] T004 [P] 在 `tests/conftest.py` 建立临时 HOME/XDG、文件哨兵、网络阻断及假 core/API/子进程 fixture，并先在 `tests/test_termcfg_init_local.py` 写首次默认组件、非 TTY 空选拒绝、`init-local --edit` 旧→新及显式清空的失败测试；默认测试不得启动真实宿主或读取真实订阅。

---

## Phase 2: Foundational（阻断所有故事的前提）

**Purpose**: 固定输入、安全路径、私人状态与脱敏错误语义。

- [X] T005 在 `src/termcfg/config.py` 实现 `MachineSelection`：`machine_id` 为单一路径段，`components` 仅为 `zsh/tmux/mihomo` 子集，`target_home` 为当前用户拥有的绝对目录，`private_state_root` 在仓库外；私人机器文件 0600、目录 0700，未知字段失败。
- [X] T006 [P] 在 `src/termcfg/catalog.py` 实现 `Component`、`SourceArtifact`、`LockedAsset` 清单读取：来源只在仓库内、目标相对 HOME、目标 ID 唯一且组件间无重叠；core/远程插件锁含明确版本或提交、平台、官方来源、长度、SHA-256、解包方式及必要入口/资源。
- [X] T007 在 `src/termcfg/home_targets.py` 实现目标祖先属主/权限、路径分量、文件类型、硬链接与 no-follow 检查，不在此任务读取旧目标正文或计算摘要；在 `src/termcfg/lease.py` 实现固定私人 XDG 状态根 `termcfg/leases/machines/<machine_id>.lock` 的逐级 0700 目录/0600 单硬链接普通锁文件、no-follow 打开及非阻塞独占内核锁，首次 init-local 也能先锁，活动操作占用时返回 4、不依赖 PID 强行解锁。旧 symlink 仅供显式接管并保存链接本身。
- [X] T008 [P] 在 `src/termcfg/secret_boundary.py` 实现保守的非秘密准入：只允许已知公开来源及可确认的旧非秘密目标；疑似含订阅、凭据或无法判定的目标在摘要计算和普通备份前阻断，给出迁移私人值的具体下一步，且不能靠接管确认绕过。
- [X] T009 [P] 在 `src/termcfg/diagnostics.py` 定义 `ready/blocked/degraded/unverified`、脱敏原因码与 `next_command`、每 2 秒内进度/心跳及最终摘要；进度写 stderr，`--json` 的 stdout 仅有一个最终对象，输出不得含文件正文、私人 URL、密钥、有效代理配置或原始子进程 stderr。
- [X] T010 在 `src/termcfg/cli.py` 接入 `--machine`、`--component`、`--json`、`components`、`init-local [--edit] [--none]` 与退出码 0/2/3/4/5/6；新建或编辑先取得同机器 OperationLease，读取配置后一次多选且仅预选检测到必需程序的 zsh/tmux，mihomo 默认不选；编辑时预选旧值并展示旧→新值，确认后原子替换私人机器文件，非 TTY 必须显式给出组件或 `--none`，不收集订阅或 secret，也不改 HOME 目标。

**Checkpoint**: 可读取严格机器选择与组件清单，安全目标读取和脱敏错误可由隔离 fixture 验证；尚不写 HOME 目标。

---

## Phase 3: User Story 1 — 检查后安全同步所选组件（Priority: P1）🎯 MVP

**Goal**: 对 zsh、tmux、mihomo 分别预览公开配置；显式锁定并安装版本化 core/插件，`apply` 在整次调用完成所有配置备份后复制公开配置，同步不操作服务。

**Independent Test**: 临时 HOME 中分别选择单组件，并测试多组件调用在第二个组件备份失败时零覆盖；已接管旧目标可备份，未选组件及会话/运行数据不变；运行中的假服务没有收到重载/重启。

### Tests for User Story 1

- [X] T011 [P] [US1] 在 `tests/test_termcfg_catalog.py` 写来源/完整 core 与插件锁、平台条目、清单重叠和未知字段的拒绝测试；使用虚构资产摘要与平台，不访问网络。
- [X] T012 [P] [US1] 在 `tests/test_termcfg_plan.py` 写逐文件操作、环境阻断、首次接管、`.zshenv` 脱敏提示、预览后目标替换及交互 TTY 无需复制 `plan_id/target_id` 的契约测试；初始化测试已由 T004 先于 T010 提供。
- [X] T013 [P] [US1] 在 `tests/test_termcfg_apply.py` 写整次调用备份优先、第二个组件备份失败时全部目标零覆盖、同机器两个并发 apply 至多一个取得锁且另一个写前返回 4、基线/当前/期望三方比较与漂移拒绝、重复无变化不改写或轮换备份、成功变更仅保留上一版配置备份、写入/状态提交中断后可诊断恢复且不虚报成功、一次总体确认加最多一次 `.zshenv` 专门确认、非 TTY ID 绑定及未选组件/会话/运行数据哨兵测试。
- [X] T014 [P] [US1] 在 `tests/test_termcfg_mihomo_sync.py` 写显式 lock 与 core/插件 sync 的假下载、长度/SHA-256/解包/入口校验、0700 包目录与执行入口/0600 非执行资源及属主校验、同机器 sync 与另一 sync/apply 争锁时后到者写前返回 4；两个维护者 lock 同仓库旧身份竞争时不丢更新，lock 与下载中的 sync 交错时 sync 提交前发现快照失效并返回 4；交互式 apply 展示预览后等待确认时让 lock 提交新锁，确认后 apply 复核过期快照、写前返回 4 且 HOME 目标/备份/journal/EffectState 字节不变；lock 与已持仓库共享租约的 apply 在写入期间互斥，包/状态/备份/HOME 不基于过期锁提交；合法 machine_id 恰为 `repo-<仓库摘要>` 时机器/仓库锁仍使用不同文件；锁更新中断后旧锁字节保持不变、慢下载每 2 秒内进度、连接/空闲/总超时与 SIGINT 后可诊断重试、无锁平台及离线 apply 测试；并验证 sync 选定新 core 后持久记录 `pending_core_effect`。

### Implementation for User Story 1

- [X] T015 [P] [US1] 在 `terminals/zsh/` 和 `terminals/tmux/` 迁入经审查的公开配置与辅助脚本，记录来源摘要；`.zshenv` 为整文件源，移除配置加载时 zinit/TPM 自动联网安装，并让缺少可选插件安全降级。
- [X] T016 [P] [US1] 在 `terminals/mihomo/` 迁入并改造公开 `mihomo-mgr` 与非秘密基础配置；私人订阅、controller secret、有效配置、路由状态、日志及统计只留独立私人目录，不复制旧混合 `config.yaml`。
- [X] T017 [P] [US1] 在 `src/termcfg/lease.py`、`src/termcfg/packages.py`、`locks/termcfg/mihomo.json` 与 `locks/termcfg/plugins.json` 实现仓库级 `RepositoryLease`（固定私人 XDG 根的 `termcfg/leases/repos/<仓库规范路径摘要>.lock`，与机器锁的 `machines/` 目录不相交，0600 单硬链接普通锁文件/逐级 0700 父目录，no-follow、非阻塞共享/独占锁）和显式 `lock --component ID --version VERSION`；固定首个 Linux x86_64 官方 core 与所声明 zsh/tmux 远程插件的完整来源、版本/提交、精确资产、长度、SHA-256、入口和运行资源。先在共享锁下记录旧锁身份，联网准备后持独占锁复查，冲突返回 4；新锁暂存完整校验后原子替换，超时/中断保留旧锁字节，锁解析不安装或启动软件，其他未核验平台不宣称支持。
- [X] T018 [US1] 先在 `schemas/termcfg/state.schema.json` 与 `src/termcfg/state.py` 定义严格的最小 `EffectState`（机器、已选 core 身份、公开配置身份、分别持久的 `pending_core_effect/pending_config_effect`、未知字段失败，不含私人值）；再在 `src/termcfg/packages.py` 实现显式 `sync --component ID`：先取同机器 OperationLease，再以仓库共享锁读取完整锁快照，下载期间可释放仓库锁；激活和提交前重新取得共享锁并复核快照身份，持有至所选 core 和 `pending_core_effect` 状态提交，快照变更返回 4 且不选择旧版本。只消费现有锁，把 core/可选插件下载至当前用户所有的 0700 私人暂存与版本化包目录，归档/非执行资源 0600、清单声明的可执行入口 0700；激活前后校验完整资产、目录形状、属主、mode、链接边界及入口。缺锁不得改用 PATH 或 latest；不操作现有服务，失败不碰 HOME 配置，配置 rollback 不降级软件。
- [X] T019 [US1] 在 `src/termcfg/environment.py` 按组件检查 OS/架构、来源完整性、必需/可选命令、目标 HOME/属主/权限与 core 缓存；必要缺项阻止该组件写入，可选缺项只降级。
- [X] T020 [US1] 在 `src/termcfg/preview.py` 生成 `plan_id` 和逐配置目标 `create/replace/unchanged/adopt-required/conflict/blocked`、来源身份、非秘密旧目标身份、备份安排、core/插件依赖状态及 mihomo 服务的只读可管理/外部/未检查状态；先做秘密准入再计算摘要，只读、离线、无正文，执行前重新核对所有依据。
- [X] T021 [US1] 在 `schemas/termcfg/state.schema.json` 与 `src/termcfg/state.py` 扩展 T018 的 `EffectState`，加入严格的 TargetRecord、BackupSet、最近成功版本指针及 TransactionJournal（非秘密前后身份、阶段、私人备份引用、未知字段失败）；再在 `src/termcfg/transaction.py` 实现先取 OperationLease、在锁内重算预览并收集确认，确认后取 RepositoryLease 共享锁并再次复核锁、来源、目标和状态身份，持两锁到依赖该锁的配置状态提交或持久恢复记录，锁冲突或快照过期返回 4 且不写 HOME。基线/当前/期望三方比较：当前等于期望不重写，当前等于基线才更新，目标漂移或双方冲突时保留目标与旧备份且不接纳新基线。写前复查，全选中组件配置目标先备份并校验，任一失败零覆盖；以同目录原子替换和 `prepared → backed_up → writing → committed/recovery_pending` 持久 journal 执行，失败/中断可安全诊断与恢复，外部改动阻止自动恢复。仅成功且有变更时轮换为上一版配置备份并安全清理更旧成功备份，无变化/失败不轮换；mihomo 公开配置成功提交且确有变更时在同一锁内持久记录 `pending_config_effect`，失败或无变化不新增原因。
- [X] T022 [US1] 在 `src/termcfg/transaction.py` 实现首次接管与 `.zshenv` 门槛：旧普通文件/旧 starter 链接即使内容相同也逐项列出 target ID，TTY 可在明确展示全清单后一次确认全部接管，非 TTY 逐个 target ID 绑定当前预览；旧 `.zshenv` 有自定义非秘密内容时另行确认当前预览，拒绝则 zsh 整组件零写入。
- [X] T023 [US1] 在 `src/termcfg/cli.py` 接入显式 `lock`、`sync`、`doctor --strict`、`plan`、`apply` 与 `--timeout/--plan-id/--adopt-target/--confirm-zshenv`；TTY 的 `apply` 内展示预览并一次确认接管与执行，必要时另确认 `.zshenv`，非 TTY 缺预览 ID/明确接管即失败；sync/apply 的最终摘要分别显示持久的 core/配置待生效原因，给出当前已实现且可执行的 `doctor/plan` 诊断命令，并明确服务操作尚未提供，不输出不存在的 service 命令或把未核验服务写成已生效；多组件 apply 逐组件报告，部分成功不得冒充整体成功。US3 接入 service 后才提示显式重载/重启；所有命令区分 stderr 阶段进度与 stdout 最终摘要，超时/中断说明副作用和下一条命令。
- [X] T024 [US1] 在 `tests/test_termcfg_apply.py` 完成隔离 P1 集成验收：三组件可单独选择，首次交互无需复制 ID，第二组件备份失败时全部零覆盖，未选目标、私人目录和会话/服务数据哨兵不变；更新/漂移/中断后可恢复性及上一版备份轮换满足 T021，预览显示代理服务可管理状态，运行中代理不被操作，sync/apply 的最终摘要及私人状态分别保留 core/配置待生效原因，失败或重复无变化 apply 不新增原因，输出不建议尚不存在的服务命令，记录实际命令和结果。

**Checkpoint**: US1 只有在三方比较、上一版备份轮换和失败恢复均通过隔离验收后，才可作为安全文件同步的内部 MVP；`plan` 提供代理服务只读可管理状态，完整 `status/rollback/service` 交互由后续故事补齐。整体功能须完成 US2/US3 后再对用户宣称可用。

---

## Phase 4: User Story 2 — 识别漂移并恢复上一版（Priority: P2）

**Goal**: 拒绝静默覆盖后续用户修改，保留部分失败事实，并恢复最近一次成功同步前的目标。

**Independent Test**: 首次接管、第二次更新、重复无变化同步和逐组件回滚后，内容及必要权限符合预期；用户改动后 update/rollback 均冲突且不丢备份。

### Tests for User Story 2

- [X] T025 [P] [US2] 在 `tests/test_termcfg_drift.py` 扩展 T013 的三方比较回归：覆盖来源和目标同时变化、权限/链接/属主身份异常、旧备份仍可用，以及回滚预览遇漂移时拒绝继续；任何冲突均不更新基线或静默覆盖。
- [X] T026 [P] [US2] 在 `tests/test_termcfg_recovery.py` 写首次接管配置恢复、`rollback --plan-only` 只读产生专用 ID、非 TTY 用该 ID 恢复、rollback 与进行中的 apply/sync 同机真实竞争时后到者写前返回 4 且 HOME 目标/备份/journal 字节不变、原目标不存在时安全移除、只保留最近一次成功配置备份、成功 rollback 消费备份且不降级 core/插件及漂移拒绝恢复测试。
- [X] T027 [P] [US2] 在 `tests/test_termcfg_interrupt.py` 扩展 T013 的 apply 中断回归，注入回滚中断及恢复时再次中断，验证逐目标 pending/已完成/未完成事实、备份保留与外部改动冲突。

### Implementation for User Story 2

- [X] T028 [US2] 在 `schemas/termcfg/state.schema.json` 与 `src/termcfg/state.py` 扩展 T021 已具备的 TargetRecord/BackupSet/TransactionJournal，加入只读回滚预览身份、成功 rollback 消费备份及回滚中断恢复状态；仅存非秘密来源/前后身份与摘要、权限、阶段和私人备份引用，不存文件正文或私人值，未知字段失败。
- [X] T029 [US2] 在 `src/termcfg/transaction.py` 复核并补齐 T021 三方比较的边缘情况：来源与目标同时变化、权限/链接/属主身份变化以及回滚预览生成期间的外部改动；保持现有安全拒绝规则，不另起第二套 apply 判定。
- [X] T030 [US2] 在 `src/termcfg/transaction.py` 为 T031 的 rollback 提供复用 T021 持久 journal 与上一版备份的安全原语：写前复查目标身份、回滚中断阶段记录、备份保留及外部改动冲突拒绝；备份消费动作仅供成功 rollback 提交调用，不改动版本化运行包。
- [X] T031 [US2] 在 `src/termcfg/transaction.py` 实现组件级配置 rollback：先取得同机器 OperationLease 并在持锁下复查目标身份与摘要，恢复旧普通配置文件/旧链接内容及必要权限；原不存在只移除仍归本管理器且未漂移的配置目标，成功才消费备份，core/插件软件版本保持不变。
- [X] T032 [US2] 在 `src/termcfg/cli.py` 接入 `rollback --component ID --plan-only` 的只读回滚预览及专用 `plan_id`，TTY `rollback` 内预览后一次确认，非 TTY `rollback --plan-id ID` 核对快照；冲突和恢复待处理给出下一条命令。
- [X] T033 [US2] 在 `tests/test_termcfg_recovery.py` 完成隔离 P2 集成验收并记录命令/结果：原内容与权限恢复、重复 apply 不轮换备份、漂移静默覆盖数为零、部分失败可定位。

**Checkpoint**: US2 与 US1 联合可完成安全更新与回滚；服务状态仍可标记未检查。

---

## Phase 5: User Story 3 — 查看环境与组件状态（Priority: P3）

**Goal**: 清晰区分文件、环境、依赖、私人配置和 mihomo 服务状态，并提供只针对自身进程的显式服务操作。

**Independent Test**: 缺必需项/可选项、已同步但未运行、运行中待生效、外部/PID 复用及显式 start/reload/restart/stop 均有准确状态与原因码；文件同步不调用服务。

### Tests for User Story 3

- [X] T034 [P] [US3] 在 `tests/test_termcfg_status.py` 写 `doctor` 每组件与整体 ready/blocked、`--strict` 阻断退出码、JSON `overall_ready/ready/next_command`、文件漂移、待恢复、两种待生效原因及三命令离线预览测试。
- [X] T035 [P] [US3] 在 `tests/test_termcfg_service.py` 写假 core/API/进程的 start/stop/reload/restart、同机器 service start/reload 与进行中的 sync/apply 真实并发争锁且后到者写前返回 4、匹配租约重复 start 幂等、外部实例或端口占用拒绝二次启动、服务等待每 2 秒内心跳/总超时/SIGINT、0600 私人有效 YAML 与 0700 父目录、私人 YAML 不进普通摘要/日志/备份及生效证据不足测试。

### Implementation for User Story 3

- [X] T036 [US3] 在 `src/termcfg/mihomo.py` 定义 `MihomoPrivateRuntime`：仅 `service start` 或需要新有效配置的 `reload/restart` 从当前用户独占的 0700 私人目录读取订阅/secret，用 YAML 结构化序列化器生成并校验仅供运行的、当前用户所有且 0600 的私人有效配置；`status/stop` 不读取订阅或重建 YAML，秘密不进入普通渲染/摘要/状态/日志/备份。
- [X] T037 [US3] 在 `src/termcfg/mihomo.py` 实现 `ServiceLease`：保存 UID、PID、进程开始身份、可执行文件/锁身份、非秘密公开基础配置摘要和控制端身份；不得对含秘密的私人有效 YAML 计算或保存摘要，身份匹配不全标为 `unknown/external`，不得向其发停止/重启信号。
- [X] T038 [US3] 在 `src/termcfg/mihomo.py` 实现显式 start/stop/reload/restart：修改服务租约前取得同机器 OperationLease，匹配租约的健康实例重复 start 不重复启动，外部/身份不明实例或端口占用返回冲突；禁用旧 mgr 隐式数据库下载/配置改写/统计 daemon，只操作自身租约与受限控制端，启动/重启 30 秒、停止/重载 15 秒内给出健康结果或超时状态。
- [X] T039 [US3] 在 `src/termcfg/mihomo.py` 消费 T018/T021 已持久记录的 `pending_core_effect/pending_config_effect`，实现显式服务操作后的 `effective/unverified` 判定：分别核验进程可执行版本、健康及安全可观察的公开配置加载证据，只在证据充分时清除对应原因；不能证明有效配置已加载则保持 `unverified`，不得以私人有效 YAML 摘要作为证据。
- [X] T040 [US3] 在 `src/termcfg/environment.py` 和 `src/termcfg/diagnostics.py` 汇总按组件环境、来源/锁、文件同步/漂移、备份/恢复、私人配置就绪与服务事实；未检查事实一律标为 `unverified`。
- [X] T041 [US3] 在 `src/termcfg/cli.py` 接入 `status` 与 `service status/start/stop/reload/restart --timeout`；`status` 只读，服务副作用必须显式调用并显示 check/start-or-signal/health 阶段与每 2 秒内心跳，失败包含组件、原因码、已发生副作用及下一条命令且保留原待生效状态。
- [X] T042 [US3] 在 `tests/test_termcfg_service.py` 完成隔离 P3 集成验收：同步中自动 reload/restart 次数为零、service 与 sync/apply 同机竞争时写前冲突且状态/包/目标无交错、显式操作状态准确、外部进程无信号、私人值不进入输出和状态。

**Checkpoint**: 三个用户故事在默认隔离环境均可独立验证，服务状态不再由文件状态推断。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 文档、全局审查与有边界的验收证据。

- [X] T043 [P] 在 `docs/termcfg.md`、`README.md` 和 `README.zh-CN.md` 说明普通用户复用已提交锁的 `sync → apply` 路径与维护者显式 `lock` 路径、交互/脚本确认差异、同机器活动锁及仓库共享锁冲突与可重试命令、运行包执行入口/资源权限、回滚预览、超时/进度、配置回滚不降级软件、私人配置迁移、服务待生效及退出码。
- [X] T044 在 `examples/termcfg-machine.toml` 与 `docs/termcfg.md` 提供不含真实路径/订阅/凭据的虚构机器示例，区分公开配置、私人目录、服务租约和可选插件显式准备。
- [X] T045 在 `tests/test_termcfg_security.py` 补齐跨故事安全回归：未知字段、路径穿越/链接竞态、0600 机器/仓库活动锁文件的 symlink/硬链接/属主拒绝、机器 ID 与仓库锁名称相同仍不发生路径别名、疑似秘密拒绝备份、错误/JSON/日志脱敏、未选组件哨兵及进程身份冲突。
- [X] T046 在 `specs/003-sync-terminal-tools/quickstart.md` 和 `docs/termcfg-acceptance.md` 执行并记录离线三命令预览、无手抄 ID 的交互 apply、US1 三方比较/备份轮换/失败恢复、非 TTY 回滚两步流程、rollback 与 apply/sync、sync 与 service/apply 的同机器竞争，以及维护者 lock/lock、lock/sync、交互式 apply 等待确认期间 lock 更新的仓库级竞态（确认后返回 4、HOME/备份/journal/EffectState 零写入）、运行包目录/入口/资源权限、慢操作进度/超时/中断、各故事隔离测试的实际命令/环境/结果/未覆盖项；真实 HOME/core/订阅/tmux smoke 仅在单独明确授权后执行并单独记录。
- [X] T047 在 `src/termcfg/`、`locks/termcfg/`、`terminals/`、`docs/termcfg.md` 与 `tests/test_termcfg_security.py` 做实现 review：逐项核对 FR-001–FR-028、SC-001–SC-013、交互步骤与耗时可视性、宪章秘密/所有权/机器及仓库活动锁/运行包权限/恢复/退出码、来源许可和文档一致性，修复发现的问题并复跑受影响隔离测试。

---

## Dependencies & Execution Order

### Phase Dependencies

```text
Setup T001–T004
  → Foundation T005–T010
  → US1 T011–T024 (安全文件同步内部 MVP)
  → US2 T025–T033 (边缘漂移/回滚)
  → US3 T034–T042 (状态聚合/显式服务)
  → Polish T043–T047 (需要全部故事完成后收口)
```

- US1 依赖共同安全路径、秘密准入、严格清单和脱敏错误；`T017` 的显式完整锁及 RepositoryLease 先于 `T018` 的真实资产安装，`T021` 的 apply 必须复用仓库共享租约；仓库读写锁只在机器独占锁之后获取，维护者 lock 仅取仓库独占锁。`T007` 仅建立安全路径与机器活动锁、不计算旧目标摘要，`T020/T021` 读取旧目标内容或计算摘要前必须先通过 `T008` 的非秘密准入。
- `T004` 先写初始化失败测试，再由 `T010` 实现 CLI；`T007` 的 OperationLease 先于所有机器状态写入；`T018` 先建立最小严格 `EffectState` 供 sync 记录 core 待生效，`T021` 扩展状态 schema 并在任何 apply 写入前完成三方比较、上一版备份、持久 journal 与失败恢复，`T028–T031` 再补回滚状态与执行；`T039` 只补服务生效核验，不承担首次写入待生效状态。
- US2 依赖 US1 已通过的安全 apply 与备份/事务/所有权记录，扩展边缘漂移和显式 rollback。US3 依赖 US1 的锁定 core 与私人 mgr 分离，`T040` 的状态聚合还依赖 US2 的恢复状态；按图在 US2 后集成，避免缺少恢复事实。
- 单故事内先写其风险测试，再实现对应逻辑；同一文件的任务按编号顺序进行。真实 smoke 不在默认自动测试路径。

### Parallel Opportunities

- Setup：`T002` 来源盘点、`T003` schema 和 `T004` fixture 可在不同文件并行。
- Foundation：`T006` 清单、`T008` 秘密准入、`T009` 诊断可分别推进；`T007` 需复用 `T005` 的 HOME 边界。
- US1：`T011–T014` 四组风险测试、`T015–T017` 三组公开来源/锁可并行；`T018–T024` 在所依赖来源和基础实现到位后串接。
- US2：`T025–T027` 分别测试漂移、回滚和中断；实现共享 `transaction.py` 的 `T029–T031` 串行。
- US3：`T034` 状态测试与 `T035` 服务测试可并行；`T036–T039` 共用 `mihomo.py` 串行；`T040` 聚合状态和 `T041` CLI 依赖前面的状态与服务接口。

### Parallel Example: User Story 1

```text
T011 tests/test_termcfg_catalog.py  ||  T012 tests/test_termcfg_plan.py
T013 tests/test_termcfg_apply.py    ||  T014 tests/test_termcfg_mihomo_sync.py
T015 terminals/zsh/,terminals/tmux/ ||  T016 terminals/mihomo/ || T017 locks/termcfg/mihomo.json
```

### Parallel Example: User Story 2

```text
T025 tests/test_termcfg_drift.py || T026 tests/test_termcfg_recovery.py || T027 tests/test_termcfg_interrupt.py
```

### Parallel Example: User Story 3

```text
T034 tests/test_termcfg_status.py || T035 tests/test_termcfg_service.py
```

## Implementation Strategy

### MVP First

1. 完成 Setup、Foundation 与 US1；用临时 HOME/XDG、虚构配置及假服务证明文件同步和备份路径。
2. 检查 P1 的独立验收和实际证据；尚未实现的 rollback/service 能力明确标为未实现，不能把它们计入 MVP 通过。
3. 继续 US2 完成安全回滚，再完成 US3 的状态及显式代理服务管理，最后做跨故事 review。

### Incremental Delivery

每完成一个故事，执行其独立测试与已交付故事的回归；记录实际命令、环境与未验证平台。Linux x86_64 的隔离测试不能推定 macOS 或真实订阅工作。真实 smoke 只在用户单独明确授权时安排，且不以第三方进程退出 0 作为唯一成功证据。
