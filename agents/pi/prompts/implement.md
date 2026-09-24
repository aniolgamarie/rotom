---
description: 按当前模式实施任务并验证具体变更
argument-hint: "<task>"
---

实施以下任务：$@

1. 读取相关源码和业务仓库规则，明确范围、约束和验收标准；沿用现有用户授权。
2. 普通模式由父会话实施；完成后把具体 diff/patch、相关规则和验收标准交给 fresh reviewer。
   reviewer 只读，必须使用明确绑定的模型；未绑定或工具不可用时报告 NOT_RUN。
3. managed 模式通过 kernel_task 的 fix 工作流；遵循 kernel-orchestrate，使用候选 worktree、
   已声明项目检查和 required review，不在原 checkout 自动合并。
4. 用户明确要求外部委托时使用 model_delegate，明确 backend/model，并选择适用 preset。
   模板不能改变权限或启用写入。写操作需要明确授权、独立 worktree 和公共写租约。
5. 运行适用检查并核实审查发现。分别报告实际变更、检查证据、审查结果和未验证项。
   空结果、超时、未终止或仅有 accepted 状态都不能作为完成证据。
