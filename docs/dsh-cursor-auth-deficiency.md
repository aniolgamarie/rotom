# DSH Cursor 认证缺陷记录

- 记录日期：2026-09-17
- 状态：已定位，待上游修复；rotom 侧已搁置 Cursor 路线
- 影响配方：`dsh-default`（含 `cursor-auth` 插件的所有 DSH 配方）
- 关联文件：`agents/dsh/agent.toml`、`locks/dsh/vendor/cursor-managed.patch`、`docs/dsh.md`、`docs/live-acceptance.md`

## 摘要

DSH 通过社区插件 `dsh-plugin-oauth-subs` 接入 Cursor 订阅。该插件的 Cursor 翻译层（`parseTurns`）把 DSH 注入的连续 `user` 消息拆成多个"未回答历史轮"，只把最后一条当作本轮任务，导致首轮真实用户问题丢失，模型回复"I don't see a specific task yet"并开始自行猜测不存在的 skill（如 `using-superpowers`）。

这是 **Cursor 路线的协议适配缺陷**，不是 rotom 补丁引入，也不是 DSH 启动/部署失败。`doctor` 全绿、登录成功、模型目录可见都不能暴露该问题，只有真实发送首轮请求才会触发。

## 现象

用户在 DSH TUI 中发送："现在 review 一下我们的 DSH 配置，你的评价是什么？"

实际行为：

1. 模型首轮回复："I don't see a specific task yet. What would you like help with?"
2. 随后模型自行扫描仓库，误调用 catalog 中存在但 DSH 未部署的 `openspec-explore`
3. 进一步推断应使用 `using-superpowers`、`brainstorming`、`writing-plans` 等 Pi 生态 skill
4. 这些 skill 不在本次 DSH skill catalog，反复失败：`Error: skill "using-superpowers" is unknown or no longer available`
5. `repeat-tool-reminder` 检测到重复调用，但模型仍持续重试同名 skill

## 根因

### 协议阻抗失配

DSH 内部使用 OpenAI 线性消息格式，把动态上下文（AGENTS.md、runtime 快照、skill catalog）注入为连续的 `role: "user"` 消息，用 `<system-reminder>` 标签区分语义。这对三种线性协议（`openai-completions` / `openai-responses` / `anthropic-messages`）完全合法。

Cursor 订阅走 `AgentService/Run`（Connect RPC v1 protobuf over HTTP/2），是**轮次型协议**：一轮 = 一个用户输入 + 模型随后所有动作；本轮任务只接受一段 `userText`，历史轮进 `conversationState`。

### 翻译层折叠错误

`dsh-plugin-oauth-subs` 的 `src/oauth/cursor/request.ts` 中 `parseTurns()` 对每条 `user` 消息都调用 `finalizeCurrentTurn()` 开新轮：

```ts
if (role === "user") {
  if (current) turns.push(current)
  current = { userText: textOf(msg.content), steps: [] }
  continue
}
```

随后 `openaiToCursor()` 只把最后一段 `userText` 当成本轮 `currentText`。于是：

```text
DSH 发送：
  user: "review 一下 DSH 配置"        ─┐
  user: AGENTS.md reminder            │  被折叠成 4 个"未回答历史轮"
  user: runtime 快照                   │
  user: skill catalog                 ─┘

Cursor 收到的本轮任务 = skill catalog（最后一条）
真实问题 = 无人回答的历史
```

### 本地确定性复现

直接调用 `openaiToCursor()`（不发网络请求），输入上述 4 条连续 user 消息：

```json
{
  "userTextSentAsCurrent": "<system-reminder><available_skills>...</available_skills></system-reminder>",
  "historicalTurns": [
    { "userText": "现在 review 一下我们的 DSH 配置……", "stepCount": 0 },
    { "userText": "<system-reminder>workspace instructions</system-reminder>", "stepCount": 0 },
    { "userText": "Current runtime context", "stepCount": 0 }
  ]
}
```

真实问题落入未回答历史，skill catalog 成为当前任务——与实际首条回复完全吻合。

## 证据链

1. **注入源在 DSH host 核心**：`@deepseek-ai/dsh-agent-instructions`（README："first request includes one durable baseline message"），不在 TUI 或前端。web 与 TUI 共用同一 host 核心。
2. **TUI 不是注入方**：TUI 包内 `available_skills` 仅命中 `types/dsh-adapter/contract.*` 类型契约文件（消费方），非生产方。
3. **rotom 补丁不触及翻译层**：`cursor-managed.patch` 只改 `controller.js/ts`（关自动导入、封自升级）和 `index.js/ts`（`/cursor-login` 命令），不包含 `request.js/ts`。`parseTurns()` 是未修改的上游原始代码。
4. **会话日志**：`using-superpowers` 首次出现于会话日志第 259 条，源自模型输出，此前不存在于 DSH system prompt、skill catalog、DSH home、rotom 配置或用户输入。
5. **Pi 生态同款 bug**：`ndraiman/pi-cursor-provider#10` 报告同类现象（首轮 "there wasn't a specific task"，`pi-subagents` 注入 roster 触发），修复 PR #11 至今 open 未合并。`@rahularya01/pi-cursor`（Pi 生态 Cursor 桥，oauth-subs 逆向源头）的 `message-parsing.ts` 有相同 `finalizeCurrentTurn()` 模式。

## 影响范围

- **所有宿主**：`dsh web` 与 TUI 共用同一 host 核心和翻译层，web 版同样会触发（未实测，但代码证据链完整）。
- **所有 Cursor 模型**：适配错误发生在模型看到请求之前，换 Grok / Composer / Claude 等任意 Cursor 模型都不能修复。
- **DSH 默认注入策略必触发**：DSH 把 AGENTS.md/skill catalog 注入为 user 消息，首轮必然产生连续 user。Pi 核心把上下文放 system 区域，默认不触发；只有注入 user 消息的 Pi 插件（如 pi-subagents）才触发。

## 为什么不是 rotom 补丁引入

rotom 在 `dsh-plugin-oauth-subs` 上打了 5 类补丁（`locks/dsh/vendor/cursor-managed.patch`）：

| 补丁 | 作用 |
|---|---|
| `cursorAutoImport = false` | 关闭自动读取本机 Cursor 凭据（隔离原则） |
| 新增 `/cursor-login` | TUI 下提供登录入口（避免起 web 宿主） |
| `checkUpdate.apply` 抛错 | 禁止运行时自升级（版本锁定） |
| `startAutoUpdateWatch` return | 禁止后台自升级（同上） |
| 禁用 `stampDshHostVersion` | 运行包不可变（哈希锁定） |

全部是"环境交互"补丁，**没有一项触及消息翻译层**。`parseTurns()` 在未打补丁的原始插件里一模一样存在。

## 为什么不更换插件

公开可查的 DSH Cursor 订阅接入**全部是非官方社区逆向项目**，DSH 官方（deepseek-ai/deepseek-harness）不提供 Cursor 订阅路线：

| 插件 | 登录方式 | 验证证据 | 规模 |
|---|---|---|---|
| `xxww0098/dsh-plugin-oauth-subs`（当前） | web 设置页；rotom 补 `/cursor-login` | 唯一有公开真实会话验收的（oauth-codex 路线 211 次调用）；Cursor 路线无验收 | 相对最活跃 |
| `NOirBRight/dsh-llm-cursor` | web 设置页，明确拒绝 CLI 凭据 | 无测试/用户证据；README 醒目警告 ToS 封号 | ≈0 star |
| `orrinzeng/dsh-cursor-subscription` | web 设置页 Browser Sign-in | 无测试/用户证据 | ≈1 star |
| `V1ki/dsh-plugin-subscriptions` | web 设置页 | 质量最高（~30 测试 spec）但**不支持 Cursor** | 未知 |

三个 Cursor 候选都是 web 设置页登录、均无真实用户验证、均逆向同一协议。换插件大概率换一个同款 `parseTurns` bug，还要重做 rotom 的 vendor/patch/lock 全链路。

## 当前处理方式

1. **Cursor 路线搁置**：不从 `/model` 选择 `oauth-cursor`，避免走坏路径。登录态留在实例 `dsh-home/oauth-subs/` 无害（不调用就不耗额度、不触发风控）。
2. **改用 dsh-auth 的 openai-codex**：`/auth login openai-codex`，选 "Device code login (headless)"，在本地浏览器完成 ChatGPT 登录。这是 TUI 配套原生认证，不经过 oauth-subs 翻译层。
3. **备选 API key 路线**：通过 `overrides.providers` + `secret:` 引用直连任意 OpenAI 兼容网关，完全绕开社区 OAuth 插件。

## 未来修复方向

### 优先级 A：上游反馈

向 `xxww0098/dsh-plugin-oauth-subs` 报 issue，附本次无凭据复现：

- 输入：4 条连续 user 消息（真实问题 + AGENTS + runtime + skill catalog）
- 输出：`currentText` = skill catalog，真实问题落入未回答历史
- 引用 `ndraiman/pi-cursor-provider#10` 同类案例

上游修复后 rotom 只需 bump vendor 版本，无需自维护行为补丁。

### 优先级 B：rotum 侧补丁（需用户单独授权）

若上游不修，可在 `cursor-managed.patch` 追加 `parseTurns` 连续 user 合并补丁：

- 第一条真实 user 作为本轮任务
- 紧随其后、未被 assistant 回答的 user 消息拼进同一 `userText`
- 只有真正的历史问答（assistant/tool 之后的新用户输入）才进 `turns`
- 回归测试覆盖本次故障形状

这与现有隔离补丁同一条供应链，但违反"不随意修改社区代码"偏好，需单独评估。

### 优先级 C：Pi 生态接管 Cursor

`specs/001-unify-pi-capabilities` 已规划 `pi-cursor` 配方（Bun + `@rahularya01/pi-cursor@1.4.29`）。Pi 核心把上下文放 system 区域，默认不触发该缺陷。但：

- 未做 live 验证
- 若启用注入 user 消息的 Pi 插件（如 pi-subagents），同款 bug 会复发
- `@rahularya01/pi-cursor` 与 oauth-subs 共享同源逆向代码，`message-parsing.ts` 有相同 `finalizeCurrentTurn()` 模式

### 优先级 D：Cursor 官方 CLI

`cursor.com/install` 提供官方 `agent` CLI，原生终端交互、订阅登录、经过验证。但它是独立 harness，不是 DSH 插件，等于为 Cursor 订阅换一个 agent 框架。可作为 rotom 未来"第二个工具"接入（Pi/Codex 接口已为此设计）。

## 相关文件

- 配置：`agents/dsh/agent.toml`、`agents/dsh/plugins.toml`、`profiles/dsh-default.toml`
- 锁定：`locks/dsh/vendor/cursor-managed.patch`、`locks/dsh/vendor/cursor-provenance.json`、`locks/dsh/package-lock.json`
- 文档：`docs/dsh.md`、`docs/upstream-verification.md`、`docs/live-acceptance.md`
- 会话日志：`instances/dsh/dsh-default/dsh-home/sessions/--data-1-weixiaoxian.wxx-dev_tool-rotom--/599513c3-5fe8-46da-9a93-746f4e23b890/session.v3.jsonl.zstd`
- 翻译层源码（运行包内）：`node_modules/dsh-plugin-oauth-subs/src/oauth/cursor/request.ts`
- 注入源（host 核心）：`node_modules/@deepseek-ai/dsh-agent-instructions/lib/index.js`
