# Full 产品接线执行边界

2026-10-11，Root 决策。承接既有 spec、执行/提供者/持久服务契约及已验组件；本文件收敛后续实施顺序，不新增用户目标，不将组件通过升级为产品通过。

先完成当前 Base 正式来源冻结和真 CLI 文件权限正反链，再由唯一 executor 补 Full 的显式配置与候选构建输入。Full 保持 candidate，直到自身公开 SDK、安装及产品行为验收完成；Base current 与 Full candidate 可以并存。每次配方变化须由正常 producer 重新派生身份，相关已安装证据按实际身份分列。

## 配置与包

Full 复用六项 Base 能力，明确选择统一 delegate、Task Keeper 和独立 Durable 只读服务。风险审查保持可选且默认关闭；严格输入上限未验证前禁止自动启用。只读/普通诊断不连接服务，不发送模型请求，不启动 Worker 或 Durable。

旧 Task Keeper/model-delegate 的 0.84.4 peer 和 pi-subagents 要求不作为现代兼容依据。现代接入通过仓库自有公开适配实现，退出独立 pi-subagents 调度依赖；旧已安装资产及恢复引用保留。不能仅改 peer 版本便声明兼容，不向上游、缓存 SDK 或第三方宿主打补丁。

Full 的角色、工具、资源、包和能力绑定均显式定义。候选可以验证配置/来源/构建，不能伪造运行资格。尚未实现的服务或执行接口明确 unavailable，不能靠空实现签发正常结果，不能为补候选创建第二队列。

## 统一委派与 Task Keeper

具体动作、发送切点与累计预算以 [unified-delegate-integration-decisions.md](unified-delegate-integration-decisions.md) 固定。

先把已有 DelegationRuns、schema3 动作登记、Supervisor 与 WorkspaceLeases 接成唯一的受管执行核心。逻辑 run ID 保持不变；各次发送/执行有独立 attempt/lease 身份。message/continue 必须核原 run、实际后端 native identity、当前授权/预算与恢复事实；unknown 不自动重发，不从文本推断 completed 或释放 Writer。

Pi 通过固定公开 Agent/会话接口接入，Codex 通过已选择的官方 CLI 公开协议接入。两宿主的 Skill、CLI 和 Pi 工具只调用同一核心。Task Keeper 保留自身工作流/检查/证据数据库，其 adapter 调用上述核心；phase journal 记录工作流事实，不再拥有另一套派发执行权威。固定 Inspect/Fix、唯一 Worker、可信 checker、最多两轮和失败证据语义保持。

## 独立 Durable 生命周期

Durable 不接管或依赖 Task Keeper 队列。复用已验 storage、request admission、readonly registry、phase Models 和 attempt store，完成一条实际产品链：显式 submit → 单 owner → 同批 Task/Doc 持久受理 → 受限只读工具与唯一发送门 → 持久结果 → 查询/重连 → 取消/恢复。

服务启动由实际 Full 控制面唯一入口负责；普通启动、编辑、status/result/watch 不隐式启动它。公开 description、索引 codec、只读 owner scope、FD 数字及同 UID 不能授予初始化权限。现有组件的 False 权限属性保留；真正 owner 控制器必须持有本次实际创建/打开的锁、原 source holder、真实进程/管道对象和当前 validator。

锁与事务采用既定顺序：部署/私有目录及来源校验 → source 保护 → 原子 owner 排他锁 → 旧 owner/兼容与未完成记录对账 → 公开 SQLite 打开并读回 WAL/FULL → SDK admission。索引协调不跨任意 RPC 持锁；后继写入和 ACK 均按原记录和回执核对。原 caller、source 生命周期和实际 controller 的持有/交接实现由 Root 负责，executor 不自行猜测或扩权限。

受理只在同一 SDK Session.commit 的 RootTask/Doc 持久确认后返回 accepted；丢回执仅查询原 ID，不重复提交。外部发送先持久 sending；结果先持久再推进/通知。sending 未知保持预留，阻止该任务后续自动发送；无关任务可查询/执行。status/result/watch 使用只读观察，不调用会推进调度的 wait/resume。取消先持久撤销，再中止；SDK 静止和外部终止证据齐全才 canceled。进程退出、结果可取、费用结算分别记录。

## 验收与记录

每个完整实施包自行实现、执行受影响默认检查、常规修复并交回稳定 diff；只在真实前提被推翻或事务/恢复语义不明时升级 Root。无需用户逐小步发“继续”。已授权低风险原生测试直接执行。

优先验证真正 profile/CLI/SDK/服务的组合，不再增加孤立的“只准备下一原语”包。旧组件收据可支持未变接口判断，但不得复制为新安装身份的产品通过。最终至少观察稳定任务 ID、实际模型发送数、Writer/owner 数、原存储设置、预算累计、受保护哨兵、物理停止与资源回收。未测试、失败、环境不足和未知窗口都保留。
