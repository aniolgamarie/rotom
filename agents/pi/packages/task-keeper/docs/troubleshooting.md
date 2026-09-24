# 排障速查

[文档首页](../README.md) · [配置参考](configuration.md) · [状态维护](state-maintenance.md)

首先运行`/orch doctor`，已有任务再运行`/orch status <jobId>`。保留原jobId、reason、候选目录和错误工件，先确认是未配置、正常等待、执行未知还是验收失败。

| 现象/原因 | 如何处理 |
|---|---|
| 包在settings里但没工作 | 检查enabled及对应feature；init创建的是禁用配置。重启受控Pi，不把安装当作启用 |
| 没有kernel_task | 启动时需启用managedWorkflows并允许该工具；使用上手指南的受控启动器。普通恢复模式不注册受管工具 |
| bindingGaps、ROLE_BINDING_REQUIRED | 配置角色、profile和真实检查；provider/model必须存在于Pi目录 |
| PROJECT_ROUTE_NOT_APPROVED | 核对allowedRoutes和目标repository的projectRouteApprovals；不要让模型绕过授权 |
| 运行时/扩展未认证 | 使用已验证Node/Pi版本及包内补丁subagents，重跑prepare后重启；其他扩展不自动继承认证 |
| WAITING_QUOTA | 正常等待，查看notBefore/incident与deadline。不要高频继续或清数据库 |
| REQUEST_TIMEOUT | 核对单请求策略、profile剩余时限和任务deadline；统计与实际发送事实仍保留，不能当成未计费 |
| QUEUED、waiting_start_window | 尚未到期/不在窗口，或无资源；检查明确时区及活动任务上限 |
| scheduled_start_missed_resume_required | Pi退出期间错过启动；需要用户resume，原deadline仍有效 |
| 无窗口或deadline耗尽 | 核对用户提交时间和窗口。已过期任务不能通过普通resume延长期限 |
| second_opinion_disagreement_exchange_limit | 查看B意见和已完成工作；不能继续无限交换，也不能通过关闭全局B使旧任务通过 |
| BUDGET_DENIED、STEP_BUDGET_EXHAUSTED等 | 查看同一workScope的已用与预留量；统计begin和新建job不是清账方法 |
| unknown、EXECUTION_NOT_RECONCILED | 不知道原执行/外部工具是否结束。保持现场和占用，先核实终止证据；重启或发stop不等于已经结束 |
| 新仓库创建工作树失败 | 受管任务需要有HEAD的Git仓库；先在演示/目标仓库完成合适的初始提交，不能把未初始化目录当作已有候选来源 |
| 测试退出0但仍BLOCKED | 检查真实计数、跳过/缺失、parser和required reviewer；Done文本不能替代验收 |
| CHECK_INPUTS_CHANGED等 | 检查是否修改了验收脚本。先审查变化，再按返回digest进行approve-checks；不要直接降低阈值 |
| receiptCurrent=false | 候选、根版本、模型/运行绑定或工件变化，旧回执仅是历史；重新核对当前候选 |
| MODEL_CONTROL_REVOKED | 旧模型回复失去写控制权；等待新的真实用户指令，不能复用旧tool-call ID |
| PACKET_TOO_LARGE | 必要账本事实超出展示预算；缩小当前任务范围，或由用户调整packetByteBudget。不会截掉阻塞事实继续发送 |
| usage费用unknown | 缺usage、SDK缺省零、未绑定套餐、报价过期或不适用均可能导致未知；查看source/coverage，不代表免费 |
| history-insufficient-configured-order | 检查同组、输入档、工作合同、模型版本、完整费用、币种和已验证样本；不会额外调用模型来凑样本 |
| DATABASE_MIGRATION_REQUIRED | 停止使用该状态根的控制器后，按状态维护步骤显式升级；不要删除数据库 |

`/orch audit`给出主会话原始失败索引，status中的failureGroups保留汇总，artifacts指向独立工件。服务端模型权重身份未知时会明确标注，不能仅凭请求model字段认定实际权重。

提交问题时提供脱敏的doctor/status、版本、具体命令、错误和已有工件路径即可；不要粘贴API key。候选和原工作区应先保留，排障步骤不包含自动删库、清预算或盲目重放未知写入。
