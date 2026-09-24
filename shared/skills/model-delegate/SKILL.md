---
name: model-delegate
description: Delegate a bounded review or investigation through agentcfg's model_delegate tool, or use its explicit user CLI for supervised Pi/Codex execution, progress, cancellation, resume and authorized linked-worktree implementation.
---

# Model Delegate

使用当前 agentcfg 实例的唯一委托入口。Pi 工具优先使用 `model_delegate`；独立 CLI 从当前
已部署技能的 `scripts/run-model.sh` 调用。不得扫描 HOME、寻找全局宿主、复用旧收据或在失败后换 backend。

## 普通模型工具

工具始终只读。提供具体目标、范围、检查标准、允许的 cwd，并指定 backend 和精确模型或已绑定 model_role：

```json
{"backend":"pi","mode":"review","preset":"review","task":"检查指定变更，给出有依据的问题与未覆盖范围","cwd":"/absolute/project","model_role":"reviewer","timeout_seconds":300}
```

可选 preset：general、context、challenge、plan、research、review、scout；它们是用途/输出模板，
不是额外 agent 或新的权限。需要 Codex 时明确 `backend: "codex"` 并使用实例允许的精确 Codex model。
工具只调用现有管理者的 external executor；不得自行 fork sibling runner 或另建队列。

保留 run_id 和 artifact_ref。`verified-execution` 仅表示本次执行身份、输出、事件与终止证明通过，
不等于评审通过或任务验收。核对发现、候选和覆盖范围；observed_model 为 null 时不要假称服务端模型已报告。
长结果用同一 CLI 的 `result --run-id ID --offset N --limit 2048` 分页读取，next_offset 为 null 才读完。

Task Keeper managed 上下文会拒绝外部委托，不能用另一 Pi/Codex 进程绕过它的预算或权限。
遇到 unknown/start_unknown 不得再次 start；先查看原运行的状态和监督证据。

## 用户显式 CLI

未在已部署技能目录调用时必须提供 `--instance`。模型/provider 使用实例的精确绑定；Pi 的自定义原生 provider
带 `agentcfg-` 前缀。所选运行包、路由、账号与工具链必须已就绪；命令不会安装依赖。

```sh
./scripts/run-model.sh start --instance /private/instance --backend pi --mode investigate \
  --provider agentcfg-example --model fictional-model --cwd /absolute/project --prompt-file /private/task.md --detach
./scripts/run-model.sh status --instance /private/instance --run-id RUN_ID
./scripts/run-model.sh poll --instance /private/instance --run-id RUN_ID --after RUN_ID:0 --wait-seconds 30
./scripts/run-model.sh wait --instance /private/instance --run-id RUN_ID --wait-seconds 30
./scripts/run-model.sh cancel --instance /private/instance --run-id RUN_ID
./scripts/run-model.sh resume --instance /private/instance --run-id RUN_ID --prompt-file /private/followup.md
```

`--observe` 输出实际语义 checkpoint；不输出私密推理和原始错误。wait 超时不会取消任务。
resume 使用新 run/attempt，必须证明旧执行终止，保留同 backend/model/worktree/policy/runtime 关联。
跨协议或没有合法 resume token 时拒绝，不能猜测 last session。独立启动与交互 Pi 共用实例锁；实例活跃时使用工具入口或先退出交互 Pi。

## 显式写入

只有用户明确授权的 Codex implement 可以写。必须同时满足：机器配置为 explicit-write、
CLI 提供 `--allow-workspace-write` 与 `--worktree-root`、目标为已存在的独立 linked Git worktree。
候选属于已配置项目，并取得共享 WorkspaceWriteLease。Pi backend 和模型工具不能升为写模式。

权限规则还必须能无扩权转换为原生 profile；仅允许 write 的规则不能被扩大成 create/delete/rename。
写入不自动重试；取消不是回滚，不自动合并、提交或推送候选。

## Context 与反馈

`--context-file` 接受 schemas/context-v2.json；`--memory-file` 转换显式提供的旧 entries/revision。
权威 task/constraints 不裁掉；预算不足时失败。保留来源、争议与截断记录，统计或上下文分组不产生新权限。
工具的 context_artifact 引用实例中已导入的 context，不能是任意文件路径。

`--feedback-required` 要求 context 与结构化结果。模型只返回 facts/conflicts/summary；控制者绑定 run、turn、
当前候选及 artifact 身份。新模型论断保持 unverified，结构与关联通过不等于事实已验证。

## 验证边界

默认测试仅用临时 HOME、假 backend 和假 supervisor。native/live 需要独立证据。
当前迁移中的未完成项以仓库 specs/001-unify-pi-capabilities/tasks.md 为准；不能把源导入或 mock 通过称为完整平台迁移。
