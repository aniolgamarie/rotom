# 维护流程分支复审（2026-10-26）

审查基线：main `45953f09ce14908282b4af4c08101227e151ca3f`；候选分支
`feat/tool-maintenance-workflows-20261026`，初始审查提交 `2cda58d76b49b3509db68312cbf17b1f108a2289`。
该范围包含代理整合 `ca6083e` 和维护实现 `2cda58d`，共 85 个变更文件；本次复审修正另行保存。

**结论：仍有一个 P1 未解决，当前不满足合入条件。** 先前测试与原生分项通过的事实保留，
不能以它们覆盖本次发现的失败分支。main 与其四个未提交 Pi 锁文件没有被修改；没有合入或推送。

## 未解决：P1 — Pi 打印模式的保护失败不能终止执行

位置：[公开控制扩展](../../agents/pi/templates/session-control.mjs) 的 `stop()` / `session_start`。
helper 启动失败、claim 被拒绝或 helper 失联时，扩展记录停止状态并调用 `ctx.shutdown()`。
官方 Pi 1.3.0 的打印模式没有向扩展绑定 shutdown handler，因此该调用不会结束宿主。
`-p` / `--print` 以及 stdin 或 stdout 非 TTY 时选择的隐式打印模式都受影响。

官方 `dist/modes/print-mode.js` 的 `runPrintMode`、`dist/main.js` 的模式选择和
`dist/core/agent-session.js` 的公开上下文绑定已核对。使用原生产扩展、官方打印组件和替身
helper/runtime 的隔离复现观察到：helper 失败 1 次、shutdown 调用 1 次、失败后仍调用
prompt 1 次，打印流程返回 0。没有启动模型请求、读取真实账号或会话，也没有修改官方包。

这不能证明已占用的显式 session 租约被抢走：明确恢复目标的初始租约仍由 manager 预先持有。
它证明“保护不可用后不继续运行”的启动/执行约束不成立，可能在保护未成立时继续新会话，
因而必须修复后才能接受当前候选。

下一步需要完整设计并验证打印模式的失败阻断：公开 `input` 返回 `action: handled`
可以阻止普通提示词，但尚不足以证明扩展发起的消息和运行中 helper 失联都被覆盖。
须覆盖启动失败、claim 拒绝、显式/隐式打印、扩展入口及运行中失联；不得用只断言
`shutdown()` 被调用的替身测试替代宿主行为验证，不修改上游或使用私有接口。

状态：**失败待修复设计与验收**。本次没有声称输入 hook 已解决该问题，也没有静默禁用打印模式。

## 已修正的发现

| 级别 | 触发与问题 | 修正及验证 |
| --- | --- | --- |
| P2 | `run pi -- --session=ID` 被转换成 `--session=FILE`；官方解析器只识别分开的 `--session FILE`，等号参数被忽略。 | 统一转换成两个 argv token，保留原生 `--` 之后的字面内容。隔离回归覆盖两种写法；官方 Pi RPC 验证精确初始 ID、切换后 ID、重复租约拒绝与退出。 |
| P2 | 维护停止仍 pending、恢复只有 intent，或 setup intent 被 cancel 状态覆盖时，`maintenance status` 可能返回 0。 | 按原停止与各阶段事实判断未完成结果，返回 4；取消不覆盖未知结果。18 个三工具场景中，修复前 15 个复现失败、3 个已通过，修复后受影响完整模块通过；查询不写入或重发。 |
| P2 | 工作区帮助没有说明 Herdr 前提，端点不可用和元数据已保存但标题未同步的反馈容易误解。 | 按操作补充静态 help、失败及未知端点提示；提示在 stderr，保留原 stdout/JSON、退出码与已保存结果。checkout 创建后进入失败仍保留 checkout。 |
| P3 | spec 仍称候选未提交、TTY 与本轮整库验证待完成。 | 区分既有阶段证据、本次复审结果和未完成的官方全 CLI 维护验收；原 pane/new-tab 能力明确仍未开放。 |

Pi 参数修正后的三个来源锁 identity 为
`1c2986e858b6f905b17f3af4cfe349ca4fdbd56b08df311fb2d984cfc309b430`。
来源锁、静态组合表与能力文档同步；这只标识实际测试来源，不消除上面的打印模式缺陷。

## Herdr 使用边界

- `work enter` / `named enter` 需要配置的 Herdr 和可核验 API，可从外部启动配置的 headless 会话。
- `work open` / `close` / `rebind` 需要当前 Herdr 调用上下文及运行中的 API。
- `list --live` / `status` / `reconcile` 不启动 Herdr；端点 unknown 不表示空闲，也不能直接推断未安装。
- 配置与注册元数据、离线 list、无 `--enter` 的 Git worktree 创建不需要 Herdr；named rename 的原生标题同步可能待处理。
- `resume --here` 和 `maintenance restore` 不需要 Herdr；`--original` / `--new-tab` 当前未准入，安装 Herdr 不会启用。

## 审查覆盖与证据

| 范围 | 审查内容 |
| --- | --- |
| 代理与既有入口 | 全部代理整合 diff、签名能力探测、显式代理选择、窄后端兼容、maintenance 独立准入和相应测试。 |
| 编排与恢复 | 清单/追加事件校验、CAS、取消和并发结果、独立 setup 批准、恢复部署绑定、重复/未知结果不重放。 |
| 运行与控制 | DSH/Pi/OMP 启动观察、pidfd 停止、sidecar 与旧 reader、OMP Domain/owner 协调及共享包保护。 |
| 会话与来源 | 三工具头部读取、Pi claim/helper/公开扩展、历史观察、严格字段与 UTF-8、来源锁和组合表。 |
| CLI 与文档 | 全部修改的 help/交互/补全/退出码、schema、zsh 来源摘要、测试变更、README、指南、spec/plan/tasks/契约与验证记录。 |

executor 使用 gpt-6.1-sol / medium 完成独立运行路径审查与提示实现；scout 使用
gpt-6-luna / high 核对 Herdr 调用链及文档；主代理审查事务与代理边界、复现状态码问题并验收修正。
未在其它已审查路径确认新的具体缺陷；这不是不存在其它问题的保证。

本次执行结果分别记录，不相加为全库结果：

- 完整 help/resume/Herdr 模块：274 passed；随后增加 worktree 进入失败调用链用例，完整 Herdr 模块 29 passed。
- Pi guard/观察/运行、精确停止、维护 CLI、会话恢复和能力表：391 passed / 4 skipped。四项为 Pi 专属场景的非 Pi 参数跳过。
- 独立运行路径阶段检查曾为 179 passed / 1 failed；失败来自 guard 修改后来源锁尚未同步，更新锁后的完整停止模块已包含于上面的通过组。
- 官方 Pi 隔离 RPC 补验：等号形式输入被转换为官方分开参数，初始/切换 ID 精确匹配，重复 claim 拒绝，原 pidfd SIGTERM 后退出 143；无网络/模型请求。
- 打印模式失败分支：上述 P1 仍可复现，不能计作保护通过。

私人任务记录保存实际 argv、摘要、退出码和原始日志。之前 13,561 passed / 12 skipped
属于提交 `2cda58d` 的分组对账，不是本次修正后重新执行的整库结果。
完整官方宿主贯穿 Rotom CLI 的维护流程、其它平台与可选锁定 Bun SDK 检查仍未验证。
主目录新增 Pi 锁组合的恢复准入仍未验收；其格式有效不代表该组合已支持维护恢复。
