# Pi 0.86+ 与 pi-cursor 1.4.31+ 两个独立 bug 叠加导致 cursor 卡死（遗留问题）

- 记录日期：2026-09-22（同日修正：补充 Bug B，原结论"降级 Pi 即可"不完整）
- 状态：已回退稳定组合（全局 Pi 0.85.1 + pi-cursor 1.4.29），待 pi-cursor 发布含 PR #37 修复的版本后升级
- 影响范围：
  - Bug A（TranscriptContext 断层）：Pi ≥ 0.86.0 + pi-cursor ≤ 1.4.36
  - Bug B（原生 shell 挂死）：pi-cursor 1.4.31 ~ 1.4.36，**与 Pi 版本无关**；仅当模型走到原生 shell 的真实工具任务时触发
- 关联文件：`agents/pi/packages/task-keeper/package.json`（peerDeps `>=0.84.4 <0.85.0`，天然规避）、`docs/pi-cursor-stale-pin-legacy.md`（前序遗留问题：pi-cursor 版本过旧）
- 上游跟踪：[PR #35](https://github.com/Rahularya01/pi-cursor/pull/35)、[PR #37](https://github.com/Rahularya01/pi-cursor/pull/37)、[PR #39](https://github.com/Rahularya01/pi-cursor/pull/39)（均未合并，npm 最新仍为 1.4.36）

## 摘要

两个独立 bug 叠加导致 cursor 模型在真实工具任务中永久卡死（spinner 空转 1 小时+、无输出无错误、watchdog 不触发）：

**Bug A（Pi 0.86.0 引入，Pi 降级可解决）**：provider 流输入从 `Context` 改为 `TranscriptContext`（breaking change，见 [v0.86.0 release](https://github.com/earendil-works/pi/releases/tag/v0.86.0)），pi-cursor ≤1.4.36 仍读 `context.systemPrompt` / `context.tools`——这两个字段在新版 `normalizeContext()` 中被整体丢弃（工具定义与 prompt 改以 transcript system message 增量 `toolsAdded`/`toolsRemoved`/`sections` 承载）。结果：发给 Cursor 的请求没有系统提示和工具表（`systemChars: 28, toolCount: 0`），模型失去 Pi 工具，被迫走 Cursor 原生 exec channel。

**Bug B（pi-cursor 1.4.31 引入，与 Pi 版本无关，9-22 resume 实测揭示）**：1.4.31 起 Cursor 原生工具（read/grep/shell）直接在流上执行，其中 `shellStreamArgs` 路径 wire drift（ShellArgs 字段 15/17/21），服务端永不完成该 turn；idle watchdog 在 tool/exec 暂停期间不计时（180s 守卫失效）。1.4.29 对未知 exec 回答 `ExecClientThrow`，模型自动 fallback `mcp_pi_bash` 闭环——这是 9/17-18 稳定期（106+143 次工具调用全部成功）的实际机制。

**处置**：回退历史稳定组合 **Pi 0.85.1 + pi-cursor 1.4.29**（全局 npm + `pi install` + starter 模板三处同步）。教训：pi-cursor 桥接层健康度同时取决于自身版本与 Pi 本体版本，升级任一前必须核对兼容矩阵。

## 现象

交互模式使用 cursor 模型（`kimi-k3`、`grok-4.5/4.6`、`composer-*`）执行需要工具的真实任务时：

1. TUI 永久卡在 "Working..." spinner（实例：1 小时+ 无响应，无输出、无错误、不超时）
2. session 中 `Assistant: 0`——模型无任何回复；进程保持到 Cursor API 的活跃连接，socket 仅剩小流量心跳
3. `pi -p` 非交互模式同模型间歇性空输出（约 30~40%）；session 中 assistant 消息完整但 stdout 无内容
4. 简单对话（"say hi"）大多正常；**凡需工具操作的任务几乎必现**——这是与"模型质量问题"区分的关键特征

## 根因

### 断层 1：请求构成损坏（决定性证据）

lifecycle 日志（`PI_CURSOR_LIFECYCLE_LOG`）中同一 `request_size` 事件对比：

| 环境 | systemChars | toolCount | mcpSchemaBytes |
|---|---|---|---|
| Pi 0.86.1 + pi-cursor 1.4.36 | **28**（占位 fallback） | **0** | 0 |
| Pi 0.85.1 + pi-cursor 1.4.36 | **35761** | **28** | 19161 |

`systemChars: 28, toolCount: 0` 即处于 bug 状态；上游修复目标值参考 [PR #35](https://github.com/Rahularya01/pi-cursor/pull/35) 的验证表（`systemChars 28→22088, toolCount 0→22`）。

### 断层 2（Bug B）：原生 shell 路径挂死 + watchdog 失效（与 Pi 版本无关，9-22 resume 实测揭示）

- pi-cursor 1.4.31 起原生工具（read/grep/shell）直接在流上执行；`shellStreamArgs` 路径 wire drift（ShellArgs 字段 15/17/21），**服务端不会从此流完成 turn**（1.4.36 实测：`grepArgs → readArgs → shellStreamArgs → backgroundShellSpawnArgs → [永久挂起]`）
- pi-cursor 的 idle watchdog 在 tool/exec 暂停期间不计时（默认 180s 守卫不触发），turn 永久挂起
- 1.4.29 对未知 exec 回答 `ExecClientThrow`（日志 `exec_unknown_shape`），模型自动 fallback `mcp_pi_bash` 经 Pi 注册表闭环——这是 9/17-18 稳定期的实际机制
- 简单对话（"say hi"）不触发工具，两个版本都看似正常——只有真实工具任务暴露

### 次要观察（独立问题，不直接导致本卡死）

- [Issue #38](https://github.com/Rahularya01/pi-cursor/issues/38)：`grok-4.7` 参数化路由（`effort` vs 服务端 `reasoning_effort` schema 漂移）报 `not_found`；workaround 用 sibling ID（`grok-4.7-high`）
- `conversationCheckpointUpdate` 在解析器中被分类为 `"work"` 会重置 idle 计时器（1.4.27 仅排除 heartbeat），延长挂起窗口
- `pi -p` 空输出时 session 持久化完整，疑似 Pi 侧 `-p` 渲染竞态

## 处置（2026-09-22 已执行）：回退历史稳定组合

**Pi 0.85.1 + pi-cursor 1.4.29**（9/17-18 实测 249 次工具调用全部成功的组合）。多 node 版本环境需对每个版本单独执行，且个别版本的 npm `prefix` 配置会重定向全局目录（本机 v24.14.0 曾指向 v24.1.0，出现"降级假成功"），需加 `--prefix` 显式指定：

```bash
npm install -g @earendil-works/pi-coding-agent@0.85.1   # 每个 nvm node 版本都要执行
pi install npm:@rahularya01/pi-cursor@1.4.29            # 同步更新 settings.json
# starter 模板 templates/pi/default.template.jsonc 同步钉 1.4.29，再 :PiGenerate
```

验证通过（1.4.29 + Pi 0.85.1）：`systemChars 36050, toolCount 28`；模型发起 `shellStreamArgs` → `exec_unknown_shape`（拒绝）→ 自动 fallback `mcp_pi_bash` → `bridge_close code=0`，任务正常完成；resume 编译 session 不再挂死。已运行的 pi 进程内版本不变，需退出重开。

**回退 1.4.29 的已知代价**（带病稳定，详见 `pi-cursor-stale-pin-legacy.md`）：issue #31 workspace 误报每轮注入（任务可完成）、issue #30 cache 统计为 0、原生工具被拒回 MCP 的交互损耗。不回退的备选是 PR #37 分支（未合并社区 PR）。失去 Pi 0.86/0.87 新功能；0.86+ 创建的 session 在 0.85.1 下可能无法恢复，重要 session 需在新版下提前收尾。

**rotom 侧影响评估**：

- `agents/pi/packages/task-keeper/package.json` 的 peerDeps `>=0.84.4 <0.85.0` 恰好避开 Pi 0.86，本地包开发与测试不受波及
- 但全局 Pi CLI 若被升级（如 nvm 重装 node 后顺手 `npm i -g` 最新版），cursor 配方会静默进入本 bug 状态——**无报错、无登录异常**，只有真实工具任务才暴露

**已知代价**：失去 Pi 0.86/0.87 新功能（prompt cache warming、`/bug`、per-model compaction budgets 等）；0.86+ 创建的 session（transcript 新格式、0.87 的 `ContextEditEntry`）在 0.85.1 下可能无法恢复，重要 session 需在新版下提前收尾。

## 恢复路径

满足以下**全部条件**后再升级全局 Pi / pi-cursor：

1. pi-cursor 合并 PR #37（transcript 恢复 + 拒绝 shellStreamArgs 挂起路径）并发布 ≥1.4.37；PR #39（grok-4.7 路由）一并合入更佳
2. 升级后验证两项：`systemChars >> 28 && toolCount > 0`（Bug A 已修）；真实 bash 任务闭环、`shellStreamArgs` 后无永久挂起（Bug B 已修）
3. starter 模板同步改回新版本的精确钉，再 `:PiGenerate`
4. Pi 本体可保持 0.85.1 或升回 0.86.x+（PR #37 同时兼容两侧）
5. 若 rotom 将来需要 peer 更高版本 Pi（如 task-keeper 升级），同步更新本文与 `pi-cursor-stale-pin-legacy.md` 的钉死版本

## 验证方法

```bash
PI_CURSOR_LIFECYCLE_LOG=/tmp/cur.log pi -p --provider cursor --model composer-2 "hi"
grep request_size /tmp/cur.log   # 正常标准：systemChars 数万级、toolCount > 0
```

`systemChars: 28 && toolCount: 0` 即 bug 状态，无论 `pi doctor` / 登录状态 / 模型目录是否正常。

## 时间线

| 日期 | 事件 |
|---|---|
| 2026-09-05 | Pi 0.85.1 发布（最后无此问题的版本） |
| 2026-09-19 | Pi 0.86.0 发布，引入 TranscriptContext breaking change |
| 2026-09-20 | pi-cursor 1.4.36 发布（未适配）；PR #35 提交 |
| 2026-09-21 | 本机全局 Pi 升级 0.86.1；PR #37、#39 提交；Pi 0.87.0 发布（breaking change 未回滚，反而强化 transcript 方向） |
| 2026-09-22 | 卡死定位 Bug A；Pi 降级 0.85.1 后 resume 实测发现 Bug B（shellStreamArgs 挂死与 Pi 版本无关）；pi-cursor 回退 1.4.29 恢复稳定组合并验证；记录本文档 |

## 与 pi-cursor-stale-pin-legacy.md 的关系

前序问题（09-21）：pi-cursor 被精确钉死在 1.4.29，旧 bug 污染上下文（`pi update` 跳过钉死包导致长期未更新）。处置是升级到 1.4.36。

本文档问题（09-22）：升级 pi-cursor 到 1.4.36 后，先暴露 1.4.31+ 的原生 shell 挂死（Bug B），又叠加 Pi 0.86.1 的 TranscriptContext 断层（Bug A）。处置是整体回退 Pi 0.85.1 + pi-cursor 1.4.29。两者共同说明：pi-cursor 桥接层的健康度同时取决于自身版本与 Pi 本体版本，任一侧升级前必须核对兼容矩阵并做真实工具任务验证（"say hi" 级别测试无法暴露本类问题）。
