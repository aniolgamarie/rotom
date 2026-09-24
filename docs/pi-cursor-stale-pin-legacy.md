# Pi 扩展精确钉死导致 pi-cursor 旧版 bug 污染上下文（遗留问题）

- 记录日期：2026-09-21
- 状态：已止血（升级到 1.4.36），根治项待办
- 影响范围：starter 仓库管理的 Pi 配置（`templates/pi/default.template.jsonc` → `~/.pi/agent/settings.json`）；走 `cursor` provider 的所有模型会话
- 关联文件：`templates/pi/default.template.jsonc`、`~/.pi/agent/settings.json`、`~/.pi/agent/sessions/--data-1-weixiaoxian.wxx-dev_tool-starter--/2026-09-21T06-08-52-357Z_*.jsonl`、`~/.pi/agent/sessions/--data-1-weixiaoxian.wxx-ob_work-4_4_x_RO--/2026-09-21T07-45-13-316Z_*.jsonl`

## 摘要

第三方扩展 `@rahularya01/pi-cursor` 是 Pi ↔ Cursor 原生 protobuf 协议（`api2.cursor.sh`）的桥接层，Pi 的工具以 MCP 工具（`mcp_pi_<tool>`）形式发给 Cursor 模型。本地钉死的 1.4.29 带两个已修 bug：issue #31（每轮向 Cursor 误报 workspace 为空）和 1.4.31 之前的原生工具拒绝问题。导致 9 月 21 日两个会话中 cursor provider 模型（grok-4.6 / glm-5.2）收到被污染的上下文、全程 0 次真实工具调用、用文本编造"工具被拒 / workspace 为 none"等信息，浪费数轮排查。

这是**协议桥接层旧版 bug + 版本钉死无提醒机制**共同作用的问题，不是 Pi 本体故障，也不是模型本身幻觉（模型是如实转述被注入的错误上下文）。

## 现象

1. 会话 A（starter，review mihomo-mgr 需求）：grok-4.6 全程 0 次工具调用，声称"工作区已从 starter 变为 none""所有原生工具不可用"，并跑偏去讲 OceanBase 内存管理。
2. 会话 B（4_4_x_RO，ELR 代码讨论）：glm-5.2 同样 0 次工具调用，反复声称工具被拒；用户被误导去 UI 里"修复"了一个没坏的 workspace；切到 glm-5.3-flash（zhipu-tf 直连）后一次成功，45 次工具调用定位到 `LockForReadFunctor::inner_lock_for_read`。
3. 共同模式：cursor provider 的模型全瘫，直连 provider（bailian/kimi_tf/zhipu-tf）的模型全好。

## 根因

### 桥接层 bug（均已在上游修复）

- **issue #31**（修复于 1.4.34）：扩展回复 `requestContextArgs` 时从不设置 `env.workspacePaths`，每一轮都告诉 Cursor"当前工作区为空"，Cursor 据此向上下文注入 "Workspace folders changed from `<cwd>` to none" 提醒。模型如实转述，形成"workspace 丢失"假象。
- **原生工具拒绝**（修复于 1.4.31）：模型按 Cursor 习惯调用原生工具（read/grep/shell）被扩展拒绝而非执行，模型学到"工具调用必失败"，转而用文本叙述工具失败（"native Cursor tool not available in Pi. Use the MCP tools provided instead"）。
- 次要：历史回放时工具名渲染为 `mcp_pi_<tool>` 形式反噬新调用（1.4.34 修）；grok-4.6 在 Cursor 上另有 tool 执行顽瘴（1.4.27 修过一个挂 90 分钟的 park）。

### 版本钉死机制放大

- Pi 对精确版本钉（`npm:pkg@x.y.z`）设计为 frozen，`pi update --extensions` / `--all` 均**跳过**被钉死的包（`docs/packages.md` 明确记载）。
- Pi 启动版本检查只覆盖 Pi 本体（`pi.dev/api/latest-version`），**扩展无过期提醒**。
- starter 模板在 8 月 30 日前后钉了当时的最新 1.4.29，此后 7 个修复版无人手动 bump。
- 失败是沉默的（不崩溃、只演工具调用），且只影响 cursor provider 路径，潜伏约 3 周才暴露。

## 已做修复（2026-09-21）

1. `templates/pi/default.template.jsonc`：`pi-cursor@1.4.29` → `@1.4.36`。
2. `~/.pi/agent/settings.json`：同步改为 `@1.4.36`（JSON 语法已校验）。
3. 已执行 `pi install npm:@rahularya01/pi-cursor@1.4.36`，安装缓存实际版本验证为 1.4.36。
4. **注意**：运行中的 Pi 进程仍加载旧扩展，需重启会话（或 reload 扩展）后生效。

## 遗留问题（待优化）

### P1 其余扩展版本巡检

2026-09-21 巡检发现 13 个 npm 精确钉中 8 个落后（pi-cursor 已修）：

| 扩展 | 当前 | 最新 | 备注 |
|---|---|---|---|
| @gotgenes/pi-permission-system | 29.3.0 | 33.0.5 | 跨大版本，changelog 已审查，见下方结论 |
| @narumitw/pi-btw | 0.55.3 | 0.60.3 | minor 连跳 5 个 |
| pi-mcp-adapter | 2.32.1 | 2.35.0 | 信任边界桥接类，优先审 |
| pi-web-access | 0.27.0 | 0.30.0 | |
| @fission-ai/openspec | 1.11.0 | 1.13.1 | |
| @juicesharp/rpiv-todo | 2.9.0 | 2.10.1 | |
| pi-smart-compact | 9.6.0 | 9.7.0 | |
| @aliou/pi-processes | 0.11.1 | 0.12.0 | |

最新：pi-readseek 0.9.16、pi-slopchop 0.10.1、@tintinweb/pi-subagents 0.19.0、@rahularya01/pi-cursor 1.4.36、@tigorhutasuhut/pi-rules 0.6.0。

### pi-permission-system 29.3.0 → 33.0.5 changelog 审查结论（2026-09-21）

已通读 gotgenes/pi-packages changelog，无配置键迁移要求，升级安全，但有两处行为变化的 breaking：

- **31.0.0**：bash 路径门禁收紧——for/select 循环操作数、case 主体里的路径也会被 gate（更安全，可能多弹权限询问）。
- **33.0.0**：MCP 权限规则改为也作用于前缀命名工具（如 `github_search_code`），且 MCP 规则匹配改为 last-match-wins（原来是 first-match）。若 settings.json 里配了 MCP 工具规则，语义会变。
- 其余为修复：33.0.2-5 的 inline-shell 秘密脱敏、引用参数操作数投影、启动配置警告展示；32.x 的 prompt 段处理与权限弹窗键位重映射（新能力）。

结论：可以升级，升级后留意 MCP 相关权限规则是否符合预期。

### P2 建立巡检机制

- 在 starter 增加扩展版本检查脚本：读 settings.json 的 `npm:` 钉，批量对比 npm 最新版，输出落后清单。建议挂到定期维护或 PiGenerate 流程里。
- 重点盯信任边界类扩展（pi-cursor、pi-mcp-adapter 这类协议桥接层），普通工具扩展可放宽节奏。

### P3 上游 feature request（可选）

向 Pi 社区提议：`pi list --outdated` 或启动 footer 提示"N 个扩展落后于最新版"。本体有 update check 而扩展没有，这个不对称容易坑人。

### P4 模型选择经验

pi-cursor README 实测模型表只有 composer-2 / composer-1.5 / claude-sonnet-5 / gpt-5.5 / grok-4.5；动态发现的模型（grok-4.6、glm-5.2 等）工具调用稳定性无保证。重要任务优先用表内模型或直连 provider。

## 排查方法沉淀

遇到"模型声称工具失败"时：

1. 看会话日志（`~/.pi/agent/sessions/<cwd-slug>/<session>.jsonl`）中 `role: toolResult` 记录数——**0 calls 的"失败"是编造或被注入信息诱导**。
2. 对比同会话中不同 provider 模型的表现，定位是否为某条桥接链路问题。
3. 查扩展 changelog 中是否有点名相同症状的修复记录（本次 1.4.34 changelog 原文即为 "The spurious 'Workspace folders changed from `<cwd>` to none' reminder is gone"）。
