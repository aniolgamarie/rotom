# 维护流程分支复审（2026-10-26）

## 2026-10-27 增量：已停止会话与快捷恢复

本轮以候选 `4738b04` 为起点，main 仍为 `45953f0`。新增 `resume --stopped --list`、TTY 单项选择、非交互精确 batch/run、停止前人工备注及 OMP 固定标题槽投影。恢复复用维护的部署绑定与持久意图；原停止/更新/恢复事务未改写。v1 清单仍可读，新计划 v2 保存展示信息，标题不作会话身份，不读取正文生成摘要。候选继续留在任务分支，未合入 main。

独立复审发现 stop-only 快照没有 workflow 来源证明：整个维护日志目录缺失后，不能认定残留快照可绕过原日志直接恢复。已将这些记录限制为人工核对命令，只有完整 workflow 进入快速选择。另一处显示问题也已修正：候选提示“可尝试恢复（启动前复核）”，human 的标题/路径过滤 C 类及 U+2028/U+2029 控制/分隔字符；JSON 保留精确原值。取消、已有派发、未知、更新未完成、目录/身份/部署变化仍拒绝快速交接。

| 本轮最终检查 | 结果与范围 |
| --- | --- |
| 新历史后端、会话头、维护编排三模块 | 366 passed，退出 0；真实临时状态和追加日志，三工具假宿主；包括 v1 兼容、标题正文哨兵及日志丢失负例。 |
| 新历史 CLI/后端、维护 CLI、普通恢复、帮助、zsh 六模块 | 540 passed / 4 skipped，退出 0；四项为已有 Pi 专属场景的非 Pi 参数跳过。 |
| 最终显示强化补验 | 2 passed / 64 deselected，退出 0；U+2028/U+2029 与 bidi 显示保留完整目录/ID。 |
| 公开文档检查及文档测试 | 检查 PASS、无发现；4 passed，退出 0。补全来源摘要与差异格式检查通过。 |

各组重叠，不相加为全库结果。写入阶段另有 3,587 passed / 4 skipped 的广组，通过时间早于最后的旧快照限制和显示修正，仅保留阶段证据。最初 UI 组 428 passed / 4 skipped / 2 failed（遗漏静态补全 flag 和展示断言不符）及后端组 357 passed / 3 failed（测试调用了不存在的完成方法）均已修正并纳入上述最终组，无未解决失败。

executor 使用 gpt-6.1-sol / medium 完成 UI/补全与相关隔离测试；scout 使用 gpt-6-luna / high 调查标题来源并独立复审恢复边界；主代理负责后端、旧日志兼容、最终设计与审查。私人任务记录保存实际命令、来源摘要和提交绑定。没有读取真实会话/账号、启动官方宿主或操控 Herdr；本轮新入口的真实全 CLI 维护链路、其它平台等仍未验证，不影响已有原生证据的范围。

T126–T129 完成；T125 的人工 main 整合批准与整合验收仍未完成。以下保留前一轮原始审查与验证。

审查基线：main `45953f09ce14908282b4af4c08101227e151ca3f`；候选分支
`feat/tool-maintenance-workflows-20261026`，初始审查提交 `2cda58d76b49b3509db68312cbf17b1f108a2289`。
该范围包含代理整合 `ca6083e` 和维护实现 `2cda58d`，共 85 个变更文件；本次复审修正另行保存。

**结论：本次复审发现的 P1 已修复并通过受影响验收；候选仍待人工批准合入。**
原始失败证据和阶段测试均保留，下面单列最终修正与验证范围。main 与其四个未提交 Pi 锁文件没有被修改；没有合入或推送。

## 已修复：P1 — Pi 保护失败后的执行阻断

位置：[公开控制扩展](../../agents/pi/templates/session-control.mjs) 的 `stop()` / `session_start`。
修正前，helper 启动失败、claim 被拒绝或 helper 失联时，扩展记录停止状态并调用 `ctx.shutdown()`。
官方 Pi 1.3.0 的打印模式没有向扩展绑定 shutdown handler，因此该调用不会结束宿主。
`-p` / `--print` 以及 stdin 或 stdout 非 TTY 时选择的隐式打印模式都受影响。

官方 `dist/modes/print-mode.js` 的 `runPrintMode`、`dist/main.js` 的模式选择和
`dist/core/agent-session.js` 的公开上下文绑定已核对。使用原生产扩展、官方打印组件和替身
helper/runtime 的隔离复现观察到：helper 失败 1 次、shutdown 调用 1 次、失败后仍调用
prompt 1 次，打印流程返回 0。没有启动模型请求、读取真实账号或会话，也没有修改官方包。

这不能证明已占用的显式 session 租约被抢走：明确恢复目标的初始租约仍由 manager 预先持有。
它证明“保护不可用后不继续运行”的启动/执行约束不成立，可能在保护未成立时继续新会话，
因而必须修复后才能接受当前候选。

进一步核对发现，RPC 的 shutdown handler 只设置延迟退出标记，TUI shutdown 也有异步清理窗口。
因此最终实现按公开 `ctx.mode` 区分 TUI，所有模式均在保护失败时关闭本 helper 的 stdin、
请求 `ctx.abort()`、同步写固定通知并以 4 结束当前进程。TUI 先通过公开 `ctx.ui.custom()`
回调调用公开 `TUI.stop()`，同步恢复终端后退出；没有修改官方运行包或访问私有宿主接口。
锁定 Pi 1.3.0 的 custom 工厂同步调用行为已核对，官方 interactive-shell 扩展示例也使用
custom / TUI.stop 接口。工厂缺失、抛错、没有同步调用及清理失败均保留立即退出，不能继续运行。
可信单元测试可替换退出函数；官方加载路径和真实子进程验证均使用实际 `process.exit(4)`。

本轮最终来源锁 identity：
`e286d053f59613d94c8be14d89f3def12dafdc67ef54a9746d7d2229ce362d9a`。
来源锁、静态准入表和能力文档与实际测试代码一致。

| 最终验证 | 结果 |
| --- | --- |
| 两份 Node 控制扩展测试 | 71 passed，退出 0；其中 28 条真实子进程用例验证各模式失败退出、正常退出及 TUI 清理异常。宿主上下文与 helper 为替身，不启动第三方宿主。 |
| 受影响 Python 模块 | 391 passed / 4 skipped，退出 0；覆盖 guard、观察、运行、停止、维护 CLI、恢复与能力表。四项为 Pi 专属场景的非 Pi 参数跳过。 |
| 官方 Pi 启动失败，4 项 | 显式 print、隐式非 TTY、JSON、RPC 均退出 4；固定通知一次；后续扩展和输入回调未到达。JSON 只输出官方启动会话头，其它模式无 stdout。 |
| 官方 Pi 真实 helper，6 项 | 正常 print 退出 0；print/TUI 的真实 claim 拒绝退出 4；print/RPC/TUI 在已成功 claim 后、公开 input 回调等待中失联均退出 4，延迟回调和扩展消息未继续。TUI 两项均观察到 raw mode，退出后终端属性与启动前一致。 |
| 官方 Pi 正常 RPC，1 项 | 最终来源组合仍精确加载原 ID、切换到目标 ID、拒绝重复 claim，原 pidfd SIGTERM 后退出 143。 |

Node 隔离验证命令为 `node --test tests/node/pi-session-control.test.mjs tests/node/pi-session-control-failure.test.mjs`。
默认测试没有启动官方宿主；上表官方检查为另外显式授权的隔离步骤。

真实 helper 已核验退出；显式目标的 manager 租约保持到管理上下文关闭，随后释放物理租约。
旧 run 的持久归属仍阻止新 run 接管，没有因宿主消失而自动清除。helper 可能晚于宿主退出，
立即退出不等于所有相关进程已释放；现有完整释放观察与维护准入仍生效。

这些原生检查使用 Linux、原用户 UID、网络隔离和合成 HOME/会话，不读取真实账号或发起模型请求。
没有验证执行中的真实模型/外部工具回滚，也不承诺撤销保护失败前已经产生的副作用。
TUI 检查覆盖本地 PTY 的属性恢复；慢 SSH 的排队按键与终端写失败未验证，失败退出不等待异步输入排空。
本轮没有以此开放实际加载完成断言、自动继续或原 pane 恢复。

阶段失败也保留：写入进行中的 Python 检查为 380 passed / 4 skipped / 11 failed，失败为来源锁尚未跟随修改，
不能算通过；停止写入并更新锁后完整重跑为上表的 391 passed / 4 skipped。
首轮原生 TUI 失联探针把临时终端查询子进程当作 helper，发生 ProcessLookupError；
改为按自建 helper 的精确 argv 核验后重跑六项全部通过，没有据该探针错误修改产品代码。

状态：**实现与分项验收完成**。整合批准与下文单列的未验证范围仍保留。

## 已修正的发现

| 级别 | 触发与问题 | 修正及验证 |
| --- | --- | --- |
| P2 | `run pi -- --session=ID` 被转换成 `--session=FILE`；官方解析器只识别分开的 `--session FILE`，等号参数被忽略。 | 统一转换成两个 argv token，保留原生 `--` 之后的字面内容。隔离回归覆盖两种写法；官方 Pi RPC 验证精确初始 ID、切换后 ID、重复租约拒绝与退出。 |
| P2 | 维护停止仍 pending、恢复只有 intent，或 setup intent 被 cancel 状态覆盖时，`maintenance status` 可能返回 0。 | 按原停止与各阶段事实判断未完成结果，返回 4；取消不覆盖未知结果。18 个三工具场景中，修复前 15 个复现失败、3 个已通过，修复后受影响完整模块通过；查询不写入或重发。 |
| P2 | 工作区帮助没有说明 Herdr 前提，端点不可用和元数据已保存但标题未同步的反馈容易误解。 | 按操作补充静态 help、失败及未知端点提示；提示在 stderr，保留原 stdout/JSON、退出码与已保存结果。checkout 创建后进入失败仍保留 checkout。 |
| P3 | spec 仍称候选未提交、TTY 与本轮整库验证待完成。 | 区分既有阶段证据、本次复审结果和未完成的官方全 CLI 维护验收；原 pane/new-tab 能力明确仍未开放。 |

Pi 参数修正后的三个来源锁 identity 为
`1c2986e858b6f905b17f3af4cfe349ca4fdbd56b08df311fb2d984cfc309b430`。
该 identity 对应参数修正阶段，后续失败阻断的最终来源 identity 见上表；旧阶段证据不改写为新来源。

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

此前复审阶段的执行结果分别保留，不相加为全库结果：

- 完整 help/resume/Herdr 模块：274 passed；随后增加 worktree 进入失败调用链用例，完整 Herdr 模块 29 passed。
- Pi guard/观察/运行、精确停止、维护 CLI、会话恢复和能力表：391 passed / 4 skipped。四项为 Pi 专属场景的非 Pi 参数跳过。
- 独立运行路径阶段检查曾为 179 passed / 1 failed；失败来自 guard 修改后来源锁尚未同步，更新锁后的完整停止模块已包含于上面的通过组。
- 官方 Pi 隔离 RPC 补验：等号形式输入被转换为官方分开参数，初始/切换 ID 精确匹配，重复 claim 拒绝，原 pidfd SIGTERM 后退出 143；无网络/模型请求。
- 原始打印失败复现属于修正前证据；最终失败阻断的验收结果见上表。

私人任务记录保存实际 argv、摘要、退出码和原始日志。之前 13,561 passed / 12 skipped
属于提交 `2cda58d` 的分组对账，不是本次修正后重新执行的整库结果。
完整官方宿主贯穿 Rotom CLI 的维护流程、其它平台与可选锁定 Bun SDK 检查仍未验证。
主目录新增 Pi 锁组合的恢复准入仍未验收；其格式有效不代表该组合已支持维护恢复。
