# 依赖、原生加载与实例生命周期契约

## 1. 组件与责任

| 组件 | 责任 |
|---|---|
| PiAdapter | 严格配置、native 字段与资源意图、凭据投影规则、启动说明、capture/doctor 投影 |
| PiBackend | 独立 Pi 锁解析、显式 frozen install、平台资源、完整收据与修复 |
| instance supervisor | 实例活动保护、子执行归属、平台进程观察、显式停止/reconcile及受限recover_stop |
| workspace write lease | Git工作区身份锚定的跨实例写入互斥与持久记录，独立于profile/XDG目录 |
| runtime launcher | 固定 HOME/env、封闭资源 loader、所选引擎、实际加载身份记录 |
| AgentManager vendor | 唯一子执行队列和记录；ordinary session executor、managed process executor及model-delegate external executor |
| Task Keeper | 任务、候选、请求预算、恢复、检查、审查、一次性调度 |

公共 backend 协议继续提供 read_lock/resolve_lock/sync/root/status/executable_paths/toolchain；
Pi 使用自己的 lock schema，不复制 DSH 的 package 名称、helper 检查或 Superpowers 限制。
需要共用的 staging/原子替换/收据校验抽取为中性函数，DSH 旧输入与输出保持不变。
Pi 已部署启动保存 `runtime_identity = digest(lock_identity, slice_identity, platform, toolchain_identity)`；
root/status 用该组合身份定位对应历史收据，回滚不按当前 profile 重选切片。
增加可选 backend `runtime_identity(workspace, lock)` 钩子；未提供时返回旧 lock.identity，保持DSH兼容。
Pi版本化LaunchSpec/保存记录同时保留 source lock_identity 和新 runtime_identity；
runtime.record、run、doctor、sync与依赖预检统一使用已保存的runtime_identity定位安装树。
旧记录缺该字段时回落lock_identity；不得将源锁身份与安装树身份混写。
配置候选记录所选slice和其版本化引用集合，回滚严格使用历史值。

## 2. 版本与源码来源

- Pi 0.84.4；Node 24.14.0 + npm 11.19.1 为锁生成及 Node 配方运行基线。
- `@tintinweb/pi-subagents` 0.19.0 固定上游 SHA 加 `0.19.0-agentcfg.1` 补丁。
- Task Keeper 本地目标 `0.2.0-agentcfg.1`，替换旧 0.63.0 依赖；不得在运行树出现旧管理者可加载入口。
- Cursor 可选配方使用 Bun 1.4.0；Node/npm 仍负责锁和依赖准备。
- 可选 Codex CLI 0.154.0 使用上游对应平台发行物；不借用 PATH 中未锁定程序。
- model-delegate完整源码、两backend和Pi工具桥属于运行资源；旧codex-delegate及codex-agents不进入新切片。
- 其他来源以 [能力矩阵](capability-matrix.md) 为版本输入；完整传递依赖在 lock 阶段产生。

锁生成产物必须给出真实 tarball/源码摘要，不允许占位摘要。此计划不提前伪造未构建归档的哈希。

## 3. PiLock v1

字段详见 [数据模型](../data-model.md)。所有字段 closed；sources 为 npm/git/local/asset 判别联合。

锁生成可对上游 shrinkwrap 缺少的 SHA512 SRI 查询精确 package@version 的官方 npm 元数据补全，但 tarball 地址必须与已解析条目完全一致。该行为仅属于显式在线 lock；read_lock/sync 不修补锁。发布包遗漏完整许可证时，npm 来源可显式声明 `license_sources`（目标 license_files 路径 → `agents/pi/build/licenses/` 内的来源文件）；来源参与 recipe_digest，sync 只补缺失文件，已有不同正文会失败。它不改变原 npm 归档及其 integrity。
每个配方有 profile_slice 与独立完整 package.json/package-lock.json；根锁索引覆盖所有切片，
sync 对选中切片的原始完整文件对执行 npm ci，不裁剪、改写或按运行时重新解析总锁。
下载内容缓存可去重，安装树和收据仍按切片独立。
identity 覆盖完整 npm lock、源归档、vendor 补丁、资源清单、构建规则、adapter/bridge 版本与平台要求。

- npm：精确版本、resolved、integrity、完整依赖树。
- git：完整 commit、确定性归档及摘要，禁止以 branch/tag 作为最终身份。
- local：仓库相对源树、完整内容及执行意图摘要、归档，不依赖源仓库本机路径。
- asset：上游发布 HTTPS URL、平台/架构、archive_digest、archive_member、target、license_files；用于选择的外部可执行程序。vendor_path 可选：提供时消费锁目录内归档，否则只在显式 sync 时按当前平台下载。asset 不进入 npm dependencies；同一目标必须覆盖锁中全部平台且每平台唯一。许可证放在参与 recipe_digest 的 agents/pi/build/licenses/ 下。完整归档摘要核验后只提取声明入口，拒绝链接、重复条目、路径越界、过大内容和错误 ELF/Mach-O 架构；不会在安装阶段执行该宿主。
- build_steps：明确 argv、平台、输入摘要、输出清单；只执行已审阅步骤，无通用生命周期授权。

基本安装使用 `npm ci --ignore-scripts`。原生 readseek、权限依赖 WASM、可选平台包与本地 helper
必须列入必要产物检查，不能仅凭 npm 返回 0 就激活。
构建源和 dev/build 依赖也要锁；运行树不携带旧机器 node_modules、测试报告或秘密。

## 4. 激活、损坏和修复

1. 验证配置、锁、权限与活动记录；未知/活动 execution 返回 4。
2. 新私人 staging 使用隔离安装 HOME 和缓存；下载仅 sync/lock 允许。
3. 核对每个包、entrypoint、许可证、资源引用、执行位和可加载插件身份。
4. 生成 runtime receipt；同目录原子激活，失败不替换可用运行包。
5. 运行前重新校验正文与必要入口，不用 marker/size/mtime 替代。
6. damaged 由 sync 暂存修复；修复槽与配置 pending 分开，账号 home 固定。

## 5. 原生发现与启动约束

runtime launcher 直接使用锁切片中的 Pi SDK/入口。resource loader 接受生成的绝对已安装路径清单，
在加载 factory 前排除未选择的扩展；禁止 npm:/git: 动态解析、全局 fallback 和隐式下载。
SDK 自带 updater/package commands 在此受管入口禁用或转换为“请通过 agentcfg sync/lock”提示。

默认不发现 cwd 下未声明的 project packages/extensions/agents；启用 project_resources 时必须
先生成合并后的清单和身份，普通角色可按明确规则覆盖，受管角色同名覆盖一律冲突。
规则、技能与项目上下文仍从显式已选择资源加载；禁止从关闭扫描推导“业务项目不可读取”。

role 资源从受管角色目录显式注册，新框架不依赖旧 pi.subagents.agents 自动发现。
启动记录 `loaded_manifest_digest`、实际角色/工具/插件来源与运行时身份；这一记录只能证明加载，
不能证明模型调用或任务完成。每次版本/策略变化使旧不匹配证据 stale。

保留变量包括 HOME、XDG 各根、PI_CODING_AGENT_DIR、PI_CODING_AGENT_SESSION_DIR、CODEX_HOME、
AGENTCFG_INSTANCE_ID、AGENTCFG_RUNTIME_ID、AGENTCFG_SUPERVISOR_ENDPOINT 和所有 grant/bridge 前缀。
只给所需进程注入所需秘密，worker 不继承不相关 provider 或 Codex 凭据。

## 6. 活动与停止

supervisor先持久登记allocating intent及全部目标，再预留workspace，持久提交starting/spawn_committed后才能spawn；
manager、检查器、Codex和所选后台工具必须经过它。预留中崩溃的回收证明和提交后unknown规则见恢复契约。
控制端点位于实例私人目录，nonce 按激活生成，所有请求验证 owner 与实例身份。

- 配置/依赖变更需排他访问且没有未完成/unknown execution。
- supervisor 持有实例租约，父 Pi 退出仍等待已登记工作结束；若监督崩溃，持久记录继续阻止变更。
- 停止是用户明确任务控制，由 supervisor 仅终止已证实归本次任务的 worker/进程组；
  不因 apply/sync 请求自动杀进程，不杀旧 home 或其他工具的进程。
- 新supervisor经同实例认证后，可用持久记录中的旧owner只读reconcile历史lease；
  旧nonce不授予新dispatch/cancel权限，也不因激活变化自动释放。完整终止或从未启动证据才可解锁。
  若旧supervisor已证实失效，用户可显式recover --stop取得绑定计划/目标的新停止授权，
  撤销旧generation后只终止已核实拥有的执行；旧控制者仍活跃或身份未知时拒绝。
- 不合作工具、无法登记归属的后台工作或身份不确定时保持 unknown，报告操作目标与复查指引。
  Linux Pi 宿主及官方 Codex 的整次委托分别置于独立 PID 命名空间：固定 bwrap 创建 PID 1 的第一方门控程序，
  supervisor 核对 init/包装进程的出生身份、命名空间及 NSpid=1，持久登记 v3 记录后才写入 G 放行；EOF 不执行目标。
  PID 1 退出由内核终止该命名空间及其后代，停止以 pidfd 指向已确认的 init，终止证明同时覆盖包装进程。
  即使原生工具另建进程组或孙进程重新托管，也不依赖轮询完整捕获其出生链。僵尸必须匹配原出生身份才能判为已退出。
  宿主使用独立的门控socket，通过SO_PEERCRED核验连接者就是已观察到的init，再登记及放行，保留原始stdin/TTY。
  宿主的文件挂载继承调用者已有权限；此层只增加内核进程范围，不替代文件授权。四个Linux配方均锁定并安装该helper。
  旧 v1/v2 记录保留原算法与 escaped/unknown，不升级或清除旧保护；其他执行与 macOS 保留原边界。
- model-delegate的Pi/Codex单run经同一supervisor登记，禁止调用旧runner或未锁定CLI；
  skill直接执行时也必须认证实例和工作区授权。批量请求由既有上层manager分配并发，runner不另排队。
- 所有受控写入先取得独立WorkspaceWriteLease。锁锚定到worktree专属Git管理目录inode，
  私人持久标记位于该git-dir的agentcfg/write-lease.json，不随实例HOME/state_root改变。
  内核锁释放不抹去未知持久记录，跨profile同worktree并发只能一个成功；细节见
  [控制恢复与工作区契约](recovery-and-workspaces.md)。
- 普通 session executor 的活动也登记；只要父会话活跃，宿主租约有效。
  它的 stopped 不能作为受管终止证据，也不能在未清理外部工作时释放整个实例保护。

## 7. 平台执行后端

| 平台 | 进程身份与检查隔离 | 前提与失败行为 |
|---|---|---|
| Linux x86_64/arm64 | boot/start ticks、namespace、独立进程组；bwrap verifier | bwrap/所需 namespace 与精确工具链可用；缺失拒绝 managed 写入 |
| macOS arm64/x86_64 | libproc helper 获取 start time/PGID、nonce 管道、新进程组；sandbox-exec verifier | Xcode CLT/clang 和 sandbox-exec 能力探测；缺失拒绝该配方认证 |

helper 与沙箱策略从已审阅源码构建，记录系统/SDK/编译器和输出摘要。
verifier 必须前台、限定 argv，默认无网络，只可写候选和私人临时目录；
不允许任意 daemonize 命令。停止须 revoke → 身份复核 → TERM → 宽限期 → KILL → wait/close → 外部工作清零。
未经证实的状态不能计为物理终止；不宣称抵御同用户任意恶意代码。

四个平台格子分别记 mock/native/managed/live 结果；未通过格子不发布对应支持。
完整 Linux/macOS 是交付目标，不能通过删除 Task Keeper 把 base-only 计为全能力。
