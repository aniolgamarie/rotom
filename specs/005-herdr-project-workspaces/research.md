# Phase 0 research — Herdr 项目工作区

日期：2026-10-18。区分 tagged 源码、仓库事实、设计决策与执行证据。社区背景保存在 [evidence.md](../../openspec/changes/herdr-native-workspaces/evidence.md)，需求以 [spec.md](spec.md) 为准。

## R1 运行时与候选版本

**Decision**: Python >=3.11，使用已准备的 .venv；3.11.11 仅本机观察。每次安装/升级显式核对最新 stable 并记录精确资产。当前 [latest release](https://github.com/herdrdev/herdr/releases/latest) 指向 [v0.9.5](https://github.com/herdrdev/herdr/releases/tag/v0.9.5)，作为候选而非永久版本门禁。

**Rationale**: 宪章 IX 区分兼容范围、实测版本和部署身份。PATH 中旧 0.8.0 只有元信息观察，不是通过基线；相同版本字符串也不证明 server/规则相同。

**Alternatives considered**: 精确锁 Python 补丁会排除兼容环境；任意“更大版本”不证明协议；启动联网更新破坏离线契约。均拒绝。

## R2 项目身份与调用上下文

**Decision**: 用 git -C PATH rev-parse --show-toplevel 得到 checkout，再 realpath；拒绝控制字符，空格/中文/引号/元字符保持字面。主副本与 linked worktree 分开，不用 common git dir。新建前通过worktree.list(cwd=checkout)取得source.repo_root；0.9.5拒绝从linked checkout发起open，因此使用该主仓库路径作为open cwd，path仍为canonical checkout。原生 worktree.open 按 canonical checkout 复用；provenance 为项目事实，动态 cwd/标题仅显示。

open 必须有 HERDR_PANE_ID，向所选 server 显式 pane.current(caller_pane_id=...)，核对当前 workspace 的 worktree provenance。禁止省略 caller 的焦点回退。移动后重查，失效/不明退出4；外部 --new 同样拒绝。

**Rationale**: [worktree handler](https://github.com/herdrdev/herdr/blob/v0.9.5/src/app/api/worktrees.rs) 按 canonical checkout 查 already_open_workspace；[pane handler](https://github.com/herdrdev/herdr/blob/v0.9.5/src/app/api/panes.rs) 缺 caller 时会使用全局焦点。同 server 焦点共享，不是每客户端独立。

**Alternatives considered**: cwd 跟踪、分支/名称、最近项目、固定 workspace 环境变量均可能错归属；额外项目数据库没有必要。

## R3 server 生命周期与端点固定

**Decision**: Linux 上从公开 herdr session list --json 的 socket_path 选择 endpoint，用 O_PATH|O_NOFOLLOW|O_CLOEXEC 打开，核对同用户 socket/受保护祖先。操作期间保留 fd，每个普通 API 请求连接 /proc/self/fd/<fd>。失败后不重新按原路径连接。替换 socket 后只能到原监听对象或失败，不会自动控制新同名 server。使用公开 [Socket API](https://herdr.dev/docs/socket-api/) JSON 协议，不猜内部 socket 路径。

**Rationale**: [API server](https://github.com/herdrdev/herdr/blob/v0.9.5/src/api/server.rs) 每连接仅处理一条普通请求，不能使用一条持续连接完成多步事务。公开 ping 没有 boot UUID；数字 ID 可能在冷启动重用。stat 前后检查或订阅 EOF 不能阻止请求落到替换实例。

2026-10-18 执行了仅临时目录、自有 Python Unix socket 的内核实验：固定旧 socket 的 O_PATH fd，unlink 后同路径新建 listener，连接 proc fd 仍由旧 listener 接收；关闭旧 listener 后 errno111，并未转到新 listener，退出0。首次沙箱 bind 被拒，随后受控本地执行通过。该证据只证明本机 Linux 机制，不是 Herdr/平台/SSH 验收。依据 [open(2)](https://man7.org/linux/man-pages/man2/open.2.html)、[proc_pid_fd(5)](https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html)。实现须做同类合成能力预检；缺能力退出5，不能降级自动变更。

**Alternatives considered**: 持续普通 API 不受支持；events sentinel 不提供 fencing；权限代理/改宿主越界；只信 session 名不安全。端点固定仅限定 server 存活期，不声称跨 API 原子性，也不阻止用户原生移动对象。

## R4 并发与未知结果

**Decision**: Linux每UID共用固定 `/tmp/rotom-work-UID/operation.lock` 无内容flock，串行本入口start/enter/open。父目录0700、文件0600，验证同用户普通文件、O_NOFOLLOW，永不unlink锁文件；拒绝不安全既有路径，不自动chmod接管。锁不依赖machine/local的state_root，两个配置选择同server也不能绕过，不存终端清单。原生操作不受锁约束，使用前后核对成员关系；变化退出4，不发送输入/关闭对象。

workspace 保存短 rw_project SHA256、随机 rw_epoch、7个 rw_ROLE 状态；pane 保存 epoch/role/op/kind/phase。source 固定 rotom-work-v1，不设 TTL。完整路径仅从 native provenance 取得。先写 pending 再 tab.create；launcher 自报新 pane op marker，父调用对账后提交。创建与 metadata 非原子；不能证明完成时保留 pending/unknown，退出4，不自动重试 create/启动/清理。

**Rationale**: [metadata normalization](https://github.com/herdrdev/herdr/blob/v0.9.5/src/app/api_helpers.rs) 将值 trim/过滤/截到80 chars，patch最多16 keys、resource最多32；不能无损保存任意路径。request.id 仅响应关联，不是幂等键。worktree.open 能复用 checkout，但超时不等于未创建。

**Alternatives considered**: 创建后才标记封不住重复窗口；锁不能解决调用崩溃；按machine的state_root建锁会被另一配置绕过；terminal inventory越界。未知pending不允许--new覆盖或自动过期回收，metadata重读不是取消fencing；已确认commit/accepted可只读对账后完成登记，不能重启。其余未决结果退出4保留对象，用户显式处理；unknown不能当absent。状态机见 [data-model.md](data-model.md)。

## R5 冷恢复与 primary

**Decision**: 新创建且完整确认的项目可把初始 shell 标 primary，其余 absent。已有但无本入口运行期证明的 workspace，enter 仅建立本轮 epoch、所有用途 unknown，不接管原生终端。默认 unknown 退出4；--new 可在无可确认 primary 时建立该角色 primary，保留旧布局及其他 unknown。已知 primary 的关闭/移动需同 endpoint 完整查询确认后才可记 absent；不明仍 unknown。

**Rationale**: [workspace.rs](https://github.com/herdrdev/herdr/blob/v0.9.5/src/workspace.rs) 与 [restore.rs](https://github.com/herdrdev/herdr/blob/v0.9.5/src/persist/restore.rs) 冷恢复清空 metadata。标记缺失不证明从未创建；primary/extra 用 op 关联，名称不构成所有权。

**Alternatives considered**: 恢复后重建全部角色会重复；自动认领同名 tab 会误操作。--new 是用户已选路径，不新增自动接管。

**Recovery refinement**: enter可完成唯一同op且已证明failed/commit清空或accepted/commit匹配的登记；failed是launcher不可逆分支。其余pending继续4，原生项目/tab仍可使用。未知事实无法重建时，只能等该server工作自然结束并由用户明确授权停服后冷恢复；不自动清pending或终止任务。具体步骤见[runbook](contracts/work-cli.md#pending-recovery-runbook)。

## R6 新终端启动

**Decision**: 静态受管配置增加 terminal.default_shell="rotom-work-shell"、shell_mode="non_login"，PATH 必须指向本仓库 launcher。work 启动新 server 时为其 PATH 前置仓库根，不改全局 shell。无 payload（普通tab/分屏/冷恢复）则 exec 已校验 $SHELL，空值 /bin/sh，拒绝指回自身；Linux 沿用 non-login 交互 shell。

有 payload 时只接收版本化 JSON 的机器选择、checkout、workspace/epoch/role/op 等非秘密意图。重建固定允许 argv，不接收任意命令文本。新 pane 自报 ready，等待父调用提交本 op，再消费/清除 handoff 并 execvpe。未提交/错误/重复marker/超时/归属不符不启动工具，显示错误后进普通shell，保留可见终端。父调用只报告已交给入口，不声称登录/任务开始或完成；exec失败由launcher明确报错。一次性语义由本仓库负责，不声称上游保证；冷恢复不重放 payload。

**Rationale**: [TabCreateParams](https://github.com/herdrdev/herdr/blob/v0.9.5/src/api/schema/tabs.rs) 无argv；[pane run](https://github.com/herdrdev/herdr/blob/v0.9.5/src/cli/pane.rs) join参数发送输入；[default shell](https://github.com/herdrdev/herdr/blob/v0.9.5/src/pane.rs) non_login直接执行无附加参数，tab env是字面映射。

**Alternatives considered**: PTY send input可能混入用户输入；agent.start只支持固定工具并通过shell输入；通用调度器越界。静态 executable 名避免新建 termcfg 模板系统；doctor和新建握手验证launcher来源，未准备退出5。

## R7 配置与既有启动契约

**Decision**: termcfg 新增 opt-in herdr、静态 catalog 目标与 schema 枚举，不改 state version。只拥有 target_home/.config/herdr/config.toml；HERDR_CONFIG_PATH 或 XDG_CONFIG_HOME 指到其他根时检查失败，提示显式准备相同文件，不静默重定向。未选组件不操作 Herdr。旧v2 state不重写，新herdr记录旧代码不能消费；pending先由新代码恢复，再考虑代码回退。

machine.work 增加 binary/session/pi_profile/dsh_profile/codex 选择，editor沿用 machine.editor。普通配置 load_credentials=False；shell/edit 不解析 secret。Agent 使用现有 agentcfg [selectors] --profile ID run pi|dsh --cwd ROOT，全局参数在子命令前，不新建profile。独立Codex默认 --no-daemon，保留显式daemon选择，不改Pi委托。

**Rationale**: termcfg catalog只读静态字节/sha，无模板；现有transaction/preview/state可复用。现有agentcfg run不安装部署，共享run lease允许并发，但非真实并发会话证明。machine.editor为单一executable，不是shell文本。

**Alternatives considered**: 全量继承Agent环境、精确补丁锁、重构运行包、Codex adapter、新DSH profiles越界。状态扩展仅通过既有资源/锁可选接入，无法安全兼容即继续普通终端，不扩sandbox/socket权限。

## R8 基准与验收

**Decision**: 独立 tools/bench/herdr_upgrade.py 提供离线validate/compare及显式opt-in run/calibrate。冻结版本化合成负载、3 batch采样、单位与policy。first-baseline、A/A、固定输入runtime A/B、完整组合A/B分开。必需证据缺失、错误、未校准均不能PASS；可选PSS/wakeup缺测单列未验证。具体见 [benchmark](contracts/benchmark.md)。

**Rationale**: 复用 [升级基准材料](../../openspec/changes/herdr-native-workspaces/upgrade-benchmarks.md) 的负载/采样，不伪造旧版成绩；独立runner不扩大agentcfg CLI，原生run要授权/隔离预检。首次无已验收A时可用同候选重复测量估计噪声，先冻结首轮绝对预算，完成对应验收后建立基线；不能循环要求先有基线才能建立基线。

**Alternatives considered**: 版本号代替测试、CI代替真实客户端、混入Agent成本、事后放宽policy、切入口称状态回退均拒绝。

## Research closure and evidence status

无待澄清产品选择。端点固定、launcher、配置诊断、native worktree行为有明确实现/原生门禁和失败行为；设计和源码审计本身不是通过事实。此前设计阶段未运行宿主；用户后续授权剩余验收并指定本机为唯一环境后，已用校验过的官方资产执行Linux核心、PTY/回环SSH、冷恢复、Avalon Review及DSH/Codex部分入口。实体交互、Pi准备、模型交接、完整性能基线与生产推广仍缺证。最终关联检查与各分层结果见implementation-evidence.md。

## Implementation refinement (2026-10-19)

primary token保存 `p:<op>:<pane_id>`（仍不超过80字符），使当前完整pane查询能区分已关闭和metadata擦除，不另建库存。handoff额外绑定local配置路径与普通启动选择摘要，恰好一个machine/local选择；reuse前后复查调用pane/epoch。accepted写入丢响应按可能已交接处理，失败上报不明时退出launcher。新server启动前增加官方 `herdr config check`，先验证文件存在，避免解析失败/缺文件回退默认自动恢复。依据：[v0.9.5 CLI](https://github.com/herdrdev/herdr/blob/v0.9.5/src/cli.rs)、[loader](https://github.com/herdrdev/herdr/blob/v0.9.5/src/config/io.rs)。以上均为保守实现细化，不扩展生产入口。

## Native acceptance refinement (2026-10-19)

原生0.9.5验证发现并修复三项：启动server显式umask 077（不放宽socket保护）；linked checkout通过公开worktree.list的主仓库source发起open；普通机器配置加载传入公开adapter schemas，仍禁止解析凭据。绑定当前核心源码摘要的独立原生复验确认022调用环境下socket父目录0700/socket0600、中文空格linked路径与symlink唯一归属、合法DSH agent_options可加载。此为实现纠正，不改项目身份或启动边界。

基准的user namespace虽可创建，但同UID映射隐藏宿主root UID，与既有socket祖先保护不兼容。本机后续改用显式`--offline-sockets`：固定fixture helper通过已有libseccomp设置no_new_privs，拒绝非AF_UNIX的socket/socketpair及io_uring_setup，关闭继承的额外FD，实测后代继承和Unix IPC可用，保留宿主UID及原有祖先保护。该路径不引入服务或提权，只供授权合成负载，不是针对恶意程序的通用沙箱。依据：[内核seccomp filter](https://kernel.org/doc/html/latest/userspace-api/seccomp_filter.html)、[no_new_privs](https://cdn.kernel.org/doc/html/latest/userspace-api/no_new_privs.html)。

本机没有可委派cgroup完整CPU计量；保持必需CPU口径，显式单case诊断允许保留实际观测，但必须partial/invalid，不能建立性能基线。完整矩阵每subject固定窗口/屏障下限18492秒，另加操作耗时；不在缺必要能力时盲跑长矩阵。本机是本轮唯一测试环境，缺少的测量能力单列，不转嫁为必须另找机器的前提。实际结果见implementation-evidence.md。
