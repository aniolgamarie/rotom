# 统一委派产品接线决定

2026-10-11 Root，承接执行契约与 Full 产品接线执行边界。依据实际调用链 `full-unified-delegate-call-path-review01`；不将旧 v2 单轮或 v3 意图登记称为多轮产品已实现。

## 固定动作语义

- `submit` 建立一个稳定 schema3 逻辑 run；一个获准动作最多派生一个物理 attempt。复用现有 Supervisor、ExecutionStore、WorkspaceLeases 和结果/终止检查，没有新执行队列。
- `message` 是向当前已确认 running 的同一后端提交一次 steer。空闲、状态未知、尚未 ready 或后端不支持时明确拒绝/不可用，不能自动转成新任务或积攒第二跟进队列。
- `continue` 只在旧物理 attempt 有验证的终止/回收事实、兼容原 native 会话和有效恢复 token 后创建新的有界物理 attempt；保留逻辑 run ID。新 attempt/lease 身份必须不同，重新核用户范围、策略、运行包/后端、输入与累计预算。未知旧执行不继续。
- `cancel` 先持久逻辑撤销事实，再调用原监督者/后端停止；确认请求不等于终止，只有原证据才能释放 Writer。结果可读取、费用结算与物理停止分别报告。

## 关联与发送切点

v3 的原 action/request 幂等层保持。物理 v2 run 可以作为单个 attempt 复用，不能把其重新生成的 run ID冒充逻辑 ID。统一核心持久保存 action→attempt/native identity/lease/result 的关联；Task Keeper工作流只保存指向该事实的引用，不另派发执行。

在首次可能创建外部工作/提交消息之前，持久记录该动作已进入 sending/starting及预算预留。持久化失败则零发送。ACK丢失、传输错误、进程崩溃或发送后取消不能证明未发送，保留 unknown和预留；同动作重试只查询/对账，不能再次发送。只有经实际发送边界证明 not-sent的动作才可释放预留。单纯超时或SDK错误不是该证明。

成功回执必须核同一原 attempt、native身份/消息序号、请求/授权和结果/终止事实，先持久再通知。已终止记录、错误结果与未验证结果分开；不能从模型输出中的“已完成”改变状态。状态、poll/result/watch不启动模型/Worker，不用查询补发未知动作。

## 预算与后端

同一逻辑 run绑定原 account/budget scope；每attempt进入原共享请求计量入口并使用同一累计账本。重启、继续、重连、profile切换不清累计。未观察计费保持unknown，不能写0；已知/估算与仍占用预留分别显示。输入/输出/请求/轮次/费用/截止时间按当前可信配置核验；本包不能绕过模型审查的严格输入计量约束，AUTO OFF保持。

Pi复用现有官方Agent facade及公开模型/工具接口，补真正物理worker与稳定会话恢复/消息通道；退出旧0.84.4默认worker路径。Codex统一使用固定官方CLI公开协议，app-server编码器需接真实有界stdio transport及thread/turn事件，不能只复用编码器声明多轮可用。两个后端的能力不对称时明确逐项unavailable，禁止自动换后端或账号。

Task Keeper的planner不是写操作权威，但worktree provisioner有真实Git写副作用，须纳入原维护/工作区准入。现代Full应由仓库自有公开extension factory明确装配统一核心/adapter，不能为了取得bridge重新加载旧pi-subagents包或修补上游。

## 完整验收包

使用原生产入口和同一核心，覆盖两个请求同ID同内容/异内容、同run steer/continue、unknown零重发、真实选择/角色上限/单Writer、取消迟到、消息顺序、预算累计/超限、持久失败和query零调用。默认替身与真实Pi/Codex/原生SQLite/真实模型分层；明确每格支持和证据，不能用单轮或内存Agent观察替代持久多轮。先完成代码/受影响默认检查再验证固定真实组合，不增加孤立DTO/纯codec任务来替代接线。
