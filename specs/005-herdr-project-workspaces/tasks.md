# Tasks: Herdr 项目工作区与可验证升级

**Input**: `specs/005-herdr-project-workspaces/` 中的 spec.md、plan.md、research.md、data-model.md、contracts/、quickstart.md；治理依据 `.specify/memory/constitution.md` 2.3.0。

**Prerequisites**: 设计已完成；本文件记录实施任务进度；实现与隔离检查已推进，默认隔离测试不启动真实宿主；后续授权原生验收按分项证据记录，不代表生产切换通过。任务中的新文件按 plan.md 创建，既有文件增量修改；只使用未修改的官方工具和公开能力，不新增 daemon、终端库存、profile 或 Codex adapter。

**Tests**: spec.md 明确要求风险与隔离验证。先写对应测试并确认因缺实现失败，再实现并执行相关检查；默认仅临时 HOME/XDG、fake API/假子进程、网络阻断及虚构数据，不启动 Herdr/Avalon/Pi/DSH/Codex，不读取真实密钥或会话。

**Format**: `- [ ] Tnnn [P?] [USn?] 描述（确切文件路径）`。[P] 只表示在注明前置完成后可与不同文件、无相互依赖的任务并行；同一文件始终单写入者。勾选只表示该项要求已有证据；尚未完成的真实验收保持未勾选，详见 implementation-evidence.md。下文所有“实际 argv/原始证据”均在仓库外私人执行记录中保存（目录 0700、文件 0600）；公开文档/report 只写 normalized_argv、路径标签、原件 digest/evidence_ref，不得把归一化数组称为原始 argv。只有核验私人原件才能支持实际执行身份。

## Phase 1: Setup — 共享准备

**Purpose**: 固定测试边界、公开契约 fixture 与证据记录；不安装或联网选版。

- [X] T001 在 `specs/005-herdr-project-workspaces/implementation-evidence.md` 建立公开任务记录，逐项区分原文“已完成/进行中/失败待决策/环境不足未验证；normalized_argv/exit/evidence ref”，记录候选/target main/锁摘要、环境类别、normalized_argv/私人原件digest、退出码和脱敏引用；私人原件单独保存实际argv，实现和所有真实验收初始均未执行。
- [X] T002 [P] 在 `tests/fixtures/herdr-native/v1/api-schema.json`、`tests/fixtures/herdr-native/v1/responses.json`、`tests/fixtures/herdr-native/v1/source.json` 固定已研究官方 tag 的公开 API schema、响应和来源摘要，保留上游 tag/来源/许可证，仅覆盖允许方法、seq 行为和错误，不把当前候选版本写成唯一兼容版本，不执行宿主。
- [X] T003 [P] 在 `tests/work_helpers.py` 新建共享 fake server/时钟/子进程与临时 Git checkout 工具，强制 HOME/XDG/网络/秘密读取哨兵隔离，支持丢响应、延迟、换端点、ID 复用、原生成员移动以及并发 barrier，禁止默认测试启动第三方宿主。

## Phase 2: Foundational — 所有故事的阻塞前置

**Purpose**: 建立最小普通配置、协议客户端、无意图 shell 与互斥/metadata 原语。这里仅使用静态配置 fixture，不要求 US4 正式部署，也不开放自动工具启动。

- [X] T004 [P] 在 `tests/test_work_config.py` 编写配置、入口和秘密哨兵测试：原文“通用配置未知字段失败”，拒绝 provider/token/credential/resume-session/recent-project；覆盖缺 work、互斥选择器、二进制 shell 文本、配置位置不符、无凭据读取及 Python 引导范围。
- [X] T005 在 `schemas/local.schema.json`、`src/termcfg/work_config.py`、`work` 实现严格 machine.work/CLI 与已准备 .venv 引导：herdr_binary/session 必填，session 为“1..64个ASCII字母数字/下划线/连字符，首字符字母数字”，codex_daemon 布尔默认 false，binary/editor 单 executable；遵守原文“WorkSelection…非秘密选择；pi/dsh显式profile”“不解析SecretStore”，业务 Python >=3.11、系统 Python 3.8 仅转交，参数错误 2、准备不足 5；依赖 T004。
- [X] T006 [P] 在 `tests/test_herdr_api.py` 编写公开协议/端点固定测试：每连接一请求、响应 id、畸形/超长响应、非 ready socket、无 O_PATH/procfs、socket 替换/原 listener 停止、同用户/祖先保护和单调超时；不创建第三方进程。
- [X] T007 在 `src/termcfg/herdr.py` 实现允许方法白名单、session list/启动 argv、ping/schema 能力核对、O_PATH 固定 fd/dev/inode 和每请求 proc fd 连接，遵守原文“请求只连固定fd，不失败重连旧路径；无虚构boot UUID”；“默认总deadline30秒（T061的受管pi/dsh open为60秒）：等锁最多10秒、connect2秒、单request5秒”裁至剩余预算，mutation 不重发，能力失败 5/文件系统失败 6；不实现 send-input/server stop/agent.start；依赖 T002、T006。
- [X] T008 在 `rotom-work-shell`、`src/termcfg/work_shell.py`、`tests/test_work_shell_fallback.py` 实现并隔离验证无 payload 时 exec 原 SHELL、空值 /bin/sh、递归 launcher 拒绝及 .venv 来源验证；建立 `tests/fixtures/herdr-native/v1/config.toml` 最小 default_shell/non_login fixture，冷恢复/手工分屏只进普通 shell；此时有 payload 明确失败且不启动工具，不依赖 US4。
- [X] T009 [P] 在 `tests/test_work_metadata.py` 编写 metadata 容量/格式/seq 和固定互斥风险测试：跨 machine/local、不同 state_root 仍串行同用户 start/enter/open；锁不存内容、不 unlink，unsafe owner/symlink/权限失败；其他来源占满 metadata 退出 4 且不清理；公开 seq 迟到抑制与数值范围不满足则禁止自动变更。
- [X] T010 在 `src/termcfg/work.py` 实现 Linux 每 UID 固定 `/tmp/rotom-work-UID/operation.lock` 无内容 flock（父 0700、文件 0600、同用户普通文件、O_NOFOLLOW、永不 unlink），覆盖 start/enter/open 并受总 deadline 限制；实现原文“patch最多16 keys、resource最多32 keys”“workspace最多10 keys、pane最多8 keys”“key为ASCII字母数字/下划线且<=32 bytes，value为ASCII且<=80字符”，固定 source、无 TTL、每 resource/source 严格递增 monotonic_ns seq，不承诺跨 resource 原子性；依赖 T007、T009。

**Checkpoint**: fake 能力与无 payload shell 可验证；尚无工具启动、正式配置采用或原生通过证据。固定 UID 锁以主代理同步后的设计为准，不能退回可绕过的 machine state_root 锁。

## Phase 3: User Story 1 — 进入已有项目并保持归属 (P1, MVP)

**Goal**: 显式 Git checkout 进入与复用，不依赖 Agent 或正式配置部署。

**Independent Test**: `.venv/bin/python -m pytest tests/test_work_identity.py tests/test_work_recovery.py`；fake 中构造 3 项目×3 checkout×3 终端，100 次重复和 2/10 并发，零重复/错归属，无编辑器或 Agent 启动。

- [X] T011 [P] [US1] 在 `tests/test_work_identity.py` 编写 Git 子目录/symlink/linked worktree、同名/切分支/外置目录及注入字符测试，落实“canonical_root为现存Git checkout realpath；project_digest为UTF-8规范路径SHA256，64位小写hex；label只显示”和“身份=(所选endpoint, canonical_root)”；非 Git/无效路径退出 2 且零 server 创建/修改，禁止 NUL/换行/其他控制字符但不误拒正常 Git symlink。
- [X] T012 [P] [US1] 在 `tests/test_work_recovery.py` 编写并发 enter、创建成功响应丢失、ready 超时、冷恢复/重复映射/epoch 矛盾测试，覆盖 SC-001 规模与次数、不同选择器共享固定 UID 锁、未知不重试及保留初始临时工作区；覆盖唯一同op failed且commit清空时保留role并完成登记、accepted补登记不重启、多匹配/缺marker持续4、自然退役后授权停服再冷恢复的runbook边界。
- [X] T013 [US1] 在 `src/termcfg/work.py` 实现 Git argv 与 realpath 解析、完整 native worktree provenance 复核及工作区唯一映射；明确 Git 错误先于 server 副作用，路径不经 shell，digest 不替代路径；依赖 T011。
- [X] T014 [US1] 在 `src/termcfg/work.py` 实现锁内发现/确实不存在才 headless start、API-ready、worktree.open 与只读对账，只有完整确认新建才初始shell primary/其余absent，并给该无payload初始shell写完整project/epoch/role/op/kind/commit=op/phase=accepted归属标记；已有无 epoch 则“epoch为32位随机hex”、所有角色 unknown，重复enter不改变epoch/角色；已有pending只在唯一同op且failed/commit清空或accepted/commit匹配的完整证明下登记并clear，不明持续4；依赖T012、T013。
- [X] T015 [US1] 在 `work`、`src/termcfg/work.py` 接通 enter 内部 focus/外部 exec attach，attach 前复核固定 socket，拒绝未确认 Herdr 的旧 tmux 嵌套及跨 session，不重启既有 server；attach/已运行任务不受管理 deadline 终止，保留原生退出码；依赖 T014。
- [X] T016 [US1] 在 `docs/herdr-workspaces.md` 记录 Git 首阶段范围、work enter 使用、共享焦点/尺寸、原生tab/分屏与cd/branch边界、unknown与pending恢复runbook（failed/accepted登记；未知继续native工作；全部任务自然结束并另获停服授权后冷恢复），执行本故事隔离命令并将 argv/exit/SC-001 观察写入 `specs/005-herdr-project-workspaces/implementation-evidence.md`；依赖 T015。

## Phase 4: User Story 2 — 按稳定用途找到终端 (P1)

**Goal**: 确认调用归属后复用或显式新增；新建用握手，永不向既有终端发送启动输入。

**Independent Test**: `.venv/bin/python -m pytest tests/test_work_context.py tests/test_work_roles.py tests/test_work_launch.py`；复用 100 次零输入/重启/新增，显式新增 10 次不替换默认；外部/未知普通和 --new 各 10 次零副作用。

- [X] T017 [P] [US2] 在 `tests/test_work_context.py` 编写 caller pane、移动/关闭/跨 session/过期 ID/新 server/别处焦点测试；HERDR_PANE_ID 仅 locator，缺上下文普通和 --new 均 4，不读 cwd/recent/global active 猜归属，不创建/启动/attach。
- [X] T018 [P] [US2] 在 `tests/test_work_roles.py` 编写 primary/extra/absent/unknown、冷恢复、已知成员移出、多 primary 和容量冲突测试，落实“role∈shell/edit/build/debug/pi/codex/dsh；kind∈primary/extra”；核对 SC-002 次数，关闭/移动须完整查询后才 absent，不自动提升 extra。
- [X] T019 [P] [US2] 在 `tests/test_work_launch.py` 编写 ready→commit→accepted→final patch 全失败窗口与崩溃/超时/exec 失败测试：过期或未提交退可见 shell、payload 不继承/不重放；accepted 后 final patch 丢响应只在完整证明既有 op 已提交后完成登记，禁止再次 exec；未决 pending 对普通 open/--new 均阻止创建并退出 4，不自动覆盖/清除/超时回收；已有已确认 primary 仍可仅 focus，无法证明的结果继续 4。
- [X] T020 [US2] 在 `src/termcfg/work.py` 实现显式 pane.current(caller_pane_id=ID)、provenance/epoch/成员前后重查与仅focus复用，每次还核对phase=accepted且commit=op（这是启动交接而非Agent任务状态），登记后failed/commit矛盾转unknown/4并保留pane，不自动重试；稳定显示label；普通 unknown 4，--new 保留已有 primary，否则仅本 role 建新 primary，shell/build/debug 不猜任务命令；依赖 T017、T018、US1。
- [X] T021 [US2] 在 `src/termcfg/work_shell.py` 实现严格 `ROTOM_WORK_LAUNCH_V1` 解析/验证：原文“最大16384 bytes”“version=1；role；kind=primary|extra；op/epoch各32位hex；project_digest为64位hex”“expires_at_ns为正整数的同机单调绝对deadline”；checkout/workspace/session/socket dev/ino/来源和 machine/local 互斥必验，未知字段/任意 command/argv/秘密/控制字符/超长拒绝不截断；依赖 T019。
- [X] T022 [US2] 在 `src/termcfg/work_shell.py` 实现新 pane 一次性 ready/commit/accepted 握手，不获取父 flock；验证 pending/op、自身成员、epoch/provenance、固定端点和期限，accepted 后消费环境再 exec 允许 shell，失败写稳定非秘密failed/error并清本pane commit、保留终端；accepted请求可能已应用且额外最多2秒失败上报也不明时退出launcher，不留下伪有效普通shell；failed为不可逆分支，此后迟到commit也不能重新进入业务exec；ready/accepted 不宣称应用登录成功；依赖 T021。
- [X] T023 [US2] 在 `src/termcfg/work.py` 实现依赖预检→pending→tab.create(cwd/env/focus=false)→确认 ready→commit→accepted→单 patch 更新角色/clear pending→focus；原文“rw_pending…<role>:<32位op>:<primary或extra>；无pending时clear”，7 个 rw_ROLE 为 absent/unknown/p:<32位op>:<pane_id>，pane 前五项与 commit=op 完整校验；不明只读对账/4，不重建/清理；未决 pending 一律阻止普通 open/--new 新建，不自动覆盖/清除/超时回收，也不声称重读 metadata 提供取消 fencing；已确认 primary 仍可仅 focus，accepted 只有完整证明已提交才补登记不重新 exec；seq 仅抑制迟到旧 patch；依赖 T020、T022。
- [X] T024 [US2] 在 `work`、`docs/herdr-workspaces.md` 接通严格 open ROLE [--new]、缺上下文先 enter 提示与 0/2/4/5/6 边界，执行本故事隔离命令并将无输入/握手/冷恢复证据写入 `specs/005-herdr-project-workspaces/implementation-evidence.md`；依赖 T023。

## Phase 5: User Story 3 — 保持输入正确与工作连续 (P1)

**Goal**: 明示共享规则并准备/执行分层输入与连续性验收；fake 不替代真实客户端。

**Independent Test**: 默认 `.venv/bin/python -m pytest tests/test_work_client_contract.py` 仅验收包边界；授权后的每个 SSH/客户端组合须通过合成输入、20 轮缩放/切换和三类断开存活验证，独立于真实 Agent。

- [X] T025 [P] [US3] 在 `tests/test_work_client_contract.py` 新建隔离测试，确认 native 验收未 opt-in 不启动宿主、不读取剪贴板，服务冷恢复无 payload/历史命令重放，attach 退出不杀服务，缺平台/客户端证据不生成支持通过结论。
- [X] T026 [P] [US3] 在 `docs/herdr-workspaces.md` 编写逐客户端输入记录与持续 producer 验收步骤：中文/宽字符/多行/Shift+Enter/编辑器组合键/C-x 前缀原样/显式本地复制粘贴、20 轮分屏 resize/focus，双客户端共享焦点/尺寸，OSC52 只写不查询原剪贴板；列明实际支持组合及失败判据。
- [X] T027 [US3] 仅在获得独立原生 Herdr 授权后，按 `specs/005-herdr-project-workspaces/quickstart.md` 在隔离 server 验证有效配置诊断、非 login wrapper/zsh 集成、客户端退出/启动 shell 退出原 producer PID 保留、主动停止后仅布局恢复不重放任务，将候选/能力/argv/行为证据写入 `specs/005-herdr-project-workspaces/implementation-evidence.md`；依赖 T025、T026，未经授权保持未勾选。
- [X] T028 [US3] 仅在获得对应 SSH/真实客户端及显式合成复制授权后，执行 T026 的输入、多客户端和远程断连重连矩阵，确认 SC-003/004 零错误输入/目标且持续进程保留；记录 `specs/005-herdr-project-workspaces/implementation-evidence.md` 的具体组合与缺证，不查询原剪贴板、不以原生退出 0 替代行为证据；依赖 T027，未经授权保持未勾选。

## Phase 6: User Story 4 — 显式管理配置并安全回退 (P2)

**Goal**: opt-in 单文件 Herdr 管理，复用现有 termcfg 所有权/恢复，不接管私人状态。

**Independent Test**: `.venv/bin/python -m pytest tests/test_termcfg_herdr.py tests/test_termcfg_recovery.py tests/test_termcfg_migration.py`；临时 HOME 中预览/采用/冲突/中断/回退，五次无变化部署不写文件、不换备份，旧 zsh/tmux/state 哨兵不变。

- [X] T029 [P] [US4] 在 `tests/test_termcfg_herdr.py` 编写旧机器未 opt-in、旧 v2 state/pending、声明目标采用、非受管状态哨兵、unsafe parent/外部修改/中断恢复及 SC-005 五次 no-op 测试；配置路径重定向失败，不停止进程获取写权限。
- [X] T030 [P] [US4] 在 `terminals/herdr/config.toml` 实现契约静态字节：C-x/native Goto/non_login wrapper、安静 UI，关闭 sound/toast/Agent resume/版本与规则后台检查/experimental history；在 `terminals/catalog.json` 声明原文“ID=herdr.config、component=herdr、source=terminals/herdr/config.toml、destination=.config/herdr/config.toml、sha256/mode”（0600），不插值私人路径、不拥有 socket/session/cache/manifest。
- [X] T031 [US4] 在 `schemas/termcfg/machine.schema.json`、`schemas/termcfg/catalog.schema.json`、`schemas/termcfg/state.schema.json`、`src/termcfg/config.py`、`src/termcfg/catalog.py`、`src/termcfg/state.py` 扩 opt-in herdr enum 与可选 previous.herdr，严格未知失败，落实原文“state仍v2，只扩component enum/previous可选herdr键”，未选机器/旧记录不迁移不重写；依赖 T029、T030。
- [X] T032 [US4] 在 `src/termcfg/cli.py`、`src/termcfg/preview.py`、`src/termcfg/transaction.py` 接通显式 init-local/plan/adopt/apply/pending/recover/previous/rollback，复用逐文件事务与冲突复查、稳定 plan ID/no-op 备份规则；只处理声明拥有文件，不停止活动实例，不把配置 rollback 当程序/state 降级；依赖 T031。
- [X] T033 [US4] 在 `src/termcfg/doctor.py` 新建计划中的 Herdr 检查（通过现有environment/CLI诊断接缝）并由现有 `src/termcfg/environment.py` 和 `src/termcfg/cli.py` 检查/展示接缝接入（diagnostics.py只负责通用输出，无需修改），核验 executable/来源/.venv/default_shell 意图及 HERDR_CONFIG_PATH/XDG_CONFIG_HOME 规范目标；普通 doctor 离线不启动宿主，实际生效须引用独立授权 native 诊断/握手；未选组件不要求 binary；依赖 T032。
- [X] T034 [US4] 在 `examples/termcfg-machine.toml`、`examples/local.example.toml`、`docs/termcfg.md`、`docs/local-config.md` 更新虚构 opt-in/preview/adopt/recover/rollback 示例，写明旧代码不能消费新 Herdr 记录，先用新代码处理 pending/受管状态再代码回退，保留私人目录与非受管数据；依赖 T033。
- [X] T035 [US4] 执行本故事隔离命令并在 `specs/005-herdr-project-workspaces/implementation-evidence.md` 记录旧 zsh/tmux 兼容、五次 no-op、冲突/中断/回退的 argv/exit/哨兵结果；仅该隔离范围可勾选，配置生效仍须 T027 的授权证据；依赖 T034。

## Phase 7: User Story 5 — 独立编辑器与既有 Agent 入口 (P2)

**Goal**: 在新 pane 用准确 argv/cwd 启动已准备入口，保留身份和显式 Review 交接。

**Independent Test**: `.venv/bin/python -m pytest tests/test_work_tools.py tests/test_work_review_boundary.py tests/test_work_launch.py`；fake 核对每 role 选择器、cwd、身份哨兵、无安装部署/账号迁移，真实交互按工具另授权。

- [X] T036 [P] [US5] 在 `tests/test_work_tools.py` 编写 edit/pi/dsh/codex argv、profile/agent 匹配、准备不足建 tab 前失败、cwd 字面、环境白名单和身份哨兵测试；shell/edit 断言 load_credentials=False 且 SecretStore.resolve 未调用，不允许默默换配方。
- [X] T037 [P] [US5] 在 `tests/test_work_review_boundary.py` 编写 Review 边界测试/合成导出 fixture：work 不读整个 Avalon 状态目录，不自动刷新/广播/删除已保存导出，交接仅所选文件、明确目标且同 checkout，daemon 策略不改变 Pi 委托或全局入口。
- [X] T038 [US5] 在 `src/termcfg/work_config.py` 实现已准备 editor executable、Pi/DSH 显式现有 profile 与 agent 匹配及独立 codex_binary 验证；仅读取普通配置/部署契约，不 sync/apply/install/download/改锁，不新增 profile/adapter 或 workspace HOME；依赖 T036、US2。
- [X] T039 [US5] 在 `src/termcfg/work_shell.py` 接入 edit 的单 executable、`agentcfg [selectors] --profile ID run pi|dsh --cwd ROOT` 与 codex 默认 --no-daemon（显式 true 才省略）固定 argv；保留原身份/state/env 白名单，exec 前去 payload，exec 失败可见且不误记 Agent 启动成功，不影响活动 daemon；依赖 T038。
- [X] T040 [US5] 在 `src/termcfg/work.py` 将工具准备/来源/身份预检放在 pending/tab.create 前，验证准备好的 launcher 与静态 config 意图，不为既有 server 重启或改环境，复用仅 focus；执行本故事隔离命令并记录 `specs/005-herdr-project-workspaces/implementation-evidence.md`；依赖 T037、T039。
- [X] T041 [US5] 在 `docs/herdr-workspaces.md` 记录 Avalon 显式刷新/独立审查/仅选定文件交接、关闭 Review 保留导出，以及 Codex 不共享 daemon 默认与 Pi 委托/全局习惯边界；列出各工具缺准备/身份不符失败和实际验收所需授权；依赖 T040。
- [X] T061 [US5] 原生准备暴露Pi完整运行包校验耗尽工作流期限后，在 `src/agentcfg/pi_runtime_packages.py` 使用固定根和fd相对遍历，保留每个文件的完整SHA256及权限、链接、根/目录/文件前后身份核验；`tests/test_pi_inventory.py` 覆盖内容篡改、替换、越界链接和FD关闭。通过官方lock入口重新生成 `locks/pi/manifest.json` 与四个profile的package-lock，不手改身份、不修改上游；正式plan/sync/apply后复验原生受管入口。原生再次暴露统一30秒不足时，`src/termcfg/work_config.py`、`work.py`、`work_shell.py`仅把pi/dsh open总预算设为60秒，其他角色30秒、锁10/connect2/request5不变，launcher共享父绝对期限；相关`tests/test_work_entry.py`、`tests/test_work_launch.py`验证范围、无重置和过期不exec。对应FR-018/019/032、SC-006；完成证据见implementation-evidence.md，native剩余范围仍由T042跟踪。
- [X] T042 [US5] 仅在分别获得 Avalon/所选 Agent/真实账号或模型调用所需授权后，在合成 checkout 验证 edit/pi/dsh/codex cwd、既有身份、Review 选定交接、独立 Codex daemon 边界及零安装/部署/迁移，结果分工具写入 `specs/005-herdr-project-workspaces/implementation-evidence.md`；依赖 T041、T061、适用的 T027，不以无账号 smoke 代替账号证据，未经授权保持未勾选。

## Phase 8: User Story 6 — 有证据的稳定版采用与升级 (P2)

**Goal**: 离线 schema/判定与授权原生负载分离，首次真实测量建立首基线，推广只改未来入口。

**Independent Test**: `.venv/bin/python -m pytest tests/test_herdr_benchmark.py tests/test_herdr_upgrade_policy.py`；fake 证明缺证/未知字段/未校准/不可比/producer 不足不能误判通过；原生校准、基准、canary 分别独立授权。

- [X] T043 [P] [US6] 在 `tests/test_herdr_benchmark.py` 编写 validate/run/calibrate/compare 参数/退出码、隔离预检、原子新文件不覆盖、实际身份不符、null 不当 0、producer 不足 invalid、必需缺证 unverified、正确性 failure 和首轮无基线误判测试；native 未授权零启动，真实 Agent 成本不混主报告。
- [X] T044 [P] [US6] 在 `tests/fixtures/herdr-bench/v1/manifest.json`、`tests/fixtures/herdr-bench/v1/policy.json`、`tests/fixtures/herdr-bench/v1/producer.py`、`tests/fixtures/herdr-bench/v1/checkouts.json` 固定虚构项目/假提交、seed、允许 argv、就绪与专属清理标签；隔离 machine.editor 仅指向固定版本化 producer executable，经 open edit --new 使用，fixture只读checkout根固定 `.rotom-bench-v1.json`（version=1、run_id、mode=idle/output/record、seed、control_dir、config_digest）；同checkout配置在启动前写完且immutable，实例按已确认HERDR_PANE_ID映射，不同mode/batch/run使用新checkout，不扩生产 role/任意 argv；覆盖 idle/output-1/10/30、projects-27、detached-30、clients-size、churn-leak；policy 未校准值用 null+reason，不捏造预算或批准引用。
- [X] T045 [US6] 在 `schemas/herdr-benchmark-manifest.schema.json`、`schemas/herdr-benchmark-policy.schema.json`、`schemas/herdr-benchmark-report.schema.json` 实现独立版本与每层additionalProperties=false，落实原文“fixture/manifest/policy/schema身份、非识别环境、授权类别、normalized_argv、私人原件digest/evidence_ref、批次/指标/判定”；严格source/target/lock、官方release/tag/commit/asset URL+SHA256、磁盘/运行版本、配置/检测规则/集成来源摘要、预期argv与公开normalized_argv/私人原件digest/evidence_ref、单位/n/null+reason/四种状态及引用一致性；自摘要采用排序键/UTF-8/紧凑分隔/无ASCII转义的canonical JSON，排除自身digest字段、拒绝非有限数字，公开归一化记录不冒充原始argv，实际身份须核验私人原件；依赖T043、T044。
- [X] T046 [US6] 在 `tools/bench/herdr_upgrade.py` 实现离线 validate/compare 与新文件同目录原子落盘，原文“输出文件必须是新文件，存在时退出 4”，错误码 0/2/3/4/5/6 与脱敏摘要；严格输入摘要/身份/冻结引用、scope 与 first-baseline candidate-only，无 baseline 绝不输出 A/B 升级通过；依赖 T045。
- [X] T047 [US6] 在 `tools/bench/herdr_upgrade.py` 实现 runtime/full-stack一次配对采集（--paired-output，新文件且与--output不同；首轮/calibrate拒绝；报告保存共同paired_run_id/冻结和实际顺序/单调窗口）与 run/calibrate 的显式 --allow-native/--authorization 及隔离预检（标志不代替授权），临时 HOME/XDG/专用 socket/虚构 checkout/网络限制/哨兵；合成终端 producer 仅通过隔离 machine.editor 固定 fixture executable 和 open edit --new/new-pane launcher，不接受任意启动 argv；runner控制目录0700/实例文件0600、只允许已登记pane，拒绝重复/陌生实例；ready/start barrier的JSON仅run_id/phase=warmup或measure/start_ns正整数，采用固定同机单调start，不传任意指令；不用 eval/PTY send-input/pane run/agent.start；只清理 manifest 本轮对象且重查归属，不明保留证据不重试；依赖 T046、US2。
- [X] T048 [US6] 在 `tools/bench/herdr_upgrade.py` 实现三 batch/固定单调 start 与 ready/start barrier/60 秒预热/300 秒测量、每暖路径每 batch >=200（总 >=600）、冷启动每 batch 30 仅 median/range（p95 需 >=200）及 nearest-rank p95；output 每终端 128 bytes×512 lines/s×300s=19,660,800 bytes，记录背压/计数/producer CPU，不足只将性能标 invalid（已观察正确性 failure 仍优先总体 failure）；detached 在测量 start barrier 前断开全部 client，完整测量窗口 300 秒；含 detached 全断开、双 client 120×40/80×24 每 10 秒共 30 轮、churn 固定 27 存量/创建关闭及 attach-detach 各 300 次/每 50 次静置 60 秒/尾部 30 分钟；CPU/RSS/对象/进程/FD 分组防 PID 复用，PSS/wakeup 可选不扩权；依赖 T047。
- [X] T049 [US6] 在 `tests/test_herdr_upgrade_policy.py` 和 `tools/bench/herdr_upgrade.py` 实现并测试冻结绝对预算、相对且绝对回归、近零规则、同身份 A/A 噪声、三 batch 一致性/预注册重测保留首轮，runtime 固定配置/规则/集成与 full-stack 分开；未校准/噪声未解/必需缺值不能 PASS，invalid 性能结论只能 unverified，但已观察正确性错误时总体优先 failure，不得以 invalid 掩盖；optional 缺测不阻塞其他充分范围；执行本故事默认命令并记录 `specs/005-herdr-project-workspaces/implementation-evidence.md`；依赖 T048。
- [X] T050 [US6] 在 `docs/herdr-upgrades.md`、`docs/templates/herdr-upgrade-report.md` 编写显式核对最新官方 stable/暂留原因与重评条件、兼容能力而非精确版本门禁、精确候选收据，及首次冻结预算→同 candidate A/A→人工批准冻结 policy→first-baseline→后续同机 runtime/full-stack A/B 流程；分别记录程序/配置/检测规则/集成/锁/环境身份，文档与脚本存在不算测量通过；依赖 T049。
- [X] T062 [US6] 在 `tools/bench/cpuacct.py`、`tools/bench/cpuacct_admin.py`、`tools/bench/herdr_upgrade.py`、`tests/fixtures/herdr-bench/v1/producer.py`、`schemas/herdr-benchmark-report.schema.json` 实现可选本轮v1 cpuacct委派，严格核验管理员收据、boot/source/固定fd与成员身份；仅在新建测试runner/子进程中迁移自身，driver/server/client/producer分组，覆盖短命及daemon后代user+system，不改已有任务或配额。以301个内核快照及固定50ms端点容差绑定300秒窗口，原件包含module/source/window/member摘要，公开报告只留脱敏引用；缺证不晋升CPU覆盖。`tests/test_herdr_cpuacct.py`、`tests/test_herdr_cpuacct_admin.py` 和关联benchmark/policy测试验证拒绝、异常恢复、PTY非阻塞排空、合法斜率7点（六个静置点+30分钟尾部）及普通资源300点，默认不sudo/启动宿主。用户显式准备四个空子组后先验证短命/线程/双fork统计与顺序迁组，再执行独立原生窗口并证明该窗口的自有子进程归零；委派空组保留给T051，全部基准结束后的管理员清理由T051跟踪。对应FR-027/028/029/034、SC-007/008；依赖T049，完整矩阵仍由T051跟踪。
- [X] T063 [US6] 在 `tools/bench/client_geometry.py`、`tools/bench/herdr_upgrade.py` 与固定 `tests/fixtures/herdr-bench/v1/producer.py` 完成原生UI可核验就绪/尺寸证明：record输出与run绑定的固定首帧标记，fresh UI实际读到后才开始首个nonce；从barrier等待期开始只接收严格本轮nonce，回报真实PTY尺寸及阶段；两个owned UI在单pane/干净默认偏好下按每10秒30轮resize/focus序列各自claim geometry，按公开pane.layout精确匹配；成功清理经固定C-x+d原生detach并确认UI退出0后才关PTY，失败不改写退出码；完整detached/churn矩阵仍独立证明长窗口存活。每batch保存60帧geometry及200帧attach端到端原件，严格source/PID-starttime/nonce/阶段/单调边界/配置与摘要核验，报告布尔值无原件不能PASS；measurement_tool摘要绑定runner/cpuacct/geometry模块。`tests/test_herdr_client_proof.py`、`tests/test_herdr_geometry.py`、`tests/test_herdr_client_benchmark.py` 及关联benchmark/policy反例覆盖伪proof、篡改、错窗口、缺batch、端到端计时及FD关闭；真实短双UI探针单列，完整矩阵仍由T051跟踪。对应FR-012/013/026/027/028/033/034、SC-007/008；依赖T048/T062。
- [X] T065 [US6] 在 `tools/bench/herdr_upgrade.py` 修订已知专用server的case收尾：先重新查询全部pane，严格比对与owned全部pane_id/terminal_id/workspace_id三元组集合一致且非空、无重复或缺字段，再经固定socket以官方server stop停止该专用server；未知、丢失或替换对象直接失败并保留，不再跨workspace逐个close导致最后pane进入关闭确认，不放宽confirm_close、权限或操作结果核验。`tests/test_herdr_benchmark.py`及关联Herdr隔离回归覆盖多个workspace、单pane、重排、未知/缺失/替换/重复/空owned及route/command失败；更新必要runner/measurement封印，不改负载/预算。新projects-27完整单batch复验须含各200warm样本、重复/并发正确性、27个producer/301 CPU快照、原件与正常client/server退出及四空组；报告保持partial invalid。对应FR-024/027/028/033/034、SC-007/008；依赖T049、T062、T063，完成后T064方可结束原生复验，T051须使用新epoch全量重跑。
- [X] T064 [US6] 在 `src/termcfg/work_config.py` 消除普通项目入口无条件展开完整Agent公共catalog的耗时：先沿用严格 `load_local(..., load_credentials=False)`；仅在本地原生Agent选项需要schema上下文而返回明确adapter-schema错误时加载原完整catalog重验，其余错误保持失败；不增加缓存、守护进程或配置接口，不修改共享Agent校验和启动语义。`tests/test_work_config.py`及相关work/API/配置秘密测试证明无原生选项时不加载catalog、未知字段及无效原生覆盖仍拒绝、有效覆盖使用完整上下文、非adapter-schema错误不转为成功且不解析凭据。通过默认隔离回归后，在新私有HOME/server执行projects-27单batch完整场景，核对各200次warm enter/reuse及原已批准p95≤1000ms预算、原件与正常清理；报告保持partial invalid，不晋升基线，完整三batch重跑仍由T051负责。对应FR-019/024/027/028/033/034、SC-007/008；依赖T024、T049、T065。
- [X] T066 [US6] 按2026-10-20用户明确接受范围，在仓库外私有原件目录实现仅供本轮使用的校准例外复核与隔离反例测试：冻结runner/三个schema及measurement四源不改；原始invalid报告与计数不改；严格绑定用户批准、原report/raw SHA和唯一detached-30/output/batch1/warmup实例的1行/128字节偏差、同pane/run/PID与phase/CPU原件，所有其他预热/正式输出及正确性/完整矩阵/指标/预算/原件门禁保持严格。审阅后保存独立接受收据及由原pending policy原样派生指标/噪声的冻结policy；首基线独立复核先重验该显式例外，才调用原compare公开Python参数，保留schema合法comparison与独立provenance，不给原严格CLI增设隐式豁免。不启动宿主的反例覆盖篡改、额外缺口、measure缺口、错身份/重叠/漏样/预算/额外invalid和候选失败；记录script/probe SHA及argv/退出码。public交付仅在本feature的spec/plan/contract、`docs/herdr-upgrades.md`与evidence记录授权范围/算法/结果，不增加通用豁免框架；对应FR-027/028/033/034、SC-007/008；依赖T049/T065，T051首基线接续依赖本项。
- [X] T051 [US6] 仅在获得显式选版/原生基准授权后，按 `docs/herdr-upgrades.md` 核对较新稳定版与官方资产/运行身份、冻结绝对预算/负载，执行独立 A/A 校准并经批准冻结 policy 后运行完整首轮矩阵和 compare，已有合格 A 才执行同机三 batch/runtime/full-stack A/B；在 `specs/005-herdr-project-workspaces/implementation-evidence.md` 及授权指定的公开合成报告中记录normalized_argv/私人原件digest/退出码/SC-007/008 与可选缺证，不伪造旧版/预算/首基线；全部基准及需要读取委派身份的canary原件复核结束后，仅由管理员按原收据删除已确认空的本轮cpuacct组，未经授权保持未勾选；依赖 T050、T062、T063、T064、T065、T066、适用的 T027/T028。
- [X] T052 [US6] 仅在独立 canary/未来入口切换与回退授权后，按 `docs/herdr-upgrades.md` 先用新工作试用新 server，再显式选择未来入口；分别演练 binary 选择、termcfg 配置 rollback、合成或受保护副本 native state 兼容/停止不兼容回退，记录磁盘 client/运行 server 配对和旧长任务/唯一原件不变的 SC-009 证据到 `specs/005-herdr-project-workspaces/implementation-evidence.md`；不 live handoff/杀旧实例/假称进程迁移，证据通过本身不授权切换；依赖T051的严格性能验收通过、US4及适用的US3；T051最终管理员空组清理在canary读取委派结束后统一收尾，不作为canary执行前置。未经授权保持未勾选。

## Phase 9: User Story 7 — 按需 Agent 状态提示 (P3)

**Goal**: 状态始终可关、实例独立验证；不兼容时明确保持关闭也是本故事允许交付。

**Independent Test**: `.venv/bin/python -m pytest tests/test_work_optional_status.py`；关闭增强重跑核心 fake 流程；可选启用须两个实例/子任务/延迟事件关联证据，不能据提示操作任务。

- [X] T053 [P] [US7] 在 `tests/test_work_optional_status.py` 编写增强全关仍完成 enter/人工用途/edit/Agent fake 启动、无自动任务/完成判断/关闭、并发根实例/子任务/延迟或未知关联不串会话测试，缺能力保持关闭且不请求额外 socket 权限。
- [X] T054 [P] [US7] 在 `docs/herdr-workspaces.md` 增补可选状态兼容评估表：公开扩展 API/现有资源与锁/依赖身份/实例关联/权限边界，明确 HERDR_ENV/HERDR_PANE_ID/HERDR_BIN_PATH/HERDR_SOCKET_PATH 仅 machine.environment.inherit 逐项选择，继承不等于仅上报权限；不装 controller skill、不强制 peer、不新增 profile/adapter、不改宿主；不能安全兼容时记录原因并保持关闭。
- [X] T055 [US7] 在 `src/termcfg/work_config.py`、`src/termcfg/work_shell.py` 核验状态默认全关、既有 env 白名单不自动扩张；按 T054 明确评估结果，安全条件不足就保持普通 Agent 终端并记录限制到 `specs/005-herdr-project-workspaces/implementation-evidence.md`，仅在既有公开资源/锁确有兼容支持时另列准确目标、身份与验收证据后接入，不为任务完成强行补丁或扩文件范围；依赖 T053、T054、US5，设计前提失败交主代理决定。
- [X] T056 [US7] 执行本故事默认隔离命令并记录 `specs/005-herdr-project-workspaces/implementation-evidence.md` 的 SC-010 全关证据；如拟启用状态，先取得对应原生/各 Agent 实例授权，再分别验收两并发实例、子 Agent 与延迟事件，不明一律 unknown；无授权或不兼容仅启用分项保持未验证/关闭，不能阻塞已验证核心；依赖 T055。

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: 对稳定实现与证据做最终收敛；不自动提交、合并、发布或切换生产入口。

- [X] T057 在 `specs/005-herdr-project-workspaces/quickstart.md`、`docs/herdr-workspaces.md`、`docs/herdr-upgrades.md` 同步最终 argv/路径/支持矩阵/已验证与未覆盖范围，核对 7 故事和下列 44 项覆盖，不把 MVP/fake/计划/CI/退出 0 描述为生产切换证明；依赖已选择交付故事的写入完成。
- [X] T058 在 `specs/005-herdr-project-workspaces/implementation-evidence.md` 记录最终隔离回归 `.venv/bin/python -m pytest tests/test_work_*.py tests/test_herdr_api.py tests/test_termcfg_herdr.py tests/test_termcfg_recovery.py tests/test_termcfg_migration.py tests/test_herdr_benchmark.py tests/test_herdr_upgrade_policy.py tests/test_config_*.py tests/test_termcfg_catalog.py tests/test_termcfg_init_local.py tests/test_termcfg_status.py` 的normalized_argv/私人执行原件digest/退出码及风险覆盖；若新改动导致失败先修本轮受影响路径，两种有效尝试仍失败交主代理，不弱化测试、不启动第三方宿主；依赖 T057。
- [X] T059 在 `specs/005-herdr-project-workspaces/implementation-evidence.md` 单列原生/SSH/编辑器/Agent/账号/bench/canary/回退的授权、执行模型、状态和缺证，真实 failure 保留失败待决策，环境不足未验证不冒充通过也不阻塞无关代码；将 T028/T051/T052/T062/T063 未完成子范围保持未勾选；T056最终选择全关，条件启用不在本次交付中，不冒充启用通过；依赖 T058。
- [X] T060 在 `specs/005-herdr-project-workspaces/implementation-evidence.md` 记录写入结束后的稳定 diff、公开隐私/来源/锁/精确身份/支持边界审查与主代理验收，检查只用官方公开能力、无秘密/私人路径/宿主补丁；若后续改动重跑受影响检查，main 前进重新评估；任何提交/合并/远端更新另按 `docs/publication-policy.md`、`docs/worktrees.md` 核对批准身份和门禁，不由本任务授权；依赖 T059。

## Dependencies & Execution Order

```text
Setup (T001–T003)
  └─ Foundation (T004–T010)
       ├─ US1 → US2 → US5 → US7 (可保持增强关闭)
       ├─ US3 验收包 → [独立授权] 原生/SSH 验收
       ├─ US4 opt-in 配置部署/恢复
       └─ US6 schema/fixture/离线判定
            └─ US2 launcher → 原生负载执行器
                 └─ [独立授权 + 适用 US3] 基准/首基线
                      └─ [独立授权 + US4] canary/未来入口与回退
已选择交付故事的稳定写入 → Polish → 主代理验收
```

- Foundation 先完成；T005 依赖 T004，T007 依赖 T002/T006，T010 依赖 T007/T009；T008 的无 payload shell 不等待 US4。
- US1 不依赖 US4 正式部署；使用 foundation 的静态 config fixture 与无 payload launcher 可独立 fake 验收。US2 基于 US1 项目事实增加安全握手；US5 仅在其后增加既有工具 argv，不改变职责。
- US3 的 T025/T026、US4、US6 的 T043–T046 可在 foundation 后独立准备与隔离验收；T027 的原生核心验收须 US1/US2 完成及独立准备有效静态配置，可以使用隔离 fixture，不把 US4 生产部署作为 US1 前置。真实 editor/Agent 对应 T042，不由 US3 自动授权。
- US6 T047 之后依赖 US2 launcher；T051 依赖适用的真实客户端证据、预算批准与基准授权；T052 的配置回退依赖 US4。没有已验收 A 不阻止首轮 A/A 校准/首基线流程，也不允许伪造 A/B。
- US7 依赖 US5 启动路径，但增强关闭/不兼容不阻塞 US1–US6。任何启用若需新增未指定资源文件，先由主代理确认范围，不擅自扩展。
- 并发写入 `src/termcfg/work.py`、`src/termcfg/work_shell.py`、`src/termcfg/work_config.py`、`work`、`docs/herdr-workspaces.md` 或证据记录必须串行；测试任务先于相应实现。同用户原生操作不受本锁约束，任何阶段都不能声称多 API 全局事务。

## Parallel Examples（前置完成后，仅不同文件且无相互依赖）

| Story | 可并行任务 | 不共享的文件与前置 |
| --- | --- | --- |
| US1 | T011 / T012 | identity 与 recovery 测试；foundation 完成后同时写失败测试 |
| US2 | T017 / T018 / T019 | context、roles、launch 三份测试；US1 完成后写测试 |
| US3 | T025 / T026 | client-contract 测试与 workspace 文档；foundation 完成且文档无其他写入者 |
| US4 | T029 / T030 | termcfg 测试与静态 config/catalog；foundation 完成后，互不依赖 |
| US5 | T036 / T037 | tools 与 review-boundary 两份测试；US2 完成后 |
| US6 | T043 / T044 | benchmark 测试与合成 fixture；foundation 完成后 |
| US7 | T053 / T054 | optional-status 测试与 workspace 文档；US5 完成且文档无其他写入者 |

## Implementation Strategy

1. MVP = Setup + Foundation + US1 的隔离项目进入/复用，独立展示时不启动 editor/Agent。它不是原生平台、输入、恢复、性能或生产切换证明。
2. 继续 US2 后才允许已验证的新 pane shell 握手；US3 提供原生/客户端门禁，US4 完成 opt-in 所有权与恢复，US5 衔接既有工具并独立验收。
3. US6 首先离线实现并验证判定，然后按授权分层取得候选/基准/首基线/新工作 canary/未来入口证据。预算由验收目标冻结，不能在见到候选结果后反推或放宽；真实 Agent/网络成本单列。
4. US7 默认关闭、允许评估不兼容后保持关闭。最终仅声称已实际执行且有充分证据的范围，未授权验收继续 unchecked，不因无法执行原生验收停止无关代码工作。

## Requirement Coverage Matrix（34 FR + 10 SC）

| Requirement | 实现/验证任务 | 可核验结果 |
| --- | --- | --- |
| FR-001 | T013–T016 | 显式 enter、内 focus/外 attach 与复用 |
| FR-002 | T011、T013、T014 | endpoint + canonical checkout、worktree 分离 |
| FR-003 | T012、T014、T007 | 锁、只读对账、未知不重试 |
| FR-004 | T014、T016 | 仅初始 shell，原生 pane 不接管 |
| FR-005 | T011、T013 | 非 Git 2 且服务零副作用 |
| FR-006 | T017、T018、T020、T024 | 严格 7 role/--new、上下文前置 |
| FR-007 | T018、T020、T024 | 复用只 focus、零输入/重启 |
| FR-008 | T018、T019、T023 | extra 不换 primary，未决 pending 阻新建、accepted 证据登记 |
| FR-009 | T012、T018、T020 | 冷恢复 unknown/4、保留布局 |
| FR-010 | T020、T022、T024 | 稳定 label、人工用途无命令猜测 |
| FR-011 | T007、T017、T020、T023 | caller/成员/端点前后核对 |
| FR-012 | T015、T026、T028、T063 | tmux 拒绝与双客户端共享规则 |
| FR-013 | T026–T028、T063 | 合成输入/前缀/复制/resize 真实证据 |
| FR-014 | T008、T025、T027、T028 | 断连任务存活、冷恢复不重放 |
| FR-015 | T029–T032、T035 | opt-in、声明文件、旧状态不重写 |
| FR-016 | T029、T032、T034、T035 | preview/adopt/conflict/no-op/recover/rollback |
| FR-017 | T030、T033、T027 | 静态保守配置与有效加载诊断 |
| FR-018 | T036、T038–T042、T061 | 既有 editor/Agent argv/cwd/身份 |
| FR-019 | T005、T038–T040、T061、T064 | 缺准备先失败、无隐式安装部署 |
| FR-020 | T011、T021、T036、T039 | 字面路径、允许 argv、零 PTY 注入 |
| FR-021 | T037、T041、T042 | Review 显式选定交接/导出保留 |
| FR-022 | T036–T039、T041、T042 | 独立 Codex daemon 不改 Pi/全局 |
| FR-023 | T053–T056 | 默认关闭、实例关联、不据提示操作 |
| FR-024 | T002、T007、T054、T055、T060、T065、T064 | 官方公开接口、无 daemon/库存/扩权 |
| FR-025 | T050、T051 | 最新 stable 核对、暂留重评 |
| FR-026 | T045、T050、T051、T063 | 发行/运行/配置/规则/集成精确身份 |
| FR-027 | T044、T047、T048、T051、T062、T063、T065、T066、T064 | 可重放矩阵、指标定义、Agent 成本分开 |
| FR-028 | T046、T049–T051、T062、T063、T065、T066、T064 | 固定同机 A/B、policy、缺证不 PASS |
| FR-029 | T043、T046、T049–T051、T062 | 首轮真实结果、可选缺测不扩权 |
| FR-030 | T050–T052 | 独立验收→新工作 canary→显式未来入口 |
| FR-031 | T034、T050、T052 | 程序/配置/native state 三类回退 |
| FR-032 | T005、T007、T050、T061 | 运行时兼容范围与能力门禁 |
| FR-033 | T001、T027、T028、T042、T051、T059、T063、T065、T066、T064 | 分层证据、四种任务状态 |
| FR-034 | T003、T025、T043、T047、T059、T060、T062、T063、T065、T066、T064 | 默认隔离与独立授权/脱敏 |
| SC-001 | T011、T012、T016、T044、T051 | 3×3×3、100 重复/10 并发零重复错归属 |
| SC-002 | T017–T019、T024、T051 | 100 复用/10 新增/缺上下文各 10 次 |
| SC-003 | T026、T028 | 每声明组合 20 轮与零错输入/目标 |
| SC-004 | T025、T027、T028 | 三类断开原进程保留、布局不冒充进程 |
| SC-005 | T029、T032、T035 | 5 次 no-op、只影响声明目标 |
| SC-006 | T036–T042、T061 | 各入口 cwd/身份、零额外安装/交接 |
| SC-007 | T043、T045、T046、T049、T051、T062、T063、T065、T066、T064 | 必需证据/门槛/未执行零误判 |
| SC-008 | T048、T049、T051、T062、T063、T065、T066、T064 | 三 batch、>=600 暖操作或明确 first-baseline |
| SC-009 | T052 | 旧任务/唯一状态保留，不兼容明确停止 |
| SC-010 | T053–T056 | 全关核心可用，状态零自动任务操作 |

跨切面任务的显式映射：T004→FR-019/FR-032/FR-034；T006→FR-003/FR-024；T009/T010→FR-003/FR-008/FR-011；T057/T058→FR-033/FR-034（覆盖全部故事的收敛与关联回归）。这些不是额外产品需求。

## 当前状态与未验证环境

用户已明确授权完成剩余工作；本表不再以缺少重复授权解释未执行项。所有原生操作限定隔离HOME、合成checkout及自有server，未切换生产入口。

| 范围 | 当前状态 | 证据/任务 |
| --- | --- | --- |
| 核心与termcfg实现 | 已完成；本轮原生发现三项已修复 | implementation-evidence.md；最近全关联回归830 passed绑定修前快照；后续Pi/DSH期限相关141项及CPU统计相关检查分开记录 |
| Linux原生配置/项目/进程/冷恢复 | 已完成 | T027；9checkout/27终端、100重复/2与10并发、100复用/10额外，PTY连续性和冷恢复 |
| SSH/真实客户端/显式复制 | 已完成本轮声明组合 | T028；macOS26.6.2/Ghostty1.3.1 stable八步、Avalon内部Ctrl+w v/h/l与显式+复制均完成，回环双客户端及断连亦通过；其他组合不扩展声明 |
| Avalon/Agent/账号/模型 | 已完成本轮所选启动及模型交接范围 | T042/T061；Avalon/DSH/Codex入口、Review导出保留、官方Codex真实模型选定交接通过；受管Pi期限修订后双实例实际Node/独立租约持续存活及专属清理通过 |
| 原生基准/校准/首基线 | 已完成；完整首基线严格PASS，管理员空组清理完成 | T051/T066；三batch、33个完整CPU窗口及原件、45项正确性、1338 producer及426个输出phase精确计数通过；原校准唯一预热例外保留，首基线无例外。必需未验证0、可选未验证267；四空组最后由原管理员脚本删除，exit0 |
| canary/未来入口/三类回退 | 已完成本轮独立验收 | T052；显式bootstrap、work enter/build/debug及复用、长任务身份、配置rollback/reapply、旧binary能力拒绝、状态保护副本、compatibility_unproven_stop均完成；四子任务正常退出、所有登记server/wrapper收尾；原始失败保留，后续步骤独立补验并由Root接受；生产入口未切换 |
| 可选状态 | 已完成（最终选择全关） | T056；SC-010隔离路径通过，不宣称启用、双实例关联或通知验收 |

本机是本轮唯一测试环境，不以另找机器作为推进前提。实际失败及修复保留原件，不改记为环境缺失；无法满足的环境能力不能冒充通过，也不阻止无关实现。当前66/66项完成；本轮工作树实现与约定的本机验收完成，完整性能/独立canary/管理员清理均有独立收据；合入main与生产默认入口切换不由验收结果自动授权。最终检查与只读分析见implementation-evidence.md、implementation-review.md。
