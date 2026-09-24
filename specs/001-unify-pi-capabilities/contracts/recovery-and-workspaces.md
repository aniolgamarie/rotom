# 控制恢复与跨实例工作区写入契约

**Version**: 1  
**Resolves**: 分析报告 U1、U2。本文补充managed/external executor与实例监督接口，所有实现尚待完成。

## 1. 控制恢复与普通reconcile分离

普通reconcile仍然只读核对旧记录，不能恢复旧nonce的权限或隐式终止运行。
新增用户显式的停止恢复入口，不启动Pi宿主、不调用模型、不因apply/sync/rollback自动触发：

```text
agentcfg --machine NAME --profile ID recover pi --lease LEASE_ID
agentcfg --machine NAME --profile ID recover pi --lease LEASE_ID --stop --expect-plan DIGEST
```

第一条返回脱敏停止计划与plan_digest，不发信号。第二条表示用户针对该计划明确请求停止。
该功能仅回收归属已证明的旧执行，不提供任意PID/目录/进程组参数，也不接管旧任务继续执行。
lease已证实reclaimed或failed且有完整未启动证明时同请求幂等返回；非Pi profile/缺失参数为2，身份冲突或未知为4，IO为6。

## 2. StopRecoveryPlan / StopRecoveryGrant

计划字段：schema_version=1、instance_id、lease_id、old_supervisor_activation_id、
old_supervisor_process_identity、old_manager_activation_id、target_process_identities、
external_work_ids、workspace_write_lease_ids、old_grant_generation、plan_kind=stop_execution/abort_allocation、
allocation_journal_digest、plan_digest、created_at、expires_at。
有效期固定为生成后300秒；期间身份、外部工作或grant generation变化都使digest失效。

授权字段：recovery_id、plan_digest、request_id、requested_action=stop、requester_uid、
new_supervisor_activation_id、target_lease_id、revocation_generation、state、evidence_refs。
state为authorized/stopping/verified/stale/unknown；授权只允许撤销和停止本计划目标，
不允许dispatch、resume、扩权、读取秘密或未经未启动/终止证明直接清理旧lease。requester身份来自本地认证通道，不能信任请求正文的UID。

## 3. 原子准入和终止步骤

1. 新supervisor获取同实例恢复互斥锁，验证私有目录、UID和持久记录完整性。
2. 必须证明旧supervisor进程身份已结束；仅控制端点失联或超时不算。旧控制者仍活跃时返回4，
   引导使用其原控制入口；不能抢走一个活跃控制者的执行。
3. 复核计划未过期。stop_execution要求目标PID/启动时间/boot/进程组与登记证据一致；
   abort_allocation要求第5节的持久未启动证明。无法证明归属时保持unknown，
   不给用户一个忽略身份检查的force选项，也不只凭同UID向进程组发信号。
4. 原子写入仅stop的RecoveryGrant与递增revocation_generation，撤销旧执行grant。
   旧manager/worker后续工具、模型、检查及dispatch请求必须拒绝旧generation；旧任务预算和证据不重置。
5. 按平台后端向本计划内身份已核实的进程发TERM，宽限后再次核对身份再KILL，等待实际退出并清点已登记外部工作。
6. stop_execution只有完整终止与外部工作清零后，分别写入termination证据、释放工作区写租约并将execution置reclaimed；
   abort_allocation没有进程可停止，按持久分配日志撤销本次预留并以never-started证据记execution=failed。
   不能以计划被接受、信号已发送或旧控制者死亡代替终止证明。
7. 新supervisor在恢复中再次崩溃时，下一激活从RecoveryGrant重做身份核对并幂等完成同一停止；
   不重派任务或重复记模型消耗。证据不足仍unknown，保持所有保护。

停止授权按目标ExecutionLease递增generation，不撤销其他任务的无关grant。
RecoveryGrant保存首次授权时的不可变计划/分配证据摘要与旧、新generation。
重放同request或恢复中再崩溃时复用该授权，不重新递增generation，也不把授权自身造成的变化误判为新请求的过期计划。
新请求仍完整执行计划时效/身份检查；恢复已有授权时必须确认当前generation等于其revocation_generation，
若被其他有效操作改变则拒绝继续，不能越过新的控制状态。

旧manager本身若仍活着，不获得新控制权限；它不能继续使用已撤销generation。
用户要继续任务，必须在旧执行证实终止后，经既有显式resume创建同task的新attempt。

## 4. 跨实例工作区身份与仲裁位置

实例租约保护运行包与配置；WorkspaceWriteLease独立保护业务worktree，必须同时满足两者才能写。
同一宿主上的所有Pi profile、Task Keeper、model-delegate及受控编辑/检查入口使用同一规则。

工作区键由host_boot_id、UID、实际worktree根的文件系统身份、该worktree专属Git管理目录身份组成。
linked worktree使用其独立git-dir，不仅使用共享common-dir；相同worktree经路径别名或不同HOME访问必须得到同一键。
持有已验证目录句柄，按实际文件系统身份比较，不用字符串路径或profile名作为互斥键。

仲裁锁绑定到已存在的worktree专属Git管理目录inode的advisory lock，而不是实例XDG目录。
持久记录存于该git-dir下专属 `agentcfg/write-lease.json`，目录0700、文件0600；
这是监督者明确拥有的运行元数据，不能进入配置备份或被模型工具写入。
先安全验证git-dir及祖先、链接和已有标记所有权；冲突、只读或不可靠锁语义时拒绝受管写入。
本版仅支持有可靠本机文件锁的Git工作区；不承诺跨主机共享文件系统互斥，非Git受管写入明确拒绝。
不同实例state_root、HOME或仓库入口不能改变仲裁位置；测试使用临时Git工作区，不写真实项目。

## 5. WorkspaceWriteLease

字段：schema_version=1、workspace_key、canonical_worktree_identity、git_dir_identity、
instance_id、execution_lease_id、task_id（普通显式操作可空）、attempt_id、holder_nonce、
supervisor_activation_id、grant_generation、state、termination_evidence_refs。
state为reserved/active/revoking/unknown/released；allocation_id固定等于引用的execution_lease_id。
路径只作为私人定位信息，不是所有权证明。

- **先持久化分配意图**：在实例准入互斥锁下创建ExecutionLease，state=allocating、process_identity=null、
  spawn_committed=false，记录全部planned_workspaces的身份/受保护定位、排序、holder_nonce及allocation_id；
  文件和父目录落盘完成前，不写任何共享workspace预留，也不启动进程。
- 再按workspace_key排序逐一在短时advisory锁内写reserved，引用已经存在的分配意图。
  成功列表可追加到journal；即使共享写入后、追加前崩溃，恢复仍能从完整planned_workspaces核对每项。
- 全部所需预留成功且重新核对owner/generation后，持久提交state=starting、spawn_committed=true，
  fsync后才允许spawn。该提交是唯一启动边界；不宣称多目录写入物理原子。
- allocating/starting记录都阻止重复准入。正常预留失败先撤销本次已拥有的预留，再记录failed/never-started，
  不修改其他owner的标记。清理中再次崩溃可幂等重做。
- 任何reserved/active/revoking/unknown都阻止其他owner获取写权限，返回WORKSPACE_BUSY/退出4。
- 控制者失效后，只有完整allocating日志、spawn_committed=false、generation匹配且启动边界未提交，
  才可生成abort_allocation计划作为“从未启动”证明。recover --stop核对该计划后，按planned_workspaces
  释放所有仍属本allocation的reserved；缺项/已released可幂等处理，其他owner标记保持不动。
- starting或spawn_committed=true但缺PID/握手，不能推定未启动；日志缺失/损坏也不能据PID不存在清锁，
  保持unknown并走身份/终止取证。supervisor崩溃导致内核锁释放不忽略任何持久记录。
- 同任务的writer与检查器只通过父grant显式派生受控子操作，不各自抢锁；子操作不能扩大根或并发writer上限。
- 跨实例并发获取使用同一锁与记录，必须恰有一个成功；不同worktree可各持自己的写租约。
- 必须规范化每个实际写目标对应的worktree；额外工作区需在启动前按workspace_key排序一次性预留，
  任意失败撤回尚未启动的本次预留，不部分启动，也不依靠不同锁顺序等待造成死锁。
- 文件write/edit/rename/delete、可写项目检查、外部editor、stash/restore及显式Codex写入都需该准入。
  rename的源和目标各自检查；受管reader/reviewer无写入口。
- 读取不会授予写租约；检查/审查结果仍须关联candidate digest，外部非受控修改会使证据失效。

旧执行的写租约只能由原owner释放，或由上述经过认证的stop recovery在完整终止后释放。
不得以TTL、PID不存在、换profile或删除持久文件清锁。任意绕过管理器的同UID恶意程序不在承诺内。

## 6. 约束与验收

V09/V14：控制者崩溃worker存活→只读reconcile→明确stop授权→generation撤销→实际终止→两种租约释放；
还需覆盖旧控制者仍活着、PID复用、过期计划、重放请求、恢复中再崩溃和外部工作未知。

V09还覆盖：allocating落盘前后、写入第1/第N个workspace reserved后、追加journal前、提交starting前后及清理中崩溃；
未提交启动边界可证明未启动并回收，已提交/日志缺失时不误清锁。

V13/V22：两个profile对同一worktree同时申请恰一个成功；路径别名/不同HOME不绕过，
不同worktree可并行；ordinary editor与Task Keeper/model-delegate writer互斥；
活跃或unknown租约期间不能启动另一writer，旧执行证实终止后才可重试。

默认只用文件/进程身份替身；Linux/macOS原生锁及进程行为在各自native授权层证明。
