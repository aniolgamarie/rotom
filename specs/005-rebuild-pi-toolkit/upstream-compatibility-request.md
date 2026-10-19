# Pro 候选的上游兼容性问题草案

本文件只供审阅，未发送 issue、评论或 PR，未修改或分发候选插件。它不是 T064 准入通过。

## 可复现的公开接口差异

目标为官方 `@earendil-works/pi-coding-agent@1.3.0` 和
`@mjakl/pi-subagent@3.1.0`，固定来源见 [module-admission](module-admission.md)。

mjakl `index.ts:874` 对每次有效 `subagent` 调用执行 `getPersistentSessionDir(ctx)`，
与是否提供 `session` 无关。该函数在 `index.ts:629–644` 探测
`ctx.sessionManager.usesDefaultSessionDir`。Pi 1.3 的公开 `ReadonlySessionManager`
并未包含该成员；它提供公开的 `getSessionDir()`、`getCwd()` 等只读方法。
回退分支已能通过公开路径比较完成判断，但此前的非公开成员探测仍存在。

期望上游只使用受支持的只读接口，保留默认目录/显式 session-dir 的原有语义。
本仓库不通过强转、代理、monkey patch 或自行改发行包隐藏此问题。

## 建议上游验证

1. 仅提供 Pi 1.3 公开 ReadonlySessionManager 的合成上下文，默认与显式目录分别测试。
2. 以属性访问哨兵拒绝任何 `usesDefaultSessionDir` 探测；普通 ephemeral 调用也必须通过。
3. 覆盖缺失/无法解析目录的失败路径，不自动改变账号、会话或目录所有权。
4. 发布未修改的正式版本，给出精确 npm integrity、许可和支持的 Pi peer 范围。

以上是上游修复建议，没有在仓库 vendor/cache 中实施。新的正式版本仍须独立审包、完整锁与组合验收。

## 修复这一项之后仍须满足的 Pro 条件

- 公开深度 1 已有真实路径；保持无子代理继续派生。
- 每主会话最多两个实际活动调查，两个主会话可各两个。单批限制不等于跨调用并发上限。
- 子任务只读工具与全部间接资源必须有闭包；提示词不构成权限约束。
- 无后台、无持久 session/parent-context 绕过；取消和未知退出不提前释放名额。
- 精确当前任务/模型/结果与进程状态分开；截断、空结果、失败和缺失回执不冒充成功。
- 不新增自有执行器或调度器来补足插件能力，不调用宿主私有接口。

受限 `read/ls`、关闭发现资源和公开 tool_call 准入策略的静态可行性已有研究，
但仍需新正式候选的完整公开接口与原生证据；本草案不承诺该组合已经可运行。
