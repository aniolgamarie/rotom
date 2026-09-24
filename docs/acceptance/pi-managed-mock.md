# Pi 监督与受管执行：实施中的隔离记录

本页仍是阶段记录，T036—T043 已实现基础代码与对应 mock；T044—T057 尚未完成，不代表 Task Keeper 已适配或受管流程可用。

## 当前可验证的原语

- ExecutionStore：allocating 完整意图 → 按键预留共享工作区 → 持久 starting/spawn_committed → spawn → 身份握手。
- WorkspaceLeases：锁锚定实际 worktree 的专属 git-dir inode；跨 profile/HOME 与路径别名共用记录。
- StopRecoveryPlan：300 秒有效期；旧控制者必须已结束，未知目标不授予停止权限。
- StopRecoveryGrant：保存首次计划及旧/新 generation；授权中断后幂等继续，只允许停止。
- never-started 回收：完整 allocating 日志且尚未提交启动边界才成立；starting 缺 PID 仍受保护。
- released 前先持久化终止证据；下一 writer 核对引用、摘要、执行身份与 generation。
- Linux 元数据后端：boot/start/namespace 身份、已记录子进程、pidfd 信号、TERM/KILL 后复核；脱离组或记录丢失保持 unknown。

默认测试只使用临时 Git 目录、线程竞争、进程身份回调与假 `/proc` 数据。
Linux 后端测试的信号调用由回调替代；Python 默认测试也禁止 kill/killpg/pidfd 信号入口。

## 当前测试记录（2026-09-16）

- 监督/恢复/工作区/Linux 后端：29 passed，8.23 秒。
- 信号隔离边界及入口回归：54 passed，7 subtests passed，0.81 秒。
- 其中包含原控制者仍活跃、PID 复用、计划过期、授权/撤销/停止过程中断、下一恢复控制者接替、外部活动未知、路径别名、linked worktree 与损坏日志。

以上数字为各自命令的结果，存在重叠，不累加为总数。
目前这些原语尚未接入真实宿主监督进程、Task Keeper 桥接和 model-delegate；不可据此宣称新能力已交付。

## macOS 实施依据

Apple 的 [libproc 声明](https://github.com/apple-oss-distributions/xnu/blob/main/libsyscall/wrappers/libproc/libproc.h)
与 [进程信息结构](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/proc_info.h)
提供进程、父进程、进程组及开始时间字段。macOS 路径将使用本机 helper 和实际 SDK 编译身份，
不会读取或模拟 Linux `/proc`。这些声明不是本仓库的 macOS 运行通过证据；对应 native 验收仍未执行。

### macOS 包含关系与验证边界

核对 [Apple 的 event.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/event.h)
确认 NOTE_TRACK/NOTE_TRACKERR/NOTE_CHILD 不再受支持，因此实现不使用这些标记假装自动追踪全部后代。
helper 使用两次一致的 PID/出生身份清点及原父出生身份还原归属；断裂或不稳定的身份保留 unknown。
停止调用按 audit token 的 PID/version 核对目标，避免信号误投复用 PID。
实现依据为 [唯一身份 ABI](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/proc_info_private.h)
及 [内核进程信息实现](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/proc_info.c)。
系统缺少这些能力时返回依赖/能力错误，不退回裸 PID 停止。

`python scripts/test-pi-macos-mock.py` 使用替身 SDK 编译实际 C 逻辑，覆盖已知后代、重新归父、断裂父链、清点竞争与信号前身份变化。
测试内任何真实 fork/kill/socket 都会中止。该结果属于 mock，不代表真实 macOS SDK、系统接口或沙箱已通过。
`build_macos_helper` 会记录源码、clang、SDK 与二进制摘要；编译成功本身仍保留 native_verification=not-run。

## 监督入口接通后的回归

- 全量隔离 Python：945 passed，7 subtests passed，76.34 秒。
- Node 默认 mock：41 passed。
- C helper 的替身 SDK 编译及清点逻辑测试通过。
- run 使用冻结在运行包内的 Python 监督源码；父宿主结束后仍保护已登记 worker。
- apply/sync/rollback/run 共用实例目录锁和不可变归属记录，不能通过切换 state_root 绕过。
- recover 的计划/停止只依赖已保存身份与机器定位，不要求当前新模型、秘密或新依赖锁就绪。

完整 Task Keeper、单管理者 vendor 和 model-delegate 集成仍未交付；所有原生/账号验收仍未执行。

## 新 AgentManager 与 Task Keeper 协议接入

- Task Keeper 已从冻结 starter 来源完整迁入；旧 0.63 适配器只在不发布的 migration 目录保留。
- subagents 固定上游提交 `e955e29c51b7a6cce37e1108cd2d6c57a77e151c`，派生补丁可从原始 Git 归档重建全部修改文件；身份见 `agents/pi/packages/subagents-patch/manifest.json`。
- `node agents/pi/packages/subagents-vendor/scripts/test-mock.mjs`：26 项通过。覆盖实际 AgentManager 的共享队列、普通 resume、排队不启动、同步失败保留占位、批量取消、未消费结果保护、单监听者和持久幂等。
- `node agents/pi/packages/task-keeper/scripts/test-mock.mjs`：20 项通过。新增实际 SQLite 的 Task/Attempt 持久化与新协议客户端；回执丢失保留 start_unknown，owner/manager 更换拒绝复用准入。
- 派生源码在临时依赖环境中，以 Pi SDK 0.84.4 执行 `tsc --noEmit` 通过；biome 检查 172 个文件，无错误或警告。检查环境使用本机 Node 24.1.0，不是目标 Node 24.14.0 的原生验收。
- Python 监督准入回归 4 项通过：排队意图不占物理进程名额，真正 start 在监督锁内执行总并发检查，已提交 start 的重复调用不重复创建进程。

这些证据仅证明当前协议层和队列。Task Keeper 的 service/UI、fresh worker、实际 transport、守卫 IO 和原生组合仍按后续任务接通；运行包不因派生版本号而宣称 managed ready。native/live 保持 not-run。

## Fresh worker 与实际 IO 接口（源码/mock 检查点）

- `managed-worker-main.ts` 从冻结运行包解析 SDK/Task Keeper，使用内存 session、空资源 loader、精确工具集合和零原生重试。环境只携带所选 provider 凭据，不复制 auth.json。
- supervisor 在启动前核对 closed descriptor、角色全文 hash、结果 schema、模型/路线和任务数据库；实际文件 IO 经私有 RPC，复核 grant、根目录句柄和共享写租约。
- SDK 对 thinking 的隐式降级会在请求前拒绝；Pi 专属 `model_settings` 可声明 reasoning 与 thinking level 映射。
- 父退出只自动撤销完整且从未提交 spawn 的预留；未知启动保持保护。用户恢复 capability 不允许 allocate/start。
- 模型请求在实际 fetch 前计量；成功 SSE 的 `[DONE]` 是请求结算边界。代理失败无直连 fallback；未提供费用保持 null。
- 读取工具的结果只有出现在后续成功请求的真实 payload 中才记录为已交付；事件文件按 producer/sequence 关联。
- Linux verifier 的已存在拒绝目标使用零权限只读视图；不可表示的缺失目标明确拒绝，不在业务目录静默制造挂载占位。参数依据 [bubblewrap 官方实现](https://github.com/containers/bubblewrap/blob/main/bubblewrap.c)。此处尚无原生沙箱通过证据。

T048 已完成源码与 mock。T049—T052 的权限、预算和结果实现仍在联调；Task Keeper 工作流/UI 尚未接回，不能据此宣称整套功能可运行。完整 native/live 验收仍独立进行。

## 权限、请求与结果接口检查点

T049—T052 的接口实现已完成：父策略拒绝规则采用明确转换表，模糊/未知形式拒绝；新 child reporter 只导出受管工具与观察器，不加载旧扩展运行时。SQLite 请求保留和 reservation 带版本，未知状态保守保留；父侧辅助请求在 managed scope 中于 SDK/HTTP 两层执行前拒绝。失败 worker 保留规范化原因和 observation。Task Keeper 对取得的 receipt 再验证本次身份、候选、模型与监督证明，先保存副本，再允许 consume。

这些是接口与 mock 检查点；inspect/fix、检查执行、恢复、一次性调度及 UI 仍在 T053—T057 接线，不能视作完整迁移或 native/live 通过。

## 工作流接线与恢复（T053—T057）

- `agentcfg-workflow.test.ts`：实际 TaskService、固定图、唯一 AgentManager 和辅助执行器；
  模型与 supervisor 使用替身。inspect/fix 的通过、zero-tests 拒绝、旧 snapshot 审查拒绝均通过；原 checkout 哨兵不变。
- `agentcfg-execution.test.ts`：业务步骤先持久 attempt，再准备封闭 worker context；相同幂等键不重复分配。
- `agentcfg-recovery.test.ts`、`agentcfg-adapter.test.ts`：丢失派发应答不重发；完整验证收据补回关联；
  unknown 不作停止证明；一次性调度原子准入、错过暂停、用户恢复保持 task/budget。
- `manager-executor.test.ts`：物理终止已核实但结果损坏时，可以释放逻辑槽位；仍无成功收据。
- `agentcfg-usage.test.ts`：unknown 请求占用预算，费用保持 null；统计重分组不重置预算或重复计量。
- 默认 Task Keeper mock 入口：35 passed。此前 runtime+TK 全集91 passed；新增统计与恢复测试另通过，最终全集待汇总。
- TK 生产源码 typecheck 使用0.84.4公开SDK类型通过；历史 native测试没有移入默认测试，也不算新版通过。
- `examples/pi-managed.toml` 展示三个模型角色、精确检查 argv、项目根和本机显式候选策略。
  默认公共 project-default 仍是 deny；没有给普通会话新增写权限。
- 此处无真实 Pi、模型服务、系统隔离器或 macOS执行证据；native/live仍为not-run。
